# FDE Demo Script

This script is for a 15-minute local MVP demo. The default path is fully
offline: fake deterministic embeddings and fake deterministic LLM output. Use
the local-qwen3 or live OpenAI-compatible paths only after their manual gates
have already passed.

## 1. Opening

Positioning:

> local-rag is a local-first enterprise knowledge-base RAG reference. It shows
> how a field team can turn a Markdown or Obsidian vault into searchable,
> cited, agent-facing answers without giving the agent direct database access.

Point out the loop:

```text
Markdown vault -> chunking -> embeddings -> pgvector -> retrieval -> /ask
```

## 2. Show the Sample Vault

```bash
find samples/acme-vault -type f | sort
```

Open one or two files:

```bash
sed -n '1,120p' samples/acme-vault/policies/Support\ Escalation\ Policy.md
sed -n '1,120p' samples/acme-vault/policies/Data\ Handling\ Policy.md
```

Callout:

- The source of truth is plain Markdown.
- Headings become retrieval metadata.
- Citations point back to vault-relative paths.

## 3. Start Postgres and Prepare the Index

```bash
test -f .env || cp .env.sample .env
source .venv/bin/activate
docker compose up -d postgres
rag db init
rag embeddings warmup
rag ingest samples/acme-vault
```

Callout:

- Docker Compose starts only Postgres with pgvector.
- The Python app, CLI, tests, and API run from the local virtualenv.
- `rag ingest` is an operator action; the agent-facing API does not mutate the index.

## 4. Ask a High-confidence Question

```bash
rag search "客户 P1 工单应该怎么升级？"
rag ask "客户 P1 工单应该怎么升级？"
```

Point to:

- `results[0].source = policies/Support Escalation Policy.md`
- `mode = rag`
- `citations[0].source = policies/Support Escalation Policy.md`

Explain:

> The answer is grounded in retrieved local chunks. The agent receives an answer
> plus citations, not raw table access.

## 5. Start the API

In one shell:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
curl -sS http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

Callout:

- Agents should call `/ask` or `/search`, not Postgres.
- The API owns validation, thresholding, context assembly, citations, and error shape.
- Postgres stays an implementation detail behind the service boundary.

## 6. Show No-answer Behavior

```bash
rag ask "完全不存在的随机问题 xyz"
```

Point to:

- `mode = no_answer`
- `citations = []`

Explain:

> Low confidence is not treated as an answer. This is the safer default for
> enterprise knowledge-base demos.

## 7. Enable Fallback Explicitly

```bash
RAG_FALLBACK_ENABLED=true rag ask "完全不存在的随机问题 xyz" --fallback
```

Point to:

- `mode = fallback`
- `citations = []`
- answer text says it is not from the local knowledge base

Explain:

> Fallback requires both a request flag and a global enable switch. It is
> intentionally separate from cited RAG answers.

## 8. Optional Semantic Demo: local-qwen3

Do this before the live demo, not during the demo. The model download is large
and should already be cached.

```bash
pip install -e ".[local-qwen3]"

EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
rag embeddings warmup

EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
pytest -m local_qwen3 tests/test_local_qwen3_threshold.py -s
```

Gate summary to show:

```text
resolved_threshold=0.35
min_expected_top_score=0.6738
max_no_answer_top_score=0.2727
margin=0.4011
```

Then rebuild embeddings with local-qwen3 before the demo:

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
rag ingest samples/acme-vault
```

## 9. Optional Live LLM Demo

Only do this after the manual live gate passes:

```bash
scripts/manual_live_ask.sh
```

The live gate requires `LLM_PROVIDER=openai-compatible`, `LLM_BASE_URL`,
`LLM_MODEL`, and `LLM_API_KEY`, and it verifies HTTP `/ask` rather than the CLI
service path.

## 10. Close

Close with:

> The MVP demonstrates the deployment shape: local source documents, local
> vector storage, explicit thresholds, clear no-answer behavior, citations, and
> an agent-facing API boundary.
