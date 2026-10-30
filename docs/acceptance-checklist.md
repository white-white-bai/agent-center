# Agent Center 交付验收清单

> 基线：《智能体中台概要设计 v0.3》《详细设计说明书 V1.0》
> 判定口径：**通过** / **部分通过** / **未通过**；每项必须给出可复现的证据。
> 当前版本：后端主线已完成，328 项自动化测试通过；Docker 本地栈（app + MySQL + Redis + 内嵌 Milvus Lite）已验证。

## 一、总体判定

| 范围 | 结论 | 说明 |
| --- | --- | --- |
| 后端主线（M0–M4） | 部分通过 | 功能完整度约 80%，可支撑单场景试点 |
| 生产上线 | 未通过 | 模型、审核、迁移、压测、前端联调、生产存储形态均未验证 |
| 安全与合规 | 部分通过 | 8 类自动化安全专项全部拦截；外部审核联调与第三方渗透测试待做 |
| 可观测与运维 | 部分通过 | **本地观测栈联动通过**：Prometheus target up、Exemplar→Tempo Trace、Grafana 看板 10 面板；生产高可用与告警演练待做 |

## 二、P0：试点前必须完成

| 编号 | 事项 | 现状 | 交付物 | 验收标准 |
| --- | --- | --- | --- | --- |
| A1 | 真实模型联调 | 仅桩模型 | 联调报告、样例集、`model_usage_log` 截图 | 50 条真实问题中决策 JSON 解析成功率 ≥ 98%；流式首 token 正常；工具调用与降级模型各验证 10 次 |
| A2 | 审核服务联调 | **部分通过**：协议/鉴权/字段映射完成，输入输出各 20 条与失败拒绝自动化通过；真实服务待联调，见 `docs/moderation-integration-report.md` | 审核客户端、联调记录 | 输入/输出各 20 条用例拦截正确；审核服务不可用时按策略拒绝且返回兜底话术，不输出未审内容 |
| A3 | Dify/knowflow 迁移试点 | **部分通过**：Dify 文档/分段导入、chatflow 工具、断点重试与执行接口完成并自动化验证；真实 dataset/30 题评测待做，见 `docs/dify-migration-report.md` | 试点空间、迁移清单、评测集 | 选 1–2 个知识库、50+ 文档；抽样 30 题引用准确率 ≥ 90%；同步失败可重试恢复 |
| A4 | 生产建表与 MySQL 冒烟 | **本地通过**：DDL 41 表、关闭自动建表、CRUD/SSE 冒烟通过；生产 DBA 执行待做，见 `docs/ddl-smoke-report.md` | `docs/schema-mysql.sql` 执行记录 | DBA 执行后表数 41；`AC_AUTO_CREATE_TABLES=false` 启动，CRUD/SSE 冒烟通过 |
| A5 | 前端与 SSE 联调 | **本地通过**：nginx 30 分钟保持 + 主动断线续流（无缺失/重复）+ 网关下游重启重连均通过；生产网关/前端/移动网络待做，见 `docs/a5-sse-gateway-report.md`、`docs/a5-sse-reconnect-report.md` | 联调记录、网关配置 | 单连接保持 ≥ 30 分钟不断；断线用 `lastEventId` 重放无丢事件、无重复；网关缓冲关闭、超时 ≥ 300s |
| A6 | 性能压测 | **部分通过**：2000/200 桩模型 0–0.15% 错误、TTFT P95 6.3–6.6s、E2E P95 9.6–10.7s；真实模型双节点 40/20 零错误、TTFT P95 6.22s、E2E P95 6.25s（样本小、同机模拟），见 `docs/load-test-report.md`、`docs/real-model-multinode-report.md` | 压测方案与报告 | 2000 活跃会话；首 token P95 ≤ 2s、端到端 P95 ≤ 8s（含 1–2 次工具调用）；错误率 < 1%；SSE 重连成功率 ≥ 99% |
| A7 | Redis/Milvus 生产形态 | **本地通过**：2 副本锁/限流验证 + 独立 Milvus 检索与重启持久化；生产集群/对象存储/调优待做，见 `docs/multi-instance-check-report.md`、`docs/milvus-standalone-report.md` | 多实例部署记录 | 2 个 app 副本下会话锁互斥、限流计数共享；独立 Milvus 检索结果与 Lite 一致；重启后数据不丢 |
| A8 | 安全专项测试 | **自动化通过**：8 类用例全部正确拦截，报告见 `docs/security-test-report.md`；外部渗透测试待做 | 安全测试报告 | 跨租户读取、越权工具、伪造确认、重复写操作、敏感信息入记忆、删除后检索、提示词注入绕过 8 类用例全部不通过（即被正确拦截） |

