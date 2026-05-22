# MVP Scope

本文档定义 `local-rag` 的 MVP 边界。这个 MVP 不是个人玩具 demo，而是一个 FDE 可以带到企业现场演示的 local-first RAG reference sample。

## 目标

MVP 的目标是跑通一个可信的企业知识库闭环：

```text
Markdown / Obsidian vault
  -> 解析
  -> 切块
  -> embedding
  -> pgvector 索引
  -> 检索
  -> OpenAI-compatible LLM 生成答案
  -> 返回引用
  -> agent 调用
```

MVP 应该让 FDE 可以在客户现场回答这些问题：

- 企业知识如何进入系统？
- 业务同事如何维护知识？
- RAG 答案如何追溯到原文？
- 检索没命中时系统如何避免幻觉？
- agent 如何安全地使用企业知识库？
- PoC 如何在本地一键启动，不依赖复杂云资源？

## 目标用户

- FDE：用于企业客户现场演示、PoC 搭建、需求澄清和技术方案讲解。
- 企业技术团队：用于理解 RAG 的基础架构、数据边界和可扩展路径。
- 业务知识维护者：通过 Obsidian 或 Markdown 文件夹维护 sample 知识库。

## MVP 演示故事

MVP 应内置一个模拟企业知识库，例如 `samples/acme-vault/`：

```text
samples/acme-vault/
  00-index.md
  products/
    Atlas CRM.md
    Atlas CRM FAQ.md
  policies/
    Data Handling Policy.md
    Support Escalation Policy.md
  runbooks/
    API Latency Runbook.md
    Postgres Incident Runbook.md
  sales/
    Competitive Positioning.md
  support/
    Common Customer Issues.md
```

FDE 可以演示以下问题：

- 客户 P1 工单应该如何升级？
- Atlas CRM 支持哪些数据导出限制？
- API 延迟升高时值班工程师应该怎么处理？
- 哪些客户数据不能发给外部模型？
- 和竞品对比时销售应该避免哪些说法？

每个回答都必须返回来源文件和标题路径。

这些问题应整理到 `eval/questions.yaml`，每个条目至少包含 `id`、`question`、`expected_sources`、`expected_mode`，用于 smoke test 和 threshold 校准。

## 一键部署

MVP 的主路径是：**Postgres/pgvector 跑在 Docker，Python API 和 CLI 跑在本地 venv**。

```bash
cp .env.sample .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`.env.sample` 提供完整配置模板，用户先复制为 `.env`；`.env` 不提交，必须加入 `.gitignore`。Docker Compose 使用 `.env` 中的 Postgres 配置启动数据库，本地 Python 服务和 CLI 读取同一个 `.env` 中的 RAG/LLM/embedding 配置。默认 `.env` 使用 `LLM_PROVIDER=fake` 和 `EMBEDDING_PROVIDER=fake`，用于无外网 smoke。

`.env.sample` 至少包含：

```text
POSTGRES_DB=local_rag
POSTGRES_USER=local_rag
POSTGRES_PASSWORD=local_rag
DATABASE_URL=postgresql://local_rag:local_rag@localhost:5432/local_rag
TEST_DATABASE_URL=postgresql://local_rag:local_rag@localhost:5432/local_rag_test
VAULT_PATH=samples/acme-vault
EMBEDDING_PROVIDER=fake
EMBEDDING_MODEL=fake-lexical-v1
EMBEDDING_DIM=1024
EMBEDDING_DEVICE=cpu
EMBEDDING_CACHE_DIR=.cache/embeddings
LLM_PROVIDER=fake
LLM_BASE_URL=
LLM_MODEL=fake-local
LLM_API_KEY=
LLM_TIMEOUT_SECONDS=30
RAG_TOP_K=5
RAG_MIN_SIMILARITY=
RAG_CONTEXT_TOKEN_BUDGET=6000
RAG_FALLBACK_ENABLED=false
```

配置加载必须使用 `python-dotenv`。本地 venv 进程启动时加载 repo 根目录 `.env`，并使用 `override=False`，因此优先级固定为：**OS environment / shell export > `.env` > 代码内默认值**。`.env` 路径不能依赖当前工作目录：CLI 必须从当前目录向上查找同时包含 `pyproject.toml` 和 `.env.sample` 的 repo root，或通过 `rag --env-file PATH` 显式指定。空字符串视为未设置；`RAG_MIN_SIMILARITY=` 为空表示使用 provider 动态默认值，`fake` 初始目标解析为 `0.90` 且必须通过 fake calibration 测试固化，`local-qwen3` 解析为 `0.35`。如果用户显式在 shell 或 `.env` 中设置 `RAG_MIN_SIMILARITY`，显式值覆盖 provider 默认值。配置摘要必须打印 resolved threshold，但不能打印 API key，只能打印 API key 是否存在。

做真实联网测试时修改 `.env` 中的通用 `LLM_*` 变量，例如：

```text
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k
LLM_API_KEY=
```

用户本地测试时可以在 `.env` 中填入 `LLM_API_KEY`，也可以在 shell 层仅当 `KIMI_API_KEY` 非空时执行 `export LLM_API_KEY="$KIMI_API_KEY"` 把已有 provider key 映射到通用变量。代码只读取通用 `LLM_*` 变量，不读取 Kimi-specific 环境变量。本地 venv 主路径默认读取 `.env`，其中 `DATABASE_URL` 必须是宿主机可访问的地址。

默认 quickstart 和 CI 使用 `EMBEDDING_PROVIDER=fake`，不会下载 embedding 模型。FDE 现场语义 demo 必须显式设置 `EMBEDDING_PROVIDER=local-qwen3` 和 `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`，并先执行 `rag embeddings warmup` 预热模型缓存。

本地开发路径使用 Python venv：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Docker Compose 只包含：

- `postgres`：Postgres + pgvector。

Postgres 默认只暴露到宿主机 loopback：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-local_rag}
      POSTGRES_USER: ${POSTGRES_USER:-local_rag}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-local_rag}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./app/schema.sql:/docker-entrypoint-initdb.d/001-schema.sql:ro
    ports:
      - "127.0.0.1:5432:5432"

volumes:
  postgres_data:
```

