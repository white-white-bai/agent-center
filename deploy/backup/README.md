# 备份定时与恢复

## 密钥

- 使用 `AC_BACKUP_KEY` 或 `--key-file` 提供口令；脚本用 scrypt 派生密钥、AES-256-GCM 加密。
- 密钥文件权限建议 `0400`，不要与备份存放在同一目录。
- 未提供密钥且传了 `--require-encryption` 时，备份直接失败，不会落明文。

## Linux cron

```bash
sudo install -m 0400 /dev/null /etc/agent-center/backup.key
# 写入密钥后：
sudo cp deploy/backup/agent-center-backup.cron /etc/cron.d/agent-center-backup
```

## Windows 计划任务

```powershell
schtasks /Create /TN "AgentCenterBackup" /SC DAILY /ST 02:00 ^
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File E:\agent-center\deploy\backup\agent-center-backup.ps1 -KeyFile C:\secure\agent-center-backup.key"
```

## 恢复

```bash
AC_BACKUP_KEY=... python scripts/dr_restore.py \
  --backup backups/mysql_20261030T091412Z.sql.enc \
  --manifest backups/manifest_20261030T091412Z.json \
  --target-db agent_center_drill --drop-existing
```

`--manifest` 会先校验加密文件 sha256；恢复时解密到临时文件，完成后删除。生产恢复账号应使用专用账号，不要使用 root。
