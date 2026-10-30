# A5 SSE 网关 30 分钟测试报告

> 日期：2026-10-30
> 网关：nginx 1.27-alpine（本地真实反向代理，非生产网关）
> 上游：Agent Center 会话级 SSE `/api/v1/chat/sessions/{id}/stream`
> 目标：A5 单连接保持 ≥30 分钟、心跳、缓冲关闭、读超时 ≥300s

## 一、结论

| 指标 | 结果 |
| --- | --- |
| 目标时长 | 1800s |
| 实际连接时长 | **1800.94s** |
| 心跳数 | **119** |
| 首次心跳 | 15.16s |
| 最后一次心跳 | 1791.91s |
| 最大心跳间隔 | **15.07s** |
| `stream.ready` | 收到 |
| `stream.end` | 收到 |
| 错误 | 无 |
| nginx 访问日志 | `GET .../stream?timeoutSeconds=1800...` **200**，11689 bytes |
| 30 秒烟测 | 5 次心跳、间隔 5.03s、正常结束 |

心跳按时到达且间隔稳定，说明 nginx **未缓冲** SSE；1800s 内无断连，满足单连接 ≥30 分钟要求。

## 二、网关配置

`deploy/gateway/nginx-sse.conf`：

```nginx
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_buffering off;
proxy_cache off;
proxy_request_buffering off;
proxy_read_timeout 1900s;
proxy_send_timeout 1900s;
chunked_transfer_encoding on;
```

启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml \
  --profile gateway up -d gateway
```

## 三、复现

```bash
# 准备会话（省略，见脚本参数）
python scripts/sse_gateway_hold.py \
  --url http://127.0.0.1:8080 \
  --session-id <id> --tenant <tenant> \
  --seconds 1800 --heartbeat 15 \
  --output sse_30min_result.json
```

## 四、说明与残余风险

- 本轮为本地 nginx，不是生产 API Gateway/LB；生产网关仍需按同样参数（关闭缓冲、读超时 ≥300s、HTTP/1.1）配置并复测。
- 断线 `Last-Event-ID` 续传已由 `tests/integration/test_session_stream.py` 与单 Run 续流测试覆盖；本轮未在 30 分钟内注入网络断开。
- 未测试移动网络切换、网关滚动重启、多副本负载均衡下的长连接粘性。
- 会话级流当前轮询数据库，长连接数量很大时需改为 Redis Stream/推送。
