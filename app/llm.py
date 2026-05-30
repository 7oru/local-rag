from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Protocol

import httpx

from app.config import ConfigError, Settings, load_settings
from app.context import ContextCitation
from app.prompts import (
    FALLBACK_SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT,
    build_fallback_user_prompt,
    build_rag_user_prompt,
)


class LLMError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LLMResponse:
    answer: str


class LLMClient(Protocol):
    def answer_rag(
        self,
        *,
        question: str,
        context: str,
        citations: list[ContextCitation],
    ) -> LLMResponse:
        ...

    def answer_fallback(self, *, question: str) -> LLMResponse:
        ...

    def stream_rag(
        self,
        *,
        question: str,
        context: str,
        citations: list[ContextCitation],
    ) -> Iterator[str]:
        ...

    def stream_fallback(self, *, question: str) -> Iterator[str]:
        ...


class FakeLLMClient:
    def answer_rag(
        self,
        *,
        question: str,
        context: str,
        citations: list[ContextCitation],
    ) -> LLMResponse:
        if not citations:
            return LLMResponse(
                answer="The local knowledge base does not contain enough information."
            )

        citation_numbers = ", ".join(f"[{index}]" for index in range(1, len(citations) + 1))
        sources = ", ".join(citation.source for citation in citations)
        first_context_line = _first_content_line(context)
        return LLMResponse(
            answer=(
                f"Based on the local knowledge base {citation_numbers}: "
                f"{first_context_line} Sources: {sources}."
            )
        )

    def answer_fallback(self, *, question: str) -> LLMResponse:
        return LLMResponse(
            answer=(
                "This answer is not from the local knowledge base. "
                f"General answer for: {question}"
            )
        )

    def stream_rag(
        self,
        *,
        question: str,
        context: str,
        citations: list[ContextCitation],
    ) -> Iterator[str]:
        yield from _chunk_text(
            self.answer_rag(
                question=question,
                context=context,
                citations=citations,
            ).answer
        )

    def stream_fallback(self, *, question: str) -> Iterator[str]:
        yield from _chunk_text(self.answer_fallback(question=question).answer)


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        settings: Settings,
        http_client: httpx.Client | None = None,
        http_client_factory: Callable[[float], httpx.Client] | None = None,
    ) -> None:
        _validate_openai_settings(settings)
        self._base_url = settings.llm_base_url.rstrip("/")  # type: ignore[union-attr]
        self._api_key = settings.llm_api_key or ""
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout_seconds
        if http_client is not None:
            self._client = http_client
        elif http_client_factory is not None:
            self._client = http_client_factory(self._timeout)
        else:
            self._client = httpx.Client(timeout=self._timeout)

    @property
    def timeout(self) -> float:
        return self._timeout

    def answer_rag(
        self,
        *,
        question: str,
        context: str,
        citations: list[ContextCitation],
    ) -> LLMResponse:
        del citations
        return self._chat(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_prompt=build_rag_user_prompt(question=question, context=context),
        )

    def answer_fallback(self, *, question: str) -> LLMResponse:
        return self._chat(
            system_prompt=FALLBACK_SYSTEM_PROMPT,
            user_prompt=build_fallback_user_prompt(question=question),
        )

    def stream_rag(
        self,
        *,
        question: str,
        context: str,
        citations: list[ContextCitation],
    ) -> Iterator[str]:
        del citations
        yield from self._chat_stream(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_prompt=build_rag_user_prompt(question=question, context=context),
        )

    def stream_fallback(self, *, question: str) -> Iterator[str]:
        yield from self._chat_stream(
            system_prompt=FALLBACK_SYSTEM_PROMPT,
            user_prompt=build_fallback_user_prompt(question=question),
        )

    def _chat(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=self._request_body(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    stream=False,
                ),
            )
        except httpx.TimeoutException as exc:
            raise LLMError("llm_timeout", "LLM request timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("llm_upstream_error", "LLM upstream request failed.") from exc

        if response.status_code in {401, 403}:
            raise LLMError("llm_auth_failed", "LLM authentication failed.")
        if response.status_code == 429:
            raise LLMError("llm_rate_limited", "LLM upstream rate limited the request.")
        if response.status_code >= 400:
            raise LLMError("llm_upstream_error", "LLM upstream returned an error.")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("llm_upstream_error", "LLM upstream response was malformed.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMError("llm_upstream_error", "LLM upstream response was empty.")

        return LLMResponse(answer=content.strip())

    def _chat_stream(self, *, system_prompt: str, user_prompt: str) -> Iterator[str]:
        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=self._request_body(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    stream=True,
                ),
            ) as response:
                _raise_for_status(response)
                saw_content = False
                saw_done = False
                for line in response.iter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    content = _extract_stream_delta(data)
                    if content:
                        saw_content = True
                        yield content

                if not saw_done:
                    raise LLMError(
                        "llm_upstream_error",
                        "LLM upstream stream ended unexpectedly.",
                    )
                if not saw_content:
                    raise LLMError("llm_upstream_error", "LLM upstream stream was empty.")
        except httpx.TimeoutException as exc:
            raise LLMError("llm_timeout", "LLM request timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("llm_upstream_error", "LLM upstream request failed.") from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _request_body(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "stream": stream,
        }


def create_llm_client(
    settings: Settings | None = None,
    *,
    http_client: httpx.Client | None = None,
    http_client_factory: Callable[[float], httpx.Client] | None = None,
) -> LLMClient:
    resolved = settings or load_settings()
    if resolved.llm_provider == "fake":
        return FakeLLMClient()
    if resolved.llm_provider == "openai-compatible":
        return OpenAICompatibleLLMClient(
            settings=resolved,
            http_client=http_client,
            http_client_factory=http_client_factory,
        )
    raise LLMError("llm_config_missing", "Unsupported LLM provider.")


def _validate_openai_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("LLM_BASE_URL", settings.llm_base_url),
            ("LLM_API_KEY", settings.llm_api_key),
            ("LLM_MODEL", settings.llm_model),
        )
        if not value
    ]
    if missing:
        raise LLMError(
            "llm_config_missing",
            "LLM_PROVIDER=openai-compatible requires " + ", ".join(missing) + ".",
        )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise LLMError("llm_auth_failed", "LLM authentication failed.")
    if response.status_code == 429:
        raise LLMError("llm_rate_limited", "LLM upstream rate limited the request.")
    if response.status_code >= 400:
        raise LLMError("llm_upstream_error", "LLM upstream returned an error.")


