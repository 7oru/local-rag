from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    AskRequest,
    AskResponse,
    Citation,
    ErrorBody,
    ErrorResponse,
    HealthChecks,
    HealthDetails,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)


def test_all_schema_models_construct_and_serialize() -> None:
    health = HealthResponse(
        status="ok",
        checks=HealthChecks(
            app="ok",
            database="ok",
            schema="ok",
            pgvector="ok",
            embedding_config="ok",
            retrieval_ready="not_ready",
        ),
        details=HealthDetails(
            embedding_provider="fake",
            embedding_model="fake-lexical-v1",
            documents=0,
            chunks=0,
            embeddings_current_config=0,
        ),
    )
    result = SearchResult(
        source="support/Common Customer Issues.md",
        relative_path="support/Common Customer Issues.md",
        heading_path=["Support", "P1 Escalation"],
        heading="P1 Escalation",
        content="Escalate customer P1 incidents to the on-call engineer.",
        score=0.91,
    )
    search = SearchResponse(
        query="客户 P1 工单应该如何升级？",
        top_k=5,
        results=[result],
        confidence=0.91,
    )
    ask = AskResponse(
        mode="rag",
        confidence=0.91,
        answer="按 P1 escalation policy 处理。",
        citations=[
            Citation(
                source="support/Common Customer Issues.md",
                heading="P1 Escalation",
                score=0.91,
            )
        ],
    )

    assert health.model_dump()["checks"]["retrieval_ready"] == "not_ready"
    assert search.model_dump()["results"][0]["source"] == result.relative_path
    assert search.model_dump()["results"][0]["heading"] == "P1 Escalation"
    assert ask.model_dump()["citations"][0]["source"] == result.source


@pytest.mark.parametrize("model,field", [(SearchRequest, "query"), (AskRequest, "question")])
def test_empty_query_and_question_are_rejected(model, field: str) -> None:
    with pytest.raises(ValidationError):
        model(**{field: "   "})


@pytest.mark.parametrize("top_k", [0, 21])
def test_invalid_search_top_k_is_rejected(top_k: int) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="valid", top_k=top_k)


@pytest.mark.parametrize("top_k", [0, 21])
def test_invalid_ask_top_k_is_rejected(top_k: int) -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="valid", top_k=top_k)


def test_ask_response_rejects_mixed_mode() -> None:
    with pytest.raises(ValidationError):
        AskResponse(mode="mixed", confidence=0.5, answer="", citations=[])


def test_error_response_top_level_shape() -> None:
    response = ErrorResponse(
        error=ErrorBody(
            code="invalid_request",
            message="Request validation failed.",
            details={"field": "query"},
        )
    )

    assert response.model_dump() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
            "details": {"field": "query"},
        }
    }


def test_search_result_source_and_heading_relationships_are_enforced() -> None:
    with pytest.raises(ValidationError):
        SearchResult(
            source="a.md",
            relative_path="b.md",
            heading_path=["Heading"],
            heading="Heading",
            content="content",
            score=0.5,
        )

    with pytest.raises(ValidationError):
        SearchResult(
            source="a.md",
            relative_path="a.md",
            heading_path=[],
            heading="a.md",
            content="content",
            score=0.5,
        )
