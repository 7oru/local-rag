from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from app.config import Settings, load_settings


FAKE_PROVIDER = "fake"
FAKE_MODEL = "fake-lexical-v1"
LOCAL_QWEN3_PROVIDER = "local-qwen3"
LOCAL_QWEN3_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_DIMENSION = 1024
QWEN_QUERY_INSTRUCTION = (
    "Instruct: Given a user question, retrieve relevant passages from the local "
    "enterprise knowledge base that answer the question\nQuery: {query}"
)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
PATH_SEPARATORS_PATTERN = re.compile(r"[/\\._-]+")
WHITESPACE_PATTERN = re.compile(r"\s+")

FIELD_WEIGHTS = {
    "content": 1.0,
    "heading_path": 2.0,
    "relative_path": 1.5,
    "tags": 1.25,
    "wikilinks": 1.25,
}


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot produce vectors."""


@dataclass(frozen=True)
class EmbeddingInput:
    content: str
    heading_path: Sequence[str] = field(default_factory=tuple)
    relative_path: str = ""
    tags: Sequence[str] = field(default_factory=tuple)
    wikilinks: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class WarmupResult:
    provider: str
    model: str
    dim: int
    cache_dir: str
    device: str
    cached: bool

    def summary_lines(self) -> list[str]:
        return [
            f"provider={self.provider}",
            f"model={self.model}",
            f"dim={self.dim}",
            f"cache_dir={self.cache_dir}",
            f"device={self.device}",
            f"cached={'true' if self.cached else 'false'}",
        ]


class EmbeddingClient(Protocol):
    provider: str
    model: str
    dim: int

    def embed_documents(self, items: Sequence[EmbeddingInput]) -> list[list[float]]:
        ...

    def embed_query(self, query: str) -> list[float]:
        ...


class FakeEmbeddingClient:
    provider = FAKE_PROVIDER
    model = FAKE_MODEL
    dim = EMBEDDING_DIMENSION

    def embed_documents(self, items: Sequence[EmbeddingInput]) -> list[list[float]]:
        return [fake_lexical_embedding(item) for item in items]

    def embed_query(self, query: str) -> list[float]:
        return fake_lexical_embedding(EmbeddingInput(content=query))

    def warmup(self, settings: Settings) -> WarmupResult:
        vector = self.embed_query("warmup")
        if len(vector) != self.dim:
            raise EmbeddingError(f"fake warmup returned {len(vector)} dimensions")
        return WarmupResult(
            provider=self.provider,
            model=self.model,
            dim=self.dim,
            cache_dir=settings.embedding_cache_dir,
            device=settings.embedding_device,
            cached=True,
        )


class LocalQwen3EmbeddingClient:
    provider = LOCAL_QWEN3_PROVIDER
    model = LOCAL_QWEN3_MODEL
    dim = EMBEDDING_DIMENSION

    def __init__(self, *, cache_dir: str | Path, device: str = "cpu") -> None:
        self.cache_dir = Path(cache_dir).expanduser()
        self.device = device
        self._model = None

    def embed_documents(self, items: Sequence[EmbeddingInput]) -> list[list[float]]:
        texts = [format_document_text(item) for item in items]
        return self._encode(texts, is_query=False)

    def embed_query(self, query: str) -> list[float]:
        return self._encode([query], is_query=True)[0]

    def _encode(self, texts: Sequence[str], *, is_query: bool) -> list[list[float]]:
        if not texts:
            return []

        model = self._load_model(allow_download=False)
        return self._encode_with_model(model, texts, is_query=is_query)

    def warmup(self) -> WarmupResult:
        model = self._load_model(allow_download=True)
        vector = self._encode_with_model(model, ["warmup"], is_query=True)[0]
        if len(vector) != self.dim:
            raise EmbeddingError(
                f"local-qwen3 warmup returned {len(vector)} dimensions, expected {self.dim}"
            )
        return WarmupResult(
            provider=self.provider,
            model=self.model,
            dim=self.dim,
            cache_dir=str(self.cache_dir),
            device=self.device,
            cached=True,
        )

    def _load_model(self, *, allow_download: bool):
        if self._model is not None:
            return self._model
        if not allow_download and not self._cache_looks_ready():
            raise EmbeddingError(
                "local-qwen3 model cache is missing. "
                f"provider={self.provider} model={self.model} "
                f"cache_dir={self.cache_dir} device={self.device}. "
                "The Qwen3-Embedding-0.6B cache needs roughly 1.5GB of disk. "
                "Run `rag embeddings warmup` before embedding with local-qwen3."
            )

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "local-qwen3 requires optional dependencies. "
                'Install them with `pip install -e ".[local-qwen3]"`.'
            ) from exc

        try:
            self._model = SentenceTransformer(
                self.model,
                cache_folder=str(self.cache_dir),
                device=self.device,
            )
        except Exception as exc:
            raise EmbeddingError(
                "Could not load local-qwen3 embedding model. "
                f"provider={self.provider} model={self.model} "
                f"cache_dir={self.cache_dir} device={self.device}. "
                "Run `rag embeddings warmup` to download or refresh the cache."
            ) from exc
        return self._model

    def _encode_with_model(
        self,
        model,
        texts: Sequence[str],
        *,
        is_query: bool,
    ) -> list[list[float]]:
        try:
            if is_query:
                vectors = model.encode(
                    list(texts),
                    prompt_name="query",
                    normalize_embeddings=True,
                )
            else:
                vectors = model.encode(list(texts), normalize_embeddings=True)
        except TypeError:
            if is_query:
                texts = [QWEN_QUERY_INSTRUCTION.format(query=text) for text in texts]
            vectors = model.encode(list(texts), normalize_embeddings=True)

        return [_to_float_list(vector) for vector in vectors]

    def _cache_looks_ready(self) -> bool:
        if not self.cache_dir.exists():
            return False
        return any(self.cache_dir.rglob("*Qwen3*")) or any(self.cache_dir.rglob("*qwen3*"))


def create_embedding_client(settings: Settings | None = None) -> EmbeddingClient:
    resolved = settings or load_settings()
    if resolved.embedding_provider == FAKE_PROVIDER:
        return FakeEmbeddingClient()
    if resolved.embedding_provider == LOCAL_QWEN3_PROVIDER:
        return LocalQwen3EmbeddingClient(
            cache_dir=resolved.embedding_cache_dir,
            device=resolved.embedding_device,
        )
    raise EmbeddingError(f"Unsupported embedding provider: {resolved.embedding_provider}")


def warmup_embeddings(settings: Settings | None = None) -> WarmupResult:
    resolved = settings or load_settings()
    client = create_embedding_client(resolved)
    if isinstance(client, FakeEmbeddingClient):
        return client.warmup(resolved)
    if isinstance(client, LocalQwen3EmbeddingClient):
        return client.warmup()
    raise EmbeddingError(f"Unsupported embedding client: {type(client).__name__}")


def fake_lexical_embedding(item: EmbeddingInput, *, dim: int = EMBEDDING_DIMENSION) -> list[float]:
    values = [0.0] * dim
    add_weighted_field(values, item.content, weight=FIELD_WEIGHTS["content"], dim=dim)
    add_weighted_field(
        values,
        " ".join(item.heading_path),
        weight=FIELD_WEIGHTS["heading_path"],
        dim=dim,
    )
    add_weighted_field(
        values,
        item.relative_path,
        weight=FIELD_WEIGHTS["relative_path"],
        dim=dim,
    )
    add_weighted_field(values, " ".join(item.tags), weight=FIELD_WEIGHTS["tags"], dim=dim)
    add_weighted_field(
        values,
        " ".join(item.wikilinks),
        weight=FIELD_WEIGHTS["wikilinks"],
        dim=dim,
    )
    return l2_normalize(values)


def add_weighted_field(
    values: list[float],
    text: str,
    *,
    weight: float,
    dim: int,
) -> None:
    counts: dict[str, int] = {}
    for token in tokenize_text(text):
        counts[token] = counts.get(token, 0) + 1

    for token, count in counts.items():
        contribution = min(count, 4) * weight
        values[feature_index(token, dim=dim)] += contribution


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = PATH_SEPARATORS_PATTERN.sub(" ", normalized)
    return WHITESPACE_PATTERN.sub(" ", normalized).strip()


def tokenize_text(text: str) -> list[str]:
    normalized = normalize_text(text)
    tokens: list[str] = []

    for match in TOKEN_PATTERN.finditer(normalized):
        token = match.group(0)
        if len(token) == 1 and token.isalpha():
            continue
        tokens.append(token)

    for match in CJK_PATTERN.finditer(normalized):
        run = match.group(0)
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))

    return tokens


def feature_index(feature: str, *, dim: int = EMBEDDING_DIMENSION) -> int:
    digest = hashlib.sha256(f"{FAKE_MODEL}:{feature}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % dim


def l2_normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vectors must have the same dimension")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def format_document_text(item: EmbeddingInput) -> str:
    parts = [
        f"Source: {item.relative_path}",
        f"Headings: {' > '.join(item.heading_path)}",
        f"Tags: {' '.join(item.tags)}",
        f"Links: {' '.join(item.wikilinks)}",
        item.content,
    ]
    return "\n".join(part for part in parts if part.strip())


def _to_float_list(vector) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="local-rag embedding utilities")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--warmup", action="store_true", help="Warm up configured provider")
    action.add_argument("--embed", metavar="TEXT", help="Embed a query without downloading models")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.warmup:
            result = warmup_embeddings(settings)
            print("\n".join(result.summary_lines()))
            return 0

        client = create_embedding_client(settings)
        vector = client.embed_query(args.embed)
        print(f"provider={client.provider}")
        print(f"model={client.model}")
        print(f"dim={client.dim}")
        print(f"vector_dim={len(vector)}")
        print(f"l2_norm={math.sqrt(sum(value * value for value in vector)):.6f}")
        return 0
    except Exception as exc:
        print(f"embedding error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
