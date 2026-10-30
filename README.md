# Agent Center

政务智能体中台（Agent Center）后端实现。技术栈：Python 3.11 + FastAPI + SQLAlchemy（异步）+ LangGraph。
支持 Agent 定义与发布、多轮会话、ReAct 运行时、工具中心、知识检索、记忆与画像、评测与运营。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
# 或使用锁定版本：.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000/docs 查看 OpenAPI。默认使用 SQLite，启动时自动建表。

## 一键启动（Docker）

Windows：双击 `start.bat`，或在 PowerShell 中：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

Linux / macOS：

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

脚本会自动：检查并启动 Docker、从 `.env.example` 生成 `.env`（不覆盖已有文件）、构建并启动容器、等待健康检查通过后打印访问地址。

其他参数：

| 命令 | 作用 |
| --- | --- |
| `scripts/start.ps1 -Logs` / `scripts/start.sh --logs` | 跟踪应用日志 |
| `scripts/start.ps1 -Stop` / `scripts/start.sh --stop` | 停止并移除容器（保留数据卷） |
| `scripts/start.ps1 -NoBuild` / `-NoBuild` | 跳过镜像构建，仅启动 |

也可以直接使用 compose：

```bash
# 可选：在项目根目录创建 .env 填写模型密钥（compose 会自动读取）
#   AC_LLM_API_KEY=sk-xxx

docker compose up -d --build
```

启动后：

| 服务 | 地址 |
| --- | --- |
| 应用 / OpenAPI | http://localhost:8000/docs |
| MySQL | localhost:3307（用户 `agent` / 密码 `agent_pass`，库 `agent_center`） |
| Redis | localhost:6380 |
| Milvus | 默认使用内嵌 Milvus Lite，数据在 `milvus_lite_data` 卷（`/data/milvus.db`） |

说明：
- 默认栈为 app + MySQL + Redis，启动时自动建表（`AC_AUTO_CREATE_TABLES=true`）。
- 需要独立 Milvus 服务时：`AC_MILVUS_URI=http://milvus:19530 docker compose --profile milvus up -d`，该 profile 会拉起 etcd + MinIO + Milvus；部分网络环境拉取 MinIO 镜像会被拒绝。
- 常用命令：`docker compose ps`、`docker compose logs -f app`、`docker compose down`（保留数据，`-v` 删除数据卷）。
- 构建慢时可切换镜像源（示例）：`$env:PIP_INDEX_URL='https://mirrors.aliyun.com/pypi/simple/'; docker compose build`，该值通过构建参数传给容器内 pip。
- 测试仍在宿主机执行（镜像不包含 tests）：`.venv\Scripts\python -m pytest -q`。

## 配置

所有配置通过 `AC_` 前缀环境变量或 `.env` 注入：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AC_DATABASE_URL` | `sqlite+aiosqlite:///./agent_center.db` | 数据库连接，生产使用 `mysql+aiomysql://...` |
| `AC_AUTO_CREATE_TABLES` | `true` | 启动时自动建表；生产建议关闭并使用 Alembic |
| `AC_MODEL_PROVIDER` | `stub` | `stub`、`litellm` 或 `openai`（OpenAI 兼容网关） |
| `AC_LLM_BASE_URL` | 空 | 模型网关地址，如 `https://api.commandcode.ai/provider/v1` |
| `AC_LLM_API_KEY` | 空 | 模型密钥；为空时自动回退桩模型 |
| `AC_LLM_MODEL` | `deepseek/deepseek-v4.1-flash` | 主模型 |
| `AC_LLM_FALLBACK_MODEL` | `deepseek/deepseek-v4-flash` | 降级模型 |
| `AC_EMBEDDING_MODEL` | 空 | Embedding 模型；为空时使用本地哈希向量 |
| `AC_EMBEDDING_DIM` | `1024` | 向量维度，需与 Milvus 集合一致 |
| `AC_REDIS_URL` | 空 | Redis 地址；为空时使用进程内锁/限流/事件流 |
| `AC_MILVUS_URI` | 空 | Milvus 地址；容器内默认 `/data/milvus.db`（Lite） |
| `AC_CREDENTIAL_KEY` | 空 | 工具凭证加密密钥；生产必须配置 |
| `AC_SSE_HEARTBEAT_SECONDS` | `15` | SSE 心跳间隔 |
| `AC_TRACE_RETENTION_DAYS` | `90` | 轨迹保留天数 |
| `AC_OTEL_ENABLED` | `false` | 开启 OpenTelemetry Span 埋点 |
| `AC_OTEL_ENDPOINT` | 空 | OTLP/HTTP traces 地址，如 `http://collector:4318/v1/traces` |
| `AC_OTEL_SERVICE_NAME` | `agent-center` | OTel `service.name` |
| `AC_OTEL_SAMPLE_RATIO` | `1.0` | 采样比例 0–1 |
| `AC_DB_POOL_SIZE` | `10` | 数据库连接池大小 |
| `AC_DB_MAX_OVERFLOW` | `20` | 连接池溢出上限 |
| `AC_DB_POOL_TIMEOUT` | `30` | 获取连接超时（秒） |
| `AC_DB_POOL_RECYCLE` | `1800` | 连接回收秒数 |
| `WEB_CONCURRENCY` | `1` | Uvicorn worker 数；多 worker 时关闭自动建表 |
| `AC_ALERT_WEBHOOK_URL` | 空 | 告警回调地址；为空时只返回告警不推送 |
| `AC_PUBLISH_REQUIRE_EVAL` | `false` | 开启后提示词发布必须有达标评测 |
| `AC_STUB_REPLY` | 桩回复 JSON | 桩模型返回的决策 JSON |
| `AC_SENSITIVE_WORDS` | 空 | 敏感词表，逗号分隔 |
| `AC_MODERATION_URL` | 空 | 外部审核服务地址，不可用时拒绝放行 |
| `AC_MEMORY_EXTRACTION_ENABLED` | `false` | 是否异步抽取记忆 |

