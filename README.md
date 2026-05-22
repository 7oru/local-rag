# local-rag

`local-rag` is a local-first RAG reference implementation for Field Deployment
Engineers building enterprise knowledge-base demos and proofs of concept.

这个项目的 MVP 目标是让 FDE 可以在客户现场演示一条可信的企业知识库链路：

```text
Markdown / Obsidian vault
  -> parsing
  -> heading-aware chunking
  -> embeddings
  -> Postgres + pgvector
  -> retrieval
  -> citations / no-answer / agent-facing API
```

当前代码已经跑通到 retrieval：

- sample enterprise vault: `samples/acme-vault/`
- CLI: `rag db init`, `rag embeddings warmup`, `rag ingest`, `rag search`
- API: `GET /health`, `POST /search`
- embeddings:
  - default `fake-lexical-v1`: deterministic lexical embedding, no network, good for smoke tests
  - optional `local-qwen3`: `Qwen/Qwen3-Embedding-0.6B`, real local semantic embedding
- Postgres schema: `documents`, `chunks`, `embeddings`, `ingest_runs`
- pgvector stores 1024-dimensional vectors

`/ask`, LLM answer generation, final citations assembly, and OpenAI-compatible live
gate are still later MVP tasks.

## Quickstart: Offline Smoke Path

This path uses `fake-lexical-v1`, so it does not download an embedding model and
does not need an API key.

```bash
cp .env.sample .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

docker compose up -d postgres
rag db init
rag embeddings warmup
rag ingest samples/acme-vault
rag search "客户 P1 工单应该怎么升级？"
```

Expected shape:

```text
source=policies/Support Escalation Policy.md
heading=P1 Escalation
```

The second ingest should skip unchanged documents:

```bash
rag ingest samples/acme-vault
```

Expected shape:

```text
documents_skipped=9
embeddings_written=0
```

## Run the API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Search:

```bash
curl -sS http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"客户 P1 工单应该怎么升级？","top_k":5}'
```

## Semantic Demo: local-qwen3

Use this path before an FDE semantic demo. It downloads the model to disk once,
then loads it into memory only when a process uses `local-qwen3`.

Install optional runtime:

```bash
source .venv/bin/activate
pip install -e ".[local-qwen3]"
```

Download / warm up the model:

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
rag embeddings warmup
```

The default cache path is `.cache/embeddings`. On this project, the downloaded
cache is about `1.1G`. The cache stays on disk; model weights are loaded into
memory only while commands such as `rag embeddings warmup`, `rag ingest`, or
`rag search` are running. A long-running API process reuses the loaded model in
that process.

Build local-qwen3 embeddings:

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
rag ingest samples/acme-vault
```

Run the manual quality gate:

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
pytest -m local_qwen3 tests/test_local_qwen3_threshold.py -s
```

Current gate result:

```text
resolved_threshold=0.35
min_expected_top_score=0.6738
max_no_answer_top_score=0.2727
margin=0.4011
```

## Configuration

Copy `.env.sample` to `.env`. Runtime priority is:

```text
OS environment / shell export > .env > code defaults
```

Important defaults:

```text
DATABASE_URL=postgresql://local_rag:local_rag@localhost:5432/local_rag
TEST_DATABASE_URL=postgresql://local_rag:local_rag@localhost:5432/local_rag_test
VAULT_PATH=samples/acme-vault
EMBEDDING_PROVIDER=fake
EMBEDDING_MODEL=fake-lexical-v1
EMBEDDING_DIM=1024
LLM_PROVIDER=fake
RAG_MIN_SIMILARITY=
```

When `RAG_MIN_SIMILARITY` is empty, provider defaults are:

- `fake`: `0.20`
- `local-qwen3`: `0.35`

Print a redacted config summary:

```bash
rag config
```

## Tests

Default tests do not require a real embedding model or API key:

```bash
pytest
```

The test harness uses `TEST_DATABASE_URL` and refuses destructive cleanup unless
the database name ends with `_test` and differs from `DATABASE_URL`.

Manual local-qwen3 gate:

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
pytest -m local_qwen3 tests/test_local_qwen3_threshold.py -s
```

## Documents

- [MVP Scope](docs/mvp.md)
- [MVP Subtasks](docs/mvp-subtasks.md)
- [Roadmap to Full Release](docs/roadmap-to-full-release.md)
