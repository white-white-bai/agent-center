# 多实例一致性检查报告

> 日期：2026-10-30
> 环境：2 个 app 副本（8010/8011）+ 共享 MySQL 8 + 共享 Redis 7，桩模型
> 脚本：`scripts/multi_instance_check.py`、`scripts/mock_moderation.py`
> 目标：A7 多副本下的会话锁互斥、限流计数共享

## 一、结论

| 检查项 | 结果 |
| --- | --- |
| 跨实例读取会话 | 通过（实例 A 创建，实例 B 读取 200） |
| Redis 限流共享 | 通过（A 第 1 次 200，B 第 2 次 429） |
| 同会话并发消息 | 通过：两个 Run 均完成，耗时 12.71s，单请求约 6.4s，**串行化成立** |
| 会话 Turn 唯一性 | 通过：`turn_no = 1,2`，无重复 |
| 独立 Milvus | 未验证（本轮仍是各副本本地 Milvus Lite） |

## 二、发现并修复的并发 bug

**现象**：首次测试时两个副本同时处理同一会话，均计算出 `turn_no=1`，其中一个实例触发唯一键冲突：

```
Duplicate entry '16524-1' for key 'conversation_turn.uk_turn_conversation_no'
```

**根因**：请求进入流式处理前，路由阶段已经在 SQLAlchemy Session 中开启了读事务。MySQL 默认 REPEATABLE READ 下，即使 Redis 分布式锁把两个请求串行化，第二个请求拿到锁后仍使用**等锁前的旧快照**，看不到第一个请求已提交的 turn，于是再次写入 turn 1。

**修复**（`app/domain/session/chat_service.py`）：

- 等锁前 `await session.commit()`，结束路由阶段读事务；
- 拿到锁后 `await session.refresh(conversation)`，读取其他副本已提交的最新会话状态；
- 修复后并发检查：2 个 turn（1、2），2 个 Run，均 completed。

## 三、复现方式

```bash
# 1. 启动带延迟的模拟审核，制造锁持有窗口
python scripts/mock_moderation.py --port 8090 --delay 3

# 2. 启动两个 app 副本（共享 MySQL/Redis，审核指向宿主机）
docker run -d --name mi-a --network agent-center_default \
  --add-host=host.docker.internal:host-gateway -p 8010:8000 \
  -e AC_DATABASE_URL="mysql+aiomysql://agent:agent_pass@mysql:3306/agent_center?charset=utf8mb4" \
  -e AC_AUTO_CREATE_TABLES=false -e AC_DB_POOL_SIZE=5 -e AC_DB_MAX_OVERFLOW=10 \
  -e AC_REDIS_URL=redis://redis:6379/0 -e AC_MODEL_PROVIDER=stub -e AC_LLM_API_KEY= \
  -e AC_MODERATION_URL=http://host.docker.internal:8090/moderate \
  -e AC_MODERATION_TIMEOUT_MS=10000 agent-center-app:latest
# mi-b 同上，端口 8011

python scripts/multi_instance_check.py --base-a http://127.0.0.1:8010 --base-b http://127.0.0.1:8011
```

## 四、残余风险

- 本轮未部署独立 Milvus，无法验证多副本向量检索一致性；当前每个副本使用本地 Milvus Lite，只适合单实例或共享外部 Milvus。
- 会话锁 TTL 60s；若单次 Run 超过 TTL，需要续租/fencing token，当前未实现。
- 限流窗口依赖 Redis 可用；Redis 故障时降级为进程内计数，不跨实例。
- 多副本时钟、网络分区与 Redis 主从切换未演练。
