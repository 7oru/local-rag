# MVP Subtasks

本文档把 `local-rag` MVP 拆成可验证、可拆解、可理解的工程任务。每个任务都应该能独立解释价值、明确产物，并通过命令、测试或演示验证。

## 拆解原则

每个 subtask 遵循以下格式：

- 目标：这个任务解决什么问题。
- 产物：完成后 repo 里应该出现什么。
- 验证：如何证明它真的工作。
- 依赖：它依赖哪些前置任务。

任务颗粒度建议控制在半天到两天内。超过两天的任务继续拆小。

## MVP 完成定义

MVP 完成时，FDE 应能在本地跑通这条链路：

```text
cp .env.sample .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
docker compose up -d postgres
  -> rag db init
  -> ingest sample Obsidian-style Markdown vault
  -> search relevant chunks
  -> ask question
  -> receive answer with citations
  -> see no_answer or fallback behavior on low-confidence queries
```

MVP 的 ingest 能力是必须项，但只通过 CLI 或内部函数触发；MVP 不提供 `POST /ingest`。Agent-facing HTTP API 只包含 `GET /health`、`POST /search`、`POST /ask`。

MVP 的默认自动化 smoke test 应可在无外网、无真实 API key 的情况下运行。Agent-facing `/ask` 链路完成后，必须额外执行一次真实 OpenAI-compatible 联网验证。代码只读取通用 `LLM_*` 配置，不读取 provider-specific key。

MVP 的运行位置必须明确：

- Docker Compose 只负责启动 `postgres`。
- Python API、CLI、pytest 都在本地 venv 中执行。
- 默认 sample vault 路径使用宿主机路径 `samples/acme-vault`。
- 文档和 README 中不得使用容器内 CLI 或容器内 vault path 作为 MVP 主路径。

## Implementation Choices

MVP 默认技术选型固定如下，避免不同任务各自引入不兼容实现：

- Python `3.11+`。
- API：`fastapi` + `uvicorn`。
- API schema：`pydantic` v2。
- 配置：`python-dotenv`，按 Task 1 的优先级加载 `.env`。
- DB client：`psycopg` 3，不引入 ORM。
- CLI：`typer`，通过 `pyproject.toml` console script 暴露 `rag`。
- HTTP client / live check：`httpx` 或 `curl`；测试 API contract 时优先用 FastAPI `TestClient` 或 httpx in-process client。
- Markdown/frontmatter：`python-frontmatter` + `markdown-it-py`。
- token 计数：`tiktoken` 的 `cl100k_base`。
- 测试：`pytest`。
- 默认 `requirements.txt` 只包含 fake/smoke/CI 必需依赖。
- `local-qwen3` runtime 作为 optional extra / manual dependency：`sentence-transformers>=2.7.0`、`transformers>=4.51.0`、`torch`。

如果实现阶段要替换以上选型，必须先更新本文档和 MVP 文档，再改代码。

## Shared Verification Precondition

从 Task 1 开始，任何会读取配置、启动 Docker Compose、运行 CLI/API 或 pytest harness 的验证块，默认前置为：

```bash
test -f .env || cp .env.sample .env
```

如果某个验证需要 live provider、`local-qwen3` 或特殊测试库配置，应先基于 `.env.sample` 创建 `.env`，再按该任务说明修改 `.env` 或当前 shell 的通用环境变量。

## MVP API Schema Contract

`app/schemas.py` 从 Task 3 开始创建；Task 3 只放 `/health` 和统一错误响应的最小模型，Task 3.5 建立 `/health`、`/search`、`/ask` 的 API schema foundation。Task 11 和 Task 15 只能扩展或复用这些模型，不能先用临时 dict 形状。

- `HealthResponse`：`status: Literal["ok"]`、`checks: HealthChecks`、`details: HealthDetails`。
- `HealthChecks`：`app`、`database`、`schema`、`pgvector`、`embedding_config` 为 `"ok"`；`retrieval_ready: Literal["ok", "not_ready"]`。
- `HealthDetails`：`embedding_provider: str`、`embedding_model: str`、`documents: int`、`chunks: int`、`embeddings_current_config: int`。
- `SearchRequest`：`query: str`，非空；`top_k: int = 5`，范围 `1..20`。
- `SearchResult`：`source: str`、`relative_path: str`、`heading_path: list[str]`、`heading: str`、`content: str`、`score: float`。
- `SearchResponse`：`query: str`、`top_k: int`、`results: list[SearchResult]`、`confidence: float`。
- `Citation`：`source: str`、`heading: str`、`score: float`。
- `AskRequest`：`question: str`，非空；`top_k: int = 5`，范围 `1..20`；`fallback: bool = false`。
- `AskResponse`：`mode: Literal["rag", "no_answer", "fallback"]`、`confidence: float`、`answer: str`、`citations: list[Citation]`。
- `ErrorResponse`：`error.code: str`、`error.message: str`、`error.details: dict`。

`source` / heading 字段关系固定如下：

- `source == relative_path`，使用 POSIX 相对路径，是 `eval/questions.yaml.expected_sources` 的匹配字段。
- `heading_path` 是完整标题路径，例如 `["Support", "P1 Escalation"]`。
- `heading` 是展示字段：`heading_path` 非空时取最后一个元素；没有 heading 时返回空字符串 `""`，不回退到文件名。
- `Citation.source` 使用同样的 `source == relative_path` 规则；`Citation.heading` 使用同样的 heading 规则。

raw cosine similarity 可能落在 `-1.0..1.0`；MVP API 不直接暴露负分。`score` 和 `confidence` 都必须 clamp 到 `0.0..1.0`：`score = max(0.0, min(1.0, raw_similarity))`。MVP 不包含 `mixed` mode，也不包含 HTTP `IngestRequest` / `IngestResponse`。

## Internal Retrieval Contract

`SearchResult` 是外部 API projection，不暴露排序、去重和 DB join 所需的内部字段。检索 service 必须在 `app/retrieval.py` 中定义 internal `RetrievedChunk` 数据结构，至少包含：

- `chunk_id: int`
- `document_id: int`
- `source: str`
- `relative_path: str`
- `heading_path: list[str]`
- `heading: str`
- `content: str`
- `score: float`
- `chunk_index: int`
- `content_hash: str`

`POST /search` 把 `RetrievedChunk` 裁剪成 API `SearchResult`；`app/context.py` 和 `/ask` 使用 internal `RetrievedChunk` 列表做排序、去重和 citation assembly，不从 `SearchResult` 反推内部字段。`chunk_id`、`chunk_index`、`content_hash` 和 `document_id` 不进入 MVP API response。

## Task 0: Project Foundation

目标：建立项目的基础工程结构。

产物：

- `docker-compose.yml`
- `.env.sample`
- `.gitignore`
- `requirements.txt`
- `pyproject.toml`
- `app/`
- `app/cli.py`
- `tests/`
- `samples/acme-vault/`

CLI ownership：

- Task 0 建立 `pyproject.toml` console script 和 `app/cli.py` scaffold，保证 `rag --help` 可运行。
- Task 9 接入 `rag embeddings warmup`。
- Task 10 接入 `rag ingest`。
- Task 11 接入 `rag search`。
- Task 15 接入 `rag ask`。
- Task 17 统一补齐 CLI help、参数、输出格式和 exit codes。

`.gitignore` 必须包含：

- `.env`
- `.cache/embeddings/`

验证：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
rag --help
```

并确认：

```bash
docker compose config
```

依赖：无。

## Task 1: Configuration Layer

目标：统一读取环境变量，避免配置散落在代码里。

产物：

- `app/config.py`
- `.env.sample`

env 文件边界：

- quickstart 先执行 `cp .env.sample .env`；Docker Compose 使用 `.env` 中的 Postgres 配置，本地 venv 读取同一个 `.env` 中的 RAG/LLM/embedding 配置。
- `.env` 不提交，必须加入 `.gitignore`。
- `.env.sample` 是完整配置模板，默认使用 `LLM_PROVIDER=fake` 和 `EMBEDDING_PROVIDER=fake`，可直接用于无外网 smoke。
- 用户做 live test 时修改 `.env` 中的通用 `LLM_*` 变量，例如 `LLM_PROVIDER=openai-compatible`、`LLM_BASE_URL=https://api.moonshot.cn/v1`、`LLM_MODEL=moonshot-v1-8k`、`LLM_API_KEY=`。
- 代码只读取通用 `LLM_*` 变量，不读取任何 Kimi-specific 环境变量。

配置加载 contract：

- 必须使用 `python-dotenv`，`requirements.txt` 至少包含 `python-dotenv`。
- 本地 venv 进程启动时读取 repo 根目录 `.env`，不得依赖当前工作目录下的 `.env`。
- repo root detection：从当前工作目录向上查找同时包含 `pyproject.toml` 和 `.env.sample` 的目录；`rag --env-file PATH` 可显式覆盖 env 文件路径。
- 如果 CLI 在 repo 外执行且没有提供 `--env-file`，必须报清晰错误，提示进入 repo root 或传入 `--env-file`。
- dotenv 加载等价于 `load_dotenv(dotenv_path=resolved_env_file, override=False)`。
- 优先级固定为：OS environment / shell export > `.env` > 代码内默认值。
- 空字符串视为未设置。
- 配置摘要只能打印非敏感 resolved values；不得打印 API key，只能打印 API key 是否存在。

配置项至少包含：