MVP 不允许使用普通 `postgres:*` image 代替 pgvector image。fresh volume 会由 `/docker-entrypoint-initdb.d/001-schema.sql` 自动执行 schema；已有 volume 不会重新跑 Docker init script，必须通过 `rag db init` 执行同一个 `app/schema.sql`。

CLI 始终在宿主机 venv 中执行。默认 sample vault 路径是 `samples/acme-vault`；企业现场 PoC 可以把命令参数换成客户自己的 Obsidian vault 路径。

```bash
rag ingest samples/acme-vault
rag search "客户 P1 工单应该怎么升级？"
rag ask "客户 P1 工单应该怎么升级？"
```

## Implementation Choices

MVP 固定以下技术选型，避免 quickstart 和 subtasks 在实现时分叉：

- Python `3.11+`。
- API：`fastapi` + `uvicorn`。
- API schema：`pydantic` v2。
- 配置：`python-dotenv`。
- DB client：`psycopg` 3，不引入 ORM。
- CLI：`typer` + `pyproject.toml` console script。
- HTTP client / live check：`httpx` 或 `curl`。
- Markdown/frontmatter：`python-frontmatter` + `markdown-it-py`。
- token 计数：`tiktoken` 的 `cl100k_base`。
- 测试：`pytest`。
- 默认 `requirements.txt` 只包含 fake/smoke/CI 必需依赖。
- `local-qwen3` runtime 作为 optional extra / manual dependency：`sentence-transformers>=2.7.0`、`transformers>=4.51.0`、`torch`。

## MVP 功能

### Markdown / Obsidian Ingestion

MVP 支持扫描 `.md` 文件，并解析：

- 文件路径。
- YAML frontmatter。
- Markdown 标题。
- `#tag`。
- `[[Wiki Link]]`。
- `[[path/Page|Alias]]`。
- 文件 hash。

索引过程应支持增量更新：

- hash 未变化的文件跳过。
- hash 变化的文件重建 chunks 和 embeddings。
- 被删除的文件 hard delete 对应 `documents` row，并通过 `ON DELETE CASCADE` 删除 chunks 和 embeddings。

路径规范化 contract：

- `vault_path` 入库前必须 canonicalize：`Path(vault_path).expanduser().resolve(strict=True)`。
- `relative_path` 必须相对 canonical vault root 计算，使用 POSIX 分隔符 `/`，不得以 `./` 开头，不得包含 `..`。
- `file_path` 必须是文件的 resolved absolute path。

### Chunking

MVP 采用 heading-aware chunking：

- 先按 Markdown 标题层级切分。
- 每个 chunk 保留 `heading_path`。
- token 计数使用 `tiktoken` 的 `cl100k_base` tokenizer，避免不同实现用字符数、中文分词或模型私有 tokenizer 产生分叉。
- 目标大小：400 到 800 tokens。
- 最大大小：1200 tokens。
- overlap 默认 80 tokens。

chunk 应尽量能独立表达完整语义。

### Embedding

pgvector 不生成 embedding，只负责存储和检索向量。MVP 需要一个 embedding abstraction：

