from pathlib import Path

import pytest

from app.core.backup_crypto import decrypt_file, encrypt_file, is_encrypted


def test_encrypt_decrypt_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "source.sql"
    encrypted = tmp_path / "source.sql.enc"
    restored = tmp_path / "restored.sql"
    source.write_bytes(b"-- mysql dump\n" + b"x" * 1024)

    encrypt_file(source, encrypted, "test-passphrase")
    assert is_encrypted(encrypted)
    assert encrypted.read_bytes()[:5] == b"ACBK1"
    assert source.read_bytes() != encrypted.read_bytes()

    decrypt_file(encrypted, restored, "test-passphrase")
    assert restored.read_bytes() == source.read_bytes()


def test_wrong_key_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.sql"
    encrypted = tmp_path / "source.sql.enc"
    restored = tmp_path / "restored.sql"
    source.write_text("secret", encoding="utf-8")

    encrypt_file(source, encrypted, "right")
    with pytest.raises(ValueError, match="解密失败"):
        decrypt_file(encrypted, restored, "wrong")
    assert not restored.exists()


def test_tampered_file_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.sql"
    encrypted = tmp_path / "source.sql.enc"
    source.write_text("secret", encoding="utf-8")
    encrypt_file(source, encrypted, "key")

    blob = bytearray(encrypted.read_bytes())
    blob[-1] ^= 0x01
    encrypted.write_bytes(blob)
    with pytest.raises(ValueError, match="解密失败"):
        decrypt_file(encrypted, tmp_path / "out.sql", "key")