- `DATABASE_URL`
- `TEST_DATABASE_URL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `VAULT_PATH`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIM`
- `EMBEDDING_DEVICE`
- `EMBEDDING_CACHE_DIR`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_TIMEOUT_SECONDS`
- `RAG_TOP_K`
- `RAG_MIN_SIMILARITY`
- `RAG_CONTEXT_TOKEN_BUDGET`
- `RAG_FALLBACK_ENABLED`

配置默认和桥接规则：

- `LLM_PROVIDER` 支持 `fake` 和 `openai-compatible`。
- `.env.sample` 提供完整配置模板；本地 venv 主路径默认读取 `.env`。
- Docker Compose 只启动 `postgres`，默认 `POSTGRES_DB=local_rag`、`POSTGRES_USER=local_rag`、`POSTGRES_PASSWORD=local_rag`。
- 本地 venv 连接 Docker Postgres 时，`DATABASE_URL` 必须使用宿主机地址，例如 `postgresql://local_rag:local_rag@localhost:5432/local_rag`。
- destructive DB/API/smoke 测试只能使用 `TEST_DATABASE_URL`，默认示例为 `postgresql://local_rag:local_rag@localhost:5432/local_rag_test`。
- `TEST_DATABASE_URL` 解析出的 database name 必须以 `_test` 结尾，且不得等于 `DATABASE_URL`；不满足时测试必须 fail fast，不能清表。
- 默认 `VAULT_PATH=samples/acme-vault`。
- 默认 `LLM_PROVIDER=fake`，用于无 API key quickstart 和默认自动化测试。
- 真实 OpenAI-compatible 验证必须显式设置 `LLM_PROVIDER=openai-compatible`。
- `LLM_PROVIDER=openai-compatible` 时，`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 三个变量必须全部初始化。
- `LLM_PROVIDER=openai-compatible` 且任一必需变量缺失时，`/ask` 必须返回清晰配置错误，不得静默 fallback 到 fake。
- 代码不得读取 provider-specific 环境变量；本地使用任何兼容 provider 时，都应先把对应值映射到通用 `LLM_*` 变量。
- `LLM_TIMEOUT_SECONDS` 默认 `30`。
- `EMBEDDING_PROVIDER` 只支持 `fake` 和 `local-qwen3`。
- 默认 `EMBEDDING_PROVIDER=fake`，默认 quickstart、CI、smoke test 不下载 embedding 模型。
- `fake` 固定 `EMBEDDING_MODEL=fake-lexical-v1`。
- `local-qwen3` 固定 `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`。
- MVP 不支持自定义 embedding model；`EMBEDDING_MODEL` 与 provider 固定模型不一致时，config validation 必须失败。
- FDE 现场语义 demo 必须显式设置 `EMBEDDING_PROVIDER=local-qwen3` 和 `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`，并先执行 Task 9 warmup / 预下载和 Task 12 的 local-qwen3 source-hit / threshold manual gate。
- MVP 固定 `EMBEDDING_DIM=1024`；所有 provider 包括 `fake` 都输出 1024 维向量。
- 配置 `EMBEDDING_DIM` 为非 1024 时必须返回配置错误；多维度共存不进入 MVP。
- `RAG_TOP_K` 默认 `5`，允许范围 `1..20`。
- 本地 venv 默认 `EMBEDDING_CACHE_DIR=.cache/embeddings`，也可显式设为 `$HOME/.cache/local-rag/embeddings`。
- `.env.sample` 中 `RAG_MIN_SIMILARITY=` 默认留空，表示使用 provider 动态默认值。
- `RAG_MIN_SIMILARITY` 未设置或为空时，`fake` provider resolved default 由 Task 8.5 的 fake calibration 固化为 `0.20`；如果校准后调整阈值或 fake scoring 规则，必须同步更新本文档、`.env.sample` 的说明和测试断言。
- `RAG_MIN_SIMILARITY` 未设置或为空时，`local-qwen3` resolved default 为 `0.35`，作为初始值。
- 显式设置 `RAG_MIN_SIMILARITY` 时，无论来自 OS env 还是 `.env`，都覆盖 provider 动态默认值。
- `RAG_CONTEXT_TOKEN_BUDGET` 默认 `6000`。
- `RAG_FALLBACK_ENABLED=false` 是全局 fallback kill switch。
- request-level `fallback=true` 只有在 `RAG_FALLBACK_ENABLED=true` 时才允许进入 `fallback` mode。

验证：

```bash
test -f .env || cp .env.sample .env
python -m app.config
```

应能打印非敏感配置摘要，并且不能打印 API key。摘要中应能看到：

```text
llm_provider=fake
llm_api_key_present=false
rag_min_similarity=0.20
```

如果 Task 8.5 校准后调整 fake provider default，上面的期望摘要必须同步更新。

依赖：Task 0。

## Task 2: Database Bootstrap

目标：让 Postgres + pgvector 可启动、可初始化、可 healthcheck。

产物：

- `app/schema.sql`
- `app/db.py`
- Docker Compose 中的 `postgres` service。
- `rag db init`。

Docker Compose 中的 Postgres 必须使用 pgvector image，默认只暴露到宿主机 loopback，便于本地 venv 复用同一个数据库：

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

MVP 不允许使用普通 `postgres:*` image。fresh volume 才会自动执行 `/docker-entrypoint-initdb.d/001-schema.sql`；已有 volume、本地开发和测试都必须通过 `rag db init` 执行同一个 `app/schema.sql`。

schema 至少包含：

- `documents`
- `chunks`
- `embeddings`
- `ingest_runs`

schema 初始化边界：

- `app/schema.sql` 是唯一 schema source of truth，必须包含 `CREATE EXTENSION IF NOT EXISTS vector`。
- Docker fresh volume 通过 `./app/schema.sql:/docker-entrypoint-initdb.d/001-schema.sql:ro` 执行同一个 `app/schema.sql`。
- 现有数据库、本地开发和测试通过 `rag db init` idempotently 执行同一个 `app/schema.sql`。
- API startup 和 ingest 不隐式创建表；如果 schema 未初始化，`/health` 返回数据库未就绪，`rag ingest` 返回清晰错误。
- `/search`、`/ask` 和 manual live gate 的前置条件是 RAG 数据库已通过 `rag db init` 初始化，且 sample vault 已完成 ingest。

minimum DDL contract：

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

DDL 验收边界：

- `documents` 必须用 `(vault_path, relative_path)` 唯一约束防止同一 vault 重复文件。
- `chunks.document_id` 和 `embeddings.chunk_id` 必须 `ON DELETE CASCADE`，支撑 ingest 重建和删除。
- MVP 删除语义是 hard delete：被删除的源文件对应的 `documents` row 直接删除，并通过 cascade 删除 chunks 和 embeddings；MVP 不保留 `documents.deleted_at`，也不实现 soft delete retrieval filter。
- `frontmatter` / `metadata` 使用 `JSONB`；`tags` / `wikilinks` / `heading_path` 使用 `TEXT[]`。
- `embeddings.embedding` 必须是 `vector(1024)`。
- `chunks` 只对 `(document_id, chunk_index)` 建唯一约束；`content_hash` 可以有普通 index，但不能唯一，允许同一文档内合法重复段落。
- `(chunk_id, embedding_provider, embedding_model, embedding_dim)` 必须唯一，支撑 provider 隔离和补齐 embeddings。
- MVP 正确性路径使用 exact pgvector scan；`hnsw` / approximate index 不作为 MVP DDL 必须项，也不能作为 source-hit smoke test 的正确性依赖。

验证：

```bash
test -f .env || cp .env.sample .env
docker compose config
docker compose up -d postgres
rag db init
```

然后确认：

```sql
SELECT extname FROM pg_extension WHERE extname = 'vector';
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
SELECT COUNT(*) FROM documents;
```

依赖：Task 0、Task 1。

## Task 2.5: Test DB Fixture / Test Harness

目标：在任何 DB/API 测试出现前，提供统一、安全、可复用的 pytest harness，避免误连 demo DB、跳过 DB 测试或每个任务各写一套 fixture。

产物：

- `tests/conftest.py`
- `tests/test_harness.py`
- 共享 fixture：`test_db_url`、`clean_test_db`、`test_env`、`cli_env`。
- 可选 CLI subprocess helper，必须复用 `cli_env`。

fixture ownership：

- Task 2.5 只负责 DB/env/CLI harness，不导入 `app.main`，也不创建 FastAPI `TestClient`。
- Task 3 在 `app/main.py` 和 FastAPI app 存在后追加 `api_client` fixture；后续所有需要 FastAPI client 的测试必须使用 Task 3 的 `api_client`，并继承本 task 的 `test_env` / `clean_test_db` guard。
- Task 3、Task 10、Task 11、Task 15 和 Task 18 中所有需要数据库或 CLI subprocess 的测试都必须使用本 task 的共享 fixture。
- 单个任务可以增加局部 fixture，但不能绕开 `TEST_DATABASE_URL` guard，也不能直接清理 `DATABASE_URL` 指向的 demo DB。
- pytest 默认不负责启动或停止 Docker；调用方必须先启动 Postgres + pgvector。

安全 guard：

- fixture 在任何 schema init、清表、truncate 或 subprocess 调用前，必须先读取原始 demo `DATABASE_URL` 和 `TEST_DATABASE_URL`。
- `TEST_DATABASE_URL` 缺失、database name 不以 `_test` 结尾、或与原始 demo `DATABASE_URL` 完全相同时，必须 fail fast。
- safety guard 比较的是 `.env` / config 中的 demo `DATABASE_URL` 和 `TEST_DATABASE_URL`，不能因为测试运行时覆盖 `DATABASE_URL` 而失效。
- guard 通过后，测试进程、in-process service、Task 3 之后的 FastAPI client 和 CLI subprocess 的运行时 `DATABASE_URL` 才能被注入为 `TEST_DATABASE_URL`。
- destructive cleanup 只能作用于允许列表表名：`documents`、`chunks`、`embeddings`、`ingest_runs`；可以使用 FK-safe delete 顺序或 `TRUNCATE ... CASCADE`，但必须在 guard 通过后执行。

provider 注入规则：

- 默认 DB/API/smoke 测试强制注入 fake provider 配置，覆盖开发机 shell 中可能存在的真实 provider 设置：

```text
EMBEDDING_PROVIDER=fake
EMBEDDING_MODEL=fake-lexical-v1
EMBEDDING_DIM=1024
LLM_PROVIDER=fake
LLM_MODEL=fake-local
LLM_API_KEY=
LLM_BASE_URL=
```

- `test_env` 返回给 in-process app/config 使用；`cli_env` 返回给 `subprocess.run(..., env=cli_env)` 使用。
- 如果某个 manual/network gate 要测试 `local-qwen3` 或 `openai-compatible`，必须显式 opt in，并且不能复用默认 smoke fixture 名称。

验证：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
docker compose exec -T postgres createdb -U local_rag local_rag_test || true
TEST_DATABASE_URL=postgresql://local_rag:local_rag@localhost:5432/local_rag_test \
pytest tests/test_harness.py
```

