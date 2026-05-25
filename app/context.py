from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.chunking import count_tokens, encoding
from app.retrieval import RetrievedChunk, clamp_score


TRUNCATION_MARKER = "[truncated]"


@dataclass(frozen=True)
class ContextCitation:
    source: str
    heading: str
    score: float


@dataclass(frozen=True)
class AssembledContext:
    text: str
    citations: list[ContextCitation]


def assemble_context(
    chunks: Sequence[RetrievedChunk],
    *,
    token_budget: int,
) -> AssembledContext:
    if token_budget <= 0:
        return AssembledContext(text="", citations=[])

    ordered_chunks = _dedupe_chunks(_sort_chunks(chunks))
    blocks: list[str] = []
    citations: list[ContextCitation] = []

    for chunk in ordered_chunks:
        number = len(blocks) + 1
        block = _format_block(number, chunk)
        candidate = _join_blocks([*blocks, block])
        if count_tokens(candidate) <= token_budget:
            blocks.append(block)
            citations.append(_citation_for(chunk))
            continue

        if blocks:
            continue

        truncated_block = _truncate_first_block(number, chunk, token_budget)
        if truncated_block:
            blocks.append(truncated_block)
            citations.append(_citation_for(chunk))
        break

    return AssembledContext(text=_join_blocks(blocks), citations=citations)


def _sort_chunks(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    return sorted(
        chunks,
        key=lambda chunk: (
            -clamp_score(chunk.score),
            chunk.source,
            tuple(chunk.heading_path),
            chunk.chunk_index,
            chunk.chunk_id,
        ),
    )


def _dedupe_chunks(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    unique: list[RetrievedChunk] = []
    for chunk in chunks:
        key = (chunk.source, tuple(chunk.heading_path), chunk.content_hash)
        if key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
    return unique


def _citation_for(chunk: RetrievedChunk) -> ContextCitation:
    return ContextCitation(
        source=chunk.source,
        heading=chunk.heading,
        score=clamp_score(chunk.score),
    )


def _format_block(number: int, chunk: RetrievedChunk, content: str | None = None) -> str:
    return "\n".join(
        [
            f"[{number}] source: {chunk.source}",
            f"heading: {chunk.heading}",
            f"score: {clamp_score(chunk.score):.4f}",
            "content:",
            chunk.content if content is None else content,
        ]
    )


def _join_blocks(blocks: Sequence[str]) -> str:
    return "\n\n".join(blocks)


def _truncate_first_block(
    number: int,
    chunk: RetrievedChunk,
    token_budget: int,
) -> str:
    marker_content = TRUNCATION_MARKER
    if count_tokens(_format_block(number, chunk, marker_content)) > token_budget:
        return ""

    token_ids = encoding().encode(chunk.content)
    low = 0
    high = len(token_ids)
    best = marker_content
    while low <= high:
        mid = (low + high) // 2
        prefix = encoding().decode(token_ids[:mid]).strip()
        content = f"{prefix}\n{TRUNCATION_MARKER}" if prefix else marker_content
        block = _format_block(number, chunk, content)
        if count_tokens(block) <= token_budget:
            best = content
            low = mid + 1
        else:
            high = mid - 1

    return _format_block(number, chunk, best)