def _extract_stream_delta(data: str) -> str:
    try:
        body = json.loads(data)
        content = body["choices"][0]["delta"].get("content")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LLMError("llm_upstream_error", "LLM upstream stream was malformed.") from exc

    if content is None:
        return ""
    if not isinstance(content, str):
        raise LLMError("llm_upstream_error", "LLM upstream stream was malformed.")
    return content


def _chunk_text(text: str, *, chunk_size: int = 24) -> Iterator[str]:
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


def _first_content_line(context: str) -> str:
    lines = context.splitlines()
    for index, line in enumerate(lines):
        if line == "content:" and index + 1 < len(lines):
            content = lines[index + 1].strip()
            if content:
                return content
    return "The retrieved context contains relevant information."


def _run_live_check() -> int:
    try:
        settings = load_settings()
        client = create_llm_client(settings)
        response = client.answer_fallback(question="Reply with ok.")
    except (ConfigError, LLMError) as exc:
        print(f"chat_ok=false")
        print(f"error={getattr(exc, 'code', 'configuration_error')}")
        return 1

    print(f"llm_provider={settings.llm_provider}")
    print(f"llm_base_url_present={str(bool(settings.llm_base_url)).lower()}")
    print(f"llm_model_present={str(bool(settings.llm_model)).lower()}")
    print(f"chat_ok={str(bool(response.answer)).lower()}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM client utility.")
    parser.add_argument("--live", action="store_true", help="Run a live chat completion check.")
    args = parser.parse_args()
    if args.live:
        raise SystemExit(_run_live_check())
    parser.print_help()


if __name__ == "__main__":
    main()
