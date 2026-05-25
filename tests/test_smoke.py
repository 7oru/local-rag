from __future__ import annotations

import json
import subprocess
from typing import Any

import yaml
from fastapi.testclient import TestClient

from app.config import find_repo_root


def load_eval_questions() -> list[dict[str, Any]]:
    path = find_repo_root() / "eval" / "questions.yaml"
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(questions, list)
    return questions


def parse_cli(stdout: str) -> dict[str, Any]:
    return json.loads(stdout)


def expected_source_hit(body: dict[str, Any], expected_sources: list[str]) -> bool:
    returned_sources = {item["source"] for item in body["results"]}
    return any(source in returned_sources for source in expected_sources)


def expected_citation_hit(body: dict[str, Any], expected_sources: list[str]) -> bool:
    returned_sources = {item["source"] for item in body["citations"]}
    return any(source in returned_sources for source in expected_sources)


def test_mvp_end_to_end_smoke(
    api_client: TestClient,
    run_cli,
    cli_env: dict[str, str],
) -> None:
    questions = load_eval_questions()
    rag_questions = [item for item in questions if item["expected_mode"] == "rag"]
    no_answer_questions = [
        item
        for item in questions
        if item["expected_mode"] == "no_answer" and item["expected_sources"] == []
    ]
    assert len(rag_questions) >= 5
    assert no_answer_questions

    assert parse_cli(run_cli("db", "init", check=True).stdout)["status"] == "ok"
    ingest = parse_cli(run_cli("ingest", "samples/acme-vault", check=True).stdout)
    assert ingest["status"] == "success"

    for item in rag_questions:
        search_response = api_client.post(
            "/search",
            json={"query": item["question"]},
        )
        assert search_response.status_code == 200
        search_body = search_response.json()
        assert expected_source_hit(search_body, item["expected_sources"])

        cli_search = parse_cli(run_cli("search", item["question"], check=True).stdout)
        assert expected_source_hit(cli_search, item["expected_sources"])

        ask_response = api_client.post(
            "/ask",
            json={"question": item["question"]},
        )
        assert ask_response.status_code == 200
        ask_body = ask_response.json()
        assert ask_body["mode"] == "rag"
        assert expected_citation_hit(ask_body, item["expected_sources"])

        cli_ask = parse_cli(run_cli("ask", item["question"], check=True).stdout)
        assert cli_ask["mode"] == "rag"
        assert expected_citation_hit(cli_ask, item["expected_sources"])

    unrelated = no_answer_questions[0]
    no_answer_response = api_client.post(
        "/ask",
        json={"question": unrelated["question"]},
    )
    assert no_answer_response.status_code == 200
    assert no_answer_response.json()["mode"] == "no_answer"

    fallback_response = subprocess.run(
        ["rag", "ask", unrelated["question"], "--fallback"],
        env={**cli_env, "RAG_FALLBACK_ENABLED": "true"},
        text=True,
        capture_output=True,
        check=True,
    )
    fallback_body = parse_cli(fallback_response.stdout)
    assert fallback_body["mode"] == "fallback"
    assert fallback_body["citations"] == []
