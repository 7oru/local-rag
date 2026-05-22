# Roadmap to Full Release

本文档描述 `local-rag` 从 MVP 到企业级完整 sample 的路线。目标不是构建一个庞大的平台，而是形成一个 FDE 可以用于企业知识库落地的高质量 reference implementation。

## Release Philosophy

项目遵循 local-first、explainable、agent-ready 三个原则。

### Local-first

默认可以在客户本地环境运行：

- Docker Compose 一键启动。
- 知识库来自本地文件夹或 Obsidian vault。
- Postgres + pgvector 作为本地索引层。
- LLM 和 embedding provider 可通过环境变量切换。
- local-first 不等于完全离线；LLM 可以连接远程 OpenAI-compatible provider。
- 默认自动化 smoke test 应可无外网运行，但 agent-facing 链路完成后必须有一次真实 OpenAI-compatible 联网验证。

### Explainable

系统必须能解释答案从哪里来：

- 每个回答有 citations。
- 每次检索有 scores，API 返回的 score 是 cosine similarity，越高越相关。
- fallback 和 RAG 答案明确区分。
- ingest 和 retrieval 有可观测日志。

### Agent-ready

agent 使用 RAG API，而不是直接连数据库：

```text
Agent
  -> /search or /ask
  -> RAG API
  -> Postgres + pgvector
```

这样可以控制权限、prompt、fallback、引用和检索策略。

MVP 中 agent-facing API 只包含 `/search` 和 `/ask`；ingest 是 operator / FDE 通过 CLI 触发的索引构建动作，不作为 agent HTTP API 暴露。

## Milestone 0: Project Foundation

目标：建立清晰的项目定位和文档入口。

交付物：

- README 项目定位。
- MVP scope 文档。
- Full release roadmap。
- 基础 repo 结构。

完成标准：

- 新读者能在 5 分钟内理解这个项目服务于什么场景。
- FDE 能用文档解释 PoC 的目标和边界。

## Milestone 1: MVP Local RAG

目标：完成最小可用的本地 RAG 闭环。

核心能力：

