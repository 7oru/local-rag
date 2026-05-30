from __future__ import annotations

import json
from typing import Iterator

import pytest

from app.ask import stream_answer_question
from app.config import load_settings
from app.llm import LLMError, LLMResponse
from app.retrieval import RetrievalResult, RetrievedChunk


class ExplodingLLMClient:
    def answer_rag(self, **kwargs) -> LLMResponse:
        raise AssertionError("LLM should not be called")

    def answer_fallback(self, **kwargs) -> LLMResponse:
        raise AssertionError("LLM should not be called")

    def stream_rag(self, **kwargs) -> Iterator[str]:
        raise AssertionError("LLM should not be called")
        yield ""

    def stream_fallback(self, **kwargs) -> Iterator[str]:
        raise AssertionError("LLM should not be called")
        yield ""


class FailingStreamLLMClient:
    def stream_rag(self, **kwargs) -> Iterator[str]:
        yield "partial"
        raise LLMError("llm_upstream_error", "LLM stream failed")


def test_stream_answer_rag_metadata_citations_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings()
    stub_search(monkeypatch, confidence=0.8)

    events = parse_events(
        stream_answer_question(
            "客户 P1 工单应该怎么升级？",
            settings=settings,
        )
    )

    assert events[0] == (
        "metadata",
        {
            "mode": "rag",
            "confidence": events[0][1]["confidence"],
            "citations": events[0][1]["citations"],
        },
    )
    assert events[0][1]["confidence"] >= settings.rag_min_similarity
    assert events[0][1]["citations"][0]["source"] == "policies/Support Escalation Policy.md"
    assert [event for event, _ in events].count("metadata") == 1
    assert any(event == "delta" for event, _ in events)
    assert events[-1] == ("done", {"status": "ok"})


def test_stream_answer_no_answer_skips_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.99")
    monkeypatch.setattr(
        "app.ask.create_llm_client",
        lambda settings: (_ for _ in ()).throw(AssertionError("LLM should not be created")),
    )
    stub_search(monkeypatch, confidence=0.01)
    settings = load_settings()

    events = parse_events(
        stream_answer_question(
            "完全不存在的随机问题 xyz",
            settings=settings,
        )
    )

    assert events[0] == (
        "metadata",
        {
            "mode": "no_answer",
            "confidence": events[0][1]["confidence"],
            "citations": [],
        },
    )
    assert events[1][0] == "delta"
    assert "does not contain a confident answer" in events[1][1]["text"]
    assert events[-1] == ("done", {"status": "ok"})


def test_stream_answer_fallback_has_empty_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.99")
    monkeypatch.setenv("RAG_FALLBACK_ENABLED", "true")
    stub_search(monkeypatch, confidence=0.01)
    settings = load_settings()

    events = parse_events(
        stream_answer_question(
            "完全不存在的随机问题 xyz",
            fallback=True,
            settings=settings,
        )
    )

    assert events[0] == (
        "metadata",
        {
            "mode": "fallback",
            "confidence": events[0][1]["confidence"],
            "citations": [],
        },
    )
    answer_text = "".join(data["text"] for event, data in events if event == "delta")
    assert "not from the local knowledge base" in answer_text
    assert events[-1] == ("done", {"status": "ok"})


def test_stream_answer_converts_midstream_llm_error_to_sse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()
    stub_search(monkeypatch, confidence=0.8)

    events = parse_events(
        stream_answer_question(
            "客户 P1 工单应该怎么升级？",
            settings=settings,
            llm_client=FailingStreamLLMClient(),  # type: ignore[arg-type]
        )
    )

    assert events[0][0] == "metadata"
    assert ("delta", {"seq": 1, "text": "partial"}) in events
    assert events[-2] == (
        "error",
        {"code": "llm_upstream_error", "message": "LLM stream failed"},
    )
    assert events[-1] == ("done", {"status": "error"})


def stub_search(monkeypatch: pytest.MonkeyPatch, *, confidence: float) -> None:
    def fake_search(query: str, *, top_k: int = 5, settings=None) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            top_k=top_k,
            confidence=confidence,
            chunks=[
                RetrievedChunk(
                    chunk_id=1,
                    document_id=1,
                    source="policies/Support Escalation Policy.md",
                    relative_path="policies/Support Escalation Policy.md",
                    heading_path=["Support", "P1 Escalation"],
                    heading="P1 Escalation",
                    content="P1 tickets require an escalation owner and on-call engineer.",
                    score=confidence,
                    chunk_index=0,
                    content_hash="chunk-hash",
                )
            ],
        )

    monkeypatch.setattr("app.ask.search", fake_search)


def parse_events(events: Iterator[str]) -> list[tuple[str, dict]]:
    parsed: list[tuple[str, dict]] = []
    for event in events:
        lines = event.strip().splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        parsed.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return parsed
