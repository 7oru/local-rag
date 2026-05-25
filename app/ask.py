from __future__ import annotations

from app.confidence import decide_answer_mode
from app.config import Settings, load_settings
from app.context import assemble_context
from app.llm import LLMClient, create_llm_client
from app.retrieval import search
from app.schemas import AskResponse, Citation


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


def _no_answer_message(*, fallback_requested: bool, fallback_enabled: bool) -> str:
    if fallback_requested and not fallback_enabled:
        return (
            "The local knowledge base does not contain a confident answer, "
            "and fallback is globally disabled."
        )
    return "The local knowledge base does not contain a confident answer."
