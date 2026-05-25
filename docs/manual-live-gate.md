# Manual Live OpenAI-compatible Gate

This gate verifies the agent-facing HTTP `/ask` path with a real
OpenAI-compatible provider. It is manual, credentialed, networked, and not part
of default CI.

Prepare the local database and sample index:

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
```

Configure only generic `LLM_*` variables in `.env` or the current shell:

```bash
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL="<provider openai-compatible base url>"
export LLM_MODEL="<provider model>"
export LLM_API_KEY="<provider api key>"
```

If the shell already has `KIMI_API_KEY`, map it only when it is non-empty:

```bash
if [ -n "${KIMI_API_KEY:-}" ]; then
  export LLM_API_KEY="$KIMI_API_KEY"
fi
```

Start the local API server:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell, run the live gate:

```bash
scripts/manual_live_ask.sh
```

The script calls `POST http://127.0.0.1:8000/ask` and prints only `mode`,
`answer`, and `citations`. It never prints the API key. Override the server URL
with `RAG_HTTP_URL` if needed.
