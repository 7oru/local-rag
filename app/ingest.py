from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import psycopg
from psycopg.types.json import Jsonb

from app.chunking import Chunk, chunk_document
from app.config import Settings, load_settings
from app.db import connect, inspect_database
from app.embeddings import EmbeddingClient, EmbeddingInput, create_embedding_client
from app.markdown import (
    Document,
    canonicalize_vault_path,
    parse_markdown_file,
    scan_markdown_files,
)


class IngestError(RuntimeError):
    """Raised when ingestion cannot complete."""


@dataclass
class IngestResult:
    run_id: int
    vault_path: str
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    status: str
    documents_added: int = 0
    documents_updated: int = 0
    documents_deleted: int = 0
    documents_skipped: int = 0
    chunks_written: int = 0
    embeddings_written: int = 0
    error_summary: Optional[str] = None

    def summary_lines(self) -> list[str]:
        return [
            f"run_id={self.run_id}",
            f"status={self.status}",
            f"vault_path={self.vault_path}",
            f"embedding_provider={self.embedding_provider}",
            f"embedding_model={self.embedding_model}",
            f"embedding_dim={self.embedding_dim}",
            f"documents_added={self.documents_added}",
            f"documents_updated={self.documents_updated}",
            f"documents_deleted={self.documents_deleted}",
            f"documents_skipped={self.documents_skipped}",
            f"chunks_written={self.chunks_written}",
            f"embeddings_written={self.embeddings_written}",
        ]


def ingest_vault(
    vault_path: str | Path | None = None,
    *,
    settings: Settings | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> IngestResult:
    resolved_settings = settings or load_settings()
    require_database_ready(resolved_settings)
    root = canonicalize_vault_path(vault_path or resolved_settings.vault_path)
    client = embedding_client or create_embedding_client(resolved_settings)

    result = IngestResult(
        run_id=0,
        vault_path=str(root),
        embedding_provider=client.provider,
        embedding_model=client.model,
        embedding_dim=client.dim,
        status="running",
    )

    with connect(resolved_settings) as conn:
        result.run_id = create_ingest_run(conn, result)
        try:
            markdown_files = scan_markdown_files(root)
            current_paths = {item.relative_path for item in markdown_files}
            result.documents_deleted += delete_removed_documents(
                conn,
                vault_path=str(root),
                current_paths=current_paths,
            )

            for markdown_file in markdown_files:
                document = parse_markdown_file(markdown_file.file_path, root)
                process_document(conn, document, client, result)

            result.status = "success"
            finish_ingest_run(conn, result)
            return result
        except Exception as exc:
            result.status = "failed"
            result.error_summary = str(exc)
            finish_ingest_run(conn, result)
            raise IngestError(str(exc)) from exc


def require_database_ready(settings: Settings) -> None:
    status = inspect_database(settings)
    if not status.database:
        raise IngestError(f"Database is not reachable: {status.error or 'connection failed'}")
    if not status.schema:
        raise IngestError("Database schema is not initialized. Run `rag db init`.")
    if not status.pgvector:
        raise IngestError("pgvector extension is not available. Run `rag db init`.")


def create_ingest_run(conn: psycopg.Connection, result: IngestResult) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_runs (
                  vault_path, embedding_provider, embedding_model, embedding_dim, status
                )
                VALUES (%s, %s, %s, %s, 'running')
                RETURNING id
                """,
                (
                    result.vault_path,
                    result.embedding_provider,
                    result.embedding_model,
                    result.embedding_dim,
                ),
            )
            return int(cur.fetchone()[0])


def finish_ingest_run(conn: psycopg.Connection, result: IngestResult) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_runs
                SET status = %s,
                    finished_at = now(),
                    documents_added = %s,
                    documents_updated = %s,
                    documents_deleted = %s,
                    documents_skipped = %s,
                    chunks_written = %s,
                    embeddings_written = %s,
                    error_summary = %s
                WHERE id = %s
                """,
                (
                    result.status,
                    result.documents_added,
                    result.documents_updated,
                    result.documents_deleted,
                    result.documents_skipped,
                    result.chunks_written,
                    result.embeddings_written,
                    result.error_summary,
                    result.run_id,
                ),
            )


