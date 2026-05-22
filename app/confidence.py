from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import Settings


AnswerMode = Literal["rag", "no_answer", "fallback"]


@dataclass(frozen=True)
class ConfidenceDecision:
    mode: AnswerMode
    confidence: float
    threshold: float
    high_confidence: bool
    fallback_requested: bool
    fallback_enabled: bool


def decide_answer_mode(
    *,
    confidence: float,
    settings: Settings,
    request_fallback: bool = False,
) -> ConfidenceDecision:
    clamped_confidence = max(0.0, min(1.0, confidence))
    high_confidence = clamped_confidence >= settings.rag_min_similarity
    if high_confidence:
        mode: AnswerMode = "rag"
    elif request_fallback and settings.rag_fallback_enabled:
        mode = "fallback"
    else:
        mode = "no_answer"

    return ConfidenceDecision(
        mode=mode,
        confidence=clamped_confidence,
        threshold=settings.rag_min_similarity,
        high_confidence=high_confidence,
        fallback_requested=request_fallback,
        fallback_enabled=settings.rag_fallback_enabled,
    )