- MVP 只支持两个 embedding provider：`fake` 和 `local-qwen3`。
- `local-qwen3` 固定模型：`Qwen/Qwen3-Embedding-0.6B`。
- `fake` 固定模型标识：`fake-lexical-v1`。
- test-only provider：`fake` lexical deterministic embedding，用于 unit test、无网络 smoke test、CI。
- 自定义 embedding model、远程 embedding provider、`BAAI/bge-m3` 不进入 MVP。
- 每条 embedding 记录 provider、模型名和维度。

默认 quickstart、Docker Compose 和 CI 使用 `EMBEDDING_PROVIDER=fake`，不下载模型。`fake` provider 不作为 FDE demo 默认 embedding。它不是 opaque hash，也不是语义模型；它使用 deterministic lexical feature hashing，对归一化文本、CJK 字符、英文数字 token、标题和路径 metadata 做 feature hashing，输出 1024 维向量。它必须让 lexical overlap 高的 query/chunk similarity 高于无关文本，保证 `eval/questions.yaml` 中刻意设计的 sample questions 可以稳定命中 expected sources。fake smoke test 的 source-hit 只证明 pipeline、metadata、filtering 和 scoring 接线正确，不代表真实语义检索质量。

`fake-lexical-v1` 算法 contract：

- 输入由 `content`、`heading_path`、`relative_path`、`tags`、`wikilinks` 组成；query 只有 `content`。
- 文本 normalization：Unicode NFKC、lowercase、把 `/\._-` 转为空格、压缩连续 whitespace。
- tokenization：英文/数字使用正则 `[a-z0-9]+`；CJK 使用单字 unigram 加相邻 bigram；长度为 1 的英文停用词丢弃。
- metadata weighting：`content` token 权重 `1.0`，`heading_path` 权重 `2.0`，`relative_path` 权重 `1.5`，`tags` 和 `wikilinks` 权重 `1.25`。
- hashing：使用 SHA-256，hash input 格式为 `fake-lexical-v1:{feature}`，取前 8 bytes big-endian unsigned int 后对 `1024` 取模；hash seed/version 不能随运行环境变化。
- accumulation：每个 token 按权重累加到对应 bucket；同一 token 可重复计数，但单字段内单个 token 贡献上限为 `4 * weight`，避免长文重复词压倒标题和路径。
- normalization：最终向量做 L2 normalization；空输入返回全零向量并由调用方视为不可检索输入。
- 验收校准：`0.90` 是 fake provider 的初始目标阈值，必须在 sample vault/questions 上实际计算分布后固化；如果分布没有稳定 margin，应先调整 sample question、metadata 权重或 fake provider resolved default，并记录在测试里，不能用随机 seed 修正。

`EMBEDDING_MODEL` 用于配置摘要和 embedding metadata，但 MVP 中它必须与 provider 固定模型一致；如果 `EMBEDDING_PROVIDER=local-qwen3` 且 `EMBEDDING_MODEL` 不是 `Qwen/Qwen3-Embedding-0.6B`，或 `EMBEDDING_PROVIDER=fake` 且 `EMBEDDING_MODEL` 不是 `fake-lexical-v1`，配置校验必须失败。

切换 `fake` / `local-qwen3` 后必须为当前 provider 补齐对应 embeddings；增量 ingest 的 skip 判断不能只看文件 hash。

demo embedding 的执行边界：

