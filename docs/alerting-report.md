# 告警规则与 Alertmanager 联调报告

> 日期：2026-10-30
> 环境：Prometheus 2.53 + Alertmanager 0.27 + Agent Center 本地栈
> 目标：核心指标告警规则可加载、可触发、可进入 Alertmanager

## 一、结论

- Prometheus 已加载 **9 条** `agent-center` 规则，全部 `health=ok`
- Alertmanager 已接入 Prometheus，`activeAlertmanagers` 指向 `alertmanager:9093`
- 实测停止 app 后，`AgentCenterDown` 从 `pending` 进入 **firing**，Alertmanager 中为 **active**
- 新增首 token 指标 `agent_center_first_token_duration_seconds`
- 新增 SSE 连接指标：
  - `agent_center_sse_connections_total{stream,result}`
  - `agent_center_sse_connections_active{stream}`
- 主动断开一次会话 SSE，`result="disconnected"` 计数 +1

## 二、告警规则

| 告警 | 条件 | 级别 |
| --- | --- | --- |
| `AgentCenterDown` | `up{job="agent-center"} == 0`，1m | critical |
| `AgentCenterHttp5xxHigh` | 5xx 比例 > 1%，5m | critical |
| `AgentCenterRunFailureHigh` | Run 失败率 > 5%，5m | critical |
| `AgentCenterToolFailureHigh` | 工具失败率 > 10%，5m | warning |
| `AgentCenterModelFailureHigh` | 模型失败率 > 5%，5m | critical |
| `AgentCenterFirstTokenP95High` | 首 token P95 > 2s，5m | warning |
| `AgentCenterRunP95High` | 端到端 P95 > 8s，5m | warning |
| `AgentCenterSseDisconnectRateHigh` | SSE 断连率 > 5%，5m | warning |
| `AgentCenterNoTraffic` | 15m 无 HTTP 流量 | warning |

规则文件：`deploy/observability/alerts.yml`
Alertmanager：`deploy/observability/alertmanager.yml`

## 三、验证记录

```text
promtool check rules: SUCCESS: 9 rules found
amtool check-config: SUCCESS, 1 receiver
/api/v1/rules: 9 rules, health=ok
/api/v1/alertmanagers: http://alertmanager:9093/api/v2/alerts
```

触发演练：

1. 停止 `agent-center-app`。
2. 等待规则 `for: 1m` 生效。
3. Prometheus `AgentCenterDown` 状态为 `firing`。
4. Alertmanager `/api/v2/alerts` 中状态为 `active`。
5. 重启 app，`/healthz` 恢复 ok。

SSE 断连验证：

```text
agent_center_sse_connections_total{stream="session",result="disconnected"} 1
```

首 token 验证：

```text
agent_center_first_token_duration_seconds_count 1
```

## 四、生产接入

- 本地 `alertmanager.yml` 使用空接收器，仅验证规则与转发表；生产需增加企业微信/钉钉/邮件/PagerDuty 等 receiver，并配置值班路由。
- 业务侧告警仍由 `/api/v1/admin/alerts/check` + `AC_ALERT_WEBHOOK_URL` 负责（工具成功率、Run 失败率、badcase、模型成功率）。
- 阈值当前按验收目标设置；上线前需结合真实流量基线调整，并配置静默/抑制规则。
- Alertmanager 配置中的 webhook 不应写入真实密钥；使用环境变量/密钥管理注入。