def delete_removed_documents(
    conn: psycopg.Connection,
    *,
    vault_path: str,
    current_paths: set[str],
) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relative_path FROM documents WHERE vault_path = %s",
                (vault_path,),
            )
            existing_paths = {row[0] for row in cur.fetchall()}
            removed = sorted(existing_paths - current_paths)
            if not removed:
                return 0
            cur.execute(
                """
                DELETE FROM documents
                WHERE vault_path = %s AND relative_path = ANY(%s)
                """,
                (vault_path, removed),
            )
            return len(removed)


def process_document(
    conn: psycopg.Connection,
    document: Document,
    client: EmbeddingClient,
    result: IngestResult,
) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            existing = find_document(cur, document)
            if existing is None:
                document_id = insert_document(cur, document)
                chunks, embeddings_written = write_chunks_and_embeddings(
                    cur,
                    document_id=document_id,
                    document=document,
                    client=client,
                )
                result.documents_added += 1
                result.chunks_written += len(chunks)
                result.embeddings_written += embeddings_written
                return

            document_id, content_hash = existing
            if content_hash != document.content_hash:
                update_document(cur, document_id, document)
                delete_chunks(cur, document_id)
                chunks, embeddings_written = write_chunks_and_embeddings(
                    cur,
                    document_id=document_id,
                    document=document,
                    client=client,
                )
                result.documents_updated += 1
                result.chunks_written += len(chunks)
                result.embeddings_written += embeddings_written
                return

            chunk_count, embedding_count = count_current_embeddings(
                cur,
                document_id=document_id,
                client=client,
            )
            if chunk_count > 0 and chunk_count == embedding_count:
                result.documents_skipped += 1
                return

            if chunk_count == 0:
                chunks, embeddings_written = write_chunks_and_embeddings(
                    cur,
                    document_id=document_id,
                    document=document,
                    client=client,
                )
                result.documents_updated += 1
                result.chunks_written += len(chunks)
                result.embeddings_written += embeddings_written
                return

            embeddings_written = backfill_missing_embeddings(cur, document_id, client)
            result.documents_updated += 1
            result.embeddings_written += embeddings_written


def find_document(cur: psycopg.Cursor, document: Document) -> tuple[int, str] | None:
    cur.execute(
        """
        SELECT id, content_hash
        FROM documents
        WHERE vault_path = %s AND relative_path = %s
        """,
        (document.vault_path, document.relative_path),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def insert_document(cur: psycopg.Cursor, document: Document) -> int:
    cur.execute(
        """
        INSERT INTO documents (
          vault_path, file_path, relative_path, content_hash, mtime_ns, size_bytes,
          frontmatter
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            document.vault_path,
            document.file_path,
            document.relative_path,
            document.content_hash,
            document.mtime_ns,
            document.size_bytes,
            Jsonb(document.frontmatter),
        ),
    )
    return int(cur.fetchone()[0])


def update_document(cur: psycopg.Cursor, document_id: int, document: Document) -> None:
    cur.execute(
        """
        UPDATE documents
        SET file_path = %s,
            content_hash = %s,
            mtime_ns = %s,
            size_bytes = %s,
            frontmatter = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            document.file_path,
            document.content_hash,
            document.mtime_ns,
            document.size_bytes,
            Jsonb(document.frontmatter),
            document_id,
        ),
    )


def delete_chunks(cur: psycopg.Cursor, document_id: int) -> None:
    cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))


def write_chunks_and_embeddings(
    cur: psycopg.Cursor,
    *,
    document_id: int,
    document: Document,
    client: EmbeddingClient,
) -> tuple[list[Chunk], int]:
    chunks = chunk_document(document)
    if not chunks:
        return [], 0

    inputs = [embedding_input_for_chunk(chunk) for chunk in chunks]
    vectors = client.embed_documents(inputs)
    if len(vectors) != len(chunks):
        raise IngestError("Embedding provider returned the wrong number of vectors")

    embeddings_written = 0
    for chunk, vector in zip(chunks, vectors):
        chunk_id = insert_chunk(cur, document_id, chunk)
        insert_embedding(cur, chunk_id, client, vector)
        embeddings_written += 1

    return chunks, embeddings_written


