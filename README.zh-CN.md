# local-rag

[English README](README.md)

`local-rag` 是一个 local-first RAG 参考实现，面向 Field Deployment
Engineer，用来快速搭建企业知识库 demo 和 PoC。

MVP 展示的是一条可信的本地知识库问答链路：

```text
Markdown / Obsidian vault
  -> 解析
  -> 按 heading 切片
  -> embeddings
  -> Postgres + pgvector
  -> retrieval
  -> citations / no-answer / agent-facing API
```

当前 MVP 已包含完整本地 RAG 闭环：

- 示例企业知识库：`samples/acme-vault/`
- CLI：`rag db init`、`rag embeddings warmup`、`rag ingest`、`rag search`、`rag ask`
- API：`GET /health`、`POST /search`、`POST /ask`、`POST /ask/stream`
- embeddings：
  - 默认 `fake-lexical-v1`：确定性的 lexical embedding，无网络依赖，适合 smoke test
  - 可选 `local-qwen3`：`Qwen/Qwen3-Embedding-0.6B`，真实本地语义 embedding
- LLM：
  - 默认 `fake`：确定性的本地回答生成，无网络依赖
  - 可选 `openai-compatible`：`/chat/completions`，支持非 streaming 和 SSE streaming 路径
- Postgres schema：`documents`、`chunks`、`embeddings`、`ingest_runs`
- pgvector 存储 1024 维向量

## 快速开始：离线 smoke 路径

这条路径使用 `fake-lexical-v1`，不会下载 embedding 模型，也不需要 API key。
Docker Compose 只启动 Postgres；CLI、测试和 API 都在本地 Python virtualenv 中运行。

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

CLI 默认输出 JSON。`rag search` 应该能看到：

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

`rag ask` 应返回 `mode="rag"` 和 citations：

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

第二次 ingest 应跳过未变化的文档：

```bash
rag ingest samples/acme-vault
```

JSON 输出里应看到 `documents_skipped=9` 和 `embeddings_written=0`。

## 运行 API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check：

```bash
curl http://127.0.0.1:8000/health
```

Search：

```bash
curl -sS http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"客户 P1 工单应该怎么升级？","top_k":5}'
```

Ask：

```bash
curl -sS http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

SSE streaming Ask：

```bash
curl -N http://127.0.0.1:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

## Fallback 行为

`/ask` 会根据 top retrieval confidence 选择模式：

- `rag`：confidence 大于等于 `RAG_MIN_SIMILARITY`，答案使用本地 context 和 citations。
- `no_answer`：confidence 太低，本地知识库没有足够可信的答案。
- `fallback`：confidence 太低，请求带 `fallback=true`，且 `RAG_FALLBACK_ENABLED=true`。

Fallback 答案会明确说明不是来自本地知识库，并且不返回 citations：

```bash
rag ask "完全不存在的随机问题 xyz"
RAG_FALLBACK_ENABLED=true rag ask "完全不存在的随机问题 xyz" --fallback
```

## OpenAI-compatible LLM

默认 `LLM_PROVIDER=fake` 是离线路径。要使用真实 OpenAI-compatible provider，
只设置通用 `LLM_*` 变量：

```bash
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL="<provider openai-compatible base url>"
export LLM_MODEL="<provider model>"
export LLM_API_KEY="<provider api key>"
```

如果 provider 需要 `/v1`，请把它包含在 `LLM_BASE_URL` 中；local-rag 只会追加
`/chat/completions`。

### Kimi / Moonshot sample RAG 实际运行例子

下面是用 Kimi 的 OpenAI-compatible API 跑通 sample vault 的实际命令路径。应用代码仍然
只读取通用 `LLM_*` 变量；这里只是在 shell 层把 `KIMI_API_KEY` 映射成
`LLM_API_KEY`。

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

另开一个 shell：

```bash
curl -sS http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"客户 P1 工单应该怎么升级？请用中文简洁回答。","top_k":5,"fallback":false}'
```