- MVP 固定维度：`EMBEDDING_DIM=1024`。
- pgvector schema 使用 `vector(1024)`；MVP 不支持同一数据库内混存不同维度向量。
- 配置非 1024 的 `EMBEDDING_DIM` 时必须返回配置错误。
- 默认设备：`EMBEDDING_DEVICE=cpu`；可选支持 `mps` / `cuda`，但 MVP 不要求 GPU。
- 本地 venv 默认缓存目录：`EMBEDDING_CACHE_DIR=.cache/embeddings`，也可显式设为 `$HOME/.cache/local-rag/embeddings`。
- `.cache/embeddings` 应进入 `.gitignore`。
- 默认 `requirements.txt` 不安装 `local-qwen3` 大模型 runtime，确保 fake-only quickstart 足够轻。
- `local-qwen3` runtime 必须通过 optional extra 或单独 requirements 文件安装，例如 `pip install -e ".[local-qwen3]"` 或 `pip install -r requirements-local-qwen3.txt`；版本下限为 `sentence-transformers>=2.7.0`、`transformers>=4.51.0`、`torch`。
- `Qwen/Qwen3-Embedding-0.6B` 是本地 embedding 模型，约 0.6B 参数；BF16/FP16 权重约 1.2GB，建议为模型缓存预留至少 1.5GB 磁盘空间。
- `local-qwen3` 首次 `rag embeddings warmup` 可联网下载模型到 `EMBEDDING_CACHE_DIR`；缓存完成后，ingest/search 的 embedding 计算必须在本地 venv 中完成，不调用远程 embedding API。
- `local-qwen3` warmup / embed 验证是 manual/network gate，不进入默认 CI、无人值守 smoke test 或默认 task completion。
- FDE 客户现场前应先执行模型预热，确保现场可在无外网环境下使用缓存模型。
- `local-qwen3` 必须能在 CPU 环境下完成 sample vault ingest；如果首次运行需要下载模型，错误信息必须清楚提示缓存路径、预计模型大小和预下载命令。
- query embedding 必须使用 Qwen 的 query prompt 口径：优先使用 `SentenceTransformer.encode(..., prompt_name="query")`；如果封装不支持 `prompt_name`，使用固定 instruction：`Instruct: Given a user question, retrieve relevant passages from the local enterprise knowledge base that answer the question\nQuery: {query}`。
- document/chunk embedding 不加 query instruction，只使用 chunk content 和 metadata text。
- query 和 document/chunk 向量都必须 L2 normalize；pgvector cosine similarity 和 `local-qwen3` 阈值校准都基于 normalized vectors。

embedding 环境变量示例：

```text
EMBEDDING_PROVIDER=local-qwen3
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIM=1024
EMBEDDING_DEVICE=cpu
EMBEDDING_CACHE_DIR=.cache/embeddings
```

### Storage

MVP 使用 Postgres + pgvector。基础数据模型包含：

- `documents`：文件级记录。
- `chunks`：文本片段和 metadata。
- `embeddings`：chunk vector。
- `ingest_runs`：索引运行记录。

`embeddings` 向量列使用 `vector(1024)`。所有 provider 包括 `fake` 都必须输出 1024 维向量。多 embedding 维度共存不进入 MVP。

schema 初始化边界：

- `app/schema.sql` 是唯一 schema source of truth，包含 `CREATE EXTENSION IF NOT EXISTS vector`。
- Docker fresh volume 通过 `./app/schema.sql:/docker-entrypoint-initdb.d/001-schema.sql:ro` 执行同一个 `app/schema.sql`。
- 现有数据库、本地开发和测试通过 `rag db init` idempotently 执行同一个 `app/schema.sql`。
- API startup 和 ingest 不隐式创建表；如果 schema 未初始化，`/health` 返回数据库未就绪，`rag ingest` 返回清晰错误。

`app/schema.sql` 至少实现以下 DDL 语义；实现可以调整 index 名称，但不能放松类型、主外键、唯一约束、cascade、JSONB 和 vector contract：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id BIGSERIAL PRIMARY KEY,
  vault_path TEXT NOT NULL,
  file_path TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  mtime_ns BIGINT,
  size_bytes BIGINT,
  frontmatter JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (vault_path, relative_path)
);