`tests/test_harness.py` 至少覆盖：

- 缺失 `TEST_DATABASE_URL` 会 fail fast。
- `TEST_DATABASE_URL` 不以 `_test` 结尾会 fail fast。
- `TEST_DATABASE_URL == DATABASE_URL` 会 fail fast。
- guard 通过后，runtime `DATABASE_URL` 被注入为 `TEST_DATABASE_URL`。
- fake embedding / fake LLM provider 配置会注入 pytest 进程和 CLI subprocess env；Task 3 的 `api_client` 必须继承同一套 `test_env`。

依赖：Task 1、Task 2。

## Task 3: FastAPI Health Endpoint

目标：提供最小 API 服务，验证 app 和数据库连接正常。

产物：

- `app/main.py`
- `app/schemas.py`
- `GET /health`
- unified API error handlers。
- `tests/test_health.py`
- `api_client` fixture：在 `tests/conftest.py` 中基于 Task 2.5 的 `test_env` / `clean_test_db` 创建 FastAPI `TestClient`。

schema ownership：

- Task 3 创建 `app/schemas.py`，但只实现 `HealthResponse`、`HealthChecks`、`HealthDetails` 和 `ErrorResponse` 的最小模型。
- Task 3.5 在 `/search` 和 `/ask` 实现前补齐 `SearchRequest`、`SearchResponse`、`AskRequest`、`AskResponse` 和 `Citation`。
- Task 11 和 Task 15 必须使用 `app/schemas.py`，不得先返回临时 dict 再留给 Task 16 返工。
- Task 16 是轻量 contract audit，不是第一次创建 schema。
- `app/main.py` 必须注册 `RequestValidationError` handler，把 FastAPI / Pydantic 默认 422 响应转换成本文档定义的 `ErrorResponse`，`error.code="invalid_request"`；默认 FastAPI 422 shape 不允许进入 MVP。

fixture ownership：

- Task 3 创建 `api_client` fixture，因为此时 `app/main.py` 和 FastAPI `app` 已存在。
- `api_client` 必须在导入 `app.main:app` 前应用 Task 2.5 的 `test_env`，确保测试 API 连接 `TEST_DATABASE_URL` 并使用 fake providers。
- 后续 API 测试不得各自创建绕过 guard 的 `TestClient`。

`GET /health` 必须做全方面检查：

- app process。
- database connection。
- schema initialized。
- pgvector extension。
- embedding config validation。
- 当前 embedding config 下是否已有可检索 embeddings。

返回示例：

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

如果 database、schema 或 pgvector 不可用，返回 `503` 和统一 error response。当前 embedding config 下没有 embeddings 时，`GET /health` 仍返回 HTTP `200`，但 `retrieval_ready` 返回 `not_ready`，用于提示先执行 `rag db init` 和 `rag ingest`；真正需要检索的 `POST /search` 和 `POST /ask` 才返回 `503 retrieval_not_ready`。

验证：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
rag db init
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后在另一个 shell 执行：

```bash
curl http://localhost:8000/health
```

正向验收必须看到 HTTP `200`；没有 ingest 时允许 `retrieval_ready=not_ready`。schema 未初始化的负向场景必须由 `tests/test_health.py` 覆盖，期望 HTTP `503` 和统一 `ErrorResponse`，但不作为上面手工 quickstart 命令的默认路径。

依赖：Task 1、Task 2、Task 2.5。

## Task 3.5: API Schema Foundation

目标：在 `/search` 和 `/ask` 开始实现前，提前固定 API request/response 的 Pydantic contract，减少多 agent 并行实现时的 schema 返工。

产物：

- `app/schemas.py`
- `tests/test_api_schema_foundation.py`

行为要求：

- `app/schemas.py` 必须实现本文档顶部 `MVP API Schema Contract` 的全部模型：`HealthResponse`、`HealthChecks`、`HealthDetails`、`SearchRequest`、`SearchResult`、`SearchResponse`、`Citation`、`AskRequest`、`AskResponse`、`ErrorResponse`。
- request model 必须在模型层校验非空 `query` / `question`、`top_k` 范围 `1..20`、`fallback` 默认值。
- `AskResponse.mode` 必须使用 `Literal["rag", "no_answer", "fallback"]`；MVP 不包含 `mixed` mode。
- `source`、`relative_path`、`heading_path`、`heading` 和 `Citation` 的字段关系按顶部 contract 固定。
- 统一 error shape 在 schema 层有明确模型，FastAPI handler 和 CLI 错误输出都复用同一结构。
- Task 3.5 不实现 `/search` 或 `/ask` route；后续 route 只导入并使用这些模型。

验证：

```bash
pytest tests/test_api_schema_foundation.py
```

`tests/test_api_schema_foundation.py` 至少覆盖：

- 所有 schema model 可以构造并序列化为预期字段。
- 空 `query` / `question` 被拒绝。
- invalid `top_k` 被拒绝。
- `AskResponse.mode="mixed"` 被拒绝。
- `ErrorResponse` 顶层 shape 固定为 `{"error": ...}`。

依赖：Task 3。

## Task 4: Sample Enterprise Vault

目标：提供 FDE 可演示的企业知识库样例，并确保它可以被 Obsidian 直接打开。

产物：

```text
samples/acme-vault/
  00-index.md
  products/
  policies/
  runbooks/
  sales/
  support/
```

同时提供：

- `eval/questions.yaml`

内容要求：

- 至少 8 篇 Markdown。
- 至少 5 个可问答场景。
- `eval/questions.yaml` 至少包含 5 个 `expected_mode=rag` sample questions，且这些问题的 `expected_sources` 非空。
- `eval/questions.yaml` 另加至少 1 个 `expected_mode=no_answer` sample question，且 `expected_sources=[]`。
- 每个 sample question 包含 `id`、`question`、`expected_sources`、`expected_mode`。
- 包含 frontmatter。
- 包含 tags。
- 包含 wikilinks。
- 包含中英文混合企业术语。

验证：

```bash
rg "\[\[" samples/acme-vault
rg "^---" samples/acme-vault
rg "#[A-Za-z0-9_-]+" samples/acme-vault
test -f eval/questions.yaml
rg "expected_sources|expected_mode" eval/questions.yaml
rg "expected_mode: no_answer" eval/questions.yaml
rg "expected_sources: \\[\\]" eval/questions.yaml
```

依赖：Task 0。

## Task 5: Markdown File Scanner

目标：扫描 vault 中所有 Markdown 文件，并忽略非知识文件。

产物：

- `app/markdown.py`
- `scan_markdown_files(vault_path)`

行为要求：

- 递归扫描 `.md`。
- 返回相对路径和绝对路径。
- `vault_path` 入库前必须 canonicalize：`Path(vault_path).expanduser().resolve(strict=True)`，并保存为字符串，确保 `samples/acme-vault`、`./samples/acme-vault` 和绝对路径不会形成多个 vault。
- `relative_path` 必须相对 canonical vault root 计算，使用 POSIX 分隔符 `/`，不得以 `./` 开头，不得包含 `..`。
- `file_path` 必须是文件的 resolved absolute path。
- 忽略隐藏目录，例如 `.obsidian`。
- 输出稳定排序，便于测试。

验证：

```bash
pytest tests/test_markdown.py
```

测试至少覆盖：

- 能找到 sample vault 的 Markdown 文件。
- 不扫描 `.obsidian`。
- `vault_path` canonicalization 后稳定。
- 相对路径稳定，并使用 POSIX 格式。

依赖：Task 4。

## Task 6: Markdown and Obsidian Parser

目标：把 Markdown 文件解析成统一 `Document` 对象。

产物：

- `Document` 数据结构。
- `parse_markdown_file(path, vault_path)`。

解析内容：

- raw content。
- frontmatter。
- Markdown headings。
- tags。
- wikilinks。
- content hash。
- relative path。

验证：

```bash
pytest tests/test_markdown.py
```

测试至少覆盖：

- YAML frontmatter。
- `#tag`。
- `[[Wiki Link]]`。
- `[[path/Page|Alias]]`。
- hash 在内容变化后改变。

