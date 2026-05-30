from __future__ import annotations

from typing import Iterator

from app.confidence import decide_answer_mode
from app.config import Settings, load_settings
from app.context import ContextCitation, assemble_context
from app.llm import LLMClient, LLMError, create_llm_client
from app.retrieval import search
from app.schemas import AskResponse, Citation
from app.sse import SSEEventFormatter


def answer_question(
    question: str,
    *,
    top_k: int = 5,
    fallback: bool = False,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> AskResponse:
    resolved_settings = settings or load_settings()
    retrieval = search(question, top_k=top_k, settings=resolved_settings)
    decision = decide_answer_mode(
        confidence=retrieval.confidence,
        settings=resolved_settings,
        request_fallback=fallback,
    )

    if decision.mode == "no_answer":
        return AskResponse(
            mode="no_answer",
            confidence=decision.confidence,
            answer=_no_answer_message(fallback_requested=fallback, fallback_enabled=decision.fallback_enabled),
            citations=[],
        )

    client = llm_client or create_llm_client(resolved_settings)
    if decision.mode == "fallback":
        llm_response = client.answer_fallback(question=question)
        return AskResponse(
            mode="fallback",
            confidence=decision.confidence,
            answer=llm_response.answer,
            citations=[],
        )

    assembled = assemble_context(
        retrieval.chunks,
        token_budget=resolved_settings.rag_context_token_budget,
    )
    llm_response = client.answer_rag(
        question=question,
        context=assembled.text,
        citations=assembled.citations,
    )
    return AskResponse(
        mode="rag",
        confidence=decision.confidence,
        answer=llm_response.answer,
        citations=[
            Citation(source=citation.source, heading=citation.heading, score=citation.score)
            for citation in assembled.citations
        ],
    )


def stream_answer_question(
    question: str,
    *,
    top_k: int = 5,
    fallback: bool = False,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> Iterator[str]:
    resolved_settings = settings or load_settings()
    retrieval = search(question, top_k=top_k, settings=resolved_settings)
    decision = decide_answer_mode(
        confidence=retrieval.confidence,
        settings=resolved_settings,
        request_fallback=fallback,
    )

    formatter = SSEEventFormatter()
    if decision.mode == "no_answer":
        return _stream_no_answer(
            formatter,
            confidence=decision.confidence,
            fallback_requested=fallback,
            fallback_enabled=decision.fallback_enabled,
        )

    client = llm_client or create_llm_client(resolved_settings)
    if decision.mode == "fallback":
        return _stream_fallback_answer(
            formatter,
            client=client,
            question=question,
            confidence=decision.confidence,
        )

    assembled = assemble_context(
        retrieval.chunks,
        token_budget=resolved_settings.rag_context_token_budget,
    )
    return _stream_rag_answer(
        formatter,
        client=client,
        question=question,
        context=assembled.text,
        citations=assembled.citations,
        confidence=decision.confidence,
    )


def _no_answer_message(*, fallback_requested: bool, fallback_enabled: bool) -> str:
    if fallback_requested and not fallback_enabled:
        return (
            "The local knowledge base does not contain a confident answer, "
            "and fallback is globally disabled."
        )
    return "The local knowledge base does not contain a confident answer."


def _stream_no_answer(
    formatter: SSEEventFormatter,
    *,
    confidence: float,
    fallback_requested: bool,
    fallback_enabled: bool,
) -> Iterator[str]:
    yield formatter.metadata(
        {
            "mode": "no_answer",
            "confidence": confidence,
            "citations": [],
        }
    )
    yield formatter.delta(
        _no_answer_message(
            fallback_requested=fallback_requested,
            fallback_enabled=fallback_enabled,
        )
    )
    yield formatter.done()


def _stream_fallback_answer(
    formatter: SSEEventFormatter,
    *,
    client: LLMClient,
    question: str,
    confidence: float,
) -> Iterator[str]:
    yield formatter.metadata(
        {
            "mode": "fallback",
            "confidence": confidence,
            "citations": [],
        }
    )
    yield from _stream_llm_chunks(formatter, client.stream_fallback(question=question))


def _stream_rag_answer(
    formatter: SSEEventFormatter,
    *,
    client: LLMClient,
    question: str,
    context: str,
    citations: list[ContextCitation],
    confidence: float,
) -> Iterator[str]:
    yield formatter.metadata(
        {
            "mode": "rag",
            "confidence": confidence,
            "citations": [
                {
                    "source": citation.source,
                    "heading": citation.heading,
                    "score": citation.score,
                }
                for citation in citations
            ],
        }
    )
    yield from _stream_llm_chunks(
        formatter,
        client.stream_rag(
            question=question,
            context=context,
            citations=citations,
        ),
    )


def _stream_llm_chunks(formatter: SSEEventFormatter, chunks: Iterator[str]) -> Iterator[str]:
    try:
        for text in chunks:
            if text:
                yield formatter.delta(text)
    except LLMError as exc:
        yield formatter.error(exc.code, exc.message)
        yield formatter.done(status="error")
        return
    yield formatter.done()
