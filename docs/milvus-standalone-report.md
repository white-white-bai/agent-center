# 独立 Milvus 验证报告

> 日期：2026-10-30
> 环境：Milvus 2.4.15 standalone + etcd 3.5.5 + LocalStack S3（MinIO 镜像被仓库拒绝）
> 目标：A7 独立 Milvus 检索一致性与重启持久化

## 一、结论

| 项目 | 结果 |
| --- | --- |
| Milvus 健康检查 | `9091/healthz` 返回 OK |
| Collection | `agent_center_knowledge` 创建成功 |
| 写入实体 | 应用知识入库后 collection entities > 0（重启前 2，重启后 4） |
| 应用检索 | 同一文档/查询返回 1 条命中 |
| Lite 对照 | 同文档/查询同样返回 1 条命中 |
| 重启持久化 | 重启 Milvus 后 collection 与实体仍存在 |
| 2 副本会话锁/限流 | 已在 `docs/multi-instance-check-report.md` 验证 |

## 二、发现并修复的问题

**现象**：app 比 Milvus 先启动时，`get_vector_store()` 捕获连接异常后缓存 `InMemoryVectorStore`，即使 Milvus 随后就绪也永久不再连接，表现为“检索有结果但 Milvus collection 为空”。

**修复**（`app/infrastructure/vector/store.py`）：

- 记录降级状态；Milvus 配置存在时每 30s 重试一次连接
- 降级时输出 warning，便于发现
- 新增回归测试：首次失败降级、到间隔后重试成功

## 三、复现步骤（本地）

MinIO 镜像 `minio/minio` 在当前网络被仓库拒绝，使用 LocalStack S3 替代：

```bash
# 1. S3（LocalStack）
docker run -d --name milvus-localstack --network agent-center_default \
  -p 4566:4566 -e SERVICES=s3 localstack/localstack:3.5.0
docker exec milvus-localstack awslocal s3 mb s3://a-bucket

# 2. etcd
docker run -d --name milvus-etcd --network agent-center_default \
  -p 2379:2379 quay.io/coreos/etcd:v3.5.5 \
  etcd -advertise-client-urls=http://0.0.0.0:2379 \
  -listen-client-urls=http://0.0.0.0:2379 --data-dir=/etcd

# 3. Milvus
docker run -d --name milvus-standalone --network agent-center_default \
  -p 19530:19530 -p 9091:9091 --security-opt seccomp=unconfined \
  -e ETCD_ENDPOINTS=milvus-etcd:2379 \
  -e MINIO_ADDRESS=milvus-localstack:4566 \
  -e MINIO_ACCESS_KEY_ID=test -e MINIO_SECRET_ACCESS_KEY=test \
  -e MINIO_USE_SSL=false milvusdb/milvus:v2.4.15 milvus run standalone

# 4. app 指向独立 Milvus
docker run -d --name milvus-app --network agent-center_default -p 8015:8000 \
  -e AC_DATABASE_URL="mysql+aiomysql://agent:agent_pass@mysql:3306/agent_center?charset=utf8mb4" \
  -e AC_AUTO_CREATE_TABLES=false -e AC_REDIS_URL=redis://redis:6379/0 \
  -e AC_MILVUS_URI=http://milvus-standalone:19530 \
  -e AC_MODEL_PROVIDER=stub -e AC_LLM_API_KEY= agent-center-app:latest

python scripts/ddl_smoke.py --base-url http://127.0.0.1:8015
```

## 四、残余风险

1. LocalStack 仅用于本地验证，不是生产对象存储；生产需正式 S3/MinIO、持久卷、备份与高可用。
2. Milvus 当前为单节点 standalone，未验证集群、副本、扩缩容与故障切换。
3. 未做大规模向量写入/检索性能与索引参数调优。
4. 未验证 Milvus collection 级备份恢复，需要纳入灾备演练。
5. `docker-compose.yml` 的 `milvus` profile 仍使用 MinIO 镜像；在镜像不可用的环境请使用本报告的 LocalStack 方式或预置 MinIO。
