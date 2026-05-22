from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import tiktoken

from app.markdown import Document


TARGET_MIN_TOKENS = 400
TARGET_MAX_TOKENS = 800
MAX_TOKENS = 1200
OVERLAP_TOKENS = 80
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    content: str
    file_path: str
    relative_path: str
    heading_path: list[str]
    frontmatter: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    wikilinks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    token_count: int = 0


@dataclass(frozen=True)
class Section:
    content: str
    heading_path: list[str]


def chunk_document(
    document: Document,
    *,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[Chunk]:
    chunks: list[Chunk] = []

    for section in split_heading_sections(document):
        content = section.content.strip()
        if not content:
            continue

        for piece in split_text_by_tokens(
            content,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        ):
            chunks.append(
                build_chunk(
                    document=document,
                    chunk_index=len(chunks),
                    content=piece,
                    heading_path=section.heading_path,
                )
            )

    return chunks


def split_heading_sections(document: Document) -> list[Section]:
    lines = document.raw_content.splitlines()
    sections: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_heading_path: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(Section(content=content, heading_path=list(current_heading_path)))
        current_lines = []

    for line in lines:
        match = HEADING_PATTERN.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack[:] = [
                (existing_level, existing_title)
                for existing_level, existing_title in heading_stack
                if existing_level < level
            ]
            heading_stack.append((level, title))
            current_heading_path = [title for _, title in heading_stack]
        current_lines.append(line)

    flush()
    return sections


def split_text_by_tokens(
    text: str,
    *,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[str]:
    token_ids = encoding().encode(text)
    if len(token_ids) <= max_tokens:
        return [text]

    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    pieces: list[str] = []
    start = 0
    step = max_tokens - overlap_tokens
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        pieces.append(encoding().decode(token_ids[start:end]).strip())
        if end == len(token_ids):
            break
        start += step

    return [piece for piece in pieces if piece]


def build_chunk(
    *,
    document: Document,
    chunk_index: int,
    content: str,
    heading_path: list[str],
) -> Chunk:
    token_count = count_tokens(content)
    return Chunk(
        chunk_index=chunk_index,
        content=content,
        file_path=document.file_path,
        relative_path=document.relative_path,
        heading_path=list(heading_path),
        frontmatter=dict(document.frontmatter),
        tags=list(document.tags),
        wikilinks=list(document.wikilinks),
        metadata={
            "source_document_hash": document.content_hash,
            "target_token_range": [TARGET_MIN_TOKENS, TARGET_MAX_TOKENS],
            "max_tokens": MAX_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
        },
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        token_count=token_count,
    )


def count_tokens(text: str) -> int:
    return len(encoding().encode(text))


@lru_cache(maxsize=1)
def encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")
