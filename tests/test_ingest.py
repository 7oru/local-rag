from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from app.config import Settings, load_settings
from app.embeddings import FakeEmbeddingClient
from app.ingest import IngestError, ingest_vault


def write_note(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nowner: test\nproduct: Atlas CRM\ntags:\n  - support\n---\n"
        + body,
        encoding="utf-8",
    )


def table_count(settings: Settings, table: str) -> int:
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return int(cur.fetchone()[0])


def fetch_one(settings: Settings, query: str, params=()):
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()


def test_sample_vault_second_ingest_skips_unchanged_documents(
    test_env: dict[str, str],
    clean_test_db: None,
) -> None:
    settings = load_settings()

    first = ingest_vault("samples/acme-vault", settings=settings)
    second = ingest_vault("samples/acme-vault", settings=settings)

    assert first.status == "success"
    assert first.documents_added == 9
    assert first.chunks_written > 0
    assert first.embeddings_written == first.chunks_written
    assert second.documents_skipped == 9
    assert second.documents_added == 0
    assert second.documents_updated == 0
    assert second.embeddings_written == 0
    assert table_count(settings, "documents") == 9
    assert table_count(settings, "chunks") == first.chunks_written
    assert table_count(settings, "embeddings") == first.embeddings_written


def test_changed_file_rebuilds_chunks_and_embeddings(
    tmp_path: Path,
    test_env: dict[str, str],
    clean_test_db: None,
) -> None:
    settings = load_settings()
    vault = tmp_path / "vault"
    note = vault / "Support.md"
    write_note(note, "# Support\n\n## P1\n\nInitial escalation text.")
    ingest_vault(vault, settings=settings)

    write_note(note, "# Support\n\n## P1\n\nChanged escalation text.")
    result = ingest_vault(vault, settings=settings)

    assert result.documents_updated == 1
    assert result.chunks_written > 0
    row = fetch_one(
        settings,
        """
        SELECT COUNT(*)
        FROM chunks
        WHERE relative_path = %s AND content LIKE %s
        """,
        ("Support.md", "%Changed escalation text%"),
    )
    assert row[0] == 1
    assert table_count(settings, "documents") == 1
    assert table_count(settings, "chunks") == table_count(settings, "embeddings")


def test_deleted_source_file_hard_deletes_document_and_cascades(
    tmp_path: Path,
    test_env: dict[str, str],
    clean_test_db: None,
) -> None:
    settings = load_settings()
    vault = tmp_path / "vault"
    note = vault / "Support.md"
    write_note(note, "# Support\n\nP1 escalation text.")
    ingest_vault(vault, settings=settings)

    note.unlink()
    result = ingest_vault(vault, settings=settings)

    assert result.documents_deleted == 1
    assert table_count(settings, "documents") == 0
    assert table_count(settings, "chunks") == 0
    assert table_count(settings, "embeddings") == 0


def test_missing_current_embeddings_are_backfilled_without_rewriting_chunks(
    tmp_path: Path,
    test_env: dict[str, str],
    clean_test_db: None,
) -> None:
    settings = load_settings()
    vault = tmp_path / "vault"
    write_note(vault / "Support.md", "# Support\n\nP1 escalation text.")
    ingest_vault(vault, settings=settings)
    chunk_count = table_count(settings, "chunks")

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM embeddings")

    result = ingest_vault(vault, settings=settings)

    assert result.documents_updated == 1
    assert result.chunks_written == 0
    assert result.embeddings_written == chunk_count
    assert table_count(settings, "chunks") == chunk_count
    assert table_count(settings, "embeddings") == chunk_count


class FailingEmbeddingClient(FakeEmbeddingClient):
    def embed_documents(self, items):
        raise RuntimeError("forced embedding failure")


def test_changed_file_failure_rolls_back_and_marks_run_failed(
    tmp_path: Path,
    test_env: dict[str, str],
    clean_test_db: None,
) -> None:
    settings = load_settings()
    vault = tmp_path / "vault"
    note = vault / "Support.md"
    write_note(note, "# Support\n\nOld stable content.")
    ingest_vault(vault, settings=settings)
    old_hash = fetch_one(settings, "SELECT content_hash FROM documents")[0]

    write_note(note, "# Support\n\nNew content that should roll back.")
    with pytest.raises(IngestError, match="forced embedding failure"):
        ingest_vault(vault, settings=settings, embedding_client=FailingEmbeddingClient())

    assert fetch_one(settings, "SELECT content_hash FROM documents")[0] == old_hash
    assert "Old stable content" in fetch_one(settings, "SELECT content FROM chunks")[0]
    assert table_count(settings, "chunks") == table_count(settings, "embeddings")
    assert fetch_one(
        settings,
        "SELECT status FROM ingest_runs ORDER BY id DESC LIMIT 1",
    )[0] == "failed"
