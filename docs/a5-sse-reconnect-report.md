# A5 SSE 断线续流与网关重启演练

> 日期：2026-10-30
> 网关：本地 nginx 1.27（`deploy/gateway/nginx-sse.conf`）
> 上游：Agent Center app（真实模型）
> 目标：断线后 `Last-Event-ID` 续流无缺失、无重复；网关下游重启后可重连

## 一、结果

| 检查项 | 结果 |
| --- | --- |
| 基线事件数 | 5 |
| 事件 ID 唯一 | 通过 |
| 首连读取 2 个事件后主动断开 | 通过 |
| 断开位置 | `run_...:2` |
| 续流事件数 | 3 |
| 续流首条 | `run_...:3` |
| 缺失 | 无 |
| 重复 | 无 |
| 网关下游重启 | 通过 |
| 重启后上游健康 | 通过 |
| 重启后 SSE 重连 | 通过 |

## 二、演练方式

1. 创建会话并完成一轮真实模型对话，取得完整事件基线。
2. 通过 nginx 打开单 Run 事件流，读完 2 个事件后主动关闭连接。
3. 携带 `lastEventId=run_...:2` 重新连接，读取剩余事件，与基线逐条比对。
4. 通过 nginx 打开会话级事件流；执行 `docker restart agent-center-app`。
5. 等待上游恢复后重新连接，收到 `stream.ready`。

脚本：

```bash
python scripts/sse_reconnect_test.py \
  --app-url http://127.0.0.1:8000 \
  --gateway-url http://127.0.0.1:8080 \
  --restart-container agent-center-app \
  --output sse_reconnect_result.json
```

## 三、结论与残余风险

- 本地已覆盖：**主动断线续流、事件不丢不重、网关下游重启后重连**。
- 尚未覆盖：真实生产 API Gateway/LB、移动网络切换、长连接粘性、前端实际重连逻辑。
- 会话级流仍按 DB 轮询；大规模长连接需改为 Redis Stream/推送。