## 可观测

开启 OTel 后自动产生四层 Span，可直接接 Jaeger、Tempo 或 Grafana：

```bash
AC_OTEL_ENABLED=true
AC_OTEL_ENDPOINT=http://127.0.0.1:4318/v1/traces   # OTLP/HTTP
AC_OTEL_SAMPLE_RATIO=1.0
```

- `http.request` → `agent.run` → `model.complete` / `tool.execute`，流式响应结束后 HTTP Span 才关闭
- 关键属性：`ac.run_id`、`ac.tenant_id`、`ac.agent_code`、`gen_ai.request.model`、`gen_ai.usage.*`、`http.response.status_code`、`error.code`
- 未配置 endpoint 时不导出；采集器不可用只影响导出，不影响业务
- 采样比例通过 `AC_OTEL_SAMPLE_RATIO` 控制，生产建议 0.01–0.1

运行时指标通过 `/metrics` 暴露（OpenMetrics，含 `trace_id` Exemplar）：

```bash
curl -s http://127.0.0.1:8000/metrics | head
```

一键启动 Prometheus + Tempo + Grafana（预置「Agent Center 总览」看板）：

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| Grafana | http://localhost:3000 | `admin/admin`，看板「Agent Center 总览」 |
| Prometheus | http://localhost:9090 | 抓取 `app:8000/metrics` |
| Tempo | http://localhost:3200 | OTLP HTTP 接收端 `:4318` |

看板包含 QPS、5xx 比例、HTTP/模型 P95、Tool 调用、Run 状态、Token 速率；HTTP 与模型延迟图上的 Exemplar 点可直接跳转到 Tempo 中对应 Trace。overlay 会自动把 `AC_OTEL_ENDPOINT` 指向 `http://tempo:4318/v1/traces`。

## 计划执行（PlanExecutor）

模型可在一次决策中给出多步只读工具计划，由独立的 `PlanExecutor` 顺序执行：

```json
{
  "type": "plan",
  "steps": [
    { "tool": "policy.search", "arguments": { "query": "营业执照" } },
    { "tool": "matter.detail", "arguments": { "code": "license" } }
  ]
}
```

- 仅允许 Agent 已绑定的只读工具；未授权工具、禁用工具、写工具均拒绝执行
- 写操作必须使用 `tool_call` 单独发起并等待确认，不得放入 `plan`（或 `fanout`）
- 单计划最多 8 步；单步失败不终止后续步骤，失败信息会明确回填给模型
- 工具结果以 `<plan_results untrusted="true">` 回填，降低工具输出注入风险
- Run 中记录 `PLAN_EXECUTOR` 步骤，SSE 输出 `tool.call` / `tool.result` 事件

## 回答复核（Critic）

Agent 版本可通过 `critic_policy` 开启高风险回答复核：

