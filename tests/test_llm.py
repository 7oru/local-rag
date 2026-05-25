from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.config import load_settings
from app.context import ContextCitation
from app.llm import LLMError, OpenAICompatibleLLMClient, create_llm_client
from app.prompts import FALLBACK_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT, build_fallback_user_prompt


def openai_settings(**overrides):
    settings = load_settings()
    values = {
        "llm_provider": "openai-compatible",
        "llm_base_url": "https://llm.example/v1/",
        "llm_api_key": "secret-token",
        "llm_model": "demo-model",
        "llm_timeout_seconds": 7.5,
    }
    values.update(overrides)
    return replace(settings, **values)


def test_fake_llm_is_deterministic_and_uses_context_without_network() -> None:
    client = create_llm_client(replace(load_settings(), llm_provider="fake"))
    citations = [ContextCitation(source="policy.md", heading="Policy", score=0.8)]

    first = client.answer_rag(
        question="What is the policy?",
        context="[1] source: policy.md\nheading: Policy\nscore: 0.8000\ncontent:\nUse P1.",
        citations=citations,
    )
    second = client.answer_rag(
        question="What is the policy?",
        context="[1] source: policy.md\nheading: Policy\nscore: 0.8000\ncontent:\nUse P1.",
        citations=citations,
    )

    assert first == second
    assert "[1]" in first.answer
    assert "policy.md" in first.answer


@pytest.mark.parametrize("field", ["llm_base_url", "llm_api_key", "llm_model"])
def test_openai_compatible_missing_config_maps_to_llm_config_missing(field: str) -> None:
    settings = openai_settings(**{field: None if field != "llm_model" else ""})

    with pytest.raises(LLMError) as exc_info:
        create_llm_client(settings)

    assert exc_info.value.code == "llm_config_missing"
    assert "secret-token" not in str(exc_info.value)


def test_openai_compatible_passes_timeout_to_http_client_factory() -> None:
    captured: dict[str, float] = {}

    def factory(timeout: float) -> httpx.Client:
        captured["timeout"] = timeout
        return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_json())))

    client = OpenAICompatibleLLMClient(settings=openai_settings(), http_client_factory=factory)

    assert client.timeout == 7.5
    assert captured["timeout"] == 7.5


def test_openai_compatible_sends_non_streaming_chat_request_and_reads_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = request.read()
        return httpx.Response(200, json=response_json("answer from model"))

    client = OpenAICompatibleLLMClient(
        settings=openai_settings(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.answer_rag(
        question="Question?",
        context="[1] source: source.md\nheading: H\nscore: 0.8000\ncontent:\nAnswer.",
        citations=[ContextCitation(source="source.md", heading="H", score=0.8)],
    )

    body = httpx.Request("POST", "https://example.invalid", content=captured["body"]).read()
    json_body = httpx.Response(200, content=body).json()
    assert response.answer == "answer from model"
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret-token"
    assert captured["content_type"] == "application/json"
    assert json_body["model"] == "demo-model"
    assert json_body["temperature"] == 0
    assert json_body["stream"] is False
    assert json_body["messages"][0] == {"role": "system", "content": RAG_SYSTEM_PROMPT}
    assert json_body["messages"][1]["role"] == "user"
    assert "Context:" in json_body["messages"][1]["content"]


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (httpx.TimeoutException("timeout"), "llm_timeout"),
        (httpx.ConnectError("network"), "llm_upstream_error"),
    ],
)
def test_openai_compatible_maps_http_exceptions(exception: Exception, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    client = OpenAICompatibleLLMClient(
        settings=openai_settings(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMError) as exc_info:
        client.answer_fallback(question="Question?")

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (401, "llm_auth_failed"),
        (403, "llm_auth_failed"),
        (429, "llm_rate_limited"),
        (500, "llm_upstream_error"),
    ],
)
def test_openai_compatible_maps_status_codes(status_code: int, code: str) -> None:
    client = OpenAICompatibleLLMClient(
        settings=openai_settings(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status_code, json={}))
        ),
    )

    with pytest.raises(LLMError) as exc_info:
        client.answer_fallback(question="Question?")

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_openai_compatible_maps_malformed_response(payload: dict[str, object]) -> None:
    client = OpenAICompatibleLLMClient(
        settings=openai_settings(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )

    with pytest.raises(LLMError) as exc_info:
        client.answer_fallback(question="Question?")

    assert exc_info.value.code == "llm_upstream_error"


def test_prompts_constrain_rag_and_identify_fallback() -> None:
    fallback_user_prompt = build_fallback_user_prompt(question="What now?")

    assert "Answer only from the provided context" in RAG_SYSTEM_PROMPT
    assert "not from the local knowledge base" in FALLBACK_SYSTEM_PROMPT
    assert "not from the local knowledge base" in fallback_user_prompt


def response_json(content: str = "ok") -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}