依赖：Task 5。

## Task 7: Heading-aware Chunking

目标：将文档按 Markdown 标题和 token 长度切成可检索 chunk。

产物：

- `app/chunking.py`
- `Chunk` 数据结构。
- `chunk_document(document)`。

行为要求：

- 保留 `heading_path`。
- 保留 `chunk_index`。
- token 计数使用 `tiktoken` 的 `cl100k_base` tokenizer。
- `requirements.txt` 必须包含 `tiktoken`。
- 目标长度 400 到 800 tokens。
- 超过最大长度时二次切分。
- 最大长度 1200 tokens。
- overlap 默认 80 tokens，可通过后续配置调整。
- 每个 chunk 带 metadata。

验证：

```bash
pytest tests/test_chunking.py
```

测试至少覆盖：

- 标题路径正确。
- 长段落会被拆分。
- chunk 顺序稳定。
- metadata 被继承。

依赖：Task 6。

## Task 8: Embedding Abstraction

目标：让 MVP 的两个 embedding provider 可稳定切换，并且第一版能本地跑通。

产物：

- `app/embeddings.py`
- `EmbeddingClient`
- `local-qwen3` demo provider。
- test-only fake provider。

MVP provider 边界：

- MVP 只支持 `fake` 和 `local-qwen3`。
- `local-qwen3` 固定模型：`Qwen/Qwen3-Embedding-0.6B`。
- `fake` 固定模型标识：`fake-lexical-v1`。
- test-only：`fake` lexical deterministic embedding，用于 unit test、无网络 smoke test、CI。
- `fake` provider 不作为 FDE demo 默认 embedding。
- 默认 quickstart 和 CI 使用 `EMBEDDING_PROVIDER=fake`，不下载模型。
- FDE 现场语义 demo 必须显式设置 `EMBEDDING_PROVIDER=local-qwen3` 和 `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`，并通过 Task 9 的 `rag embeddings warmup` 预热模型缓存，再通过 Task 12 的 local-qwen3 source-hit / threshold manual gate。
- MVP 不支持自定义 embedding model、远程 embedding provider 或 `BAAI/bge-m3`。

fake provider 边界：

- `fake` 不是 opaque hash，也不是语义模型。
- `fake` 使用 deterministic lexical feature hashing：对归一化文本、CJK 字符、英文数字 token、标题和路径 metadata 做 feature hashing，输出固定维度向量。
- `fake` 必须让 lexical overlap 高的 query/chunk similarity 高于无关文本，保证 `eval/questions.yaml` 中刻意设计的 sample questions 可以稳定命中 expected sources。
- `fake` 输出维度固定为 `1024`，与 pgvector schema 一致。
- `fake` smoke test 的 source-hit 只证明 pipeline、metadata、filtering 和 scoring 接线正确，不代表真实语义检索质量。

`fake-lexical-v1` 算法 contract：

- 输入由 `content`、`heading_path`、`relative_path`、`tags`、`wikilinks` 组成；query 只有 `content`。
- 文本 normalization：Unicode NFKC、lowercase、把 `/\._-` 转为空格、压缩连续 whitespace。
- tokenization：英文/数字使用正则 `[a-z0-9]+`；CJK 使用单字 unigram 加相邻 bigram；长度为 1 的英文停用词丢弃。
- metadata weighting：`content` token 权重 `1.0`，`heading_path` 权重 `2.0`，`relative_path` 权重 `1.5`，`tags` 和 `wikilinks` 权重 `1.25`。
- hashing：使用 SHA-256，hash input 格式为 `fake-lexical-v1:{feature}`，取前 8 bytes big-endian unsigned int 后对 `1024` 取模；hash seed/version 不能随运行环境变化。
- accumulation：每个 token 按权重累加到对应 bucket；同一 token 可重复计数，但单字段内单个 token 贡献上限为 `4 * weight`。
- normalization：最终向量做 L2 normalization；空输入返回全零向量并由调用方视为不可检索输入。
- 验收校准：fake provider default 必须通过 Task 8.5 在 sample vault/questions 上实际计算分布后固化；当前固化值为 `0.20`。如果分布没有稳定 margin，应先调整 sample question、metadata 权重或 fake provider resolved default，并把最终选择记录在测试里，不能用随机 seed 修正。

`local-qwen3` 运行边界：

- MVP 固定维度：`EMBEDDING_DIM=1024`。
- pgvector schema 使用 `vector(1024)`；MVP 不支持同一数据库内混存不同维度向量。
- 如果配置了非 1024 的 `EMBEDDING_DIM`，config validation 必须失败。
- 如果 `EMBEDDING_MODEL` 与 provider 固定模型不一致，config validation 必须失败。
- 默认设备：`EMBEDDING_DEVICE=cpu`，可选支持 `mps` / `cuda`，但 MVP 不要求 GPU。
- 本地 venv 默认缓存目录：`EMBEDDING_CACHE_DIR=.cache/embeddings`；也可显式设为 `$HOME/.cache/local-rag/embeddings`。
- `.cache/embeddings` 应进入 `.gitignore`。
- 默认 `requirements.txt` 不安装 `local-qwen3` 大模型 runtime，确保 fake-only quickstart 足够轻。
- `local-qwen3` runtime 必须通过 optional extra 或单独 requirements 文件安装，例如 `pip install -e ".[local-qwen3]"` 或 `pip install -r requirements-local-qwen3.txt`。
- 版本下限按 Implementation Choices 固定：`sentence-transformers>=2.7.0`、`transformers>=4.51.0`。
- `Qwen/Qwen3-Embedding-0.6B` 是本地 embedding 模型，约 0.6B 参数；BF16/FP16 权重约 1.2GB，建议为模型缓存预留至少 1.5GB 磁盘空间。
- `local-qwen3` 首次 `rag embeddings warmup` 可联网下载模型到 `EMBEDDING_CACHE_DIR`；缓存完成后，ingest/search 的 embedding 计算必须在本地 venv 中完成，不调用远程 embedding API。
- FDE 客户现场前应先完成 warmup，确保现场可在无外网环境下使用缓存模型。
- 模型预下载或预热命令由 Task 9 实现。
- query embedding 必须使用 Qwen 的 query prompt 口径：优先使用 `SentenceTransformer.encode(..., prompt_name="query")`；如果所用封装不支持 `prompt_name`，使用固定 instruction：`Instruct: Given a user question, retrieve relevant passages from the local enterprise knowledge base that answer the question\nQuery: {query}`。
- document/chunk embedding 不加 query instruction，只使用 chunk content 和 metadata text。
- query 和 document/chunk 向量都必须 L2 normalize；pgvector cosine similarity 和阈值校准都基于 normalized vectors。

行为要求：

- 输入文本列表。
- 输出固定维度 vector。
- 暴露 provider、模型名和维度。
- Task 8 测试环境不依赖外部网络，不加载或下载 `local-qwen3` 模型；真实模型加载验证归 Task 9。
- `local-qwen3` 生成真实语义 embedding，适合中英文混合检索。
- `local-qwen3` 在 CPU 环境下可以完成 sample vault ingest；如果首次运行需要下载模型，错误信息必须清楚提示缓存路径、预计模型大小和预下载命令。

验证：

```bash
pytest tests/test_embeddings.py
```

测试至少覆盖：

- 同一文本输出稳定。
- 不同文本输出不同。
- lexical overlap 高的文本 similarity 高于无关文本。
- CJK unigram/bigram、英文 token、heading/path/tags/wikilinks 权重按 contract 生效。
- 输出向量已 L2 normalization，空输入输出全零向量。
- vector 维度符合 schema。

依赖：Task 1。

## Task 8.5: Fake Embedding Calibration

目标：在 ingest/search/ask 的 DB/API 测试开始前，用真实 sample vault 和 sample questions 校准 fake lexical scoring 与阈值，避免 provider default 只是拍脑袋常量。

产物：

- `tests/test_fake_calibration.py`
- deterministic calibration snapshot，可以是测试断言中的固定分布值，或 `eval/fake-calibration.json`。

行为要求：

- 校准只使用 `samples/acme-vault`、`eval/questions.yaml`、Task 5-7 的 scanner/parser/chunker 和 Task 8 的 fake provider；不得依赖数据库、外网或真实 embedding 模型。
- `eval/questions.yaml` 必须至少包含 5 个 `expected_mode=rag` 问题和 1 个 `expected_mode=no_answer` 且 `expected_sources=[]` 的无关问题；数量不足时 calibration test 必须失败。
- 对每个 `expected_mode=rag` 的 sample question，计算 query 对全部 sample chunks 的 fake cosine similarity。
- top source 必须命中 `expected_sources`，且 top clamped score 必须大于等于 fake provider resolved threshold。
- 对每个 `expected_mode=no_answer` 的 sample question，`expected_sources` 必须为空，且 top clamped score 必须低于 fake provider resolved threshold。
- calibration 必须记录或断言分布摘要：`min_expected_top_score`、`max_unrelated_top_score`、`margin = min_expected_top_score - max_unrelated_top_score`。
- 如果当前 provider default 没有稳定 margin，必须在 Task 8.5 内先调整 sample question、fake metadata weighting 或 fake provider resolved default，并同步更新 Task 1 配置说明、本文档和相关测试。
- hash seed、feature order 和 tie-breaker 必须 deterministic；不得通过随机 seed 或浮动 tolerance 掩盖不稳定。

验证：

```bash
pytest tests/test_fake_calibration.py
```

