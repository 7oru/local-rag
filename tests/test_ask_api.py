from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.ingest import ingest_vault
from app.llm import LLMResponse


class ExplodingLLMClient:
    def answer_rag(self, **kwargs) -> LLMResponse:
        raise AssertionError("LLM should not be called")

    def answer_fallback(self, **kwargs) -> LLMResponse:
        raise AssertionError("LLM should not be called")


def test_ask_api_high_confidence_returns_rag_with_citations(api_client: TestClient) -> None:
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    response = api_client.post(
        "/ask",
        json={"question": "客户 P1 工单应该怎么升级？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rag"
    assert body["confidence"] >= settings.rag_min_similarity
    assert body["citations"]
    assert body["citations"][0]["source"] == "policies/Support Escalation Policy.md"
    assert "[1]" in body["answer"]
    assert "chunk_id" not in body["citations"][0]
    assert "content_hash" not in body["citations"][0]


def test_ask_api_low_confidence_without_fallback_returns_no_answer_and_skips_llm(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.99")
    monkeypatch.setattr("app.ask.create_llm_client", lambda settings: ExplodingLLMClient())
    ingest_vault("samples/acme-vault", settings=load_settings())

    response = api_client.post(
        "/ask",
        json={"question": "完全不存在的随机问题 xyz"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "no_answer"
    assert body["citations"] == []
    assert "does not contain a confident answer" in body["answer"]


def test_ask_api_fallback_request_with_global_fallback_disabled_returns_no_answer(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.99")
    monkeypatch.setenv("RAG_FALLBACK_ENABLED", "false")
    monkeypatch.setattr("app.ask.create_llm_client", lambda settings: ExplodingLLMClient())
    ingest_vault("samples/acme-vault", settings=load_settings())

    response = api_client.post(
        "/ask",
        json={"question": "完全不存在的随机问题 xyz", "fallback": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "no_answer"
    assert body["citations"] == []
    assert "fallback is globally disabled" in body["answer"]


def test_ask_api_global_fallback_enabled_returns_fallback_without_citations(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.99")
    monkeypatch.setenv("RAG_FALLBACK_ENABLED", "true")
    ingest_vault("samples/acme-vault", settings=load_settings())

    response = api_client.post(
        "/ask",
        json={"question": "完全不存在的随机问题 xyz", "fallback": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "fallback"
    assert body["citations"] == []
    assert "not from the local knowledge base" in body["answer"]


def test_ask_api_invalid_request_uses_error_response(api_client: TestClient) -> None:
    response = api_client.post("/ask", json={"question": "", "top_k": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "detail" not in body