```json
{
  "critic_policy": {
    "enabled": true,
    "mode": "risk",
    "risk_keywords": ["补贴", "金额", "比例", "时限", "收费"],
    "timeout_ms": 15000,
    "on_error": "pass"
  }
}
```

- `mode=risk` 仅在问题或回答命中风险词时复核；`always` 全量复核
- 复核模型返回 `pass / revise / reject`：`revise` 使用改写回答，`reject` 返回安全兜底话术
- 复核时会把本次检索到的知识片段一并传入，要求模型不得引用片段外政策依据
- `on_error=pass` 表示复核模型不可用或输出无法解析时放行，不阻塞对话；`reject` 则返回兜底
- 复核调用计入 token，Run 中记录 `CRITIC_REVIEW` 步骤，并产生 `critic.review` Span

## 身份与租户

请求头（由可信网关注入）：

```
X-Tenant-Id: t1
X-User-Id: u1
X-Roles: admin
X-Permissions: ...
X-Trace-Id: trace_xxx
```

管理接口（`/api/v1/admin/*`）要求 `admin` 角色或 `admin`/`admin:write` 权限。

## 主要接口

| 模块 | 接口 |
| --- | --- |
| 会话 | `POST /api/v1/chat/sessions`、`GET /api/v1/chat/sessions/{id}` |
| 对话 | `POST /api/v1/chat/sessions/{id}/messages`（SSE）、`POST .../interrupt` |
| 确认 | `POST /api/v1/chat/sessions/{id}/confirmations/{cid}` |
| 轨迹 | `GET /api/v1/chat/sessions/{id}/runs/{runId}`、`.../events?lastEventId=`、`.../stream?lastEventId=` |
| 会话管理 | `GET /api/v1/admin/sessions`（用户/状态/时间/分页） |
| 恢复 | `POST /api/v1/chat/sessions/{id}/runs/{runId}/resume` |
| 反馈 | `POST /api/v1/feedback` |
| Agent | `GET/POST /api/v1/admin/agents`、`.../{id}/versions`、`.../{id}/publish`、`.../{id}/bindings` |
| 提示词 | `POST /api/v1/admin/prompts`、`.../{id}/versions`、`.../transition` |
| 工具 | `POST /api/v1/admin/tools`、`POST .../{code}/test`、`POST .../import-openapi`、`POST .../import-mcp`、凭证管理 |
| 知识 | `POST /api/v1/admin/knowledge-spaces`、`.../documents`、`.../publish`、`POST /api/v1/knowledge/search` |
| 知识同步 | `POST /api/v1/admin/knowledge-sync-tasks` |
| 知识版本 | `POST /api/v1/admin/knowledge-documents/{id}/versions`、`.../unpublish` |
| 记忆/画像 | `GET /api/v1/memory`、`GET /api/v1/profile/summary`、`GET /api/v1/profile/suggestions` |
| 评测 | `POST /api/v1/admin/eval-datasets`、`.../cases/import`（批量基线导入）、`POST /api/v1/admin/evaluations` |
| 运营 | `GET /api/v1/admin/badcases`、`GET /api/v1/admin/audit-logs`、`GET /api/v1/admin/metrics/overview`、`GET .../metrics/prometheus`、`POST .../alerts/check` |
| 提醒 | `POST /api/v1/notifications`、`POST /api/v1/admin/notifications/dispatch-due` |
| 运维 | `POST /api/v1/admin/maintenance/purge-trace`（默认清理 90 天前轨迹）、`GET /api/v1/admin/model/health`（真实调用一次模型自检） |

### SSE 事件

`run.start`、`thinking`、`tool.call`、`tool.result`、`handoff`、`citation`、`confirmation.required`、`message.delta`、`message.end`、`error`。
事件 id 形如 `run_id:seq`，断线后可用 `/events?lastEventId=run_id:seq` 增量重放。

## 模型自检与 401 排查

```bash
curl http://localhost:8000/api/v1/admin/model/health \
  -H "X-Tenant-Id: t1" -H "X-User-Id: admin" -H "X-Roles: admin"
```

返回 `ok=true` 表示密钥、地址与模型均可用；`ok=false` 时会附带原因和提示。

业务问题端到端抽样（自动建独立租户、知识库与 Agent，输出逐题明细与汇总）：

```bash
docker cp scripts/e2e_sample.py agent-center-app:/tmp/e2e_sample.py
docker compose exec -T app python /tmp/e2e_sample.py
```

