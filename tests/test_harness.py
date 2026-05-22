from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.conftest import build_test_env, validate_test_database_urls


DEMO_DATABASE_URL = "postgresql://local_rag:local_rag@localhost:5432/local_rag"
TEST_DATABASE_URL = "postgresql://local_rag:local_rag@localhost:5432/local_rag_test"


def test_missing_test_database_url_fails_fast() -> None:
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL must be set"):
        validate_test_database_urls(DEMO_DATABASE_URL, None)


def test_test_database_name_must_end_with_test() -> None:
    with pytest.raises(RuntimeError, match="must end with _test"):
        validate_test_database_urls(
            DEMO_DATABASE_URL,
            "postgresql://local_rag:local_rag@localhost:5432/local_rag_dev",
        )


def test_test_database_url_must_not_equal_demo_database_url() -> None:
    with pytest.raises(RuntimeError, match="must not equal DATABASE_URL"):
        validate_test_database_urls(TEST_DATABASE_URL, TEST_DATABASE_URL)


def test_build_test_env_injects_runtime_database_url() -> None:
    env = build_test_env(
        {
            "DATABASE_URL": DEMO_DATABASE_URL,
            "TEST_DATABASE_URL": TEST_DATABASE_URL,
        }
    )

    assert env["DATABASE_URL"] == TEST_DATABASE_URL
    assert env["TEST_DATABASE_URL"] == TEST_DATABASE_URL


def test_test_env_injects_fake_provider_into_pytest_process(
    test_env: dict[str, str],
) -> None:
    assert os.environ["DATABASE_URL"] == os.environ["TEST_DATABASE_URL"]
    assert test_env["EMBEDDING_PROVIDER"] == "fake"
    assert os.environ["EMBEDDING_MODEL"] == "fake-lexical-v1"
    assert os.environ["EMBEDDING_DIM"] == "1024"
    assert os.environ["LLM_PROVIDER"] == "fake"
    assert os.environ["LLM_MODEL"] == "fake-local"
    assert os.environ["LLM_API_KEY"] == ""
    assert os.environ["LLM_BASE_URL"] == ""


def test_cli_env_injects_fake_provider_for_subprocess(cli_env: dict[str, str]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['EMBEDDING_PROVIDER'] + ':' + os.environ['LLM_PROVIDER'])",
        ],
        env=cli_env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip() == "fake:fake"
