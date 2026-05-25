import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import typer

from app.ask import answer_question
from app.config import ConfigError, load_settings
from app.db import DatabaseError, init_db
from app.embeddings import EmbeddingError, warmup_embeddings
from app.ingest import IngestError, ingest_vault
from app.llm import LLMError
from app.retrieval import RetrievalError, RetrievalNotReady, search, to_search_result

app = typer.Typer(
    add_completion=False,
    help="Local-first RAG reference CLI.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Database management commands.", no_args_is_help=True)
embeddings_app = typer.Typer(help="Embedding provider commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(embeddings_app, name="embeddings")


@app.callback()
def callback(
    ctx: typer.Context,
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to an explicit .env file.",
        exists=False,
        dir_okay=False,
        resolve_path=True,
    ),
) -> None:
    ctx.obj = {"env_file": env_file}


@app.command("config")
def config_command(ctx: typer.Context) -> None:
    """Print a redacted configuration summary."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
    except ConfigError as exc:
        emit_error("configuration_error", str(exc))
        raise typer.Exit(1) from exc

    emit_json(
        {
            "repo_root": str(settings.repo_root),
            "env_file": str(settings.env_file),
            "database_url": settings.database_url,
            "test_database_url": settings.test_database_url,
            "vault_path": settings.vault_path,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_dim": settings.embedding_dim,
            "embedding_cache_dir": settings.embedding_cache_dir,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "llm_base_url_set": bool(settings.llm_base_url),
            "llm_api_key_present": settings.llm_api_key_present,
            "llm_timeout_seconds": settings.llm_timeout_seconds,
            "rag_top_k": settings.rag_top_k,
            "rag_min_similarity": settings.rag_min_similarity,
            "rag_context_token_budget": settings.rag_context_token_budget,
            "rag_fallback_enabled": settings.rag_fallback_enabled,
        }
    )


@db_app.command("init")
def db_init_command(ctx: typer.Context) -> None:
    """Initialize or update the Postgres schema."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
        init_db(settings)
    except (ConfigError, DatabaseError) as exc:
        emit_error("database_error", str(exc))
        raise typer.Exit(1) from exc

    emit_json({"status": "ok", "message": "database schema initialized"})


@embeddings_app.command("warmup")
def embeddings_warmup_command(ctx: typer.Context) -> None:
    """Warm up the configured embedding provider."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
        result = warmup_embeddings(settings)
    except (ConfigError, EmbeddingError) as exc:
        emit_error("embedding_error", str(exc))
        raise typer.Exit(1) from exc

    emit_json(asdict(result))


@app.command("ingest")
def ingest_command(
    ctx: typer.Context,
    vault_path: Optional[Path] = typer.Argument(
        None,
        help="Markdown / Obsidian vault path. Defaults to VAULT_PATH.",
        exists=False,
        file_okay=False,
        resolve_path=False,
    ),
) -> None:
    """Ingest a Markdown / Obsidian vault into Postgres."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
        result = ingest_vault(vault_path, settings=settings)
    except (ConfigError, EmbeddingError, IngestError) as exc:
        emit_error("ingest_error", str(exc))
        raise typer.Exit(1) from exc

    emit_json(asdict(result))


@app.command("search")
def search_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query."),
    top_k: int = typer.Option(5, "--top-k", min=1, max=20, help="Number of results."),
) -> None:
    """Search indexed chunks with the configured embedding provider."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
        result = search(query, top_k=top_k, settings=settings)
    except RetrievalNotReady as exc:
        emit_error("retrieval_not_ready", str(exc))
        raise typer.Exit(1) from exc
    except (ConfigError, EmbeddingError, RetrievalError) as exc:
        emit_error("retrieval_error", str(exc))
        raise typer.Exit(1) from exc

    emit_json(
        {
            "query": result.query,
            "top_k": result.top_k,
            "confidence": result.confidence,
            "results": [to_search_result(chunk).model_dump() for chunk in result.chunks],
        }
    )


@app.command("ask")
def ask_command(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="Question to answer."),
    top_k: int = typer.Option(5, "--top-k", min=1, max=20, help="Number of chunks."),
    fallback: bool = typer.Option(False, "--fallback", help="Allow general fallback."),
) -> None:
    """Answer a question with the configured local RAG pipeline."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
        response = answer_question(
            question,
            top_k=top_k,
            fallback=fallback,
            settings=settings,
        )
    except RetrievalNotReady as exc:
        emit_error("retrieval_not_ready", str(exc))
        raise typer.Exit(1) from exc
    except LLMError as exc:
        emit_error(exc.code, exc.message)
        raise typer.Exit(1) from exc
    except (ConfigError, EmbeddingError, RetrievalError) as exc:
        emit_error("ask_error", str(exc))
        raise typer.Exit(1) from exc

    emit_json(response.model_dump())


def emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False))


def emit_error(code: str, message: str, details: dict[str, Any] | None = None) -> None:
    emit = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
    typer.echo(json.dumps(emit, ensure_ascii=False), err=True)


def main() -> None:
    app()