依赖：Task 4、Task 5、Task 6、Task 7、Task 8。

## Task 9: Embedding Warmup

目标：把 embedding warmup 从 ingest 中拆出来。默认路径验证 `fake` warmup；`local-qwen3` 模型缓存预热作为 FDE 现场前的 manual/network gate。

产物：

- `rag embeddings warmup`
- `python -m app.embeddings --warmup`

行为要求：

- `EMBEDDING_PROVIDER=fake` 时 warmup 是快速 no-op，只验证配置和 1024 维输出。
- 默认完成标准只要求 `fake` warmup 通过；它不得访问外网、下载模型或要求真实模型缓存。
- `EMBEDDING_PROVIDER=local-qwen3` 时加载或下载 `Qwen/Qwen3-Embedding-0.6B` 到 `EMBEDDING_CACHE_DIR`，但这属于 manual/network gate，不进入默认 CI、无人值守验收或 Task 10 的默认依赖链路。
- `local-qwen3` warmup 是唯一允许触发模型下载的 MVP 路径；下载完成后 embedding 推理必须本地运行。
- `python -m app.embeddings --embed ...` 只允许使用已存在缓存；如果 `local-qwen3` 缓存不存在，必须报错并提示先执行 `rag embeddings warmup`，不得在 `--embed` 路径隐式下载。
- 输出模型名、provider、cache dir、设备和是否已缓存，不输出任何 secret。
- 模型未能下载或加载时，错误信息必须清楚提示 cache dir、provider、device、预计模型大小和重试命令。

验证：

```bash
test -f .env || cp .env.sample .env
rag embeddings warmup
pytest tests/test_embedding_warmup.py
```

manual/network gate：

```bash
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B rag embeddings warmup
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B python -m app.embeddings --embed "客户 P1 工单应该怎么升级？"
```

Task 9 的 `local-qwen3` manual/network gate 只证明模型能下载、加载和生成 embedding，不证明检索命中可靠；FDE 现场语义 demo 前还必须执行 Task 12 的 source-hit / threshold gate。Task 9 gate 不作为默认 task completion、CI 或 smoke test 的必跑项。

依赖：Task 8。

## Task 10: Ingest Pipeline

目标：把扫描、解析、切块、embedding、入库串成一个可重复执行的流程。

产物：

- `app/ingest.py`
- `rag ingest <vault-path>`

MVP 不提供 `POST /ingest`。ingest 是 operator / FDE 触发的索引构建动作，不属于 agent-facing API。

行为要求：

- 新文件入库。
- 未变化文件跳过。
- 变化文件重建 chunks 和 embeddings。
- 删除文件从索引中移除。
- 写入 `ingest_runs`。
- skip 判断不能只看 `content_hash`，还必须比较 `embedding_provider`、`embedding_model` 和 `embedding_dim`。
- 文件内容未变化但当前 provider/model/dim 缺少 embeddings 时，保留 document/chunks，只补齐当前配置的 embeddings。
- 文件内容变化时，重建该文件的 chunks，并为当前 provider/model/dim 写入 embeddings。
- `vault_path` 写入 `documents` 和 `ingest_runs` 前必须使用 Task 5 的 canonical vault path。
- 默认 quickstart ingest 使用 `EMBEDDING_PROVIDER=fake`，不得下载真实 embedding 模型。
- 只有显式设置 `EMBEDDING_PROVIDER=local-qwen3` 时，ingest 才可能触发模型加载；FDE demo 前应先完成 Task 9 warmup，并通过 Task 12 local-qwen3 source-hit / threshold gate。
- Task 10 的默认依赖要求 Task 8.5 fake calibration 和 Task 9 fake warmup 验收通过；`local-qwen3` manual/network gate 不是默认 ingest 或 CI 前置条件。

事务边界：

- 每个新增或变化文件在单个数据库事务内完成 document upsert、旧 chunks/embeddings 删除、新 chunks/embeddings 插入。
- 变化文件重建失败时必须回滚，保留旧索引，不留下半更新状态。
- 删除文件必须 hard delete 对应 `documents` row，并通过 `ON DELETE CASCADE` 删除 chunks 和 embeddings；该操作也必须在事务内完成。
- `ingest_runs` 记录本次运行的 status、计数和错误摘要；失败时 status 不能误记为 success。

验证：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
rag ingest samples/acme-vault
pytest tests/test_ingest.py
```

第二次运行应显示大部分文件 skipped。

`tests/test_ingest.py` 至少覆盖：

- unchanged file 第二次 ingest 被 skip，不重复写 chunks/embeddings。
- changed file 会重建该 document 的 chunks 和当前 provider/model/dim embeddings。
- deleted source file 会 hard delete 对应 `documents` row，并 cascade 删除 chunks/embeddings。
- provider switch / missing current provider embeddings 时，文件内容未变化也会 backfill 当前 provider/model/dim embeddings。
- 单文件 ingest 失败会回滚，保留旧索引，不留下半更新 chunks/embeddings，`ingest_runs.status` 不能误记为 `success`。

manual/network gate：`local-qwen3` path 验证：

```bash
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B rag embeddings warmup
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B EMBEDDING_DEVICE=cpu rag ingest samples/acme-vault
```

该验证不属于 Task 10 默认完成标准、CI 或无人值守 smoke test。它应能在 CPU 环境下完成 sample vault ingest；如模型未缓存，应清楚提示下载或预热步骤。

数据库验证：

```sql
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM chunks;
SELECT COUNT(*) FROM embeddings;
```

依赖：Task 2、Task 2.5、Task 6、Task 7、Task 8、Task 8.5、Task 9。

## Task 11: Vector Retrieval

目标：根据用户 query 从 pgvector 检索相关 chunks。

产物：

- `app/retrieval.py`
- internal `RetrievedChunk` model / data structure。
- `POST /search`
- `rag search "..."`

行为要求：

- 使用 `app/schemas.py` 中的 `SearchRequest` / `SearchResponse`，`SearchResponse` 必须在 Task 11 就包含 `confidence`。
- `POST /search` 绑定 FastAPI route，route handler 调用 shared retrieval service。
- `rag search` 调用同一个 shared retrieval service，不依赖 `uvicorn` 或 HTTP server。
- query 生成 embedding。
- 内部使用 pgvector cosine distance。
- shared retrieval service 内部返回 `RetrievedChunk` 列表和 query-level `confidence`；API route 只把 `RetrievedChunk` 裁剪成 `SearchResult`。
- MVP correctness path 使用 exact scan：先按当前 provider/model/dim 过滤，再按 pgvector cosine distance 排序。小样本 smoke/source-hit 验收不得依赖 HNSW approximate index。
- 如果为了 demo 性能额外添加 HNSW index，它是可选优化；检索正确性测试必须能在 exact scan 下通过。
- retrieval 必须只搜索当前 embedding config 对应的向量：

```sql
WHERE embedding_provider = current EMBEDDING_PROVIDER
  AND embedding_model = current EMBEDDING_MODEL
  AND embedding_dim = current EMBEDDING_DIM
```

- API 返回的 `score` 是 cosine similarity，不是 pgvector raw distance。
- 转换规则：`raw_similarity = 1 - cosine_distance`。
- API response 必须 clamp：`score = max(0.0, min(1.0, raw_similarity))`；真实 embedding 的 raw cosine similarity 可能为负数，但 MVP response schema 和 tests 使用 `0.0..1.0`。
- Task 11 的基础 confidence 实现固定为：有结果时 `confidence = top_result.score`，无结果时 `confidence = 0.0`；Task 12 只补强阈值策略和校准测试，不再首次添加 response 字段。
- `score` 越高表示越相关。
- `top_k` 默认 `5`，最小 `1`，最大 `20`；超出范围由 Pydantic validation 拒绝。
- 返回 similarity score。
- 返回 source、heading、content。
- SQL 查询必须同时取出 `chunks.id` 作为 `chunk_id`、`documents.id` 作为 `document_id`、`chunk_index` 和 `content_hash`，供 internal `RetrievedChunk` 排序/去重；这些字段不得进入 API `SearchResult`。

embedding config 边界：

- `embeddings` 表使用 `vector(1024)`，并对 `(chunk_id, embedding_provider, embedding_model, embedding_dim)` 建唯一约束。
- `EMBEDDING_DIM` 固定为 `1024`；配置为其他值时 search 返回 `embedding_dim_mismatch` 配置错误。
- 切换 provider/model 后，旧 embeddings 可以留在库里，但 retrieval 不能混用。
- 当前 embedding config 下没有任何 embeddings 时，`POST /search` 返回 `503 retrieval_not_ready`；CLI `rag search` 返回非零 exit code 和同名错误。

验证：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
rag search "客户 P1 工单应该怎么升级？"
pytest tests/test_search_api.py
```

CLI 和 HTTP `POST /search` 都应命中 support escalation 相关文档。

`tests/test_search_api.py` 至少覆盖：

- FastAPI TestClient 调用 `POST /search` 返回 `SearchResponse`。
- high-confidence known question 命中 expected `source == relative_path`。
- `SearchResponse.confidence` 等于 top result clamped score；无结果时为 `0.0`。
- internal retrieval result 包含 `chunk_id`、`chunk_index`、`content_hash`，但 API `SearchResult` 不暴露这些字段。
- `top_k` 默认值、范围校验和 invalid `top_k` 的统一 `ErrorResponse`。
- 当前 embedding config 下无 embeddings 时返回 `503 retrieval_not_ready`。

依赖：Task 2.5、Task 3.5、Task 8、Task 8.5、Task 10。

