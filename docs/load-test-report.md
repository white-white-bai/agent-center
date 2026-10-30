# 并发压测报告

> 日期：2026-10-30
> 环境：Windows + Docker Desktop，12 vCPU / 15.6GB；app + MySQL 8 + Redis，本地单节点
> 模型：桩模型（`AC_MODEL_PROVIDER=stub`），压测结果**不包含真实模型推理时间**
> 脚本：`scripts/load_test.py`，压测端运行在容器网络内，避免 Windows 端口转发干扰

## 一、结论

- **2000 会话、200 并发**：最终 6 worker 配置下 **2000/2000 成功，错误率 0%**，满足 `< 1%` 要求。
- **延迟未达标**：TTFT P95 **8.48s**（目标 ≤2s），端到端 P95 **12.78s**（目标 ≤8s）。
- 单请求基线仅 232ms，说明压力下瓶颈在**单节点 CPU / 事务与运行时开销**，不是网络或连接池单点。
- 8 worker 相比 6 worker 无吞吐提升；8 worker 与多实例并存时曾因 MySQL `max_connections=151` 被打满出现 3.4% 错误，清理连接后恢复。
- 建议生产按 4–6 worker/节点横向扩展，并结合真实模型/生产磁盘重新压测。

## 二、关键结果

| 配置 | 会话/并发 | 成功 | 错误率 | 吞吐 | TTFT P95 | E2E P95 |
| --- | --- | --- | --- | --- | --- | --- |
| 单请求基线 | 1/1 | 1 | 0% | 4.3/s | 169ms | 232ms |
| 1 worker + 默认池 | 2000/200 | 1999 | 0.05% | 15.0/s | 17.55s | 22.49s |
| 1 worker + 池 20/40 | 2000/200 | 2000 | 0% | 16.2/s | 16.41s | 22.31s |
| 4 worker + 池 5/10 | 2000/200 | 1999 | 0.05% | 32.1/s | 10.33s | 13.84s |
| 6 worker + 池 5/10（1000 会话） | 1000/200 | 1000 | 0% | 36.5/s | 6.19s | 10.21s |
| **6 worker + 池 5/10（最终）** | **2000/200** | **2000** | **0%** | **36.0/s** | **8.48s** | **12.78s** |
| 8 worker + 池 3/6 | 1000/200 | 1000 | 0% | 32.0/s | 7.40s | 11.57s |

## 三、容量发现

1. **单进程并发不足**：1 worker 时吞吐约 15–16/s，TTFT P95 16–18s。
2. **4–6 worker 明显改善**：6 worker 吞吐 36/s，TTFT P95 从 16.4s 降到 8.5s。
3. **8 worker 无增益**：吞吐回落，CPU/上下文切换与 DB 争用抵消收益。
4. **连接数必须规划**：4 worker×30 + 其他实例曾打满 MySQL `max_connections=151`，直接表现为 31% 错误；生产需按副本数×池大小预留连接，并设置上限告警。
5. **MySQL fsync 不是主因**：临时将 `innodb_flush_log_at_trx_commit=2` 未显著改善，已恢复为 1。

## 四、建议

- 生产按 4–6 worker/节点部署，节点数按目标 QPS 线性扩展；多 worker 时设置 `AC_AUTO_CREATE_TABLES=false`。
- 按 `副本数 × (AC_DB_POOL_SIZE + AC_DB_MAX_OVERFLOW) < MySQL max_connections × 0.8` 规划连接。
- 下一步优先做运行时 CPU 剖析：LangGraph 节点、上下文装配、逐步骤提交；考虑合并 RunStep/消息写入事务。
- 真实模型压测需单独进行：模型延迟会主导 TTFT，当前真实模型单轮 P50 约 8s，需 fast 模型或流式首 token 优化。
- 生产压测应使用独立压测客户端与生产同规格 MySQL/网络，不以本机 Docker Desktop 结果作为最终容量结论。

## 五、事务合并优化后复测

单请求剖析发现 SQLAlchemy commit 占主要开销（单请求约 15 次事务提交）。已做低风险合并：

- turn/user/run 一次提交（原 3 次）
- assistant 消息 flush 后一次提交（原 2 次）
- RunStep 改为 flush，由后续 checkpoint/finish 统一提交
- turn 结束与 SSE 事件落库合并为一次提交

效果：

| 指标 | 优化前（单请求剖析） | 优化后 |
| --- | --- | --- |
| 单请求耗时 | 0.284s | **0.200s** |
| Session commit 次数 | 15 | **9** |
| commit 累计耗时 | 0.155s | **0.079s** |

2000 会话/200 并发（6 worker、连接池 5/10、MySQL max_connections=400）复测：

| 指标 | 优化前 | 优化后 |
| --- | --- | --- |
| 成功 | 2000/2000 | 1997/2000 |
| 错误率 | 0% | **0.15%**（<1%） |
| 吞吐 | 36.0/s | 33.6/s |
| TTFT P95 | 8.48s | **6.89s** |
| E2E P95 | 12.78s | **10.48s** |

延迟仍高于目标（TTFT ≤2s、E2E ≤8s），但分别改善约 19% / 18%；剩余瓶颈仍是单节点 CPU 与 LangGraph/上下文装配开销，需继续剖析或横向扩容。

> 说明：RunStep 改为 flush 后，依赖后续 checkpoint 或 finish 提交；若进程在这之间崩溃，最后一条步骤记录可能丢失，但 Run 状态与 checkpoint 仍可恢复。

## 六、第二轮事务合并（记忆/引用）

在首轮基础上，将情节记忆、程序记忆与引用落库改为 `flush`，由本轮最终 `turn` 提交统一持久化：

- Session commit 次数 9 → **8**
- 单请求剖析在 0.20–0.35s 间波动，收益小于首轮，主要受本地 MySQL 延迟影响
- 回归测试全量通过（322 项）

## 七、复现

```bash
# 启动桩模型实例（示例）
docker run -d --name load-app --network agent-center_default -p 8001:8000 \
  -e AC_DATABASE_URL="mysql+aiomysql://agent:agent_pass@mysql:3306/agent_center?charset=utf8mb4" \
  -e AC_AUTO_CREATE_TABLES=false \
  -e AC_DB_POOL_SIZE=5 -e AC_DB_MAX_OVERFLOW=10 \
  -e AC_REDIS_URL=redis://redis:6379/0 \
  -e AC_MODEL_PROVIDER=stub -e AC_LLM_API_KEY= -e AC_OTEL_ENABLED=false \
  -e WEB_CONCURRENCY=6 agent-center-app:latest

docker cp scripts/load_test.py load-app:/tmp/load_test.py
docker exec load-app python /tmp/load_test.py \
  --base-url http://127.0.0.1:8000 --sessions 2000 --concurrency 200
```
