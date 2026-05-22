from __future__ import annotations

import pytest

from app.confidence import decide_answer_mode
from app.config import load_settings


def test_fake_default_threshold_low_confidence_is_no_answer(
    test_env: dict[str, str],
) -> None:
    settings = load_settings()

    decision = decide_answer_mode(confidence=0.19, settings=settings)

    assert settings.rag_min_similarity == 0.20
    assert decision.mode == "no_answer"
    assert decision.high_confidence is False


def test_score_equal_to_threshold_is_rag(test_env: dict[str, str]) -> None:
    settings = load_settings()

    decision = decide_answer_mode(confidence=0.20, settings=settings)

    assert decision.mode == "rag"
    assert decision.high_confidence is True


def test_explicit_threshold_overrides_provider_default(
    monkeypatch: pytest.MonkeyPatch,
    test_env: dict[str, str],
) -> None:
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.42")
    settings = load_settings()

    assert settings.rag_min_similarity == 0.42
    assert decide_answer_mode(confidence=0.41, settings=settings).mode == "no_answer"
    assert decide_answer_mode(confidence=0.42, settings=settings).mode == "rag"


def test_request_fallback_requires_global_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
    test_env: dict[str, str],
) -> None:
    monkeypatch.setenv("RAG_FALLBACK_ENABLED", "false")
    settings = load_settings()

    assert (
        decide_answer_mode(
            confidence=0.01,
            settings=settings,
            request_fallback=True,
        ).mode
        == "no_answer"
    )

    monkeypatch.setenv("RAG_FALLBACK_ENABLED", "true")
    settings = load_settings()

    assert (
        decide_answer_mode(
            confidence=0.01,
            settings=settings,
            request_fallback=True,
        ).mode
        == "fallback"
    )


def test_local_qwen3_default_threshold_is_initial_035(
    monkeypatch: pytest.MonkeyPatch,
    test_env: dict[str, str],
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-qwen3")
    monkeypatch.setenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    monkeypatch.delenv("RAG_MIN_SIMILARITY", raising=False)
    settings = load_settings()

    assert settings.rag_min_similarity == 0.35
    assert decide_answer_mode(confidence=0.34, settings=settings).mode == "no_answer"
    assert decide_answer_mode(confidence=0.35, settings=settings).mode == "rag"


def test_confidence_is_clamped(test_env: dict[str, str]) -> None:
    settings = load_settings()

    assert decide_answer_mode(confidence=-0.5, settings=settings).confidence == 0.0
    assert decide_answer_mode(confidence=1.5, settings=settings).confidence == 1.0
