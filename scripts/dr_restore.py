"""把 MySQL 备份恢复到独立演练库，并校验表数量。

用法：
    python scripts/dr_restore.py --backup backups/mysql_xxx.sql --target-db agent_center_drill
    AC_BACKUP_KEY=... python scripts/dr_restore.py --backup backups/mysql_xxx.sql.enc \
        --manifest backups/manifest_xxx.json --target-db agent_center_drill
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from app.core.backup_crypto import decrypt_file, is_encrypted


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


def _verify_manifest(backup: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("mysql", "redis", "milvus"):
        item = manifest.get(key) or {}
        if item.get("file") == backup.name:
            expected = item.get("sha256")
            if expected and _sha256(backup) != expected:
                raise SystemExit(f"备份校验失败：{backup.name} 的 sha256 与 manifest 不一致")
            return
    raise SystemExit(f"manifest 中未找到备份文件：{backup.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--target-db", default="agent_center_drill")
    parser.add_argument("--mysql-container", default="agent-center-mysql")
    parser.add_argument("--mysql-user", default="root")
    parser.add_argument("--mysql-password", default="root_pass")
    parser.add_argument("--drop-existing", action="store_true")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--key-env", default="AC_BACKUP_KEY")
    parser.add_argument("--key-file", default="")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_]+", args.target_db):
        raise SystemExit("target-db 仅允许字母、数字、下划线")
    if args.target_db == "agent_center":
        raise SystemExit("禁止覆盖业务库 agent_center")
    backup = Path(args.backup)
    if not backup.is_file():
        raise SystemExit(f"备份文件不存在: {backup}")
    if args.manifest:
        _verify_manifest(backup, Path(args.manifest))

    plaintext_path: Path | None = None
    source = backup
    try:
        if is_encrypted(backup):
            passphrase = _passphrase(args)
            if not passphrase:
                raise SystemExit("备份已加密：请设置 AC_BACKUP_KEY 或 --key-file")
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".sql")
            handle.close()
            plaintext_path = Path(handle.name)
            try:
                decrypt_file(backup, plaintext_path, passphrase)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            source = plaintext_path

        base = [
            "docker",
            "exec",
            "-i",
            "-e",
            f"MYSQL_PWD={args.mysql_password}",
            args.mysql_container,
            "mysql",
            "-u",
            args.mysql_user,
        ]

        def run(args_list: list[str], *, stdin=None):
            result = subprocess.run(
                args_list, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1000:])
            return result

        existing = run(
            base + ["-N", "-e", f"SHOW DATABASES LIKE '{args.target_db}'"]
        ).stdout.strip()
        if existing and not args.drop_existing:
            raise SystemExit(f"目标库已存在: {args.target_db}，如需重建请加 --drop-existing")
        if existing:
            run(base + ["-e", f"DROP DATABASE `{args.target_db}`"])
        run(base + ["-e", f"CREATE DATABASE `{args.target_db}` CHARACTER SET utf8mb4"])

        started = time.perf_counter()
        with source.open("rb") as handle:
            run(base + [args.target_db], stdin=handle)
        elapsed = time.perf_counter() - started

        count = run(
            base
            + [
                "-N",
                "-e",
                "SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema='{args.target_db}'",
            ]
        ).stdout.decode().strip()
        print(
            f"restored {backup.name} -> {args.target_db} in {elapsed:.2f}s, "
            f"tables={count}, encrypted={source != backup}"
        )
    finally:
        if plaintext_path and plaintext_path.exists():
            plaintext_path.unlink()


if __name__ == "__main__":
    main()