CREATE TABLE IF NOT EXISTS chunks (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  file_path TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  heading_path TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
  frontmatter JSONB NOT NULL DEFAULT '{}'::jsonb,
  tags TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
  wikilinks TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash TEXT NOT NULL,
  token_count INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS embeddings (
  id BIGSERIAL PRIMARY KEY,
  chunk_id BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  embedding_provider TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_dim INTEGER NOT NULL CHECK (embedding_dim = 1024),
  embedding vector(1024) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (chunk_id, embedding_provider, embedding_model, embedding_dim)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
  id BIGSERIAL PRIMARY KEY,
  vault_path TEXT NOT NULL,
  embedding_provider TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_dim INTEGER NOT NULL CHECK (embedding_dim = 1024),
  status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  documents_added INTEGER NOT NULL DEFAULT 0,
  documents_updated INTEGER NOT NULL DEFAULT 0,
  documents_deleted INTEGER NOT NULL DEFAULT 0,
  documents_skipped INTEGER NOT NULL DEFAULT 0,
  chunks_written INTEGER NOT NULL DEFAULT 0,
  embeddings_written INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents (content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_relative_path ON chunks (relative_path);
CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks (content_hash);
CREATE INDEX IF NOT EXISTS idx_embeddings_config
  ON embeddings (embedding_provider, embedding_model, embedding_dim);
```

`documents.relative_path` 的唯一性以 `(vault_path, relative_path)` 为边界，避免不同 vault 的同名文件互相覆盖。`vault_path` 必须使用 canonical resolved path，避免 `samples/acme-vault`、`./samples/acme-vault` 和绝对路径被当作不同 vault。`chunks` 和 `embeddings` 必须通过 `ON DELETE CASCADE` 跟随 document 删除，支撑变化重建和删除同步。MVP 删除语义是 hard delete，不保留 `documents.deleted_at`，也不实现 soft delete retrieval filter。`chunks.content_hash` 可以有普通 index，但不能唯一，允许同一文档内重复段落。

每个 chunk 至少保存：

- `document_id`
- `chunk_index`
- `content`
- `file_path`
- `relative_path`
- `heading_path`
- `frontmatter`
- `tags`
- `wikilinks`
- `content_hash`
- `created_at`
- `updated_at`

每条 embedding 至少保存 `chunk_id`、`embedding_provider`、`embedding_model`、`embedding_dim`、`embedding`、`created_at`、`updated_at`。embedding metadata 归属 `embeddings` 表；`chunks` 不保存当前 embedding provider/model/dim，避免多个 provider 的索引状态互相覆盖。

### Retrieval

MVP 提供 vector search：

- query 生成 embedding。
- 使用 pgvector cosine distance 检索。
- 只检索当前 embedding config 对应的向量：`embedding_provider`、`embedding_model`、`embedding_dim` 必须与当前配置一致。
- MVP correctness path 使用 exact scan：先按当前 provider/model/dim 过滤，再按 pgvector cosine distance 排序。
- HNSW / approximate index 不作为 MVP DDL 必须项，也不能作为 smoke/source-hit 正确性依赖；后续若为性能添加 HNSW，测试必须仍能在 exact scan 下通过。
- 支持 `top_k`，默认 `5`，允许范围 `1..20`。
- 返回 similarity score。
- 返回 citations metadata。

推荐使用 pgvector cosine operator：

```sql
ORDER BY embedding <=> query_embedding
```

`<=>` 返回 cosine distance，值越低越相关。内部 raw similarity 转换规则为：

```text
raw_similarity = 1 - cosine_distance
```

真实 embedding 的 raw cosine similarity 可能为负数。MVP API 不直接暴露负分，`result.score` 必须 clamp 到 `0.0..1.0`：

```text
score = max(0.0, min(1.0, raw_similarity))
```

因此 `score` 越高表示越相关。`result.score` 是 chunk-level clamped similarity，`confidence` 是 query-level retrieval confidence；MVP 可以先用 top result clamped score 作为 confidence。

API 字段关系：

- `source == relative_path`，使用 POSIX 相对路径，也是 `eval/questions.yaml.expected_sources` 的匹配字段。
- `heading_path` 是完整标题路径；`heading` 是展示字段，取 `heading_path` 最后一个元素。
- 没有 heading 时 `heading` 返回空字符串 `""`，不回退到文件名。

`embeddings` 表应对 `(chunk_id, embedding_provider, embedding_model, embedding_dim)` 建唯一约束。旧 embeddings 可以留在库里，但 retrieval 不能混用不同 provider/model/dim。`EMBEDDING_DIM` 固定为 1024；如果配置或查询向量维度和 schema 不一致，search 应返回 `embedding_dim_mismatch` 配置错误而不是执行查询。空检索结果时 `confidence=0.0`、`results=[]`。

初始阈值策略：

- `RAG_MIN_SIMILARITY` 未设置或为空时，配置层按 provider 给出动态默认值。
- `fake` provider resolved default：fake calibration 固化后的值，初始目标为 `0.90`，用于 deterministic smoke test。
- `local-qwen3` resolved default：`0.35`，作为初始值。
- 显式设置 `RAG_MIN_SIMILARITY` 时，无论来自 OS env 还是 `.env`，都覆盖 provider 动态默认值。
- `local-qwen3` threshold 必须用 sample questions 校准，确保已知问题进入 `rag`，无关问题进入 `no_answer`。

后续可以加入 keyword search、metadata boost 和 rerank，但不进入 MVP 必须范围。

### Confidence and Fallback

MVP 必须明确区分回答模式：

- `rag`：知识库命中充分，只基于引用资料回答。
- `fallback`：知识库未命中，使用模型通用知识回答。
- `no_answer`：知识库未命中，且不允许 fallback。

MVP 不实现 `mixed` mode。

默认策略应保守：

```text
fallback=false
RAG_FALLBACK_ENABLED=false
```

也就是知识库没命中时返回 `no_answer`。`RAG_FALLBACK_ENABLED` 是全局 fallback kill switch，默认关闭。只有全局 `RAG_FALLBACK_ENABLED=true` 且调用方显式传入 `fallback=true`，才允许模型基于通用知识回答。

mode 判断：

```text
confidence >= RAG_MIN_SIMILARITY -> rag
confidence < RAG_MIN_SIMILARITY and fallback=false -> no_answer
confidence < RAG_MIN_SIMILARITY and fallback=true and RAG_FALLBACK_ENABLED=false -> no_answer
confidence < RAG_MIN_SIMILARITY and fallback=true and RAG_FALLBACK_ENABLED=true -> fallback
```

`no_answer` 不调用通用 LLM 回答。`fallback` 必须明确说明答案不是来自本地知识库，且 citations 为空。如果 request-level `fallback=true` 但全局 fallback 被关闭，应返回 `no_answer` 并说明 fallback 被全局禁用。

### Context Assembly

RAG context 必须 deterministic，避免 fake LLM 输出和测试断言随着实现细节漂移。

- 输入检索结果按 `score desc`、`source asc`、`heading_path asc`、`chunk_index asc` 排序。
- 去重 key 固定为 `(source, heading_path, content_hash)`，只保留第一次出现。
- context block 编号从 `1` 开始，按最终 block 顺序递增；编号用于 prompt/context 文本，`AskResponse.citations` 保持同样顺序但不新增编号字段。
- 每个 block 格式固定为 `[n] source: ...`、`heading: ...`、`score: 0.0000`、`content:` 加 chunk content。
- `score` 使用 clamped score 并格式化为 4 位小数；`heading` 为空时输出空字符串。
- token 预算用 `tiktoken` 的 `cl100k_base` 估算，最终 context 不得超过 `RAG_CONTEXT_TOKEN_BUDGET`。
- 截断策略固定：按排序后的 block 逐个加入；下一个完整 block 超预算就跳过；如果第一个 block 单独超预算，只截断 `content` 并追加 `[truncated]`。
- 空结果返回空 context string 和空 citations。

### Error Responses

所有 API error 使用统一结构：

```json
{
  "error": {
    "code": "schema_not_initialized",
    "message": "Database schema has not been initialized.",
    "details": {}
  }
}
```

MVP error code 和 HTTP status：

- `schema_not_initialized` -> `503`
- `llm_config_missing` -> `503`
- `llm_timeout` -> `504`
- `llm_auth_failed` -> `502`
- `llm_rate_limited` -> `503`
- `llm_upstream_error` -> `502`
- `embedding_dim_mismatch` -> `500`
- `invalid_request` / Pydantic validation -> `422`
- `retrieval_not_ready` -> `503`

`no_answer` 不是 error，返回 HTTP `200`。

FastAPI 必须注册 `RequestValidationError` handler，把默认 Pydantic/FastAPI 422 response 转换为统一 `ErrorResponse`：HTTP `422`，`error.code="invalid_request"`，不能保留默认顶层 `detail` shape。

返回结构示例：

```json
{
  "mode": "rag",
  "confidence": 0.82,
  "answer": "...",
  "citations": [
    {
      "source": "policies/Support Escalation Policy.md",
      "heading": "P1 Escalation",
      "score": 0.86
    }
  ]
}
```

### LLM Integration

MVP 使用 OpenAI-compatible client abstraction。

local-first 不等于完全离线：知识源、索引、Postgres/pgvector 和 RAG API 在本机；LLM 可以连接远程 OpenAI-compatible provider。默认自动化 smoke test 应可无外网运行；agent-facing `/ask` 链路完成后，另设一个 manual live release gate，使用 `LLM_PROVIDER=openai-compatible` 和已经初始化好的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 通过 HTTP `POST /ask` 做一次真实联网验证。该 gate 不属于默认 CI 或无人值守验收。

环境变量示例：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_PROVIDER=fake
LLM_MODEL=
LLM_TIMEOUT_SECONDS=30
RAG_CONTEXT_TOKEN_BUDGET=6000
RAG_FALLBACK_ENABLED=false
```

实现要求：

- 不在日志中打印 API key。
- `LLM_PROVIDER` 支持 `fake` 和 `openai-compatible`。
- 本地 venv 主路径通过 `python-dotenv` 读取 `.env` 配置，且 OS env 优先于 `.env`；`.env.sample` 提供完整模板，默认 `LLM_PROVIDER=fake`，用于无 API key quickstart 和默认自动化测试。
- `.env.sample` 可以提供 Kimi-compatible 示例值，但代码不能包含 Kimi-specific 分支。
- 真实 OpenAI-compatible 验证必须显式设置 `LLM_PROVIDER=openai-compatible`。
- `LLM_PROVIDER=openai-compatible` 时，`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 必须全部初始化；任一缺失时 `/ask` 必须返回清晰配置错误，不得静默 fallback 到 fake。
- 代码只读取通用 `LLM_*` 变量，不读取 provider-specific 环境变量。
- 支持 `LLM_TIMEOUT_SECONDS` 超时配置。
- context packing 不超过 `RAG_CONTEXT_TOKEN_BUDGET`。
- RAG prompt 必须要求模型只基于给定资料回答。
- fallback prompt 必须明确说明答案不是来自本地知识库。

OpenAI-compatible wire contract：

- 固定使用 non-streaming chat completions，MVP 不实现 streaming。
- endpoint 为 `LLM_BASE_URL.rstrip("/") + "/chat/completions"`；如果 provider 需要 `/v1`，它必须已经包含在 `LLM_BASE_URL` 中。
- headers 包含 `Authorization: Bearer {LLM_API_KEY}` 和 `Content-Type: application/json`，日志和异常不得打印 token 原文。
- request body 至少包含 `model`、`messages`、`temperature: 0`、`stream: false`；`messages` 使用 system/user 两段 prompt。
- response 读取 `choices[0].message.content`；缺失、非字符串或空白内容映射为 `llm_upstream_error`。
- timeout 映射为 `llm_timeout`；HTTP `401/403` 映射为 `llm_auth_failed`；HTTP `429` 映射为 `llm_rate_limited`；其他 HTTP/network/malformed response 映射为 `llm_upstream_error`。

manual live 验证时，必须先让本地 venv 进程读取最新 `.env`：

```bash
cp .env.sample .env
# Fill generic LLM_* values in .env.
# If your shell has KIMI_API_KEY, map it only at shell/test time:
if [ -n "${KIMI_API_KEY:-}" ]; then
  export LLM_API_KEY="$KIMI_API_KEY"
fi
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后在另一个 shell 执行：

```bash
curl -sS http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

### Agent API

MVP 不让 agent 直接连接 Postgres。agent 只通过本地 RAG API 使用知识库。

最小接口：

```http
POST /search
POST /ask
GET /health
```

`/search` 返回结构化检索结果，适合 agent 自己决定下一步。

`/ask` 返回已经生成好的带引用答案，适合快速 demo。

MVP 不提供 `POST /ingest`。ingest 是 operator / FDE 通过 `rag ingest` 触发的索引构建动作，不属于 agent-facing API。

## API 草案

### `GET /health`

返回服务、数据库、schema、pgvector、配置和当前检索索引状态。至少包含：

```json
{
  "status": "ok",
  "checks": {
    "app": "ok",
    "database": "ok",
    "schema": "ok",
    "pgvector": "ok",
    "embedding_config": "ok",
    "retrieval_ready": "ok"
  },
  "details": {
    "embedding_provider": "fake",
    "embedding_model": "fake-lexical-v1",
    "documents": 8,
    "chunks": 24,
    "embeddings_current_config": 24
  }
}
```

如果数据库不可连接、schema 未初始化或 pgvector 不可用，返回 `503` 和统一 error response。当前 embedding config 下还没有索引时，`GET /health` 仍返回 HTTP `200`，但 `retrieval_ready` 返回 `not_ready`，用于提示需要先执行 `rag db init` 和 `rag ingest`；真正需要检索的 `POST /search` 和 `POST /ask` 才返回 `503 retrieval_not_ready`。

### `POST /search`

请求：

```json
{
  "query": "客户 P1 工单应该怎么升级？",
  "top_k": 5
}
```

返回：

```json
{
  "confidence": 0.81,
  "results": [
    {
      "content": "...",
      "source": "policies/Support Escalation Policy.md",
      "relative_path": "policies/Support Escalation Policy.md",
      "heading_path": ["P1 Escalation"],
      "heading": "P1 Escalation",
      "score": 0.86
    }
  ]
}
```

### `POST /ask`

请求：

```json
{
  "question": "客户 P1 工单应该怎么升级？",
  "top_k": 5,
  "fallback": false
}
```

返回：

```json
{
  "mode": "rag",
  "confidence": 0.81,
  "answer": "...",
  "citations": [
    {
      "source": "policies/Support Escalation Policy.md",
      "heading": "P1 Escalation",
      "score": 0.86
    }
  ]
}
```

## CLI 草案

MVP 提供 CLI，方便本地操作和 smoke test。CLI 始终在宿主机 venv 中运行：

```bash
rag --help
rag db init
rag embeddings warmup
rag ingest samples/acme-vault
rag search "客户 P1 工单应该怎么升级？"
rag ask "客户 P1 工单应该怎么升级？"
```

CLI 入口通过 `pyproject.toml` console script 暴露：

```text
rag = "app.cli:main"
```

`app/cli.py` 负责统一 CLI 结构。`rag db init`、`rag embeddings warmup`、`rag ingest`、`rag search`、`rag ask` 的业务能力随对应任务逐步接入，最终由 CLI 任务统一 help text、参数、输出格式和 exit codes。

CLI 不依赖 `uvicorn` 或本地 API server。`rag search` 和 `rag ask` 必须调用与 HTTP endpoint 相同的 shared service layer；`POST /search`、`POST /ask` 也调用同一层。默认 smoke test 可以覆盖 CLI 和 in-process HTTP contract；live OpenAI-compatible 验证必须通过正在运行的 HTTP `POST /ask`。

## 非目标

MVP 不做以下内容：

- 完整 RBAC。
- 多租户权限隔离。
- Web UI。
- Obsidian 插件。
- PDF、Word、PPT、图片 OCR。
- 自动改写原始 Markdown 文件。
- 生产级身份认证。
- 分布式任务队列。
- 完整 MCP server。
- 完整 OpenAI `/v1/chat/completions` 兼容层。
- 自定义 embedding model 或远程 embedding provider。
- `POST /ingest` HTTP endpoint。

这些能力放入 full release roadmap。

## 企业边界

MVP 必须清楚展示以下边界：

- Obsidian vault 作为只读知识源。
- agent 不直接访问 Postgres。
- API key 只从环境变量读取。
- 低置信度时不把模型常识伪装成知识库答案。
- citations 返回原始文件路径和 heading。
- embedding provider 从 `fake` 切到 `local-qwen3` 时，需要为当前 provider 补齐对应 embeddings；MVP 不支持自定义模型或维度。
- agent-facing HTTP API 不暴露 ingest。

## 验收标准

MVP 完成时应满足：

- `cp .env.sample .env && docker compose up -d postgres` 可以启动 Postgres + pgvector。
- Docker Compose 使用 `pgvector/pgvector:pg16`，并把 `./app/schema.sql` mount 到 `/docker-entrypoint-initdb.d/001-schema.sql:ro`。
- `.env` 已加入 `.gitignore`，Docker Compose 从 `.env` 读取 Postgres 配置，本地 venv 通过 `python-dotenv` 读取 RAG/LLM/embedding 配置，且 OS env 覆盖 `.env`。
- `rag db init` 可以初始化 RAG 数据库。
- `rag ingest samples/acme-vault` 可以索引 sample vault。
- ingest 对 `vault_path` 做 canonicalization，`relative_path` 使用稳定 POSIX 相对路径。
- `uvicorn app.main:app --host 127.0.0.1 --port 8000` 可以启动本地 API 服务。
- `/health` 全面检查 app、database、schema、pgvector、embedding config 和当前检索索引状态。
- `/search` 可以返回相关 chunks 和 citations。
- `/ask` 可以返回带引用答案。
- 低相关问题默认返回 `no_answer`。
- 显式 `fallback=true` 且 `RAG_FALLBACK_ENABLED=true` 时返回 `fallback` mode。
- `eval/questions.yaml` 至少包含 5 个 sample questions，且 smoke test 验证 expected source 命中。
- 默认 smoke test 使用 `EMBEDDING_PROVIDER=fake` 和 `LLM_PROVIDER=fake`，不依赖外网、真实 API key 或模型下载。
- DB/API 测试共享早期 test harness：通过 `TEST_DATABASE_URL` 连接测试库，先验证库名以 `_test` 结尾且不等于 demo `DATABASE_URL`，再允许 schema init、清表或 CLI subprocess；smoke test 复用同一 fixture，并强制注入 `EMBEDDING_PROVIDER=fake`、`EMBEDDING_MODEL=fake-lexical-v1`、`LLM_PROVIDER=fake`，防止开发机 shell 环境触发模型下载或真实 API。
- agent-facing `/ask` 链路完成后，使用 `LLM_PROVIDER=openai-compatible` 和已经初始化好的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 通过 HTTP `POST /ask` 完成一次 manual live release gate；它不属于默认 CI 或无人值守 smoke test。
- README 包含 5 分钟 quickstart。
- sample vault 能用 Obsidian 直接打开。
- 至少有一个 smoke test 覆盖 ingest/search/ask 基础闭环。

## 建议项目结构

```text
local-rag/
  docker-compose.yml
  pyproject.toml
  requirements.txt
  .env.sample
  README.md
  docs/
    mvp.md
    roadmap-to-full-release.md
  app/
    main.py
    config.py
    db.py
    schema.sql
    markdown.py
    chunking.py
    embeddings.py
    ingest.py
    cli.py
    retrieval.py
    context.py
    llm.py
    prompts.py
    schemas.py
  samples/
    acme-vault/
  eval/
    questions.yaml
  tests/
```