def insert_chunk(cur: psycopg.Cursor, document_id: int, chunk: Chunk) -> int:
    cur.execute(
        """
        INSERT INTO chunks (
          document_id, chunk_index, content, file_path, relative_path, heading_path,
          frontmatter, tags, wikilinks, metadata, content_hash, token_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            document_id,
            chunk.chunk_index,
            chunk.content,
            chunk.file_path,
            chunk.relative_path,
            chunk.heading_path,
            Jsonb(chunk.frontmatter),
            chunk.tags,
            chunk.wikilinks,
            Jsonb(chunk.metadata),
            chunk.content_hash,
            chunk.token_count,
        ),
    )
    return int(cur.fetchone()[0])


def insert_embedding(
    cur: psycopg.Cursor,
    chunk_id: int,
    client: EmbeddingClient,
    vector: Sequence[float],
) -> None:
    if len(vector) != client.dim:
        raise IngestError(
            f"Embedding vector has dimension {len(vector)}, expected {client.dim}"
        )
    cur.execute(
        """
        INSERT INTO embeddings (
          chunk_id, embedding_provider, embedding_model, embedding_dim, embedding
        )
        VALUES (%s, %s, %s, %s, %s::vector)
        ON CONFLICT (chunk_id, embedding_provider, embedding_model, embedding_dim)
        DO NOTHING
        """,
        (
            chunk_id,
            client.provider,
            client.model,
            client.dim,
            vector_literal(vector),
        ),
    )


def count_current_embeddings(
    cur: psycopg.Cursor,
    *,
    document_id: int,
    client: EmbeddingClient,
) -> tuple[int, int]:
    cur.execute(
        """
        SELECT COUNT(c.id), COUNT(e.id)
        FROM chunks c
        LEFT JOIN embeddings e
          ON e.chunk_id = c.id
         AND e.embedding_provider = %s
         AND e.embedding_model = %s
         AND e.embedding_dim = %s
        WHERE c.document_id = %s
        """,
        (client.provider, client.model, client.dim, document_id),
    )
    row = cur.fetchone()
    return int(row[0]), int(row[1])


def backfill_missing_embeddings(
    cur: psycopg.Cursor,
    document_id: int,
    client: EmbeddingClient,
) -> int:
    cur.execute(
        """
        SELECT c.id, c.content, c.heading_path, c.relative_path, c.tags, c.wikilinks
        FROM chunks c
        LEFT JOIN embeddings e
          ON e.chunk_id = c.id
         AND e.embedding_provider = %s
         AND e.embedding_model = %s
         AND e.embedding_dim = %s
        WHERE c.document_id = %s
          AND e.id IS NULL
        ORDER BY c.chunk_index
        """,
        (client.provider, client.model, client.dim, document_id),
    )
    rows = cur.fetchall()
    if not rows:
        return 0

    inputs = [
        EmbeddingInput(
            content=row[1],
            heading_path=row[2] or [],
            relative_path=row[3],
            tags=row[4] or [],
            wikilinks=row[5] or [],
        )
        for row in rows
    ]
    vectors = client.embed_documents(inputs)
    if len(vectors) != len(rows):
        raise IngestError("Embedding provider returned the wrong number of vectors")

    for row, vector in zip(rows, vectors):
        insert_embedding(cur, int(row[0]), client, vector)
    return len(rows)


def embedding_input_for_chunk(chunk: Chunk) -> EmbeddingInput:
    return EmbeddingInput(
        content=chunk.content,
        heading_path=chunk.heading_path,
        relative_path=chunk.relative_path,
        tags=chunk.tags,
        wikilinks=chunk.wikilinks,
    )


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.9f}" for value in vector) + "]"