## 三、P1：试点期间补齐

| 编号 | 事项 | 现状 | 验收标准 |
| --- | --- | --- | --- |
| B1 | 话题栈接线 | 逻辑与测试有，运行时未接入 | 用户插话提问后能回到原任务，槽位与已确认事实不丢；连续 3 次插话恢复正确 |
| B2 | Fan-out 接入运行时 | 工具函数有，决策协议未接 | 模型可发起并行只读子任务；部分失败时输出标注缺失信息；子任务不修改会话主状态 |
| B3 | OpenAPI 导入接口 | 仅解析函数 | 上传 spec 后可预览并批量注册工具，重复编码返回冲突 |
| B4 | 凭证自动取用 | 已加密存储，执行器未取用 | HTTP 工具按名称自动注入凭证；日志与响应不出现明文 |
| B5 | 会话查询接口 | 仅按 ID 查询 | 管理端可按租户/用户/状态/时间分页查询，强制租户隔离 |
| B6 | 可观测与告警 | 仅指标汇总 | `/metrics` 暴露核心指标；关键告警（错误率、首 token P95、工具失败率、SSE 断连率）可推送 |
| B7 | 评测完善 | 仅答案相似度 | 新增引用准确率指标；导入 chatflow 基线问题集；提示词/Agent 发布前强制跑评测 |
| B8 | 审计全覆盖 | 覆盖部分管理动作 | 所有管理写操作（含回滚、凭证变更）有审计；支持按动作/资源/时间导出 |
| B9 | SSE 直接续流 | 通过重放接口补发 | 携带 `Last-Event-ID` 直接续流，事件连续且无重复 |
| B10 | 知识版本管理 | 文档固定 v1 | 支持重新入库生成新版本、下架旧版本；检索自动排除失效版本 |
| B11 | 情节/程序记忆 | 仅自动写语义记忆 | 会话结束生成情节记忆；成功任务沉淀程序记忆并可在相似任务复用 |
| B12 | 工具绑定与提示词绑定表 | 表已建但未使用 | 绑定关系可通过管理接口维护，运行时优先使用绑定表 |

## 四、P2：后续迭代

| 编号 | 事项 | 现状 |
| --- | --- | --- |
| C1 | 转人工工作台对接（D10） | 已确认暂不实现，仅返回兜底话术 |
| C2 | 管理后台前端（Vue3） | 已确认本期只交付 API |
| C3 | 灾备 RPO 24h / RTO 4h | **本地增强通过**：AES-256-GCM 加密备份/校验/7 天保留/定时模板完成，加密恢复 38.76s、41 表，错误密钥拒绝；生产定时、异地/对象存储、binlog 待落地，见 `docs/dr-drill-report.md` |
| C4 | Critic 评审 Agent、独立 PlanExecutor | **已完成**：Critic 高风险复核 + 独立 PlanExecutor（只读计划、失败回填、写操作拦截） |
| C5 | 主动推荐质量与摘要长度校准 | **部分通过**：长度/去重/降级校验与离线校准完成；真实样本与模型质量评测待做，见 `docs/c5-calibration-report.md` |
| C6 | MCP stdio / SSE 传输 | **已完成**：HTTP/SSE/stdio 三种传输、`/admin/tools/import-mcp` 导入、执行器接线与审计 |

## 五、试点出口准则

同时满足以下条件才可判定“满足试点需求”：

1. P0 全部通过，且每项有可复现证据。
2. 试点场景一次解决率不低于现有 chatflow 基线（允许低 5 个百分点以内）。
3. 政策类回答引用准确率 ≥ 95%。
4. 首 token P95 ≤ 2s、端到端 P95 ≤ 8s。
5. 一次回滚演练通过：Agent/提示词可回滚到上一发布版本，知识版本可回退。
6. 无 P0 级安全问题：跨租户、越权工具、伪造确认、重复写、敏感信息泄露。

