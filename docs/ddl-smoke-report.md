# 生产 DDL 冒烟报告

> 日期：2026-10-30
> 环境：MySQL 8（Docker）+ `docs/schema-mysql.sql`
> 目标：A4 生产建表与 MySQL 冒烟

## 一、结论

- 导出的 DDL 在全新库 `agent_center_ddl` 执行成功，共 **41 张表**。
- 以 `AC_AUTO_CREATE_TABLES=false` 启动应用，未依赖 ORM 自动建表。
- Agent 创建/发布、知识空间/文档/发布/检索、会话创建、SSE 对话、Run 轨迹查询均通过。
- 冒烟 Run 状态 `COMPLETED`，2 个步骤，知识检索命中 1 条。
- 本轮为本地 MySQL 8 容器验证；**生产库执行仍需 DBA 按变更流程操作**。

## 二、执行步骤

```bash
# 1. 创建隔离库并授权（本地演练用 root；生产使用 DBA 账号）
docker exec agent-center-mysql mysql -uroot -proot_pass -e "
  DROP DATABASE IF EXISTS agent_center_ddl;
  CREATE DATABASE agent_center_ddl CHARACTER SET utf8mb4;
  GRANT ALL PRIVILEGES ON agent_center_ddl.* TO 'agent'@'%';
  FLUSH PRIVILEGES;
"

# 2. 执行 DDL
docker exec -i agent-center-mysql mysql -uagent -pagent_pass agent_center_ddl < docs/schema-mysql.sql

# 3. 校验表数
docker exec agent-center-mysql mysql -uagent -pagent_pass -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='agent_center_ddl';"

# 4. 启动应用（关闭自动建表）
docker run -d --name ddl-app --network agent-center_default -p 8012:8000 \
  -e AC_DATABASE_URL="mysql+aiomysql://agent:agent_pass@mysql:3306/agent_center_ddl?charset=utf8mb4" \
  -e AC_AUTO_CREATE_TABLES=false -e AC_REDIS_URL=redis://redis:6379/0 \
  -e AC_MODEL_PROVIDER=stub -e AC_LLM_API_KEY= agent-center-app:latest

# 5. CRUD/SSE 冒烟
python scripts/ddl_smoke.py --base-url http://127.0.0.1:8012
```

## 三、冒烟结果

| 项目 | 结果 |
| --- | --- |
| DDL 表数 | 41 |
| 自动建表 | 关闭 |
| Agent 创建/发布 | 通过 |
| 知识空间/文档/发布/检索 | 通过，命中 1 条 |
| SSE 对话 | `finish=completed` |
| Run 状态 | `COMPLETED`，2 个步骤 |
| 表数量漂移 | 无（应用未隐式建表） |

## 四、生产待办

1. DBA 审核 DDL（索引、字符集、时区、账号权限）并在预发/生产执行。
2. 生产设置 `AC_AUTO_CREATE_TABLES=false`，禁止应用自动建表。
3. 建立 Alembic/变更单基线与回滚脚本；当前 `migrations/` 仅作版本管理，生产以 DDL 为准。
4. 在生产规格 MySQL 上复跑本冒烟与压测，确认连接数、慢查询与磁盘容量。
5. 备份/恢复演练需覆盖生产库（见 `docs/dr-drill-report.md`）。

## 五、说明

`docs/schema-mysql.sql` 由 `scripts/export_ddl.py` 生成；本轮未修改 DDL 内容，仅验证其可执行性与应用兼容性。
