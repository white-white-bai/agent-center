"""导出 MySQL 8 建表 DDL，供 DBA 审核与执行。

用法：python scripts/export_ddl.py [输出路径]
"""

import sys
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database.registry import Base  # noqa: E402

HEADER = """-- Agent Center MySQL 8 DDL
-- 由 scripts/export_ddl.py 生成，请由 DBA 审核后执行。
-- 所有业务表均包含 tenant_id，用于多租户隔离。

SET NAMES utf8mb4;
"""


def render() -> str:
    dialect = mysql.dialect()
    parts = [HEADER]
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        parts.append(f"{ddl};\n")
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            parts.append(f"{str(CreateIndex(index).compile(dialect=dialect)).strip()};\n")
        parts.append("\n")
    return "\n".join(parts)


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/schema-mysql.sql")
    target.write_text(render(), encoding="utf-8")
    print(f"written: {target}")


if __name__ == "__main__":
    main()
