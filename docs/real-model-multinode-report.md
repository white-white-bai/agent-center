# 真实模型双节点复测报告

> 日期：2026-10-30
> 环境：2 个 app 副本（各 2 worker）+ 共享 MySQL/Redis，同机 Docker 模拟多节点
> 模型：`deepseek/deepseek-v4.1-flash`（真实 API，备用 `deepseek/deepseek-v4-flash`）
> 压测端：宿主机脚本，按会话轮询两个节点

## 一、结果

| 指标 | 结果 |
| --- | --- |
| 会话 / 并发 | 40 / 20 |
| 成功 | **40/40** |
| 错误率 | **0%** |
| 吞吐 | 3.57 req/s |
| TTFT P50 / P95 / P99 | 3.39s / **6.22s** / 7.10s |
| E2E P50 / P95 / P99 | 3.52s / **6.25s** / 7.13s |
| 模型调用 | 40 次 SUCCESS，0 失败/降级 |
| 模型平均延迟 | 3.28s |
| Run 状态 | 19 COMPLETED，21 WAITING_USER |

说明：压测消息为通用“压测消息”，真实模型有 21 次选择澄清追问，因此 E2E 偏短；这不影响调用成功率与延迟统计，但样本不代表真实业务分布。

## 二、环境

- 两个节点使用同一镜像、同一 MySQL/Redis，`WEB_CONCURRENCY=2`，连接池 5/10。
- 客户端按会话轮询节点，没有真实负载均衡/网关。
- 模型健康检查：`ok=true`，单次 2.3s。
- `model_usage_log`：40 条 `deepseek/deepseek-v4.1-flash SUCCESS`，平均 3280ms。

## 三、结论

- 双节点 + 真实模型下 0 错误、0 降级，SSE/锁/DB 链路正常。
- 本次样本 E2E P95 6.25s（低于 8s 目标），但 TTFT P95 6.22s 仍高于 2s。
- 真实模型单次延迟约 3.3s，是 TTFT 的主要组成部分；要满足 2s 首 token，需要更快模型/流式首 token 或更小请求负载。
- 40 会话样本较小、同机模拟，不能作为生产容量结论；生产需真实 LB、多机、独立压测端与更大样本。

## 四、复现

```bash
# 两个真实模型节点（key 由 .env 提供）
docker run -d --name real-a --network agent-center_default -p 8020:8000 \
  --env-file .env \
  -e AC_DATABASE_URL="mysql+aiomysql://agent:agent_pass@mysql:3306/agent_center?charset=utf8mb4" \
  -e AC_AUTO_CREATE_TABLES=false -e AC_REDIS_URL=redis://redis:6379/0 \
  -e AC_OTEL_ENABLED=false -e WEB_CONCURRENCY=2 agent-center-app:latest
# real-b 同上，端口 8021

python scripts/load_test.py \
  --base-urls http://127.0.0.1:8020,http://127.0.0.1:8021 \
  --sessions 40 --concurrency 20 \
  --primary-model deepseek/deepseek-v4.1-flash \
  --fallback-model deepseek/deepseek-v4-flash
```