- Docker Compose 只启动 Postgres + pgvector；Python API、CLI、pytest 在本地 venv 中运行。
- Postgres 默认只暴露到宿主机 loopback，便于本地 venv 复用 Docker 数据库。
- Python venv + `requirements.txt` 本地开发路径。
- Markdown / Obsidian vault 扫描。
- frontmatter、tags、wikilinks、heading 解析。
- heading-aware chunking，token 计数使用 `tiktoken` `cl100k_base`。
- embedding provider abstraction：MVP 只支持 `fake` 和 `local-qwen3`；`local-qwen3` 固定模型 `Qwen/Qwen3-Embedding-0.6B`，test-only 使用 fake lexical deterministic embedding。
- fake embedding 只证明 pipeline/source-hit 接线，不代表真实语义检索质量。
- 默认 quickstart / CI / smoke test 使用 `EMBEDDING_PROVIDER=fake`，不下载模型。
- FDE 现场语义 demo 显式设置 `EMBEDDING_PROVIDER=local-qwen3` 和固定 `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`，并提供模型缓存和预热路径。
- `local-qwen3` 是本地 embedding provider；首次 warmup 可联网下载约 1.2GB 权重到本地 cache，之后 ingest/search 在本地 venv 中推理，不调用远程 embedding API；该 warmup 是 manual/network gate，不进入默认 CI 或无人值守 smoke test。
- `local-qwen3` query embedding 使用 Qwen query prompt，document/chunk embedding 不加 query instruction，query 和 document/chunk 向量都 L2 normalize。
- MVP 固定 `EMBEDDING_DIM=1024`，pgvector 使用 `vector(1024)`；多维度共存不进入 MVP。
- embedding cache 默认使用 `.cache/embeddings` 或 `$HOME/.cache/local-rag/embeddings`。
- schema 初始化统一走 `app/schema.sql`；fresh Docker volume 用 Postgres init script，现有 DB / 本地 / 测试用 `rag db init`。
- `vault_path` 入库前 canonicalize，`relative_path` 使用稳定 POSIX 相对路径。
- 删除文件使用 hard delete document row + `ON DELETE CASCADE`；MVP 不实现 soft delete。
- `chunks.content_hash` 不建唯一约束，允许同一文档内重复段落。
- 增量 ingest，通过 `rag ingest` 触发；MVP 不提供 `POST /ingest`。
- CLI quickstart 使用宿主机 venv：`rag ingest samples/acme-vault`。
- pgvector cosine search，内部 raw cosine similarity 可能为 `-1..1`；API 层返回 clamped `0..1` score，并按当前 embedding provider/model/dim 过滤；MVP correctness path 使用 exact scan，HNSW / approximate index 只作为后续性能优化。
- API `source` 固定等于 POSIX `relative_path`，`heading` 是 `heading_path` 的最后一项；没有 heading 时返回空字符串。
- `top_k` 默认 `5`，范围 `1..20`；空检索结果返回 `confidence=0.0`、`results=[]`。
- 主路径必须先 `cp .env.sample .env`；Docker Compose 从 `.env` 读取 Postgres 配置，本地 venv 从 `.env` 读取 RAG/LLM/embedding 配置；`.env` 不提交。
- `.env.sample` 提供完整默认值，默认 quickstart / 自动测试用 `LLM_PROVIDER=fake`，live test 可改为 Kimi-compatible 示例值；代码只读取通用 `LLM_*` 变量。
- `LLM_PROVIDER=fake|openai-compatible`；真实 OpenAI-compatible 验证显式使用 `openai-compatible`。
- OpenAI-compatible LLM client。
- `/health`、`/search`、`/ask`。
- `pyproject.toml` console script + `app/cli.py` CLI scaffold，逐步接入 `rag db init`、`rag embeddings warmup`、`rag ingest`、`rag search`、`rag ask`。
- citations。
- confidence、`no_answer` 和 `fallback` mode；MVP 不实现 `mixed` mode。
- 初始 `RAG_MIN_SIMILARITY`：fake provider 目标值 `0.90` 必须先用 sample vault/questions 做实际分布校准后固化；`local-qwen3` 初始值 `0.35` 也用 sample questions 校准。
- `RAG_FALLBACK_ENABLED=false` 作为全局 fallback kill switch；request-level `fallback=true` 只有在全局开关打开时生效。
- `RAG_CONTEXT_TOKEN_BUDGET=6000` 作为 MVP context packing 初始默认。
- sample enterprise vault。
- `eval/questions.yaml`，包含至少 5 个 sample questions 和 expected sources。
- 固定实现选型：FastAPI/Uvicorn、Pydantic v2、psycopg 3、Typer、httpx、python-frontmatter、markdown-it-py、tiktoken `cl100k_base`、pytest；默认 dependencies 只覆盖 fake/smoke/CI，`local-qwen3` runtime 作为 optional extra / manual dependency，使用 `sentence-transformers>=2.7.0`、`transformers>=4.51.0`、`torch`。

质量门槛：

- sample vault 能成功索引。
- 默认 quickstart ingest 不下载真实 embedding 模型。
- demo embedding provider 能在 CPU 环境下索引 sample vault；模型缓存和预热命令可用于现场前准备。
- 至少 5 个 sample questions 命中正确来源。
- 低相关问题默认 `no_answer`。
- `fallback=true` 且 `RAG_FALLBACK_ENABLED=true` 时明确返回 `fallback` mode。
- `RAG_MIN_SIMILARITY` 初始目标和 fake scoring 规则经过 calibration test 固化，并且 sample questions 验收能稳定区分 `rag` / `no_answer`。
- 默认 smoke test 不依赖外网或真实 API key。
- DB/API 测试共享早期 test harness，通过 `TEST_DATABASE_URL` 连接测试库；destructive cleanup 必须验证库名以 `_test` 结尾且不等于 demo `DATABASE_URL`，并强制注入 fake embedding / fake LLM provider，pytest 不负责启动 Docker。
- agent-facing `/ask` 链路完成后，使用 `LLM_PROVIDER=openai-compatible` 和已经初始化好的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 通过 HTTP `POST /ask` 做一次 manual live release gate；它不属于默认 CI 或无人值守 smoke test。
- API key 不进入日志。

## Milestone 2: Demo-grade FDE Experience

目标：让 FDE 可以稳定用于客户现场演示。

新增能力：

