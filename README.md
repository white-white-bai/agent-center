# Agent Center

政务智能体中台（Agent Center）后端实现。技术栈：Python 3.11 + FastAPI + SQLAlchemy（异步）+ LangGraph。
支持 Agent 定义与发布、多轮会话、ReAct 运行时、工具中心、知识检索、记忆与画像、评测与运营。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000/docs 查看 OpenAPI。默认使用 SQLite，启动时自动建表。

## 配置

所有配置通过 `AC_` 前缀环境变量或 `.env` 注入：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AC_DATABASE_URL` | `sqlite+aiosqlite:///./agent_center.db` | 数据库连接，生产使用 `mysql+aiomysql://...` |
| `AC_AUTO_CREATE_TABLES` | `true` | 启动时自动建表；生产建议关闭并使用 Alembic |
| `AC_MODEL_PROVIDER` | `stub` | `stub` 或 `litellm` |
| `AC_STUB_REPLY` | 桩回复 JSON | 桩模型返回的决策 JSON |
| `AC_SENSITIVE_WORDS` | 空 | 敏感词表，逗号分隔 |
| `AC_MODERATION_URL` | 空 | 外部审核服务地址，不可用时拒绝放行 |
| `AC_MEMORY_EXTRACTION_ENABLED` | `false` | 是否异步抽取记忆 |

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
| 轨迹 | `GET /api/v1/chat/sessions/{id}/runs/{runId}`、`.../events?lastEventId=` |
| 恢复 | `POST /api/v1/chat/sessions/{id}/runs/{runId}/resume` |
| 反馈 | `POST /api/v1/feedback` |
| Agent | `GET/POST /api/v1/admin/agents`、`.../{id}/versions`、`.../{id}/publish` |
| 提示词 | `POST /api/v1/admin/prompts`、`.../{id}/versions`、`.../transition` |
| 工具 | `POST /api/v1/admin/tools`、`POST .../{code}/test` |
| 知识 | `POST /api/v1/admin/knowledge-spaces`、`.../documents`、`.../publish`、`POST /api/v1/knowledge/search` |
| 知识同步 | `POST /api/v1/admin/knowledge-sync-tasks` |
| 记忆/画像 | `GET /api/v1/memory`、`GET /api/v1/profile/summary` |
| 评测 | `POST /api/v1/admin/eval-datasets`、`POST /api/v1/admin/evaluations` |
| 运营 | `GET /api/v1/admin/badcases`、`GET /api/v1/admin/audit-logs`、`GET /api/v1/admin/metrics/overview` |
| 提醒 | `POST /api/v1/notifications`、`POST /api/v1/admin/notifications/dispatch-due` |

### SSE 事件

`run.start`、`thinking`、`tool.call`、`tool.result`、`handoff`、`citation`、`confirmation.required`、`message.delta`、`message.end`、`error`。
事件 id 形如 `run_id:seq`，断线后可用 `/events?lastEventId=run_id:seq` 增量重放。

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
  infrastructure/  数据库与会话
  workers/         后台任务
migrations/        Alembic 迁移
tests/             单元与集成测试
```

## 待确认事项

见 [docs/open-questions.md](docs/open-questions.md)，包含模型来源、认证接口、向量库、Redis 限流与锁、管理前端等问题。
