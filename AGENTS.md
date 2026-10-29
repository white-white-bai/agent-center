# AGENTS.md

本文件面向在本仓库工作的编码代理与开发者，说明约定、命令与易错点。

## 项目概览

政务智能体中台（Agent Center）后端：Python 3.11 + FastAPI + SQLAlchemy（异步）+ LangGraph。
模块化单体，管理 API 与运行 API 同进程；外部依赖为 MySQL、Redis、Milvus、LLM 网关。

## 常用命令

```bash
# 安装（开发）
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"      # Windows
# source .venv/bin/activate && pip install -e ".[dev]" # Linux/macOS

# 测试
.venv\Scripts\python -m pytest -q

# 本地启动
.venv\Scripts\python -m uvicorn app.main:app --reload

# Docker 一键启动
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
./scripts/start.sh

# 生成 MySQL DDL
.venv\Scripts\python scripts/export_ddl.py
```

## 目录约定

- `app/api/v1/`：路由层，只做参数校验、依赖注入、调用服务
- `app/domain/<模块>/`：领域模型 + 服务；业务逻辑放这里
- `app/runtime/`：LangGraph 执行器、路由、交接、上下文、锁与熔断
- `app/integrations/`：LLM（OpenAI 兼容/LiteLLM）、MCP、HTTP 工具、OpenAPI
- `app/infrastructure/`：数据库、Redis 后端、向量存储
- `app/workers/`：记忆抽取、轨迹清理等后台任务

## 编码约定

- 服务函数显式接收 `ctx: TenantContext`；查询必须带 `tenant_id`。ORM 级租户守卫已启用，统计类查询才允许 `skip_tenant_guard`。
- 外部依赖（画像、记忆、知识、审核、摘要）失败时必须降级，不得阻塞对话主链路。
- 业务错误抛 `AppError` 子类；成功响应统一走 `app.core.responses.ok`。
- 模型决策统一 JSON：`final / tool_call / clarify / slots / handoff`，解析入口 `runtime/decisions.py`。
- SSE 事件统一通过 `emit()` 产生递增 `seq`，同时写 `run_event` 与 Redis Stream。
- 写操作工具必须走确认流程；业务写接口需透传 `Idempotency-Key`。
- 新增数据表：模型 + `infrastructure/database/registry.py` + `tests/unit/test_models_registry.py` + 重新生成 DDL。

## 测试约定

- 使用内存 SQLite；`tests/conftest.py` 提供 `db_session`、`client`、`async_client`。
- 模型相关测试用 `ScriptedLLMClient` 或覆写 `get_model_router`，不要真实调用外部模型。
- SSE 测试用 `async_client` 并解析 `run_id:seq` 事件流。
- 新增行为至少覆盖：正常路径、租户隔离、失败降级。

## 易错点

- Windows PowerShell 5.1 不支持 `&&`、bash heredoc；写文件使用 UTF-8（无 BOM）。
- 宿主 3306/6379 常被本机服务占用；Docker 映射为 3307/6380。
- `.env`、`*.db`、`.venv/`、`.commandcode/` 不提交。
- 未配置 `AC_LLM_API_KEY` 时自动使用桩模型，接口仍可用但回答固定。
- 依赖 `pymilvus` 在 Linux 会附带 `milvus-lite`；Windows 本地用内存向量降级。
