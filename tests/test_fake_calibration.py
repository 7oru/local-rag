from __future__ import annotations

from dataclasses import dataclass

import pytest
import yaml

from app.chunking import Chunk, chunk_document
from app.config import FAKE_DEFAULT_MIN_SIMILARITY
from app.embeddings import EmbeddingInput, FakeEmbeddingClient, cosine_similarity
from app.markdown import parse_markdown_file, scan_markdown_files


@dataclass(frozen=True)
class ScoredChunk:
    score: float
    chunk: Chunk


def test_fake_embedding_calibration_hits_expected_sources() -> None:
    questions = load_eval_questions()
    rag_questions = [item for item in questions if item["expected_mode"] == "rag"]
    no_answer_questions = [
        item for item in questions if item["expected_mode"] == "no_answer"
    ]
    assert len(rag_questions) >= 5
    assert len(no_answer_questions) >= 1

    client = FakeEmbeddingClient()
    indexed_chunks = embed_sample_chunks(client)
    expected_top_scores: list[float] = []
    unrelated_top_scores: list[float] = []

    for question in questions:
        ranked = rank_chunks(client, question["question"], indexed_chunks)
        top = ranked[0]

        if question["expected_mode"] == "rag":
            assert question["expected_sources"]
            assert top.chunk.relative_path in question["expected_sources"]
            assert top.score >= FAKE_DEFAULT_MIN_SIMILARITY
            expected_top_scores.append(top.score)
        else:
            assert question["expected_sources"] == []
            assert top.score < FAKE_DEFAULT_MIN_SIMILARITY
            unrelated_top_scores.append(top.score)

    min_expected_top_score = min(expected_top_scores)
    max_unrelated_top_score = max(unrelated_top_scores)
    margin = min_expected_top_score - max_unrelated_top_score

    assert min_expected_top_score == pytest.approx(0.2538, abs=0.0001)
    assert max_unrelated_top_score == pytest.approx(0.0594, abs=0.0001)
    assert margin == pytest.approx(0.1944, abs=0.0001)


def load_eval_questions() -> list[dict]:
    with open("eval/questions.yaml", encoding="utf-8") as file:
        return yaml.safe_load(file)


def embed_sample_chunks(client: FakeEmbeddingClient) -> list[tuple[Chunk, list[float]]]:
    indexed: list[tuple[Chunk, list[float]]] = []
    for markdown_file in scan_markdown_files("samples/acme-vault"):
        document = parse_markdown_file(markdown_file.file_path, "samples/acme-vault")
        for chunk in chunk_document(document):
            vector = client.embed_documents(
                [
                    EmbeddingInput(
                        content=chunk.content,
                        heading_path=chunk.heading_path,
                        relative_path=chunk.relative_path,
                        tags=chunk.tags,
                        wikilinks=chunk.wikilinks,
                    )
                ]
            )[0]
            indexed.append((chunk, vector))
    return indexed


def rank_chunks(
    client: FakeEmbeddingClient,
    question: str,
    indexed_chunks: list[tuple[Chunk, list[float]]],
) -> list[ScoredChunk]:
    query_vector = client.embed_query(question)
    ranked = [
        ScoredChunk(
            score=max(0.0, min(1.0, cosine_similarity(query_vector, vector))),
            chunk=chunk,
        )
        for chunk, vector in indexed_chunks
    ]
    return sorted(
        ranked,
        key=lambda item: (-item.score, item.chunk.relative_path, item.chunk.chunk_index),
    )
