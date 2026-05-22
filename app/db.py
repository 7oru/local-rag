from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psycopg

from app.config import Settings, load_settings


REQUIRED_TABLES = ("documents", "chunks", "embeddings", "ingest_runs")


class DatabaseError(RuntimeError):
    """Raised when database bootstrap or health checks fail."""


@dataclass(frozen=True)
class DatabaseStatus:
    database: bool
    schema: bool
    pgvector: bool
    documents: int = 0
    chunks: int = 0
    embeddings_current_config: int = 0
    error: Optional[str] = None


def connect(settings: Optional[Settings] = None) -> psycopg.Connection:
    resolved = settings or load_settings()
    return psycopg.connect(resolved.database_url)


def schema_path(settings: Settings) -> Path:
    return settings.repo_root / "app" / "schema.sql"


def init_db(settings: Optional[Settings] = None) -> None:
    resolved = settings or load_settings()
    path = schema_path(resolved)
    if not path.is_file():
        raise DatabaseError(f"Schema file is missing: {path}")

    sql = path.read_text(encoding="utf-8")
    try:
        with connect(resolved) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    except psycopg.Error as exc:
        raise DatabaseError(f"Could not initialize database: {exc}") from exc


def inspect_database(settings: Optional[Settings] = None) -> DatabaseStatus:
    resolved = settings or load_settings()
    try:
        with connect(resolved) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                database_ok = cur.fetchone() == (1,)

                cur.execute(
                    "SELECT extname FROM pg_extension WHERE extname = 'vector'"
                )
                pgvector_ok = cur.fetchone() is not None

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
                tables = {row[0] for row in cur.fetchall()}
                schema_ok = all(table in tables for table in REQUIRED_TABLES)

                if not schema_ok:
                    return DatabaseStatus(
                        database=database_ok,
                        schema=False,
                        pgvector=pgvector_ok,
                    )

                documents = _count(cur, "documents")
                chunks = _count(cur, "chunks")
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM embeddings
                    WHERE embedding_provider = %s
                      AND embedding_model = %s
                      AND embedding_dim = %s
                    """,
                    (
                        resolved.embedding_provider,
                        resolved.embedding_model,
                        resolved.embedding_dim,
                    ),
                )
                embeddings_current_config = int(cur.fetchone()[0])

                return DatabaseStatus(
                    database=database_ok,
                    schema=True,
                    pgvector=pgvector_ok,
                    documents=documents,
                    chunks=chunks,
                    embeddings_current_config=embeddings_current_config,
                )
    except Exception as exc:  # pragma: no cover - exercised by integration tests.
        return DatabaseStatus(
            database=False,
            schema=False,
            pgvector=False,
            error=str(exc),
        )


def _count(cur: psycopg.Cursor, table_name: str) -> int:
    if table_name not in REQUIRED_TABLES:
        raise ValueError(f"Unsupported table: {table_name}")
    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    return int(cur.fetchone()[0])
