from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
import yaml

from app.config import load_settings
from app.retrieval import search


pytestmark = pytest.mark.local_qwen3


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    mode: str
    top_source: str
    confidence: float


def test_local_qwen3_source_hit_and_threshold_gate() -> None:
    if os.environ.get("EMBEDDING_PROVIDER") != "local-qwen3":
        pytest.skip("Set EMBEDDING_PROVIDER=local-qwen3 to run this manual gate.")

    settings = load_settings()
    assert settings.embedding_provider == "local-qwen3"
    assert settings.embedding_model == "Qwen/Qwen3-Embedding-0.6B"
    assert settings.embedding_dim == 1024

    questions = load_eval_questions()
    rag_questions = [item for item in questions if item["expected_mode"] == "rag"]
    no_answer_questions = [
        item for item in questions if item["expected_mode"] == "no_answer"
    ]
    assert len(rag_questions) >= 5
    assert len(no_answer_questions) >= 1

    results: list[QuestionResult] = []
    expected_scores: list[float] = []
    no_answer_scores: list[float] = []

    for question in questions:
        retrieval = search(
            question["question"],
            top_k=5,
            settings=settings,
        )
        assert retrieval.chunks, f"{question['id']} returned no chunks"
        top = retrieval.chunks[0]
        results.append(
            QuestionResult(
                question_id=question["id"],
                mode=question["expected_mode"],
                top_source=top.source,
                confidence=retrieval.confidence,
            )
        )

        if question["expected_mode"] == "rag":
            assert top.source in question["expected_sources"], format_results(results)
            assert retrieval.confidence >= settings.rag_min_similarity, format_results(
                results
            )
            expected_scores.append(retrieval.confidence)
        else:
            assert question["expected_sources"] == []
            assert retrieval.confidence < settings.rag_min_similarity, format_results(
                results
            )
            no_answer_scores.append(retrieval.confidence)

    min_expected_top_score = min(expected_scores)
    max_no_answer_top_score = max(no_answer_scores)
    margin = min_expected_top_score - max_no_answer_top_score

    assert margin > 0.0, format_results(results)
    print(
        {
            "embedding_model": settings.embedding_model,
            "resolved_threshold": settings.rag_min_similarity,
            "min_expected_top_score": min_expected_top_score,
            "max_no_answer_top_score": max_no_answer_top_score,
            "margin": margin,
            "results": [result.__dict__ for result in results],
        }
    )


def load_eval_questions() -> list[dict]:
    with open("eval/questions.yaml", encoding="utf-8") as file:
        return yaml.safe_load(file)


def format_results(results: list[QuestionResult]) -> str:
    return "\n".join(
        f"{result.question_id}: mode={result.mode} source={result.top_source} "
        f"confidence={result.confidence:.4f}"
        for result in results
    )
