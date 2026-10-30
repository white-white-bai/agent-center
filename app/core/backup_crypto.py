"""灾备备份文件加解密（AES-256-GCM + scrypt）。"""

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ACBK1"
SALT_SIZE = 16
NONCE_SIZE = 12
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )


def is_encrypted(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(MAGIC)) == MAGIC


def encrypt_file(source: Path, target: Path, passphrase: str) -> None:
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, source.read_bytes(), MAGIC)
    target.write_bytes(MAGIC + salt + nonce + ciphertext)
    try:
        target.chmod(0o600)
    except OSError:
        pass


def decrypt_file(source: Path, target: Path, passphrase: str) -> None:
    blob = source.read_bytes()
    if len(blob) < len(MAGIC) + SALT_SIZE + NONCE_SIZE or not blob.startswith(MAGIC):
        raise ValueError("不是有效的加密备份文件")
    offset = len(MAGIC)
    salt = blob[offset : offset + SALT_SIZE]
    nonce = blob[offset + SALT_SIZE : offset + SALT_SIZE + NONCE_SIZE]
    ciphertext = blob[offset + SALT_SIZE + NONCE_SIZE :]
    try:
        plaintext = AESGCM(derive_key(passphrase, salt)).decrypt(nonce, ciphertext, MAGIC)
    except Exception as exc:  # noqa: BLE001 - 统一为可读错误
        raise ValueError("备份解密失败：密钥错误或文件损坏") from exc
    target.write_bytes(plaintext)
    try:
        target.chmod(0o600)
    except OSError:
        pass