## 六、当前进度（增量）

P1 全部完成：
- B1 话题栈接线：`topic` 决策支持 switch/resume，状态持久化
- B2 Fan-out 接入运行时：并行只读工具、部分失败标注、日志串行落库
- B3 OpenAPI 导入：预览与自动注册，重复编码跳过
- B4 凭证自动取用：按 `credential_map` 解密注入请求头
- B5 会话查询：`GET /admin/sessions`，筛选与分页
- B6 指标与告警：`/admin/metrics/prometheus`、`/admin/alerts/check`、Webhook 推送
- B7 评测与门禁：引用准确率指标、`AC_PUBLISH_REQUIRE_EVAL` 发布门禁
- B8 审计：全部管理写操作留痕
- B9 SSE 续流：`.../runs/{runId}/stream?lastEventId=`
- B10 知识版本：新版本、下架、向量索引同步清理
- B11 情节/程序记忆：每轮情节落库、工具链沉淀程序记忆
- B12 绑定表：创建版本时同步，运行时优先使用绑定表

A1 真实模型联调进展：
- 已配置真实密钥并通过 `GET /admin/model/health` 自检（`ok=true`）
- 已完成单轮真实模型端到端对话：SSE 事件、最终回答、模型用量与 Run 记录均正确
- 50 条决策样本：JSON 解析成功率 **100%**（50/50），满足 ≥98% 验收线
- 明确要求动作的 25 条样本：类型匹配 **96%**（24/25），唯一偏差为 fanout 改为澄清追问
- 流式输出正常（5 个 chunk，内容正确）
- 备用模型已验证：`deepseek/deepseek-v4-flash` 可用（原配置 `deepseek/deepseek-v4.1` 不在模型目录，返回 400，已修正）
- 业务问题端到端抽样（19 组）：路由 100%、引用 100%、关键词 100%、硬错误 0、槽位 2/2；延迟 P50 8.4s / P95 34.6s 未达 ≤8s 目标，详见 `docs/e2e-sample-report.md`
- 待补：用真实 chatflow 问题集替换人工构造样本，补真实业务工具与引用逐条核验

C6 MCP 传输已完成：
- 新增 `app/integrations/mcp/transports.py`：HTTP（含 SSE 响应）、HTTP+SSE、stdio 子进程三种传输
- 新增 `POST /api/v1/admin/tools/import-mcp`：列出远端工具、预览、按前缀批量注册，写操作标记与审计
- MCP 工具已接入 `tool/service._resolve_executor`，调用后自动关闭连接/子进程
- 新增单测（三种传输）与集成测试（导入、重复跳过、执行、非法配置）

OTel Span 已完成：
- `app/core/telemetry.py`：可开关、采样、OTLP/HTTP 导出，未安装依赖或未配 endpoint 时自动降级
- 四层 Span：`http.request` → `agent.run` → `model.complete` / `tool.execute`
- 纯 ASGI 中间件使 HTTP Span 覆盖 SSE 流式响应全过程；Run/Model/Tool Span 共享同一 trace
- 关键属性：租户、run、agent、模型、token、工具状态、HTTP 状态与 `error.code`

PlanExecutor 已完成：
- `plan` 决策：最多 8 步只读工具，顺序执行，单步失败不终止后续步骤
- 未授权/禁用/写工具全部拒绝；写操作必须走 `tool_call` 确认
- 工具结果以不可信观察回填，Run 记录 `PLAN_EXECUTOR`，SSE 输出 `tool.call` / `tool.result`
- 新增决策解析与运行时集成测试

Critic 复核已完成：
- Agent 版本配置 `critic_policy`：`risk/always` 触发、风险词可配、`on_error` 可配
- 复核输出 `pass / revise / reject`，改写替换回答、拒绝返回安全兜底
- 复核携带本次知识片段，禁止片段外政策依据；失败默认放行不阻塞主链路
- 记录 `CRITIC_REVIEW` 步骤、`critic.review` Span，token 计入 Run
- 新增单测与集成测试，覆盖改写、拒绝、低风险跳过、非法输出降级