最近一次结果见 [docs/e2e-sample-report.md](docs/e2e-sample-report.md)，安全专项见 [docs/security-test-report.md](docs/security-test-report.md)，并发压测见 [docs/load-test-report.md](docs/load-test-report.md)。

并发压测（桩模型，测平台自身开销）：

```bash
python scripts/load_test.py --base-url http://127.0.0.1:8001 --sessions 2000 --concurrency 200
```

多 worker 部署示例：`WEB_CONCURRENCY=6`，同时设置 `AC_AUTO_CREATE_TABLES=false`；按 `副本数 × (AC_DB_POOL_SIZE + AC_DB_MAX_OVERFLOW) < MySQL max_connections × 0.8` 预留连接。

灾备演练（MySQL 全量 + Redis RDB + Milvus Lite）：

```bash
python scripts/dr_backup.py --output backups
python scripts/dr_restore.py --backup backups/mysql_<ts>.sql \
  --target-db agent_center_drill --drop-existing
```

最近一次演练见 [docs/dr-drill-report.md](docs/dr-drill-report.md)。

MCP 工具接入支持 `http`、`sse`、`stdio` 三种传输，导入后可像普通工具一样绑定到 Agent：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/tools/import-mcp \
  -H "X-Tenant-Id: t1" -H "X-User-Id: u1" -H "X-Roles: admin" \
  -H "Content-Type: application/json" \
  -d '{"transport":"stdio","command":["npx","-y","@modelcontextprotocol/server-filesystem","."],"tool_prefix":"fs.","auto_register":true}'
```

SSE 传输传 `{"transport":"sse","url":"https://mcp.example.com/sse"}`；HTTP 传输传 `{"transport":"http","url":"https://mcp.example.com/mcp"}`。stdio 会以子进程运行 command，仅管理员可调用，且每次工具调用独立启停进程。

更完整的真实模型验证（50 条决策样本、流式、备用模型）：

```bash
docker cp scripts/validate_model.py agent-center-app:/tmp/validate_model.py
docker compose exec -T app python /tmp/validate_model.py
```

若返回 `401 Invalid 'Authorization' header or token`：说明密钥被服务端判定失效。Command Code 在 2026-10-29 发生过密钥批量轮换/失效（见 [issue #1084](https://github.com/CommandCodeAI/command-code/issues/1084)），处理方式：

1. 到 [Studio → API Keys](https://commandcode.ai/settings/keys) 新建 key，或执行 `cmdc login` 重新登录；
2. 更新 `.env` 中的 `AC_LLM_API_KEY`；
3. `docker compose up -d --force-recreate app` 让容器加载新密钥；
4. 再次调用 `model/health` 确认 `ok=true`。

## 数据库建表

生产环境关闭自动建表（`AC_AUTO_CREATE_TABLES=false`），由 DBA 执行 `docs/schema-mysql.sql`。
模型变更后可用 `python scripts/export_ddl.py` 重新生成。

## 开发与测试

```bash
.venv\Scripts\python -m pytest -q
```

测试使用内存 SQLite，覆盖单元、集成、租户隔离、安全与权限场景。

## 目录结构

```
app/
  api/v1/          对外与管理接口
  core/            配置、异常、租户、Trace、中间件
  domain/          领域模型与服务（agent/prompt/session/tool/memory/profile/knowledge/model/evaluation/notification/safety）
  runtime/         ReAct 执行器、路由、交接、Fan-out、上下文装配、检查点
  integrations/    LLM、MCP、HTTP 工具、OpenAPI
  infrastructure/  数据库与会话、Redis、向量存储
  workers/         后台任务
scripts/           一键启动、DDL 导出
migrations/        Alembic 迁移骨架
tests/             单元与集成测试
docker-compose.yml 本地容器编排（app + MySQL + Redis，Milvus profile）
requirements*.txt  锁定版本依赖（运行时 / 开发）
AGENTS.md          编码代理与开发约定
```

依赖安装二选一：`pip install -e ".[dev]"`（推荐开发）或 `pip install -r requirements-dev.txt`（锁定版本）。

## 待确认事项

见 [docs/open-questions.md](docs/open-questions.md)，包含模型来源、认证接口、向量库、Redis 限流与锁、管理前端等问题。
交付验收标准与差距清单见 [docs/acceptance-checklist.md](docs/acceptance-checklist.md)，开发约定与命令见 [AGENTS.md](AGENTS.md)。
