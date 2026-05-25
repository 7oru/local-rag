from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import load_settings
from app.ingest import ingest_vault
from app.main import llm_error_status
from app.schemas import AskRequest, AskResponse, Citation, HealthResponse, SearchRequest, SearchResponse


def assert_error_shape(body: dict[str, object], code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], dict)
    assert "detail" not in body


def test_openapi_uses_owned_request_and_response_schemas(api_client: TestClient) -> None:
    openapi = api_client.get("/openapi.json").json()
    schemas = openapi["components"]["schemas"]

    for model in [HealthResponse, SearchRequest, SearchResponse, AskRequest, AskResponse, Citation]:
        assert model.__name__ in schemas

    assert openapi["paths"]["/search"]["post"]["requestBody"]
    assert openapi["paths"]["/search"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/SearchResponse")
    assert openapi["paths"]["/ask"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/AskResponse")


def test_invalid_search_top_k_uses_error_response(api_client: TestClient) -> None:
    response = api_client.post("/search", json={"query": "valid", "top_k": 0})

    assert response.status_code == 422
    assert_error_shape(response.json(), "invalid_request")


def test_empty_search_query_uses_error_response(api_client: TestClient) -> None:
    response = api_client.post("/search", json={"query": "   "})

    assert response.status_code == 422
    assert_error_shape(response.json(), "invalid_request")


def test_empty_ask_question_uses_error_response(api_client: TestClient) -> None:
    response = api_client.post("/ask", json={"question": "   "})

    assert response.status_code == 422
    assert_error_shape(response.json(), "invalid_request")


def test_malformed_body_uses_error_response(api_client: TestClient) -> None:
    response = api_client.post(
        "/ask",
        content="{",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert_error_shape(response.json(), "invalid_request")


def test_llm_config_missing_maps_to_error_response(
    api_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    response = api_client.post("/ask", json={"question": "客户 P1 工单应该怎么升级？"})

    assert response.status_code == 503
    assert_error_shape(response.json(), "llm_config_missing")


def test_llm_error_status_mapping() -> None:
    assert llm_error_status("llm_config_missing") == 503
    assert llm_error_status("llm_timeout") == 504
    assert llm_error_status("llm_auth_failed") == 502
    assert llm_error_status("llm_rate_limited") == 503
    assert llm_error_status("llm_upstream_error") == 502


def test_no_answer_is_success_response(api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.99")
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    response = api_client.post("/ask", json={"question": "完全不存在的随机问题 xyz"})

    assert response.status_code == 200
    assert response.json()["mode"] == "no_answer"
