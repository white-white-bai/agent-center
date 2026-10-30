# 灾备演练报告

> 日期：2026-10-30
> 环境：本地 Docker 栈（MySQL 8 + Redis 7 + Milvus Lite），单节点
> 脚本：`scripts/dr_backup.py`、`scripts/dr_restore.py`、`app/core/backup_crypto.py`
> 目标（D12）：RPO 24h / RTO 4h

## 一、演练结论

- **MySQL 全量备份与恢复通过**：41 张表、34.6MB dump，恢复到独立库耗时 **19.81s**
- **业务可读性通过**：用恢复库启动临时 app，成功读取哨兵会话 `16523`
- **Redis RDB 恢复通过**：`redis-check-rdb` Checksum OK，恢复后 **16385 keys**
- **Milvus Lite 文件已纳入备份**（160KB），未做独立向量库恢复演练
- 明文路径本地端到端 RTO 约 **26s**（恢复 19.8s + 临时 app 启动约 6s）；加密路径仅恢复 38.76s，加启动约 45s，仍远低于 4h 目标
- **加密备份与恢复通过**：AES-256-GCM + scrypt，加密后恢复 41 表耗时 **38.76s**；错误密钥被拒绝
- 已提供 **7 天保留策略**、Linux cron 与 Windows 计划任务模板
- 仍待生产落地：**每日定时实际执行、异地/对象存储、binlog 时间点恢复**

## 二、演练步骤与证据

| 步骤 | 结果 |
| --- | --- |
| 创建哨兵会话 | tenant `dr_drill_20261030131819`，session `16523` |
| MySQL 全量备份 | `mysql_20261030T051824Z.sql`，34,618,556 bytes，sha256 记录在 manifest |
| Redis 备份 | `redis_20261030T051824Z.rdb`，8,767,395 bytes，`redis-check-rdb` 通过 |
| Milvus Lite 备份 | `milvus_20261030T051824Z.db`，163,840 bytes |
| 恢复 MySQL | 独立库 `agent_center_drill`，19.81s，41 张表 |
| 恢复后读取 | 临时 app 返回 session `16523`，`status=ACTIVE` |
| 恢复 Redis | 临时实例 DBSIZE=16385，日志 `keys loaded: 16385` |
| 清理 | 停止临时容器，删除演练库；业务库未改动 |

## 三、脚本用法

```bash
# 备份：MySQL + Redis RDB + Milvus Lite，生成 manifest 与 sha256
python scripts/dr_backup.py --output backups

# 恢复到独立演练库（禁止覆盖 agent_center）
python scripts/dr_restore.py \
  --backup backups/mysql_20261030T051824Z.sql \
  --target-db agent_center_drill --drop-existing
```

说明：`dr_restore.py` 默认使用本地 compose 的 root 账号；生产应改用专用备份/恢复账号，并限制目标库前缀。备份目录 `backups/` 已加入 `.gitignore` 与 `.dockerignore`。

## 四、生产落地差距

1. **备份调度与保留**：已提供每日 cron/计划任务模板、7 天保留与加密；生产仍需实际部署、监控失败告警，并配合 binlog 做时间点恢复。
2. **异地/对象存储**：当前备份与业务同机；加密已完成，仍需上传到独立存储并定期校验可恢复性。
3. **Redis 定位**：Redis 主要承载锁、限流与事件流，业务真相在 MySQL；若要求事件流不丢，需 AOF + 独立恢复演练。
4. **Milvus**：Lite 文件已备份；独立 Milvus 需按官方备份方案验证 collection 级恢复。
5. **RTO 组成**：本轮未计算机房/存储/镜像拉取/域名切换时间；4h 目标需在真实环境演练。
6. **安全**：备份包含业务数据，需访问控制、加密与审计；恢复账号不应使用 root。

## 五、加密与定时备份（本轮新增）

### 加密

- `AC_BACKUP_KEY` 或 `--key-file` 提供口令；scrypt 派生 32 字节密钥，AES-256-GCM 加密。
- 加密后删除明文，文件后缀 `.enc`；manifest 记录加密文件 sha256 与 `encrypted=true`。
- 恢复时支持 `--manifest` 先校验 sha256，再解密到临时文件，恢复完成后删除临时文件。
- 错误密钥或篡改文件会在解密阶段失败，不会触碰目标库。
- `--require-encryption` 可强制生产备份必须加密。

### 保留与调度

- `--retention-days 7`：按 manifest 的 `createdAt` 清理过期备份及其 artifact。
- Linux：`deploy/backup/agent-center-backup.cron`
- Windows：`deploy/backup/agent-center-backup.ps1` + `schtasks`
- 说明：`deploy/backup/README.md`

### 本轮加密演练结果

| 项目 | 结果 |
| --- | --- |
| MySQL 加密备份 | `mysql_...sql.enc`，60,347,091 bytes |
| Redis 加密备份 | `redis_...rdb.enc`，14,162,190 bytes，Checksum OK |
| Milvus Lite 加密备份 | `milvus_...db.enc`，167,985 bytes |
| 加密恢复 | 38.76s，41 张表 |
| 错误密钥 | 拒绝，未创建演练库 |
| 保留策略 | 单元测试通过（过期 manifest/artifact 删除，当前备份保留） |

## 六、复现注意事项

- 恢复前确认目标库不存在或显式 `--drop-existing`；脚本拒绝覆盖 `agent_center`。
- `docker exec` 恢复必须带 `-i`，否则 stdin 被忽略会得到空库（本轮已修正）。
- 演练完成后删除临时容器与演练库，避免占用连接与磁盘。
