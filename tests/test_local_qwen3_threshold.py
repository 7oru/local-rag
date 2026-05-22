from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
import yaml

from app.confidence import decide_answer_mode
from app.config import load_settings
from app.embeddings import create_embedding_client
from app.retrieval import search


pytestmark = pytest.mark.local_qwen3


@dataclass(frozen=True)
class GateScore:
    question_id: str
    mode: str
    confidence: float
    source: str | None


def test_local_qwen3_source_hit_and_threshold_gate() -> None:
    if os.environ.get("EMBEDDING_PROVIDER") != "local-qwen3":
        pytest.skip("manual gate requires EMBEDDING_PROVIDER=local-qwen3")

    settings = load_settings()
    assert settings.embedding_provider == "local-qwen3"
    assert settings.embedding_model == "Qwen/Qwen3-Embedding-0.6B"
    assert settings.rag_min_similarity == 0.35

    client = create_embedding_client(settings)
    questions = load_eval_questions()
    rag_questions = [item for item in questions if item["expected_mode"] == "rag"]
    no_answer_questions = [
        item for item in questions if item["expected_mode"] == "no_answer"
    ]
    assert len(rag_questions) >= 5
    assert len(no_answer_questions) >= 1

    expected_scores: list[float] = []
    no_answer_scores: list[float] = []
    gate_scores: list[GateScore] = []

    for question in questions:
        result = search(
            question["question"],
            top_k=5,
            settings=settings,
            embedding_client=client,
        )
        top = result.chunks[0] if result.chunks else None
        decision = decide_answer_mode(confidence=result.confidence, settings=settings)
        gate_scores.append(
            GateScore(
                question_id=question["id"],
                mode=question["expected_mode"],
                confidence=result.confidence,
                source=top.source if top else None,
            )
        )

        if question["expected_mode"] == "rag":
            assert top is not None, question["id"]
            assert top.source in question["expected_sources"], gate_scores
            assert decision.mode == "rag", gate_scores
            expected_scores.append(result.confidence)
        else:
            assert question["expected_sources"] == []
            assert decision.mode == "no_answer", gate_scores
            no_answer_scores.append(result.confidence)

    min_expected_top_score = min(expected_scores)
    max_no_answer_top_score = max(no_answer_scores)
    margin = min_expected_top_score - max_no_answer_top_score

    assert min_expected_top_score == pytest.approx(0.6738, abs=0.0002)
    assert max_no_answer_top_score == pytest.approx(0.2727, abs=0.0002)
    assert margin == pytest.approx(0.4011, abs=0.0002)


def load_eval_questions() -> list[dict]:
    with open("eval/questions.yaml", encoding="utf-8") as file:
        return yaml.safe_load(file)