Prometheus 指标与 Span 联动看板已完成：
- `/metrics` 暴露 OpenMetrics：HTTP QPS/延迟/状态、Run、模型延迟与 Token、Tool 调用
- 指标 Exemplar 携带 `trace_id`，Prometheus 数据源映射到 Tempo，点击 Exemplar 直达 Trace
- HTTP 指标使用完整路由模板，避免 session/run ID 造成标签爆炸
- `docker-compose.observability.yml` 提供 Prometheus + Tempo + Grafana，预置「Agent Center 总览」看板

剩余工作集中在 P0 外部依赖项（审核/Dify/压测/前端/DBA）与 P2（转人工、前端、灾备生产化）。

## 七、当前可用证据

- 自动化测试：`python -m pytest -q` → 328 passed
- 观测栈：Prometheus target up，Exemplar `trace_id` 可在 Tempo 查到 Trace，Grafana 数据源/看板加载，详见 `docs/observability-runtime-report.md`
- 压测：三轮优化后单请求 0.284s→0.153s；2000/200 桩模型 0–0.15% 错误，TTFT P95 6.3–6.6s、E2E P95 9.6–10.7s（单节点仍未达标），详见 `docs/load-test-report.md`
- 真实模型双节点：40/20 零错误、40 次真实调用全成功，TTFT P95 6.22s、E2E P95 6.25s，详见 `docs/real-model-multinode-report.md`
- SSE 断线续流：断开于 seq 2，续流从 seq 3 开始，3 条事件无缺失/重复；网关下游重启后重连成功，详见 `docs/a5-sse-reconnect-report.md`
- 上下文/LangGraph 剖析：检索早退后上下文装配 ~11ms、LangGraph 构图 ~8ms，节点无低风险优化空间，详见 `docs/context-langgraph-profile.md`
- 灾备：加密备份恢复 38.76s、41 表；7 天保留与 cron/计划任务模板；错误密钥拒绝，详见 `docs/dr-drill-report.md`
- 多实例：2 副本并发消息串行化（12.71s≈2×6.4s）、限流共享 200→429、turn 1/2 唯一，详见 `docs/multi-instance-check-report.md`
- 审核：输入/输出各 20 条拦截、不可用拒绝、鉴权与字段映射自动化通过，详见 `docs/moderation-integration-report.md`
- DDL：全新库执行 41 表，`AC_AUTO_CREATE_TABLES=false` 启动并通过 CRUD/SSE 冒烟，详见 `docs/ddl-smoke-report.md`
- SSE：会话级长连接、心跳、Last-Event-ID 续传、租户隔离测试通过，详见 `docs/sse-integration-report.md`
- A5 网关：nginx 30 分钟保持 1800.94s、119 心跳、最大间隔 15.07s、200 无断连，详见 `docs/a5-sse-gateway-report.md`
- Dify：文档/分段分页导入、chatflow 工具、断点幂等、同步执行接口与检索命中自动化通过，详见 `docs/dify-migration-report.md`
- C5：推荐去重/长度校验、摘要截断与离线校准完成，10 个构造用例关键词命中 100%，详见 `docs/c5-calibration-report.md`
- 独立 Milvus：standalone 健康、collection 写入、Lite 对照命中、重启后实体保留，详见 `docs/milvus-standalone-report.md`
- 安全专项：`pytest tests/security` 8 类全部拦截，详见 `docs/security-test-report.md`
- Docker 栈：`docker compose ps` → app/mysql/redis 均 healthy
- 端到端：知识入库 → 发布 → 向量检索返回引用（已实测）
- OTel：临时容器开启 OTLP/HTTP，宿主假 Collector 收到 2 批 Span（约 1.3KB/批）
- 指标：`/metrics` 输出 OpenMetrics，含路由模板与 `trace_id` Exemplar；observability compose 校验通过
- Critic：真实模型冒烟通过，Run 步骤为 `MODEL_RESPONSE → FINAL_RESPONSE → CRITIC_REVIEW(revise)`，回答被改写，用量 771/1086
- 建表：容器内 MySQL `agent_center` 共 41 张表（已实测）
- 设计偏差与待确认项：`docs/open-questions.md`
