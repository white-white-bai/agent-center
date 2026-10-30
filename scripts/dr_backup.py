"""本地灾备备份：MySQL 全量 + Redis RDB + Milvus Lite 文件。

用法：
    python scripts/dr_backup.py --output backups
    AC_BACKUP_KEY=... python scripts/dr_backup.py --output backups --require-encryption
"""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.backup_crypto import encrypt_file

ARTIFACT_KEYS = ("mysql", "redis", "milvus")


def _run(args: list[str], *, stdin=None) -> subprocess.CompletedProcess:
    result = subprocess.run(args, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"{result.stderr.decode('utf-8', errors='replace')[-1000:]}"
        )
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _passphrase(args) -> str:
    if args.key_file:
        return Path(args.key_file).read_text(encoding="utf-8").strip()
    return os.getenv(args.key_env, "").strip()


def _protect(path: Path, passphrase: str) -> tuple[Path, bool]:
    if not passphrase:
        return path, False
    encrypted = path.with_name(path.name + ".enc")
    encrypt_file(path, encrypted, passphrase)
    path.unlink()
    return encrypted, True


def _apply_retention(output: Path, days: int) -> list[str]:
    if days <= 0:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed: list[str] = []
    for manifest_path in sorted(output.glob("manifest_*.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(manifest["createdAt"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (OSError, ValueError, KeyError):
            continue
        if created >= cutoff:
            continue
        for key in ARTIFACT_KEYS:
            item = manifest.get(key) or {}
            name = item.get("file")
            if name:
                path = output / name
                if path.is_file():
                    path.unlink()
                    removed.append(path.name)
        manifest_path.unlink()
        removed.append(manifest_path.name)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="backups")
    parser.add_argument("--mysql-container", default="agent-center-mysql")
    parser.add_argument("--redis-container", default="agent-center-redis")
    parser.add_argument("--app-container", default="agent-center-app")
    parser.add_argument("--database", default="agent_center")
    parser.add_argument("--mysql-user", default="agent")
    parser.add_argument("--mysql-password", default="agent_pass")
    parser.add_argument("--key-env", default="AC_BACKUP_KEY")
    parser.add_argument("--key-file", default="")
    parser.add_argument("--require-encryption", action="store_true")
    parser.add_argument("--retention-days", type=int, default=0)
    args = parser.parse_args()

    passphrase = _passphrase(args)
    if args.require_encryption and not passphrase:
        raise SystemExit("未提供备份密钥：请设置 AC_BACKUP_KEY 或 --key-file")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest: dict = {"createdAt": datetime.now(timezone.utc).isoformat(), "database": args.database}
    if passphrase:
        manifest["encryption"] = {"algorithm": "AES-256-GCM", "kdf": "scrypt"}

    sql_path = output / f"mysql_{stamp}.sql"
    with sql_path.open("wb") as handle:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"MYSQL_PWD={args.mysql_password}",
                args.mysql_container,
                "mysqldump",
                "-u",
                args.mysql_user,
                "--single-transaction",
                "--quick",
                "--routines",
                "--triggers",
                args.database,
            ],
            stdout=handle,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1000:])
    sql_path, sql_encrypted = _protect(sql_path, passphrase)
    manifest["mysql"] = {
        "file": sql_path.name,
        "bytes": sql_path.stat().st_size,
        "sha256": _sha256(sql_path),
        "encrypted": sql_encrypted,
    }

    _run(["docker", "exec", args.redis_container, "redis-cli", "SAVE"])
    rdb_path = output / f"redis_{stamp}.rdb"
    _run(["docker", "cp", f"{args.redis_container}:/data/dump.rdb", str(rdb_path)])
    check = subprocess.run(
        ["docker", "exec", args.redis_container, "redis-check-rdb", "/data/dump.rdb"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    rdb_path, rdb_encrypted = _protect(rdb_path, passphrase)
    manifest["redis"] = {
        "file": rdb_path.name,
        "bytes": rdb_path.stat().st_size,
        "sha256": _sha256(rdb_path),
        "encrypted": rdb_encrypted,
        "check": check.stdout.decode("utf-8", errors="replace")[-500:],
    }

    milvus_path = output / f"milvus_{stamp}.db"
    copied = subprocess.run(
        ["docker", "cp", f"{args.app_container}:/data/milvus.db", str(milvus_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if copied.returncode == 0:
        milvus_path, milvus_encrypted = _protect(milvus_path, passphrase)
        manifest["milvus"] = {
            "file": milvus_path.name,
            "bytes": milvus_path.stat().st_size,
            "sha256": _sha256(milvus_path),
            "encrypted": milvus_encrypted,
        }
    else:
        manifest["milvus"] = {"skipped": "Milvus Lite 文件不存在（可能使用外部 Milvus）"}

    manifest_path = output / f"manifest_{stamp}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    removed = _apply_retention(output, args.retention_days)
    print(
        json.dumps(
            {"manifest": str(manifest_path), "retentionRemoved": removed, **manifest},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
