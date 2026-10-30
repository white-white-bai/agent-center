# 观测栈运行时联调报告

> 日期：2026-10-30
> 环境：本地 Docker，app + Prometheus 2.53 + Tempo 2.5 + Grafana 11.1
> 目标：指标、Trace、看板与 Exemplar 跳转的真实链路验证

## 一、结论

- Prometheus 抓取 `app:8000/metrics` 正常，target **up**
- Tempo 收到 app 的 OTLP Trace，可按 `service.name=agent-center` 查询
- Grafana 自动加载 Prometheus/Tempo 数据源与「Agent Center 总览」看板（10 个面板）
- 指标 Exemplar 已存入 Prometheus，示例：

```json
{"trace_id":"9b454c8c0adfd8f7307b8851e5a80742","value":"0.000917","timestamp":1793340679}
```

- 用该 `trace_id` 查询 Tempo 成功返回 Trace（2 个 batch），说明 **指标 → Trace 跳转链路可用**
- 本地访问：
  - Grafana `http://localhost:3000`（admin/admin）
  - Prometheus `http://localhost:9090`
  - Tempo `http://localhost:3200`

## 二、修复的问题

### 1. Exemplar 未写入 Prometheus

**原因**：Prometheus 默认没有开启 exemplar 存储。

**修复**：observability overlay 的 Prometheus 启动参数增加：

```
--enable-feature=exemplar-storage
```

### 2. HTTP 指标 Exemplar 的 trace_id 丢失

**原因**：在中间件 `finally` 阶段才读取当前 trace_id，内层框架/中间件可能已切换 OTel 上下文。

**修复**：进入 HTTP Span 后立即捕获 `trace_id`，指标上报复用该值。

修复后 `/metrics` 中出现：

```
..._bucket{...} 2.0 # {trace_id="..."} 0.001818 ...
```

## 三、验证命令

```bash
# Prometheus target
curl -s http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[].health'

# Prometheus exemplar
curl -s "http://127.0.0.1:9090/api/v1/query_exemplars?query=agent_center_http_request_duration_seconds_bucket&start=$(date +%s)-300&end=$(date +%s)"

# Tempo trace（替换 trace_id）
curl -s http://127.0.0.1:3200/api/traces/<trace_id>

# Grafana 数据源与看板
curl -u admin:admin http://127.0.0.1:3000/api/datasources
curl -u admin:admin http://127.0.0.1:3000/api/dashboards/uid/agent-center-overview
```

## 四、残余风险

- 本地为单实例 Collector/存储，未验证生产高可用、容量与保留策略。
- Grafana 默认口令仅用于本地，生产需接 SSO/密钥管理。
- Tempo 使用本地文件存储；生产建议对象存储 + 保留策略。
- 告警规则与通知渠道仍需按生产阈值配置并演练。
