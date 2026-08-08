"""API Key 加密存储（Fernet）。

加密密钥优先取环境变量 MODEL_CONFIG_ENCRYPTION_KEY（Fernet key），
未配置时自动生成并持久化到 data/secret.key（重启不失效）。
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

_KEY_FILE = Path(__file__).resolve().parent.parent / "data" / "secret.key"


def _load_key() -> bytes:
    env = os.getenv("MODEL_CONFIG_ENCRYPTION_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_bytes(key)
    return key


_fernet = Fernet(_load_key())


def encrypt_secret(text: str) -> str:
    return _fernet.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
