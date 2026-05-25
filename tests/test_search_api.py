from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import load_settings
from app.ingest import ingest_vault
from app.retrieval import search as retrieve


def test_search_api_returns_search_response(api_client: TestClient) -> None:
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    response = api_client.post(
        "/search",
        json={"query": "客户 P1 工单应该怎么升级？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "客户 P1 工单应该怎么升级？"
    assert body["top_k"] == 5
    assert body["confidence"] == body["results"][0]["score"]
    assert body["results"][0]["source"] == "policies/Support Escalation Policy.md"
    assert body["results"][0]["source"] == body["results"][0]["relative_path"]
    assert body["results"][0]["heading"] == "P1 Escalation"
    assert "chunk_id" not in body["results"][0]
    assert "content_hash" not in body["results"][0]


def test_internal_retrieval_includes_private_fields(api_client: TestClient) -> None:
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    result = retrieve("API 延迟升高时值班工程师应该怎么处理？", settings=settings)
    top = result.chunks[0]

    assert top.source == "runbooks/API Latency Runbook.md"
    assert top.relative_path == top.source
    assert top.chunk_id > 0
    assert top.document_id > 0
    assert top.chunk_index >= 0
    assert top.content_hash
    assert result.confidence == top.score


def test_search_top_k_validation_uses_error_response(api_client: TestClient) -> None:
    response = api_client.post("/search", json={"query": "valid", "top_k": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "detail" not in body


def test_search_returns_retrieval_not_ready_without_embeddings(
    api_client: TestClient,
) -> None:
    response = api_client.post("/search", json={"query": "客户 P1 工单"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "retrieval_not_ready"


def test_search_cli_uses_shared_retrieval_service(run_cli, clean_test_db: None) -> None:
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    result = run_cli("search", "客户 P1 工单应该怎么升级？", check=True)
    body = json.loads(result.stdout)

    assert body["confidence"] == body["results"][0]["score"]
    assert body["results"][0]["source"] == "policies/Support Escalation Policy.md"
