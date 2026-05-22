from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import frontmatter
from markdown_it import MarkdownIt

from pathlib import Path


TAG_PATTERN = re.compile(r"(?<![\w/])#([A-Za-z0-9_-]+)")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


@dataclass(frozen=True)
class MarkdownFile:
    vault_path: str
    file_path: str
    relative_path: str


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int


@dataclass(frozen=True)
class Document:
    vault_path: str
    file_path: str
    relative_path: str
    raw_content: str
    frontmatter: dict[str, Any]
    headings: list[Heading]
    tags: list[str] = field(default_factory=list)
    wikilinks: list[str] = field(default_factory=list)
    content_hash: str = ""
    mtime_ns: int | None = None
    size_bytes: int | None = None


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


def parse_markdown_file(path: str | Path, vault_path: str | Path) -> Document:
    root = canonicalize_vault_path(vault_path)
    resolved_path = Path(path).expanduser().resolve(strict=True)
    relative_path = relative_posix_path(root, resolved_path)
    raw_bytes = resolved_path.read_bytes()
    parsed = frontmatter.loads(raw_bytes.decode("utf-8"))
    content = parsed.content
    metadata = dict(parsed.metadata)
    stat = resolved_path.stat()

    return Document(
        vault_path=str(root),
        file_path=str(resolved_path),
        relative_path=relative_path,
        raw_content=content,
        frontmatter=metadata,
        headings=parse_headings(content),
        tags=extract_tags(content, metadata),
        wikilinks=extract_wikilinks(content),
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
    )


def parse_headings(content: str) -> list[Heading]:
    parser = MarkdownIt()
    tokens = parser.parse(content)
    headings: list[Heading] = []

    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        next_token = tokens[index + 1] if index + 1 < len(tokens) else None
        title = next_token.content.strip() if next_token and next_token.type == "inline" else ""
        line = token.map[0] + 1 if token.map else 0
        headings.append(Heading(level=int(token.tag[1]), title=title, line=line))

    return headings


def extract_tags(content: str, metadata: dict[str, Any] | None = None) -> list[str]:
    tags: set[str] = set(TAG_PATTERN.findall(content))
    frontmatter_tags = (metadata or {}).get("tags", [])
    if isinstance(frontmatter_tags, str):
        tags.add(frontmatter_tags.lstrip("#"))
    elif isinstance(frontmatter_tags, list):
        for tag in frontmatter_tags:
            if isinstance(tag, str) and tag:
                tags.add(tag.lstrip("#"))
    return sorted(tags)


def extract_wikilinks(content: str) -> list[str]:
    links = {match.group(1).strip() for match in WIKILINK_PATTERN.finditer(content)}
    return sorted(link for link in links if link)


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
