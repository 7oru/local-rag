from __future__ import annotations

from pathlib import Path

from app.markdown import canonicalize_vault_path, parse_markdown_file, scan_markdown_files


def test_scan_markdown_files_finds_sample_vault_documents() -> None:
    files = scan_markdown_files("samples/acme-vault")
    relative_paths = [item.relative_path for item in files]

    assert len(files) == 9
    assert relative_paths == sorted(relative_paths)
    assert "00-index.md" in relative_paths
    assert "products/Atlas CRM.md" in relative_paths
    assert "policies/Support Escalation Policy.md" in relative_paths


def test_scan_markdown_files_ignores_hidden_obsidian_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    hidden = vault / ".obsidian"
    notes = vault / "notes"
    hidden.mkdir(parents=True)
    notes.mkdir()
    (hidden / "workspace.md").write_text("# Hidden\n", encoding="utf-8")
    (notes / "Visible.md").write_text("# Visible\n", encoding="utf-8")

    files = scan_markdown_files(vault)

    assert [item.relative_path for item in files] == ["notes/Visible.md"]


def test_vault_path_canonicalization_is_stable() -> None:
    direct = canonicalize_vault_path("samples/acme-vault")
    dotted = canonicalize_vault_path("./samples/acme-vault")
    absolute = canonicalize_vault_path(Path("samples/acme-vault").resolve())

    assert direct == dotted == absolute


def test_scan_markdown_files_returns_safe_posix_paths() -> None:
    files = scan_markdown_files("samples/acme-vault")

    for item in files:
        assert Path(item.vault_path).is_absolute()
        assert Path(item.file_path).is_absolute()
        assert "\\" not in item.relative_path
        assert not item.relative_path.startswith("./")
        assert ".." not in Path(item.relative_path).parts


def test_parse_markdown_file_reads_frontmatter_headings_tags_and_links() -> None:
    document = parse_markdown_file(
        "samples/acme-vault/products/Atlas CRM.md",
        "samples/acme-vault",
    )

    assert document.frontmatter["owner"] == "product"
    assert document.frontmatter["product"] == "Atlas CRM"
    assert document.relative_path == "products/Atlas CRM.md"
    assert document.headings[0].level == 1
    assert document.headings[0].title == "Atlas CRM"
    assert "Data Export" in [heading.title for heading in document.headings]
    assert {"product", "atlas_crm"}.issubset(set(document.tags))
    assert "policies/Data Handling Policy" in document.wikilinks
    assert "products/Atlas CRM FAQ" in document.wikilinks


def test_parse_markdown_file_supports_alias_wikilinks() -> None:
    document = parse_markdown_file("samples/acme-vault/00-index.md", "samples/acme-vault")

    assert "products/Atlas CRM" in document.wikilinks
    assert "Atlas CRM" not in document.wikilinks


def test_content_hash_changes_when_file_content_changes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Note.md"
    note.write_text(
        "---\nowner: test\n---\n# Title\n\nInitial content #tag\n",
        encoding="utf-8",
    )
    first = parse_markdown_file(note, vault)

    note.write_text(
        "---\nowner: test\n---\n# Title\n\nChanged content #tag\n",
        encoding="utf-8",
    )
    second = parse_markdown_file(note, vault)

    assert first.content_hash != second.content_hash
