from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.config import Settings, load_settings
from app.db import connect, inspect_database
from app.embeddings import EmbeddingClient, create_embedding_client
from app.ingest import vector_literal
from app.schemas import SearchResult


class RetrievalError(RuntimeError):
    """Raised when retrieval cannot run."""


class RetrievalNotReady(RetrievalError):
    """Raised when there are no embeddings for the current config."""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    source: str
    relative_path: str
    heading_path: list[str]
    heading: str
    content: str
    score: float
    chunk_index: int
    content_hash: str


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    top_k: int
    chunks: list[RetrievedChunk]
    confidence: float


def search(
    query: str,
    *,
    top_k: int = 5,
    settings: Settings | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> RetrievalResult:
    resolved_settings = settings or load_settings()
    client = embedding_client or create_embedding_client(resolved_settings)
    ensure_retrieval_ready(resolved_settings)

    query_vector = client.embed_query(query)
    chunks = search_by_vector(
        query=query,
        query_vector=query_vector,
        top_k=top_k,
        settings=resolved_settings,
        client=client,
    )
    confidence = chunks[0].score if chunks else 0.0
    return RetrievalResult(query=query, top_k=top_k, chunks=chunks, confidence=confidence)


def ensure_retrieval_ready(settings: Settings) -> None:
    status = inspect_database(settings)
    if not status.database:
        raise RetrievalError(f"Database is not reachable: {status.error or 'connection failed'}")
    if not status.schema:
        raise RetrievalError("Database schema is not initialized. Run `rag db init`.")
    if not status.pgvector:
        raise RetrievalError("pgvector extension is not available. Run `rag db init`.")
    if status.embeddings_current_config == 0:
        raise RetrievalNotReady(
            "No embeddings exist for the current embedding config. Run `rag ingest`."
        )


def search_by_vector(
    *,
    query: str,
    query_vector: Sequence[float],
    top_k: int,
    settings: Settings,
    client: EmbeddingClient,
) -> list[RetrievedChunk]:
    vector = vector_literal(query_vector)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  c.id AS chunk_id,
                  d.id AS document_id,
                  c.relative_path,
                  c.heading_path,
                  c.content,
                  1 - (e.embedding <=> %s::vector) AS raw_similarity,
                  c.chunk_index,
                  c.content_hash
                FROM embeddings e
                JOIN chunks c ON c.id = e.chunk_id
                JOIN documents d ON d.id = c.document_id
                WHERE e.embedding_provider = %s
                  AND e.embedding_model = %s
                  AND e.embedding_dim = %s
                ORDER BY e.embedding <=> %s::vector,
                         c.relative_path ASC,
                         c.chunk_index ASC,
                         c.id ASC
                LIMIT %s
                """,
                (
                    vector,
                    client.provider,
                    client.model,
                    client.dim,
                    vector,
                    top_k,
                ),
            )
            rows = cur.fetchall()

    return [
        RetrievedChunk(
            chunk_id=int(row[0]),
            document_id=int(row[1]),
            source=str(row[2]),
            relative_path=str(row[2]),
            heading_path=list(row[3] or []),
            heading=(list(row[3] or [])[-1] if row[3] else ""),
            content=str(row[4]),
            score=clamp_score(float(row[5])),
            chunk_index=int(row[6]),
            content_hash=str(row[7]),
        )
        for row in rows
    ]


def to_search_result(chunk: RetrievedChunk) -> SearchResult:
    return SearchResult(
        source=chunk.source,
        relative_path=chunk.relative_path,
        heading_path=chunk.heading_path,
        heading=chunk.heading,
        content=chunk.content,
        score=chunk.score,
    )


def clamp_score(score: float) -> float:
    return max(0.0, min(1.0, score))