- `docs/fde-runbook.md`。
- `docs/demo-script.md`。
- `docs/architecture.md`。
- `docs/troubleshooting.md`。
- sample vault 内容扩展为完整企业故事。
- 一键 reset demo 数据。
- 标准 demo questions。
- `/health`、`/search`、`/ask` API examples。
- Docker healthchecks。
- 更清晰的 error messages。

演示脚本覆盖：

- 启动服务。
- 打开 sample vault。
- 修改一篇 Markdown 笔记。
- 通过 `rag ingest` 重新 ingest。
- 询问问题并返回引用。
- 展示低置信度 no-answer。
- 展示 fallback mode。
- 展示 agent 调用 `/search`。

质量门槛：

- FDE 按 runbook 可以在全新机器上完成 15 分钟演示。
- Demo 中每个回答都有可打开的源文件。
- 常见失败模式有排查说明。

## Milestone 3: Retrieval Quality Upgrade

目标：让 sample 能展示企业 RAG 调优思路。

新增能力：

- Hybrid search：vector + keyword。
- metadata filters：path、tag、frontmatter。
- title / heading boost。
- optional reranker。
- query rewrite。
- adjacent chunk expansion。
- deterministic context packing strategy：固定排序、去重、citation 编号、预算截断和引用格式。
- retrieval debug endpoint。

接口示例：

```http
POST /search
{
  "query": "...",
  "top_k": 8,
  "filters": {
    "tags": ["support"],
    "frontmatter.product": "Atlas CRM"
  },
  "debug": true
}
```

质量门槛：

- eval set 的 expected source hit rate 可被量化。
- 检索 debug 输出能解释为什么某个 chunk 被选中。
- hybrid search 可以在关键词型问题上优于纯 vector search。

## Milestone 4: Evaluation Harness

目标：给企业客户展示可重复的质量评估方法。

新增能力：

- `eval/questions.yaml`。
- eval runner。
- source hit rate。
- citation coverage。
- fallback accuracy。
- answer faithfulness spot check。
- latency metrics。
- markdown/html eval report。

eval item 示例：

```yaml
- id: support-p1-escalation
  question: 客户 P1 工单应该如何升级？
  expected_sources:
    - policies/Support Escalation Policy.md
  expected_mode: rag
  must_include:
    - on-call engineer
    - escalation owner
```

质量门槛：

- 每次修改 chunking、embedding、retrieval threshold 后可以跑 eval。
- 报告展示命中率、失败样例和改进建议。

## Milestone 5: Security and Governance Sample

目标：展示企业落地时的数据边界和治理模型。

新增能力：

- vault read-only policy。
- API key redaction。
- request logging without sensitive content option。
- metadata-based access filter sample。
- document classification metadata。
- deny fallback for restricted content。
- audit log table。

示例 metadata：

```yaml
---
owner: support
product: Atlas CRM
security_level: internal
allowed_roles:
  - support
  - engineering
---
```

注意：full release sample 可以展示 RBAC pattern，但不需要成为完整 IAM 产品。

质量门槛：

- 文档说明哪些能力是 sample，哪些需要客户生产环境集成。
- restricted metadata 可以影响 retrieval filters。
- fallback 不会绕过 knowledge policy。

## Milestone 6: Agent Integration

目标：让不同 agent 能稳定接入本地知识库。

新增能力：

- Tool-style HTTP API 文档。
- MCP server。
- Optional OpenAI-compatible `/v1/chat/completions` wrapper。
- Agent examples。
- OpenClaw integration note。
- Codex usage examples。

推荐工具：

```text
rag_search(query, top_k, filters)
rag_ask(question, fallback, filters)
rag_get_source(source, heading)
```

质量门槛：

- agent 可以查询知识库但不能直接写 Postgres。
- tool response 结构稳定。
- citations 对 agent 可机器读取。

## Milestone 7: Document Source Expansion

目标：从 Markdown sample 扩展到更接近企业真实文档生态。

新增 source connectors：

- Local folders。
- Markdown / Obsidian。
- PDF。
- DOCX。
- CSV。
- HTML export。
- Confluence export。
- Google Drive export。

设计原则：

- connectors 输出统一 `Document` abstraction。
- chunking 可按 source type 定制。
- metadata 保留来源系统信息。

质量门槛：

