from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.embeddings import EMBEDDING_DIMENSION, warmup_embeddings


def test_fake_warmup_returns_redacted_provider_summary(test_env: dict[str, str]) -> None:
    result = warmup_embeddings()

    assert result.provider == "fake"
    assert result.model == "fake-lexical-v1"
    assert result.dim == EMBEDDING_DIMENSION
    assert result.cached is True
    assert "cached=true" in result.summary_lines()


def test_python_module_fake_warmup(test_env: dict[str, str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.embeddings", "--warmup"],
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "provider=fake" in result.stdout
    assert "model=fake-lexical-v1" in result.stdout
    assert "dim=1024" in result.stdout
    assert "cached=true" in result.stdout


def test_python_module_fake_embed_does_not_require_network(
    test_env: dict[str, str],
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.embeddings", "--embed", "客户 P1 工单"],
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "provider=fake" in result.stdout
    assert "vector_dim=1024" in result.stdout
    assert "l2_norm=1.000000" in result.stdout


def test_cli_fake_warmup(run_cli) -> None:
    result = run_cli("embeddings", "warmup", check=True)

    assert "provider=fake" in result.stdout
    assert "model=fake-lexical-v1" in result.stdout
    assert "cached=true" in result.stdout


def test_local_qwen3_embed_requires_existing_cache(tmp_path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "EMBEDDING_PROVIDER": "local-qwen3",
            "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-0.6B",
            "EMBEDDING_DIM": "1024",
            "EMBEDDING_CACHE_DIR": str(tmp_path / "missing"),
            "LLM_PROVIDER": "fake",
            "LLM_MODEL": "fake-local",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.embeddings", "--embed", "客户 P1 工单"],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "rag embeddings warmup" in result.stderr
