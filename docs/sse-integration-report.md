# SSE 长连接与断线续流报告

> 日期：2026-10-30
> 范围：会话级长连接、心跳、Last-Event-ID 续传、租户隔离
> 状态：**代码与自动化验证完成；30 分钟真实网关/前端联调待外部环境**

## 一、结论

| 项目 | 结果 |
| --- | --- |
| 会话级长连接 | 新增 `GET /api/v1/chat/sessions/{id}/stream` |
| 心跳 | 默认 15s，可通过 `heartbeatSeconds` 临时覆盖 |
| 断线续流 | 支持 `lastEventId`（格式 `runId:seq`），不重复已接收事件 |
| 超时控制 | `timeoutSeconds` 可选，便于测试/有界连接 |
| 租户隔离 | 跨租户访问返回 404 |
| 自动化测试 | 心跳、事件续传、无重复、租户隔离全部通过 |
| 30 分钟保持 | **未实测**（需前端/网关环境）；接口支持无限保持 |

## 二、接口说明

```http
GET /api/v1/chat/sessions/{session_id}/stream
    ?lastEventId=run_xxx:3
    &timeoutSeconds=1800
    &heartbeatSeconds=15
    &pollSeconds=1
```

事件：

- `stream.ready`：连接建立
- `run.start` / `message.delta` / `message.end` 等：已落库的 Run 事件
- `heartbeat`：保活事件
- `stream.end`：到达 `timeoutSeconds` 或服务端结束

说明：现有实现中 Run 事件在 Run 结束后落库，因此会话级流用于**长连接保活与断线补偿**；实时 token 流仍使用 `POST /chat/sessions/{id}/messages` 或单 Run 流接口。

## 三、验证

自动化：

```bash
.venv\Scripts\python -m pytest -q tests/integration/test_session_stream.py
```

覆盖：

- 心跳事件出现且连接按超时关闭
- `lastEventId` 之后的事件被续传，`run.start` 不重复
- 事件 id 去重
- 跨租户 404

30 分钟保持可用以下命令在具备前端/网关的环境执行：

```bash
curl -N "http://127.0.0.1:8000/api/v1/chat/sessions/<id>/stream?timeoutSeconds=1800&heartbeatSeconds=15" \
  -H "X-Tenant-Id: t1" -H "X-User-Id: u1"
```

验收要点：

- 30 分钟内无异常断开，心跳持续
- 网关关闭缓冲（`X-Accel-Buffering: no`）、读超时 ≥300s
- 断线后带最后一个事件 id 重连，无丢失、无重复

## 四、残余风险

- 会话级流当前轮询数据库（默认 1s），连接数很高时需改用 Redis Stream/发布订阅或推送服务。
- 事件在 Run 结束后才落库，会话级流不提供实时 token；前端应继续使用消息接口的 SSE。
- 30 分钟保持、代理/负载均衡超时、移动网络切换未在真实环境演练。
- `Last-Event-ID` 指向已清理事件（保留 90 天）时将从最早可用事件开始，需前端容忍。