- Markdown/Obsidian 仍是最简单主路径。
- 新 connector 不破坏 MVP quickstart。

## Milestone 8: Operations and Production Readiness Patterns

目标：展示从 PoC 走向生产需要补齐的运行能力。

新增能力：

- Background ingest worker。
- Watch mode。
- Scheduled re-index。
- Structured logs。
- Metrics endpoint。
- Database migrations。
- Backup and restore guide。
- pgvector index tuning guide。
- deployment variants。

部署变体：

- Docker Compose local。
- Single VM。
- Kubernetes reference manifests。
- Managed Postgres with pgvector。

质量门槛：

- 文档明确区分 sample deployment 和 production deployment。
- 有迁移和重建索引指南。
- 有 embedding 模型升级流程。

## Milestone 9: Minimal Web UI

目标：给非工程观众一个可视化入口，但不让 UI 成为项目主线。

UI 能力：

- Ask 页面。
- Search debug 页面。
- Ingest status 页面。
- Source citation preview。
- Eval report viewer。

原则：

- UI 服务于 demo 和 debugging。
- 不替代 Obsidian 作为知识维护界面。
- 不做复杂 CMS。

质量门槛：

- FDE 可以不用 curl 完成基础演示。
- 检索和引用仍然可解释。

## Milestone 10: Full Release

目标：形成一个完整、稳定、可讲解、可扩展的企业知识库 sample。

Full release 应包含：

- 完整 local-first RAG implementation。
- sample enterprise vault。
- FDE runbook。
- demo script。
- architecture guide。
- evaluation harness。
- security/governance guide。
- agent integration examples。
- troubleshooting guide。
- production readiness notes。

Full release 不承诺：

- 替代客户生产 IAM。
- 成为完整知识库 CMS。
- 成为多租户 SaaS。
- 覆盖所有文档格式。
- 自动保证所有答案正确。

它承诺的是：

> 给 FDE 一个可信、可解释、可本地运行的企业 RAG reference sample，用来帮助客户理解从知识源到 agent 的完整落地路径。

## Suggested Versioning

```text
v0.1.0  MVP local RAG
v0.2.0  FDE demo experience
v0.3.0  retrieval quality upgrade
v0.4.0  eval harness
v0.5.0  security/governance sample
v0.6.0  MCP and agent integrations
v0.7.0  source connector expansion
v0.8.0  operations patterns
v0.9.0  minimal web UI
v1.0.0  full release sample
```

## Open Decisions

这些问题需要在实现过程中根据 demo 体验和客户反馈决定：

- 默认 chunk size 是否偏向中文笔记还是英文企业文档？
- eval harness 第一版是否依赖 LLM judge？
- Web UI 是否需要早于 v0.9.0？

## Risks

主要风险：

- sample 过度工程化，失去一键演示体验。
- 只追求 demo 流畅，忽略引用、fallback 和治理边界。
- embedding 和 retrieval 策略没有评估闭环，质量靠感觉调参。
- 把 fake embedding 当成 demo 默认模型，导致现场语义检索效果不可信。
- fake embedding 如果做成 opaque hash，会让离线 smoke source-hit 验收随机失效。
- demo embedding 首次运行下载模型、缺少缓存或依赖过重，导致现场一键启动失败。
- schema 初始化路径分裂，导致 Docker、CLI、测试各自创建不同表结构。
- 把 local-first 误解为必须完全离线，或把默认 smoke test 绑定到外部网络。
- agent 接口过早绑定某个具体 agent framework。
- Obsidian 支持被误解为必须开发 Obsidian 插件。

对应策略：

- 保持 Docker Compose quickstart 永远可用。
- 默认保守 fallback。
- 所有答案优先 citations。
- fake embedding 只用于测试，demo 使用真实语义 embedding。
- fake embedding 使用 lexical feature hashing，sample questions 设计为可稳定命中 expected sources。
- schema 只从 `app/schema.sql` 初始化，`rag db init` 和 Docker init script 复用同一文件。
- 明确模型缓存目录、预热命令、CPU 默认路径和 Docker runtime 依赖。
- 默认 smoke test 离线可重复，live OpenAI-compatible check 作为单独验收门。
- agent 先接 HTTP tool API，再扩 MCP。
- Obsidian 只作为 Markdown 可视化维护层。
