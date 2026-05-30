from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.retrieval import RetrievalNotReady


def test_ask_stream_api_returns_sse_events(monkeypatch) -> None:
    def fake_stream_answer_question(*args, **kwargs):
        return iter(
            [
                'event: metadata\ndata: {"mode":"rag","confidence":0.8,"citations":[]}\n\n',
                'event: delta\ndata: {"seq":1,"text":"hello"}\n\n',
                'event: done\ndata: {"status":"ok"}\n\n',
            ]
        )

    monkeypatch.setattr("app.main.stream_answer_question", fake_stream_answer_question)
    client = TestClient(app)

    response = client.post("/ask/stream", json={"question": "Question?"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == (
        'event: metadata\ndata: {"mode":"rag","confidence":0.8,"citations":[]}\n\n'
        'event: delta\ndata: {"seq":1,"text":"hello"}\n\n'
        'event: done\ndata: {"status":"ok"}\n\n'
    )


def test_ask_stream_invalid_request_uses_json_error() -> None:
    client = TestClient(app)

    response = client.post("/ask/stream", json={"question": "", "top_k": 0})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "detail" not in body


def test_ask_stream_retrieval_not_ready_uses_json_error(monkeypatch) -> None:
    def raise_not_ready(*args, **kwargs):
        raise RetrievalNotReady("missing embeddings")

    monkeypatch.setattr("app.main.stream_answer_question", raise_not_ready)
    client = TestClient(app)

    response = client.post("/ask/stream", json={"question": "Question?"})

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"]["code"] == "retrieval_not_ready"
    assert body["error"]["details"]["reason"] == "missing embeddings"
