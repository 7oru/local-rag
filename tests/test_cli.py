from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.config import find_repo_root, load_settings
from app.ingest import ingest_vault


def parse_json(stdout: str) -> dict[str, object]:
    return json.loads(stdout)


def parse_error(stderr: str) -> dict[str, object]:
    body = json.loads(stderr)
    assert set(body) == {"error"}
    return body["error"]


def test_cli_help(run_cli) -> None:
    result = run_cli("--help", check=True)

    assert "Local-first RAG reference CLI" in result.stdout


def test_cli_db_init_outputs_json(run_cli, clean_test_db: None) -> None:
    result = run_cli("db", "init", check=True)
    body = parse_json(result.stdout)

    assert body["status"] == "ok"


def test_cli_search_and_ask_output_json(run_cli, clean_test_db: None) -> None:
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    search = parse_json(
        run_cli("search", "客户 P1 工单应该怎么升级？", check=True).stdout
    )
    ask = parse_json(run_cli("ask", "客户 P1 工单应该怎么升级？", check=True).stdout)

    assert search["results"][0]["source"] == "policies/Support Escalation Policy.md"
    assert ask["mode"] == "rag"
    assert ask["citations"]


def test_cli_ask_no_answer_and_fallback(run_cli, cli_env, clean_test_db: None) -> None:
    settings = load_settings()
    ingest_vault("samples/acme-vault", settings=settings)

    no_answer = parse_json(run_cli("ask", "完全不存在的随机问题 xyz", check=True).stdout)
    fallback = subprocess.run(
        ["rag", "ask", "完全不存在的随机问题 xyz", "--fallback"],
        env={**cli_env, "RAG_FALLBACK_ENABLED": "true"},
        text=True,
        capture_output=True,
        check=True,
    )
    fallback_body = parse_json(fallback.stdout)

    assert no_answer["mode"] == "no_answer"
    assert fallback_body["mode"] == "fallback"
    assert fallback_body["citations"] == []


def test_cli_env_file_works_from_outside_repo(cli_env, tmp_path: Path) -> None:
    repo_root = find_repo_root()
    result = subprocess.run(
        ["rag", "--env-file", str(repo_root / ".env"), "config"],
        cwd=tmp_path,
        env=cli_env,
        text=True,
        capture_output=True,
        check=True,
    )
    body = parse_json(result.stdout)

    assert body["repo_root"] == str(repo_root)


def test_cli_failure_returns_nonzero_and_json_error(run_cli, clean_test_db: None) -> None:
    result = run_cli("search", "客户 P1 工单")
    error = parse_error(result.stderr)

    assert result.returncode != 0
    assert error["code"] == "retrieval_not_ready"
