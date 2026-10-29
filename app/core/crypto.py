import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

KEY_VERSION = "v1"
DEV_SECRET = "agent-center-dev-key-do-not-use-in-production"


def _derive_key() -> bytes:
    secret = get_settings().credential_key or DEV_SECRET
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_derive_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(_derive_key()).decrypt(nonce, ciphertext, None).decode("utf-8")


def key_version() -> str:
    return KEY_VERSION
