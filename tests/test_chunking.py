from __future__ import annotations

from pathlib import Path

from app.chunking import MAX_TOKENS, chunk_document
from app.markdown import parse_markdown_file


def test_chunk_document_preserves_heading_path() -> None:
    document = parse_markdown_file(
        "samples/acme-vault/policies/Support Escalation Policy.md",
        "samples/acme-vault",
    )

    chunks = chunk_document(document)

    assert chunks[0].heading_path == ["Support Escalation Policy"]
    assert ["Support Escalation Policy", "P1 Escalation"] in [
        chunk.heading_path for chunk in chunks
    ]


def test_long_section_is_split_by_token_limit(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Long.md"
    note.write_text(
        "---\nowner: sre\n---\n# Runbook\n\n## Long Section\n\n"
        + ("latency mitigation customer impact " * 900),
        encoding="utf-8",
    )
    document = parse_markdown_file(note, vault)

    chunks = chunk_document(document)

    assert len(chunks) > 1
    assert all(chunk.token_count <= MAX_TOKENS for chunk in chunks)
    assert all(chunk.heading_path == ["Runbook", "Long Section"] for chunk in chunks[1:])


def test_chunk_order_is_stable() -> None:
    document = parse_markdown_file(
        "samples/acme-vault/products/Atlas CRM FAQ.md",
        "samples/acme-vault",
    )

    first = chunk_document(document)
    second = chunk_document(document)

    assert [(chunk.chunk_index, chunk.content_hash) for chunk in first] == [
        (chunk.chunk_index, chunk.content_hash) for chunk in second
    ]
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))


def test_chunk_metadata_is_inherited_from_document() -> None:
    document = parse_markdown_file(
        "samples/acme-vault/support/Common Customer Issues.md",
        "samples/acme-vault",
    )

    chunk = chunk_document(document)[0]

    assert chunk.relative_path == "support/Common Customer Issues.md"
    assert chunk.frontmatter["owner"] == "support"
    assert "support" in chunk.tags
    assert "runbooks/API Latency Runbook" in chunk.wikilinks
    assert chunk.metadata["source_document_hash"] == document.content_hash
