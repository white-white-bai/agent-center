import importlib.util
import json
from pathlib import Path


def _backup_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dr_backup.py"
    spec = importlib.util.spec_from_file_location("dr_backup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_retention_removes_old_manifest_and_artifacts(tmp_path: Path) -> None:
    module = _backup_module()
    old_file = tmp_path / "mysql_old.sql.enc"
    old_file.write_bytes(b"old")
    old_manifest = tmp_path / "manifest_20200101T000000Z.json"
    old_manifest.write_text(
        json.dumps(
            {
                "createdAt": "2020-01-01T00:00:00+00:00",
                "mysql": {"file": old_file.name},
            }
        ),
        encoding="utf-8",
    )
    current = tmp_path / "manifest_current.json"
    current.write_text(
        json.dumps({"createdAt": "2999-01-01T00:00:00+00:00", "mysql": {"file": "keep.sql"}}),
        encoding="utf-8",
    )
    keep = tmp_path / "keep.sql"
    keep.write_bytes(b"keep")

    removed = module._apply_retention(tmp_path, days=7)

    assert not old_file.exists()
    assert not old_manifest.exists()
    assert current.exists()
    assert keep.exists()
    assert sorted(removed) == ["manifest_20200101T000000Z.json", "mysql_old.sql.enc"]
