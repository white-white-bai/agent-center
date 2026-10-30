"""把 MySQL 备份恢复到独立演练库，并校验表数量。

用法：
    python scripts/dr_restore.py --backup backups/mysql_xxx.sql --target-db agent_center_drill
"""

import argparse
import re
import subprocess
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--target-db", default="agent_center_drill")
    parser.add_argument("--mysql-container", default="agent-center-mysql")
    parser.add_argument("--mysql-user", default="root")
    parser.add_argument("--mysql-password", default="root_pass")
    parser.add_argument("--drop-existing", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_]+", args.target_db):
        raise SystemExit("target-db 仅允许字母、数字、下划线")
    if args.target_db == "agent_center":
        raise SystemExit("禁止覆盖业务库 agent_center")
    backup = Path(args.backup)
    if not backup.is_file():
        raise SystemExit(f"备份文件不存在: {backup}")

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

    def run(args_list: list[str], *, stdin=None, check: bool = True):
        result = subprocess.run(
            args_list, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1000:])
        return result

    existing = run(base + ["-N", "-e", f"SHOW DATABASES LIKE '{args.target_db}'"]).stdout.strip()
    if existing and not args.drop_existing:
        raise SystemExit(f"目标库已存在: {args.target_db}，如需重建请加 --drop-existing")
    if existing:
        run(base + ["-e", f"DROP DATABASE `{args.target_db}`"])
    run(base + ["-e", f"CREATE DATABASE `{args.target_db}` CHARACTER SET utf8mb4"])

    started = time.perf_counter()
    with backup.open("rb") as handle:
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
        f"restored {backup.name} -> {args.target_db} in {elapsed:.2f}s, tables={count}"
    )


if __name__ == "__main__":
    main()
