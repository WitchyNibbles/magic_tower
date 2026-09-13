"""Small encrypted local storage primitive for OAuth refresh tokens."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TokenStoreError(RuntimeError):
    pass


class EncryptedTokenStore:
    """A single encrypted file; never return its ciphertext to an API client."""

    def __init__(self, path: Path, key: str) -> None:
        try:
            self._cipher = AESGCM(base64.urlsafe_b64decode(key.encode()))
        except (ValueError, TypeError, binascii.Error) as error:
            raise TokenStoreError("APP_ENCRYPTION_KEY must be a 32-byte URL-safe base64 key") from error
        self.path = path

    def save(self, token: dict[str, Any]) -> None:
        payload = json.dumps(token, separators=(",", ":")).encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(12)
        self.path.write_bytes(nonce + self._cipher.encrypt(nonce, payload, b"workboard-graph-v1"))
        self.path.chmod(0o600)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_bytes()
            return json.loads(self._cipher.decrypt(raw[:12], raw[12:], b"workboard-graph-v1"))
        except (InvalidTag, ValueError, json.JSONDecodeError) as error:
            raise TokenStoreError("stored Graph token cannot be decrypted") from error

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def generate_encryption_key() -> str:
    """Useful for setup tooling; do not generate a replacement key at runtime."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()
