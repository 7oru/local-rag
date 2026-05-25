from __future__ import annotations

from app.chunking import count_tokens
from app.context import TRUNCATION_MARKER, assemble_context
from app.retrieval import RetrievedChunk, to_search_result
from app.schemas import AskResponse, Citation


def chunk(
    *,
    chunk_id: int = 1,
    source: str = "policies/Support Escalation Policy.md",
    heading_path: list[str] | None = None,
    content: str = "Escalate P1 incidents to the incident commander.",
    score: float = 0.8,
    chunk_index: int = 0,
    content_hash: str = "hash-1",
) -> RetrievedChunk:
    resolved_heading_path = ["P1 Escalation"] if heading_path is None else heading_path
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=1,
        source=source,
        relative_path=source,
        heading_path=resolved_heading_path,
        heading=resolved_heading_path[-1] if resolved_heading_path else "",
        content=content,
        score=score,
        chunk_index=chunk_index,
        content_hash=content_hash,
    )


def test_context_sorts_citations_and_formats_scores() -> None:
    lower = chunk(chunk_id=20, source="z.md", score=0.7, chunk_index=0)
    higher_later = chunk(
        chunk_id=10,
        source="a.md",
        heading_path=["Alpha"],
        content="Alpha content.",
        score=0.9,
        chunk_index=5,
        content_hash="hash-2",
    )

    assembled = assemble_context([lower, higher_later], token_budget=300)

    assert assembled.text.startswith("[1] source: a.md")
    assert "[1] source: a.md\nheading: Alpha\nscore: 0.9000" in assembled.text
    assert "[2] source: z.md\nheading: P1 Escalation\nscore: 0.7000" in assembled.text
    assert [citation.source for citation in assembled.citations] == ["a.md", "z.md"]
    assert [citation.score for citation in assembled.citations] == [0.9, 0.7]


def test_context_uses_internal_sort_fields_and_does_not_expose_them_in_api_models() -> None:
    second_by_id = chunk(
        chunk_id=2,
        source="same.md",
        heading_path=["Same"],
        content="Second by id.",
        score=0.8,
        chunk_index=0,
        content_hash="hash-2",
    )
    first_by_id = chunk(
        chunk_id=1,
        source="same.md",
        heading_path=["Same"],
        content="First by id.",
        score=0.8,
        chunk_index=0,
        content_hash="hash-1",
    )

    assembled = assemble_context([second_by_id, first_by_id], token_budget=300)
    search_result = to_search_result(first_by_id).model_dump()
    ask_response = AskResponse(
        mode="rag",
        confidence=0.8,
        answer="answer",
        citations=[Citation(source="same.md", heading="Same", score=0.8)],
    ).model_dump()

    assert assembled.text.index("First by id.") < assembled.text.index("Second by id.")
    assert "chunk_id" not in search_result
    assert "chunk_index" not in search_result
    assert "content_hash" not in search_result
    assert "chunk_id" not in ask_response["citations"][0]
    assert "content_hash" not in ask_response["citations"][0]


def test_context_preserves_source_and_empty_heading() -> None:
    root_chunk = chunk(
        source="00-index.md",
        heading_path=[],
        content="Root content.",
        score=1.2,
    )

    assembled = assemble_context([root_chunk], token_budget=100)

    assert "[1] source: 00-index.md" in assembled.text
    assert "heading: \n" in assembled.text
    assert "score: 1.0000" in assembled.text
    assert assembled.citations[0].source == "00-index.md"
    assert assembled.citations[0].heading == ""
    assert assembled.citations[0].score == 1.0


def test_context_deduplicates_by_source_heading_and_content_hash() -> None:
    original = chunk(chunk_id=1, content="Original.", score=0.9, content_hash="same")
    duplicate = chunk(chunk_id=2, content="Duplicate.", score=0.8, content_hash="same")
    other_heading = chunk(
        chunk_id=3,
        heading_path=["Other"],
        content="Other heading.",
        score=0.7,
        content_hash="same",
    )

    assembled = assemble_context([duplicate, other_heading, original], token_budget=300)

    assert "Original." in assembled.text
    assert "Duplicate." not in assembled.text
    assert "Other heading." in assembled.text
    assert len(assembled.citations) == 2


def test_context_skips_later_block_when_it_exceeds_budget() -> None:
    first = chunk(content="Short enough.", score=0.9, content_hash="first")
    large = chunk(
        chunk_id=2,
        source="large.md",
        heading_path=["Large"],
        content=" ".join(["large"] * 500),
        score=0.8,
        content_hash="large",
    )
    first_only_budget = count_tokens(assemble_context([first], token_budget=200).text)

    assembled = assemble_context([first, large], token_budget=first_only_budget + 1)

    assert "Short enough." in assembled.text
    assert "large.md" not in assembled.text
    assert len(assembled.citations) == 1


def test_context_truncates_first_block_when_it_exceeds_budget() -> None:
    large = chunk(content=" ".join(["alpha"] * 500), score=0.9)
    budget = 60

    assembled = assemble_context([large], token_budget=budget)

    assert TRUNCATION_MARKER in assembled.text
    assert count_tokens(assembled.text) <= budget
    assert len(assembled.citations) == 1


def test_empty_context() -> None:
    assembled = assemble_context([], token_budget=100)

    assert assembled.text == ""
    assert assembled.citations == []
