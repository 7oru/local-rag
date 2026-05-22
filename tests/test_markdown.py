from __future__ import annotations

from pathlib import Path

from app.markdown import canonicalize_vault_path, scan_markdown_files


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
