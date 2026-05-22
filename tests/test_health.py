from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import DatabaseStatus


def test_health_returns_ok_when_schema_exists(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["app"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["schema"] == "ok"
    assert body["checks"]["pgvector"] == "ok"
    assert body["checks"]["embedding_config"] == "ok"
    assert body["checks"]["retrieval_ready"] == "not_ready"
    assert body["details"]["embedding_provider"] == "fake"
    assert body["details"]["embedding_model"] == "fake-lexical-v1"
    assert body["details"]["embeddings_current_config"] == 0


def test_health_returns_error_when_schema_missing(
    api_client: TestClient,
    monkeypatch,
) -> None:
    from app import main

    monkeypatch.setattr(
        main,
        "inspect_database",
        lambda settings: DatabaseStatus(database=True, schema=False, pgvector=True),
    )

    response = api_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "schema_not_initialized",
            "message": "Database schema is not initialized.",
            "details": {},
        }
    }


def test_not_found_uses_error_response(api_client: TestClient) -> None:
    response = api_client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "http_error",
            "message": "Not Found",
            "details": {},
        }
    }