真实运行得到的 response 形状示例：

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

这里使用 `moonshot-v1-8k`，因为 MVP 的 LLM wire contract 固定发送
`temperature=0`。有些 Kimi 模型，例如 `kimi-k2.6`，可能要求不同 temperature，
会拒绝这个 MVP 请求形状。

### SOCKS proxy 排查

一些本地代理或 VPN 工具会导出这样的环境变量：

```bash
ALL_PROXY=socks5://127.0.0.1:15235
```

`httpx` 会自动读取这些 proxy 变量。如果环境里存在 SOCKS proxy，但 Python 环境
没有安装 SOCKS 支持，真实 LLM 调用可能失败：

```text
Using SOCKS proxy, but the 'socksio' package is not installed
```

如果 provider 可以直连，启动 `uvicorn` 或运行 `rag ask` 前可以在当前 shell 里
禁用 proxy 变量：

```bash
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
```

如果必须走 SOCKS proxy，则安装 SOCKS 支持：

```bash
pip install "httpx[socks]"
```

## 语义 demo：local-qwen3

FDE 语义 demo 前可以使用这条路径。模型会先下载到磁盘缓存，只有在进程实际使用
`local-qwen3` 时才加载到内存。

安装可选 runtime：

```bash
source .venv/bin/activate
pip install -e ".[local-qwen3]"
```

下载 / warm up 模型：

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
rag embeddings warmup
```

默认缓存目录是 `.cache/embeddings`。本项目当前下载缓存约 `1.1G`。缓存会留在磁盘；
模型权重只在 `rag embeddings warmup`、`rag ingest`、`rag search` 等进程运行时加载到内存。
长时间运行的 API 进程会在该进程内复用已加载模型。

构建 local-qwen3 embeddings：

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
rag ingest samples/acme-vault
```

运行手工质量 gate：

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
pytest -m local_qwen3 tests/test_local_qwen3_threshold.py -s
```

当前 gate 摘要：

```text
resolved_threshold=0.35
min_expected_top_score=0.6738
max_no_answer_top_score=0.2727
margin=0.4011
```

这个手工 gate 不属于默认 CI。

## 手工 live gate

sample vault ingest 完成，并且 API server 启动后，可以通过 HTTP `/ask` 验证真实
OpenAI-compatible provider：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个 shell：

```bash
scripts/manual_live_ask.sh
```

脚本需要 `LLM_PROVIDER=openai-compatible`、`LLM_BASE_URL`、`LLM_MODEL` 和
`LLM_API_KEY`。输出只包含 `mode`、`answer` 和 `citations`，不会打印 API key。
更多信息见 [Manual Live Gate](docs/manual-live-gate.md)。

## 配置

复制 `.env.sample` 到 `.env`。运行时优先级：

```text
OS environment / shell export > .env > code defaults
```

重要默认值：

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

当 `RAG_MIN_SIMILARITY` 为空时，provider 默认阈值是：

- `fake`：`0.20`
- `local-qwen3`：`0.35`

打印脱敏配置摘要：

```bash
rag config
```

## 测试

默认测试不需要真实 embedding 模型或 API key：

```bash
pytest
```

端到端 smoke test：

```bash
pytest tests/test_smoke.py
```

测试 harness 使用 `TEST_DATABASE_URL`，并且会拒绝对不以 `_test` 结尾或等于
`DATABASE_URL` 的数据库执行 destructive cleanup。

手工 local-qwen3 gate：

```bash
EMBEDDING_PROVIDER=local-qwen3 \
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
EMBEDDING_DEVICE=cpu \
pytest -m local_qwen3 tests/test_local_qwen3_threshold.py -s
```

## 文档

- [MVP Scope](docs/mvp.md)
- [MVP Subtasks](docs/mvp-subtasks.md)
- [FDE Demo Script](docs/demo-script.md)
- [Manual Live Gate](docs/manual-live-gate.md)
- [Roadmap to Full Release](docs/roadmap-to-full-release.md)