## Task 12: Confidence Strategy and Threshold Tests

目标：在 Task 11 已经返回基础 `confidence` 后，固化阈值策略、mode 前置判断和校准测试，避免 `/ask` 再各自解释分数。

产物：

- `app/confidence.py` 或等价共享 helper。
- `tests/test_confidence.py`。
- threshold / mode precheck 测试。
- manual `local-qwen3` source-hit / threshold gate，可以是 `tests/test_local_qwen3_threshold.py`、`scripts/check_local_qwen3_threshold.py` 或等价命令。

行为要求：

- `result.score` 是 chunk-level clamped cosine similarity，范围 `0.0..1.0`。
- `confidence` 是 query-level retrieval confidence。
- Task 11 已实现基础规则：`confidence = top_result.score`，空结果 `confidence=0.0`、`results=[]`；Task 12 不能改变 `SearchResponse` shape。
- Task 12 必须提供共享判断逻辑，供 Task 15 复用：`confidence >= RAG_MIN_SIMILARITY` 进入 `rag`，否则按 fallback 配置进入 `no_answer` 或 `fallback`。
- top clamped score 低于阈值时必须被判为低置信。
- top clamped score 高于或等于阈值时必须被判为高置信。
- 阈值来自配置。
- `RAG_MIN_SIMILARITY` 未设置或为空时，配置层按 provider 给出动态默认值。
- `fake` provider resolved default：Task 8.5 校准后固化的值 `0.20`。
- `local-qwen3` resolved default：`0.35`。
- 显式设置 `RAG_MIN_SIMILARITY` 时覆盖 provider 动态默认值。
- `local-qwen3` resolved default `0.35` 是初始值，必须通过下方 manual local-qwen3 gate 用 sample questions 校准：已知问题进入 `rag`，无关问题进入 `no_answer`。
- 如果 local-qwen3 gate 发现 `0.35` 没有稳定 margin，必须调整 `local-qwen3` provider default 或 sample questions，并同步更新 Task 1 配置说明、`.env.sample` 注释、本文档和测试断言。
- MVP 不实现 `mixed` mode。

验证：

```bash
test -f .env || cp .env.sample .env
pytest tests/test_confidence.py
```

测试必须覆盖低 `confidence` 的 threshold helper 判定，默认进入 `no_answer` 前置状态。

manual local-qwen3 source-hit / threshold gate：

这个 gate 用真实本地 embedding 模型验证语义检索质量；它需要模型缓存和较长运行时间，不进入默认 CI、默认 smoke test 或无人值守验收，但 FDE 现场语义 demo 前必须执行并通过。

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B EMBEDDING_DEVICE=cpu rag embeddings warmup
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B EMBEDDING_DEVICE=cpu rag db init
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B EMBEDDING_DEVICE=cpu rag ingest samples/acme-vault
EMBEDDING_PROVIDER=local-qwen3 EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B EMBEDDING_DEVICE=cpu pytest -m local_qwen3 tests/test_local_qwen3_threshold.py
```

`tests/test_local_qwen3_threshold.py` 至少覆盖：

- 读取 `eval/questions.yaml`，要求至少 5 个 `expected_mode=rag` 问题和至少 1 个 `expected_mode=no_answer` 且 `expected_sources=[]` 的问题。
- 对每个 `expected_mode=rag` 问题，`rag search` 或 shared retrieval service 的 top source 命中 `expected_sources`，且 `confidence >= local-qwen3 resolved RAG_MIN_SIMILARITY`。
- 对每个 `expected_mode=no_answer` 问题，top confidence 低于 local-qwen3 resolved threshold；通过 `/ask` 或 ask service 验证默认 `RAG_FALLBACK_ENABLED=false` 时返回 `mode=no_answer`。
- 输出或断言分布摘要：`min_expected_top_score`、`max_no_answer_top_score`、`margin`、`resolved_threshold`、`embedding_model`。
- 失败时错误信息必须说明是 source-hit 失败、threshold 过高/过低，还是模型/cache/config 未就绪。

依赖：Task 11。

## Task 13: Context Assembly and Citations

目标：把检索结果整理成 LLM 可用上下文，并生成可追溯引用。

产物：

- `app/context.py`
- citation 数据结构。

行为要求：

- context assembly 输入必须使用 retrieval service 的 internal `RetrievedChunk` 列表，不能使用已裁剪的 API `SearchResult`。
- `RetrievedChunk` 必须提供 `chunk_id`、`chunk_index` 和 `content_hash` 等内部字段；这些字段用于排序、去重和测试，不进入 API response。
- 如果上游没有明确排序，必须按 `score desc`、`source asc`、`heading_path asc`、`chunk_index asc`、`chunk_id asc` 排序后再组装。
- 重复块去重 key 固定为 `(source, heading_path, content_hash)`；重复块只保留第一次出现。
- citation 编号从 `1` 开始，按最终 context block 顺序递增。编号只用于 prompt/context 文本；`AskResponse.citations` 保持同样顺序，但不新增 API 字段。
- 每个 context block 格式固定：

```text
[1] source: policies/Support Escalation Policy.md
heading: P1 Escalation
score: 0.8600
content:
<chunk content>
```

- `source` 使用 `source == relative_path`；`heading` 为空时输出空字符串，不回退到文件名。
- `score` 在 context 中固定格式化为 4 位小数，基于 clamped score。
- context token 预算使用 `tiktoken` 的 `cl100k_base` 估算，最终字符串不得超过 `RAG_CONTEXT_TOKEN_BUDGET`。
- 截断策略 deterministic：按排序后的 block 逐个加入；如果下一个完整 block 超预算则跳过它；如果第一个 block 单独超预算，则只截断 `content` 字段并追加 `[truncated]`。
- 同一 `source` 的多个不同 chunks 不强制合并；如果后续实现合并，只能合并相邻且同 `source`、同 `heading_path` 的 blocks，并且 citation 编号仍按最终 block 顺序稳定。
- 空结果返回空 context string 和空 citations。

验证：

```bash
pytest tests/test_context.py
```

测试至少覆盖：

- citation 编号、排序和 4 位 score 格式稳定。
- context 使用 `RetrievedChunk.chunk_index` / `chunk_id` 排序，使用 `content_hash` 去重；这些内部字段不出现在 `SearchResult` / `AskResponse`。
- source 和 heading 保留。
- 重复 `(source, heading_path, content_hash)` 只保留一次。
- 超预算时按固定策略跳过或截断。
- 空结果能正常处理。

依赖：Task 11。

## Task 14: LLM Client

目标：接入 fake LLM 和通用 OpenAI-compatible LLM。

产物：

- `app/llm.py`
- `app/prompts.py`
- `LLMClient` provider abstraction。

行为要求：

- 从环境变量读取 base URL、model、API key。
- 读取 `LLM_PROVIDER`，支持 `fake` 和 `openai-compatible`。
- `fake` provider 返回 deterministic answer，用于测试；它必须基于传入 context/citations 生成可预测输出，不调用外部网络。
- `openai-compatible` provider 使用通用 OpenAI-compatible chat completions。
- `openai-compatible` provider 要求 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 都已初始化；任一缺失时必须报清晰配置错误。
- 不支持 provider-specific fallback key；代码只能读取通用 `LLM_*` 变量。
- 不在代码中硬编码任何 provider-specific base URL 或 model 默认值。
- 不打印 API key。
- 支持 timeout。
- RAG prompt 只能根据上下文回答。
- fallback prompt 明确说明不是知识库答案。

OpenAI-compatible wire contract：

- `/ask` 请求使用 non-streaming chat completions；`/ask/stream` 请求使用 SSE streaming chat completions。
- endpoint 由 `LLM_BASE_URL.rstrip("/") + "/chat/completions"` 得到；如果 provider 需要 `/v1`，它必须已经包含在 `LLM_BASE_URL` 中，代码不得自动猜测或追加 `/v1`。
- HTTP headers 固定包含 `Authorization: Bearer {LLM_API_KEY}` 和 `Content-Type: application/json`；日志、异常和测试快照不得打印 bearer token 原文。
- non-streaming request body 至少包含：

```json
{
  "model": "<LLM_MODEL>",
  "messages": [
    {"role": "system", "content": "<system prompt>"},
    {"role": "user", "content": "<user prompt>"}
  ],
  "temperature": 0,
  "stream": false
}
```

- streaming request 使用同样字段但 `stream: true`；streaming response 读取标准 `data: {...}` chunks 中的 `choices[0].delta.content`，遇到 `data: [DONE]` 结束。
- non-streaming response 读取路径固定为 `choices[0].message.content`；缺失、非字符串或空白内容都映射为 `llm_upstream_error`。
- timeout 使用 `LLM_TIMEOUT_SECONDS` 传入 HTTP client。
- upstream error mapping：timeout -> `llm_timeout`；HTTP `401`/`403` -> `llm_auth_failed`；HTTP `429` -> `llm_rate_limited`；其他 HTTP `4xx/5xx`、网络错误或 malformed response -> `llm_upstream_error`。

验证：

本地默认测试不依赖真实 API key。

```bash
pytest tests/test_llm.py
```

测试至少覆盖：

- `fake` provider 基于传入 context/citations 返回 deterministic answer，不访问网络。
- `openai-compatible` 缺少 `LLM_BASE_URL`、`LLM_API_KEY` 或 `LLM_MODEL` 时返回 `llm_config_missing`。
- 日志、异常和配置摘要不包含 API key 原文，只能显示 key 是否存在。
- timeout 配置会传入 HTTP client，并能通过 fake/mock client 断言。
- mock HTTP client 断言 non-streaming 和 streaming request body、Authorization header、messages 格式、`choices[0].message.content` 读取路径和 `choices[0].delta.content` chunk 读取路径。
- mock HTTP client 覆盖 timeout、401/403、429、5xx 和 malformed response 的错误映射。
- RAG prompt 只允许根据 context 回答；fallback prompt 明确说明不是知识库答案。

可选的 developer manual/live check 可以对 LLM client 做一次最小联网验证，但它不属于 Task 14 默认完成标准，也不进入 CI 或无人值守验收。完整 agent-facing `/ask` 联网验收见 Task 19，并且必须在 `/ask` 链路完成后执行。验证前必须先在本地 shell 或 `.env` 初始化：

```bash
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL="<provider openai-compatible base url>"
export LLM_API_KEY="<provider api key>"
export LLM_MODEL="<provider model>"
```

如果本地 shell 已经配置了 `KIMI_API_KEY`，测试时可以在 shell 层映射到通用变量：

```bash
export LLM_API_KEY="$KIMI_API_KEY"
```

这是测试/CLI 初始化步骤，不是应用代码逻辑；应用代码仍然只能读取 `LLM_API_KEY`。

可选验证命令：

```bash
python -m app.llm --live
```

应能完成一次最小 chat completion。验证请求使用：

```text
POST {LLM_BASE_URL}/chat/completions
Authorization: Bearer <LLM_API_KEY>
Content-Type: application/json
model={LLM_MODEL}
stream=false
```

预期输出只展示非敏感信息：

```text
llm_provider=openai-compatible
llm_base_url_present=true
llm_model_present=true
chat_ok=true
```

依赖：Task 1。

## Task 15: Ask Endpoint

目标：完成端到端问答 API。

产物：

- `POST /ask`
- `rag ask "..."`

行为要求：

- 使用 `app/schemas.py` 中的 `AskRequest` / `AskResponse`。
- `POST /ask` 绑定 FastAPI route，route handler 调用 shared ask service。
- `rag ask` 调用同一个 shared ask service，不依赖 `uvicorn` 或 HTTP server。
- 调 retrieval。
- 判断 confidence。
- 高置信返回 `mode=rag`。
- MVP 不实现 `mixed` mode。
- 低置信且 `fallback=false` 返回 `mode=no_answer`。
- 低置信且 `fallback=true` 且 `RAG_FALLBACK_ENABLED=true` 返回 `mode=fallback`。
- 低置信且 `fallback=true` 但 `RAG_FALLBACK_ENABLED=false` 返回 `mode=no_answer`，并说明 fallback 被全局禁用。
- 所有 RAG 答案返回 citations。
- `no_answer` 不调用通用 LLM 回答。
- `fallback` 必须明确说明答案不是来自本地知识库，且 citations 为空。

mode 判断：

```text
confidence >= RAG_MIN_SIMILARITY -> rag
confidence < RAG_MIN_SIMILARITY and fallback=false -> no_answer
confidence < RAG_MIN_SIMILARITY and fallback=true and RAG_FALLBACK_ENABLED=false -> no_answer
confidence < RAG_MIN_SIMILARITY and fallback=true and RAG_FALLBACK_ENABLED=true -> fallback
```

验证：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
rag ask "客户 P1 工单应该怎么升级？"
rag ask "完全不存在的随机问题 xyz"
RAG_FALLBACK_ENABLED=true rag ask "完全不存在的随机问题 xyz" --fallback
pytest tests/test_ask_api.py
```

