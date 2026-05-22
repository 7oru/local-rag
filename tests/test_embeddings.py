from __future__ import annotations

import math

import pytest

from app.embeddings import (
    EMBEDDING_DIMENSION,
    FIELD_WEIGHTS,
    EmbeddingInput,
    FakeEmbeddingClient,
    LocalQwen3EmbeddingClient,
    add_weighted_field,
    cosine_similarity,
    feature_index,
    fake_lexical_embedding,
    normalize_text,
    tokenize_text,
)


def test_fake_embedding_is_stable_for_same_input() -> None:
    client = FakeEmbeddingClient()
    item = EmbeddingInput(
        content="Atlas CRM supports P1 escalation",
        heading_path=["Support", "P1 Escalation"],
        relative_path="policies/Support Escalation Policy.md",
        tags=["support", "p1"],
        wikilinks=["runbooks/API Latency Runbook"],
    )

    assert client.embed_documents([item])[0] == client.embed_documents([item])[0]


def test_fake_embedding_differs_for_different_text() -> None:
    client = FakeEmbeddingClient()

    first = client.embed_query("Atlas CRM API latency escalation")
    second = client.embed_query("cafeteria lunch menu dessert")

    assert first != second


def test_lexical_overlap_scores_higher_than_unrelated_text() -> None:
    client = FakeEmbeddingClient()
    query = client.embed_query("客户 P1 escalation on-call engineer")
    related = client.embed_documents(
        [
            EmbeddingInput(
                content="For P1 escalation, notify the on-call engineer.",
                heading_path=["Support Escalation Policy", "P1 Escalation"],
                relative_path="policies/Support Escalation Policy.md",
                tags=["support", "p1"],
            )
        ]
    )[0]
    unrelated = client.embed_documents(
        [EmbeddingInput(content="The cafeteria lunch menu includes soup and salad.")]
    )[0]

    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


def test_normalization_and_tokenization_follow_contract() -> None:
    assert normalize_text("Products/Atlas_CRM-FAQ.md") == "products atlas crm faq md"
    tokens = tokenize_text("A Atlas CRM 1 客户数据")

    assert "a" not in tokens
    assert "atlas" in tokens
    assert "crm" in tokens
    assert "1" in tokens
    assert "客" in tokens
    assert "户" in tokens
    assert "客户" in tokens
    assert "数据" in tokens


def test_feature_hashing_uses_stable_sha256_bucket() -> None:
    digest = __import__("hashlib").sha256(b"fake-lexical-v1:atlas").digest()
    expected = int.from_bytes(digest[:8], byteorder="big", signed=False) % 1024

    assert feature_index("atlas") == expected


def test_metadata_fields_apply_contract_weights_without_normalization() -> None:
    values = [0.0] * EMBEDDING_DIMENSION

    add_weighted_field(values, "atlas atlas atlas atlas atlas", weight=1.0, dim=1024)
    assert values[feature_index("atlas")] == 4.0

    values = [0.0] * EMBEDDING_DIMENSION
    add_weighted_field(
        values,
        "Support Escalation",
        weight=FIELD_WEIGHTS["heading_path"],
        dim=1024,
    )
    assert values[feature_index("support")] == FIELD_WEIGHTS["heading_path"]
    assert values[feature_index("escalation")] == FIELD_WEIGHTS["heading_path"]

    values = [0.0] * EMBEDDING_DIMENSION
    add_weighted_field(
        values,
        "policies/Support Escalation Policy.md",
        weight=FIELD_WEIGHTS["relative_path"],
        dim=1024,
    )
    assert values[feature_index("policies")] == FIELD_WEIGHTS["relative_path"]

    values = [0.0] * EMBEDDING_DIMENSION
    add_weighted_field(values, "support p1", weight=FIELD_WEIGHTS["tags"], dim=1024)
    assert values[feature_index("support")] == FIELD_WEIGHTS["tags"]


def test_vectors_are_l2_normalized_and_empty_input_is_zero() -> None:
    vector = fake_lexical_embedding(EmbeddingInput(content="Atlas CRM support"))
    empty = fake_lexical_embedding(EmbeddingInput(content=""))

    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)
    assert empty == [0.0] * EMBEDDING_DIMENSION


def test_vector_dimension_matches_schema() -> None:
    client = FakeEmbeddingClient()

    assert client.dim == EMBEDDING_DIMENSION
    assert len(client.embed_query("Atlas CRM")) == 1024


def test_local_qwen3_does_not_load_or_download_when_cache_missing(tmp_path) -> None:
    client = LocalQwen3EmbeddingClient(cache_dir=tmp_path / "missing", device="cpu")

    with pytest.raises(RuntimeError, match="rag embeddings warmup"):
        client.embed_query("客户 P1 工单应该怎么升级？")
