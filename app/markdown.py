from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MarkdownFile:
    vault_path: str
    file_path: str
    relative_path: str


def scan_markdown_files(vault_path: str | Path) -> list[MarkdownFile]:
    root = canonicalize_vault_path(vault_path)
    files: list[MarkdownFile] = []

    for path in root.rglob("*.md"):
        if _has_hidden_part(path.relative_to(root)):
            continue
        resolved_path = path.resolve(strict=True)
        files.append(
            MarkdownFile(
                vault_path=str(root),
                file_path=str(resolved_path),
                relative_path=relative_posix_path(root, resolved_path),
            )
        )

    return sorted(files, key=lambda item: item.relative_path)


def canonicalize_vault_path(vault_path: str | Path) -> Path:
    return Path(vault_path).expanduser().resolve(strict=True)


def relative_posix_path(vault_root: Path, file_path: Path) -> str:
    relative = file_path.resolve(strict=True).relative_to(vault_root)
    relative_path = relative.as_posix()
    if relative_path.startswith("./") or ".." in relative.parts:
        raise ValueError(f"Unsafe relative path: {relative_path}")
    return relative_path


def _has_hidden_part(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)