`tests/test_ask_api.py` 至少覆盖：

- FastAPI TestClient 调用 `POST /ask` 的 high-confidence 问题返回 `mode=rag` 和 citations。
- 低置信且 `fallback=false` 返回 `mode=no_answer`，不调用通用 LLM。
- 低置信且 `fallback=true` 但 `RAG_FALLBACK_ENABLED=false` 返回 `mode=no_answer`。
- `RAG_FALLBACK_ENABLED=true` 且 request `fallback=true` 返回 `mode=fallback`，citations 为空，并说明不是本地知识库答案。
- invalid request 返回统一 `ErrorResponse`。

依赖：Task 2.5、Task 3.5、Task 11、Task 12、Task 13、Task 14。

## Task 16: API Contract Audit

目标：在 `/search` 和 `/ask` 已经实现后，做轻量 contract audit，确认所有 route、CLI 和错误路径都遵守 Task 3.5 固定的 schema，而不是首次收口 schema。

产物：

- `tests/test_api_schemas.py`
- 必要时对 `app/schemas.py`、route response_model 或 error handler 做小修正。

schema ownership：

- `app/schemas.py` 已在 Task 3 创建，并已由 Task 3.5 补齐 schema foundation。
- `app/schemas.py` 必须实现本文档顶部 `MVP API Schema Contract` 的字段表。
- Task 11 实现 `/search` 时必须使用已有 `SearchRequest` / `SearchResponse`。
- Task 15 实现 `/ask` 时必须使用已有 `AskRequest` / `AskResponse`。
- Task 16 只负责发现遗漏、统一字段命名、补齐 response_model / OpenAPI / error path 测试，不允许把 Task 11/15 的临时 dict 留到这里集中返工。

错误响应：

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

FastAPI integration：

- `app/main.py` 必须注册 `RequestValidationError` handler。
- Pydantic validation failure 必须返回同一个 `ErrorResponse` 结构，HTTP `422`，`error.code="invalid_request"`。
- `error.details` 可以包含经过脱敏的字段错误列表，但不能保留 FastAPI 默认 `{"detail": [...]}` 顶层 shape。
- Task 16 必须用 API test 覆盖 invalid `top_k`、空 query/question 和 malformed body。

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

至少覆盖：

- `HealthResponse`
- `SearchRequest`
- `SearchResponse`
- `AskRequest`
- `AskResponse`
- `Citation`

MVP 不包含 `POST /ingest`，因此不需要 HTTP `IngestRequest` / `IngestResponse`。

验证：

```bash
pytest tests/test_api_schemas.py
```

依赖：Task 3.5、Task 10、Task 11、Task 15。

## Task 17: CLI

目标：统一收口 CLI，让 FDE 不写 curl 也能完成 smoke test。

产物：

- `pyproject.toml` console script：`rag = "app.cli:main"`。
- `app/cli.py`。
- `rag` CLI entrypoint。
- `rag db init`。
- `rag embeddings warmup`。

命令：

