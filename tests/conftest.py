from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

import psycopg
import pytest
from dotenv import dotenv_values

from app.config import DEFAULTS, find_repo_root, load_settings
from app.db import init_db


DESTRUCTIVE_TABLES = ("documents", "chunks", "embeddings", "ingest_runs")

FAKE_PROVIDER_ENV = {
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_MODEL": "fake-lexical-v1",
    "EMBEDDING_DIM": "1024",
    "LLM_PROVIDER": "fake",
    "LLM_MODEL": "fake-local",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "",
}


def read_config_source(repo_root: Optional[Path] = None) -> dict[str, str]:
    root = repo_root or find_repo_root()
    values: dict[str, str] = dict(DEFAULTS)
    dotenv_data = dotenv_values(root / ".env")

    for key, value in dotenv_data.items():
        if value not in (None, ""):
            values[key] = value

    for key, value in os.environ.items():
        if value != "":
            values[key] = value

    return values


def validate_test_database_urls(
    database_url: Optional[str],
    test_database_url: Optional[str],
) -> None:
    if not test_database_url:
        raise RuntimeError("TEST_DATABASE_URL must be set before DB tests run.")

    test_db_name = database_name(test_database_url)
    if not test_db_name.endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL database name must end with _test.")

    if database_url and test_database_url == database_url:
        raise RuntimeError("TEST_DATABASE_URL must not equal DATABASE_URL.")


def database_name(database_url: str) -> str:
    parsed = urlparse(database_url)
    return parsed.path.rsplit("/", maxsplit=1)[-1]


def build_test_env(config_source: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    source = dict(config_source or read_config_source())
    database_url = source.get("DATABASE_URL")
    test_database_url = source.get("TEST_DATABASE_URL")
    validate_test_database_urls(database_url, test_database_url)

    env = {
        "DATABASE_URL": test_database_url,
        "TEST_DATABASE_URL": test_database_url,
        **FAKE_PROVIDER_ENV,
    }
    return env


@pytest.fixture
def original_config_source() -> dict[str, str]:
    return read_config_source()


@pytest.fixture
def test_db_url(original_config_source: dict[str, str]) -> str:
    source = original_config_source
    validate_test_database_urls(source.get("DATABASE_URL"), source.get("TEST_DATABASE_URL"))
    return source["TEST_DATABASE_URL"]


@pytest.fixture
def test_env(
    monkeypatch: pytest.MonkeyPatch,
    original_config_source: dict[str, str],
) -> dict[str, str]:
    env = build_test_env(original_config_source)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def cli_env(test_env: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(test_env)
    executable_dir = str(Path(sys.executable).parent)
    env["PATH"] = executable_dir + os.pathsep + env.get("PATH", "")
    return env


@pytest.fixture
def clean_test_db(
    test_env: dict[str, str],
    original_config_source: dict[str, str],
) -> None:
    settings = load_settings()
    validate_test_database_urls(
        original_config_source.get("DATABASE_URL"),
        original_config_source.get("TEST_DATABASE_URL"),
    )
    init_db(settings)
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE "
                + ", ".join(DESTRUCTIVE_TABLES)
                + " RESTART IDENTITY CASCADE"
            )


@pytest.fixture
def run_cli(cli_env: dict[str, str]) -> Callable[..., subprocess.CompletedProcess]:
    def _run_cli(*args: str, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["rag", *args],
            env=cli_env,
            text=True,
            capture_output=True,
            **kwargs,
        )

    return _run_cli
