#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${LLM_API_KEY:-}" && -n "${KIMI_API_KEY:-}" ]]; then
  export LLM_API_KEY="${KIMI_API_KEY}"
fi

if [[ "${LLM_PROVIDER:-}" != "openai-compatible" ]]; then
  echo "error: set LLM_PROVIDER=openai-compatible before running the live gate" >&2
  exit 1
fi

missing=()
for name in LLM_BASE_URL LLM_API_KEY LLM_MODEL; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("${name}")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "error: missing required generic LLM variables: ${missing[*]}" >&2
  exit 1
fi

url="${RAG_HTTP_URL:-http://127.0.0.1:8000}/ask"
payload='{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'

response="$(curl -fsS "${url}" \
  -H "Content-Type: application/json" \
  -d "${payload}")"

python - "${response}" <<'PY'
import json
import sys

body = json.loads(sys.argv[1])
for field in ("mode", "answer", "citations"):
    if field not in body:
        raise SystemExit(f"error: /ask response is missing {field!r}")
print(json.dumps({
    "mode": body["mode"],
    "answer": body["answer"],
    "citations": body["citations"],
}, ensure_ascii=False))
PY