本地 venv 命令：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
rag --help
rag db init
rag embeddings warmup
rag ingest samples/acme-vault
rag search "..."
rag ask "..."
```

CLI 实现边界：

- Task 0 提供 CLI scaffold。
- Task 9/10/11/15 分别接入 `embeddings warmup`、`ingest`、`search`、`ask` 子命令。
- Task 17 不重新定义业务逻辑，只统一命令结构、help text、错误信息、输出格式和 exit codes。
- CLI 必须支持全局 `--env-file PATH`，用于 repo root 外执行时显式指定 `.env`。
- CLI 不启动也不要求 API server；`rag search` 和 `rag ask` 直接调用 shared service layer。
- HTTP endpoint 也调用同一层，避免 CLI 和 API 行为分叉。
- MVP CLI 默认输出 JSON，便于 smoke test 和 agent/tool 调用；错误输出到 stderr，失败返回非零 exit code。

验证：

```bash
rag --help
rag db init
rag embeddings warmup
rag ingest samples/acme-vault
rag search "客户 P1 工单应该怎么升级？"
rag ask "客户 P1 工单应该怎么升级？"
rag ask "完全不存在的随机问题 xyz"
RAG_FALLBACK_ENABLED=true rag ask "完全不存在的随机问题 xyz" --fallback
rag --env-file .env search "客户 P1 工单应该怎么升级？"
```

验证还必须覆盖一个失败命令返回非零 exit code，例如 schema 未初始化或 retrieval not ready；错误正文输出到 stderr，并使用统一错误 code。

依赖：Task 0、Task 9、Task 10、Task 11、Task 15。

## Task 18: End-to-end Smoke Test

目标：用一个测试覆盖 MVP 主路径。

产物：

- `tests/test_smoke.py`
- `eval/questions.yaml` 被 smoke test 读取。

测试流程：

```text
init schema
ingest sample vault
search sample questions
ask sample questions
ask unrelated question
```

默认 smoke test 使用 fake lexical deterministic embedding 和 fake LLM，不依赖外网或真实 API key。Task 18 必须复用 Task 2.5 的 test harness；因为配置优先级是 OS env > `.env`，harness 必须强制注入以下运行时配置，覆盖开发机 shell 里的 provider 设置：

```text
EMBEDDING_PROVIDER=fake
EMBEDDING_MODEL=fake-lexical-v1
EMBEDDING_DIM=1024
LLM_PROVIDER=fake
LLM_MODEL=fake-local
LLM_API_KEY=
LLM_BASE_URL=
```

HTTP / CLI 边界：

- smoke test 必须覆盖 shared service layer 的 CLI 路径，例如 `rag search` / `rag ask`。
- smoke test 也必须用 FastAPI `TestClient` 或等价 in-process HTTP client 调用 `POST /search` 和 `POST /ask`，验证 API schema contract。
- smoke test 不要求启动外部 `uvicorn` 进程；Task 19 的 manual live gate 才要求通过正在运行的 HTTP server 调用 `POST /ask`。

数据库运行方式：

- smoke test 依赖一个已启动的 Postgres + pgvector 数据库，但 destructive cleanup 只能通过 Task 2.5 harness 连接 `TEST_DATABASE_URL`。
- `TEST_DATABASE_URL` guard、fake provider 注入、runtime `DATABASE_URL` 覆盖和 CLI subprocess env 注入规则全部继承 Task 2.5；Task 18 不能重新实现一套不同 fixture。
- smoke test 可以对 `TEST_DATABASE_URL` 执行 `rag db init` / schema init helper，并在测试前通过共享 fixture 清空 `documents`、`chunks`、`embeddings`、`ingest_runs`，但不负责启动或停止 Docker。
- CI 和本地路径必须先启动 postgres，再在本地 venv 中运行 pytest。
- 本地 venv 的 app/CLI 通过 `DATABASE_URL` 连接 demo 库；smoke test 通过 `TEST_DATABASE_URL` 连接测试库。
- smoke test 必须读取 `eval/questions.yaml`：至少 5 个 `expected_mode=rag` 问题和至少 1 个 `expected_mode=no_answer` 且 `expected_sources=[]` 的问题，不足时 fail fast。

测试至少覆盖：

- 至少 5 个 `expected_mode=rag` sample questions 的 expected source 命中。
- 至少 5 个 `expected_mode=rag` sample questions 返回 `mode=rag`。
- `expected_mode=no_answer` 且 `expected_sources=[]` 的无关问题在默认 `RAG_FALLBACK_ENABLED=false` 下返回 `mode=no_answer`。
- 显式设置 `RAG_FALLBACK_ENABLED=true` 且 request `fallback=true` 时返回 `mode=fallback`。

验证：

```bash
test -f .env || cp .env.sample .env
docker compose up -d postgres
docker compose exec -T postgres createdb -U local_rag local_rag_test || true
TEST_DATABASE_URL=postgresql://local_rag:local_rag@localhost:5432/local_rag_test \
pytest tests/test_smoke.py
```

注意：`pytest` 命令不要在 shell 中设置 `DATABASE_URL=...local_rag_test`。fixture 必须先比较 demo `DATABASE_URL` 和 `TEST_DATABASE_URL`，guard 通过后再给 app service / CLI subprocess 注入运行时 `DATABASE_URL=TEST_DATABASE_URL`。

如果不能使用 `docker compose exec`，可用宿主机 Postgres client 创建测试库：

```bash
PGPASSWORD=local_rag createdb -h localhost -U local_rag local_rag_test || true
```

依赖：Task 2.5、Task 8.5、Task 15、Task 16、Task 17。

## Task 19: Manual Live OpenAI-compatible Release Gate

目标：在 agent-facing `/ask` 链路完成后，用真实 OpenAI-compatible provider 做一次人工联网验证。它是带凭证、带网络的 release gate，不属于默认 CI 或无人值守 smoke test。

产物：

- manual live check 命令或脚本。
- 文档化的联网验证步骤。

行为要求：

- 使用 `LLM_PROVIDER=openai-compatible`。
- `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 必须在本地 shell 或 `.env` 中提前初始化。
- Task 19 必须显式标记为 manual/live check；默认完成标准到 Task 18 为止，CI 不自动执行 Task 19。
- 验证脚本只读取通用 `LLM_*` 变量，不读取 provider-specific key。
- 如果本地 shell 已有非空 `KIMI_API_KEY`，live test 可以先映射到通用变量 `LLM_API_KEY`，但应用代码仍不得读取 `KIMI_API_KEY`。不得把空 `KIMI_API_KEY` export 成空 `LLM_API_KEY`，以免遮蔽 `.env` 中的有效值。
- manual live check 前必须已经完成 `rag db init` 和 sample vault ingest；否则验证只是在测空库。
- 必须通过 HTTP 调用本地 `POST /ask`，不能只通过 `rag ask` 内部函数路径验证。
- 返回包含 `mode`、`answer`、`citations`。
- 日志和输出不能打印 API key。

验证：

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

`.env` 或当前 shell 必须提供：

```bash
LLM_PROVIDER=openai-compatible
LLM_BASE_URL="<provider openai-compatible base url>"
LLM_API_KEY="<provider api key>"
LLM_MODEL="<provider model>"
```

如果 `LLM_API_KEY` 来自 shell export，`.env` 中可以保持 `LLM_API_KEY=` 为空；应用仍只读取通用 `LLM_API_KEY`。

然后在另一个 shell 执行：

```bash
curl -sS http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

依赖：Task 18。

## Task 20: README Quickstart

目标：让新用户 5 分钟内跑起 demo。

产物：

- README quickstart。

必须包含：

- venv development setup。
- Docker Compose 只启动 Postgres。
- CLI、pytest 和 API 使用本地 venv；sample vault path 为 `samples/acme-vault`。
- ingest command。
- search example。
- ask example。
- OpenAI-compatible env var example。
- fallback behavior explanation。
- local-qwen3 FDE semantic demo 前的 Task 9 warmup 和 Task 12 source-hit / threshold manual gate。

验证：

让一个没有上下文的新读者只看 README，能完成本地启动和一次问答。

依赖：Task 0 到 Task 18。README 必须记录 Task 12 的 local-qwen3 source-hit / threshold manual gate 和 Task 19 的人工联网验证步骤，但默认 quickstart 不要求执行这两个 manual gates。

## Task 21: FDE Demo Script

目标：给 FDE 一份可现场照着演示的脚本。

产物：

- `docs/demo-script.md`

脚本包含：

- 项目价值开场。
- 打开 sample vault。
- 启动服务。
- ingest。
- 问一个高置信问题。
- 展示 citation。
- 问一个低置信问题。
- 开启 fallback。
- 如果脚本选择 local-qwen3 语义 demo 路径，先执行 Task 9 warmup 和 Task 12 local-qwen3 source-hit / threshold gate，并展示 gate 通过摘要。
- 解释 agent 为什么接 API 而不是 Postgres。

验证：

FDE 按脚本能在 15 分钟内完成完整演示。选择 local-qwen3 语义 demo 路径时，演示前必须已经完成 Task 12 local-qwen3 source-hit / threshold gate；现场脚本不应临时才开始下载模型或校准阈值。

真实联网演示前还必须完成 Task 19。

依赖：Task 20。

## Recommended Implementation Order

推荐按以下顺序实现：

```text
0 foundation
1 config
2 database
2.5 test DB fixture / test harness
3 health
3.5 API schema foundation
4 sample vault
5 scanner
6 parser
7 chunking
8 embeddings
8.5 fake embedding calibration
9 embedding warmup
10 ingest
11 retrieval
12 confidence
13 context/citations
14 llm
15 ask
16 contract audit
17 cli
18 smoke test
19 manual live OpenAI-compatible release gate
20 README
21 demo script
```

前半段先让数据进入系统，后半段再让答案可信地出来。

## Vertical Slice Checkpoints

为了避免只完成散件但没有闭环，MVP 设三个自动 checkpoint，另有两个 manual gates：local-qwen3 retrieval gate 和 live OpenAI-compatible release gate。

### Checkpoint A: Service Starts

完成任务：

- Task 0
- Task 1
- Task 2
- Task 2.5
- Task 3
- Task 3.5

验证：

```bash
cp .env.sample .env
docker compose up -d postgres
rag db init
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后在另一个 shell 执行：

```bash
curl http://localhost:8000/health
```

### Checkpoint B: Knowledge Indexed

完成任务：

- Task 4
- Task 5
- Task 6
- Task 7
- Task 8
- Task 8.5
- Task 9
- Task 10

验证：

```bash
cp .env.sample .env
source .venv/bin/activate
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
```

并确认数据库中有 documents、chunks、embeddings。

### Checkpoint C: Cited Answer

完成任务：

- Task 11
- Task 12
- Task 13
- Task 14
- Task 15
- Task 16

验证：

```bash
cp .env.sample .env
source .venv/bin/activate
docker compose up -d postgres
rag db init
rag ingest samples/acme-vault
rag ask "客户 P1 工单应该怎么升级？"
```

返回必须包含：

- `mode`
- `confidence`
- `answer`
- `citations`

### Manual Gate: Local-Qwen3 Source-Hit / Threshold Check

完成任务：

- Task 9
- Task 10
- Task 11
- Task 12

验证：

按 Task 12 的 `manual local-qwen3 source-hit / threshold gate` 执行。该 gate 必须在 FDE 现场语义 demo 前通过，证明 sample questions 在真实本地 embedding 下 source-hit、confidence threshold 和 `no_answer` 行为都可靠。

### Manual Release Gate: Live OpenAI-compatible Check

完成任务：

- Task 19

验证：

`.env` 或当前 shell 必须设置：

```bash
LLM_PROVIDER=openai-compatible
LLM_BASE_URL="<provider openai-compatible base url>"
LLM_API_KEY="<provider api key>"
LLM_MODEL="<provider model>"
```

本地 venv 中启动 API：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后在另一个 shell 执行：

```bash
curl -sS http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"客户 P1 工单应该怎么升级？","top_k":5,"fallback":false}'
```

返回必须包含：

- `mode`
- `answer`
- `citations`

输出和日志不得包含 API key。

## Not MVP

以下能力不进入 MVP subtask：

- Web UI。
- MCP server。
- 完整 RBAC。
- PDF/DOCX/PPT ingestion。
- 多租户。
- Kubernetes deployment。
- LLM judge eval。
- Watch mode。
- Production auth。
- 自定义 embedding model 或远程 embedding provider。

这些进入 full release roadmap。
