from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when local-rag configuration is invalid."""


DEFAULTS = {
    "POSTGRES_DB": "local_rag",
    "POSTGRES_USER": "local_rag",
    "POSTGRES_PASSWORD": "local_rag",
    "DATABASE_URL": "postgresql://local_rag:local_rag@localhost:5432/local_rag",
    "TEST_DATABASE_URL": "postgresql://local_rag:local_rag@localhost:5432/local_rag_test",
    "VAULT_PATH": "samples/acme-vault",
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_MODEL": "fake-lexical-v1",
    "EMBEDDING_DIM": "1024",
    "EMBEDDING_DEVICE": "cpu",
    "EMBEDDING_CACHE_DIR": ".cache/embeddings",
    "LLM_PROVIDER": "fake",
    "LLM_BASE_URL": "",
    "LLM_MODEL": "fake-local",
    "LLM_API_KEY": "",
    "LLM_TIMEOUT_SECONDS": "30",
    "RAG_TOP_K": "5",
    "RAG_MIN_SIMILARITY": "",
    "RAG_CONTEXT_TOKEN_BUDGET": "6000",
    "RAG_FALLBACK_ENABLED": "false",
}

EMBEDDING_MODELS = {
    "fake": "fake-lexical-v1",
    "local-qwen3": "Qwen/Qwen3-Embedding-0.6B",
}


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    env_file: Path
    postgres_db: str
    postgres_user: str
    postgres_password: str
    database_url: str
    test_database_url: str
    vault_path: str
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_device: str
    embedding_cache_dir: str
    llm_provider: str
    llm_base_url: Optional[str]
    llm_api_key: Optional[str]
    llm_model: str
    llm_timeout_seconds: float
    rag_top_k: int
    rag_min_similarity: float
    rag_context_token_budget: int
    rag_fallback_enabled: bool

    @property
    def llm_api_key_present(self) -> bool:
        return bool(self.llm_api_key)

    def summary_lines(self) -> list[str]:
        return [
            f"repo_root={self.repo_root}",
            f"env_file={self.env_file}",
            f"database_url={self.database_url}",
            f"test_database_url={self.test_database_url}",
            f"vault_path={self.vault_path}",
            f"embedding_provider={self.embedding_provider}",
            f"embedding_model={self.embedding_model}",
            f"embedding_dim={self.embedding_dim}",
            f"embedding_cache_dir={self.embedding_cache_dir}",
            f"llm_provider={self.llm_provider}",
            f"llm_model={self.llm_model}",
            f"llm_base_url_set={_format_bool(bool(self.llm_base_url))}",
            f"llm_api_key_present={_format_bool(self.llm_api_key_present)}",
            f"llm_timeout_seconds={self.llm_timeout_seconds:g}",
            f"rag_top_k={self.rag_top_k}",
            f"rag_min_similarity={self.rag_min_similarity:.2f}",
            f"rag_context_token_budget={self.rag_context_token_budget}",
            f"rag_fallback_enabled={_format_bool(self.rag_fallback_enabled)}",
        ]


def find_repo_root(start: Optional[Path] = None) -> Path:
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent

    for path in _walk_parents(current):
        if (path / "pyproject.toml").is_file() and (path / ".env.sample").is_file():
            return path

    raise ConfigError(
        "Could not find repo root. Run from the local-rag repo or pass --env-file PATH."
    )


def load_settings(env_file: Optional[Path] = None) -> Settings:
    explicit_env_file = env_file.expanduser().resolve() if env_file else None
    if explicit_env_file and not explicit_env_file.is_file():
        raise ConfigError(f"Env file does not exist: {explicit_env_file}")

    try:
        repo_root = find_repo_root()
    except ConfigError:
        if not explicit_env_file:
            raise
        repo_root = find_repo_root(explicit_env_file.parent)

    resolved_env_file = explicit_env_file or repo_root / ".env"
    load_dotenv(dotenv_path=resolved_env_file, override=False)

    return _build_settings(repo_root=repo_root, env_file=resolved_env_file)


def _build_settings(repo_root: Path, env_file: Path) -> Settings:
    embedding_provider = _string("EMBEDDING_PROVIDER")
    if embedding_provider not in EMBEDDING_MODELS:
        raise ConfigError(
            "EMBEDDING_PROVIDER must be one of: "
            + ", ".join(sorted(EMBEDDING_MODELS))
        )

    embedding_model = _string("EMBEDDING_MODEL")
    expected_model = EMBEDDING_MODELS[embedding_provider]
    if embedding_model != expected_model:
        raise ConfigError(
            f"EMBEDDING_MODEL must be {expected_model!r} when "
            f"EMBEDDING_PROVIDER={embedding_provider!r}."
        )

    embedding_dim = _int("EMBEDDING_DIM")
    if embedding_dim != 1024:
        raise ConfigError("EMBEDDING_DIM must be 1024 for the MVP.")

    llm_provider = _string("LLM_PROVIDER")
    if llm_provider not in {"fake", "openai-compatible"}:
        raise ConfigError("LLM_PROVIDER must be one of: fake, openai-compatible.")

    llm_base_url = _optional_string("LLM_BASE_URL")
    llm_api_key = _optional_string("LLM_API_KEY")
    llm_model = _string("LLM_MODEL")
    if llm_provider == "openai-compatible":
        missing = [
            name
            for name, value in (
                ("LLM_BASE_URL", llm_base_url),
                ("LLM_API_KEY", llm_api_key),
                ("LLM_MODEL", llm_model),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                "LLM_PROVIDER=openai-compatible requires "
                + ", ".join(missing)
                + "."
            )

    rag_top_k = _int("RAG_TOP_K")
    if not 1 <= rag_top_k <= 20:
        raise ConfigError("RAG_TOP_K must be between 1 and 20.")

    rag_min_similarity = _optional_float("RAG_MIN_SIMILARITY")
    if rag_min_similarity is None:
        rag_min_similarity = 0.90 if embedding_provider == "fake" else 0.35
    if not 0.0 <= rag_min_similarity <= 1.0:
        raise ConfigError("RAG_MIN_SIMILARITY must be between 0.0 and 1.0.")

    llm_timeout_seconds = _float("LLM_TIMEOUT_SECONDS")
    if llm_timeout_seconds <= 0:
        raise ConfigError("LLM_TIMEOUT_SECONDS must be positive.")

    rag_context_token_budget = _int("RAG_CONTEXT_TOKEN_BUDGET")
    if rag_context_token_budget <= 0:
        raise ConfigError("RAG_CONTEXT_TOKEN_BUDGET must be positive.")

    return Settings(
        repo_root=repo_root,
        env_file=env_file,
        postgres_db=_string("POSTGRES_DB"),
        postgres_user=_string("POSTGRES_USER"),
        postgres_password=_string("POSTGRES_PASSWORD"),
        database_url=_string("DATABASE_URL"),
        test_database_url=_string("TEST_DATABASE_URL"),
        vault_path=_string("VAULT_PATH"),
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embedding_device=_string("EMBEDDING_DEVICE"),
        embedding_cache_dir=_string("EMBEDDING_CACHE_DIR"),
        llm_provider=llm_provider,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_timeout_seconds=llm_timeout_seconds,
        rag_top_k=rag_top_k,
        rag_min_similarity=rag_min_similarity,
        rag_context_token_budget=rag_context_token_budget,
        rag_fallback_enabled=_bool("RAG_FALLBACK_ENABLED"),
    )


def _walk_parents(path: Path) -> Iterable[Path]:
    yield path
    yield from path.parents


def _raw(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return DEFAULTS[name]
    return value


def _optional_raw(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value == "":
        value = DEFAULTS[name]
    return value or None


def _string(name: str) -> str:
    value = _raw(name)
    if value == "":
        raise ConfigError(f"{name} must be set.")
    return value


def _optional_string(name: str) -> Optional[str]:
    return _optional_raw(name)


def _int(name: str) -> int:
    value = _raw(name)
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _float(name: str) -> float:
    value = _raw(name)
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc


def _optional_float(name: str) -> Optional[float]:
    value = os.environ.get(name)
    if value is None or value == "":
        value = DEFAULTS[name]
    if value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc


def _bool(name: str) -> bool:
    value = _raw(name).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean.")


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc

    print("\n".join(settings.summary_lines()))


if __name__ == "__main__":
    main()
