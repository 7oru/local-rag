# local-rag

[中文说明](README.zh-CN.md)

`local-rag` is a local-first RAG reference implementation for Field Deployment
Engineers building enterprise knowledge-base demos and proofs of concept.

The MVP is meant to let an FDE demonstrate a trustworthy enterprise
knowledge-base loop on a local machine:

```text
Markdown / Obsidian vault
  -> parsing
  -> heading-aware chunking
  -> embeddings
  -> Postgres + pgvector
  -> retrieval
  -> citations / no-answer / agent-facing API
```

The MVP now includes the full local RAG loop:

- sample enterprise vault: `samples/acme-vault/`
- CLI: `rag db init`, `rag embeddings warmup`, `rag ingest`, `rag search`, `rag ask`
- API: `GET /health`, `POST /search`, `POST /ask`, `POST /ask/stream`
- embeddings:
  - default `fake-lexical-v1`: deterministic lexical embedding, no network, good for smoke tests
  - optional `local-qwen3`: `Qwen/Qwen3-Embedding-0.6B`, real local semantic embedding
- LLMs:
  - default `fake`: deterministic local answer generation, no network
  - optional `openai-compatible`: `/chat/completions` with non-streaming and SSE streaming paths
- Postgres schema: `documents`, `chunks`, `embeddings`, `ingest_runs`
- pgvector stores 1024-dimensional vectors

## Quickstart: Offline Smoke Path

This path uses `fake-lexical-v1`, so it does not download an embedding model and
does not need an API key. Docker Compose only starts Postgres; the CLI, tests,
and API run from the local Python virtualenv.

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
rag ask "客户 P1 工单应该怎么升级？"
```

CLI commands print JSON by default. The search result should include:

```json
{
  "results": [
    {
      "source": "policies/Support Escalation Policy.md",
      "heading": "P1 Escalation"
    }
  ]
}
```

The ask result should return `mode="rag"` and citations:

```json
{
  "mode": "rag",
  "citations": [
    {
      "source": "policies/Support Escalation Policy.md",
      "heading": "P1 Escalation"
    }
  ]
}
```

The second ingest should skip unchanged documents:

```bash
rag ingest samples/acme-vault
```

Expect `documents_skipped=9` and `embeddings_written=0` in the JSON output.

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

Ask:

```bash
curl -sS http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

Ask with SSE streaming:

```bash
curl -N http://127.0.0.1:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

## Fallback Behavior

`/ask` chooses a mode from the top retrieval confidence:

- `rag`: confidence is at least `RAG_MIN_SIMILARITY`; answer uses local context and citations.
- `no_answer`: confidence is too low; the local knowledge base is not confident enough.
- `fallback`: confidence is too low, request has `fallback=true`, and `RAG_FALLBACK_ENABLED=true`.

Fallback answers are explicitly not from the local knowledge base and return no
citations:

```bash
rag ask "完全不存在的随机问题 xyz"
RAG_FALLBACK_ENABLED=true rag ask "完全不存在的随机问题 xyz" --fallback
```

## OpenAI-compatible LLM

The default `LLM_PROVIDER=fake` is offline. To use a real OpenAI-compatible
provider, set only the generic variables:

```bash
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL="<provider openai-compatible base url>"
export LLM_MODEL="<provider model>"
export LLM_API_KEY="<provider api key>"
```

If the provider expects `/v1`, include it in `LLM_BASE_URL`; local-rag appends only
`/chat/completions`.

### Kimi / Moonshot Sample RAG Run

This is the concrete command path used to verify the sample vault with Kimi's
OpenAI-compatible API. The app still reads only generic `LLM_*` variables; the
shell maps `KIMI_API_KEY` to `LLM_API_KEY` for this run.

```bash
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL=https://api.moonshot.cn/v1
export LLM_MODEL=moonshot-v1-8k
if [ -n "${KIMI_API_KEY:-}" ]; then
  export LLM_API_KEY="$KIMI_API_KEY"
fi

docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
curl -sS http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"客户 P1 工单应该怎么升级？请用中文简洁回答。","top_k":5,"fallback":false}'
```

Example response shape from the live run:

```json
{
  "mode": "rag",
  "confidence": 0.2017,
  "answer": "客户P1工单应该在15分钟内确认，并分配给escalation owner和on-call engineer，并创建war-room thread，之后每30分钟更新一次客户时间线，直到问题得到缓解。[1]",
  "citations": [
    {
      "source": "policies/Support Escalation Policy.md",
      "heading": "P1 Escalation",
      "score": 0.2017
    }
  ]
}
```

`moonshot-v1-8k` is used here because the MVP LLM wire contract sends
`temperature=0`. Some Kimi models, such as `kimi-k2.6`, may require a different
temperature and can reject this MVP request shape.

### SOCKS Proxy Troubleshooting

Some local proxy or VPN tools export environment variables such as:

```bash
ALL_PROXY=socks5://127.0.0.1:15235
```

`httpx` automatically reads these proxy variables. If a SOCKS proxy is present
but the Python environment does not have SOCKS support installed, a live LLM
call can fail with:

```text
Using SOCKS proxy, but the 'socksio' package is not installed
```

If direct access to the provider works, disable proxy variables for the current
shell before starting `uvicorn` or running `rag ask`:

```bash
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
```

If you need to route requests through the SOCKS proxy, install SOCKS support:

```bash
pip install "httpx[socks]"
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

This manual gate is not part of default CI.

## Manual Live Gate

After the sample vault is ingested and the API server is running, verify a real
OpenAI-compatible provider through HTTP `/ask`:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
scripts/manual_live_ask.sh
```

The script requires `LLM_PROVIDER=openai-compatible`, `LLM_BASE_URL`,
`LLM_MODEL`, and `LLM_API_KEY`. It prints only `mode`, `answer`, and
`citations`; it never prints the API key. See
[Manual Live Gate](docs/manual-live-gate.md).

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

End-to-end smoke test:

```bash
pytest tests/test_smoke.py
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
- [FDE Demo Script](docs/demo-script.md)
- [Manual Live Gate](docs/manual-live-gate.md)
- [Roadmap to Full Release](docs/roadmap-to-full-release.md)
