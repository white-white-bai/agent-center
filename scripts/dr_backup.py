"""本地灾备备份：MySQL 全量 + Redis RDB + Milvus Lite 文件。

用法：
    python scripts/dr_backup.py --output backups
"""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="backups")
    parser.add_argument("--mysql-container", default="agent-center-mysql")
    parser.add_argument("--redis-container", default="agent-center-redis")
    parser.add_argument("--app-container", default="agent-center-app")
    parser.add_argument("--database", default="agent_center")
    parser.add_argument("--mysql-user", default="agent")
    parser.add_argument("--mysql-password", default="agent_pass")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest: dict = {"createdAt": datetime.now(timezone.utc).isoformat(), "database": args.database}

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
    manifest["mysql"] = {
        "file": sql_path.name,
        "bytes": sql_path.stat().st_size,
        "sha256": _sha256(sql_path),
    }

    _run(["docker", "exec", args.redis_container, "redis-cli", "SAVE"])
    rdb_path = output / f"redis_{stamp}.rdb"
    _run(["docker", "cp", f"{args.redis_container}:/data/dump.rdb", str(rdb_path)])
    manifest["redis"] = {
        "file": rdb_path.name,
        "bytes": rdb_path.stat().st_size,
        "sha256": _sha256(rdb_path),
    }
    check = subprocess.run(
        ["docker", "exec", args.redis_container, "redis-check-rdb", "/data/dump.rdb"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    manifest["redis"]["check"] = check.stdout.decode("utf-8", errors="replace")[-500:]

    milvus_path = output / f"milvus_{stamp}.db"
    copied = subprocess.run(
        ["docker", "cp", f"{args.app_container}:/data/milvus.db", str(milvus_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if copied.returncode == 0:
        manifest["milvus"] = {
            "file": milvus_path.name,
            "bytes": milvus_path.stat().st_size,
            "sha256": _sha256(milvus_path),
        }
    else:
        manifest["milvus"] = {"skipped": "Milvus Lite 文件不存在（可能使用外部 Milvus）"}

    manifest_path = output / f"manifest_{stamp}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
