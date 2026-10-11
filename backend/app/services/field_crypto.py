"""Column-level AES-GCM encryption for message content kept in the local database.

The primitive is the same one ``crypto.EncryptedTokenStore`` uses, under the same
``APP_ENCRYPTION_KEY``, but sealed with its own associated data: a ciphertext
written for a database column must never verify as a stored Graph token, and vice
versa. There is no second key and no fallback -- a value that cannot be sealed or
opened raises, so cleartext can never reach the disk and garbage can never reach
the API.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from ..config import get_settings

# Deliberately not ``b"workboard-graph-v1"``; that string belongs to the token store.
EXCERPT_AAD = b"workboard-source-excerpt-v1"

# Tags the stored form so a migration can tell a sealed column from a legacy one.
CIPHERTEXT_PREFIX = "aesgcm.v1:"

NONCE_BYTES = 12


class FieldEncryptionError(RuntimeError):
    pass


def _cipher() -> AESGCM:
    key = get_settings().app_encryption_key
    if key is None:
        raise FieldEncryptionError("APP_ENCRYPTION_KEY is not configured; message content cannot be stored")
    try:
        return AESGCM(base64.urlsafe_b64decode(key.get_secret_value().encode()))
    except (ValueError, TypeError, binascii.Error) as error:
        raise FieldEncryptionError("APP_ENCRYPTION_KEY must be a 32-byte URL-safe base64 key") from error


def encrypt_text(value: str) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = nonce + _cipher().encrypt(nonce, value.encode(), EXCERPT_AAD)
    return CIPHERTEXT_PREFIX + base64.urlsafe_b64encode(sealed).decode()


def decrypt_text(stored: str) -> str:
    if not stored.startswith(CIPHERTEXT_PREFIX):
        raise FieldEncryptionError("stored message content is not encrypted; run the Alembic migrations")
    try:
        raw = base64.urlsafe_b64decode(stored[len(CIPHERTEXT_PREFIX):].encode())
        return _cipher().decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], EXCERPT_AAD).decode()
    except (InvalidTag, ValueError, TypeError, binascii.Error, UnicodeDecodeError) as error:
        raise FieldEncryptionError("stored message content cannot be decrypted") from error


class EncryptedText(TypeDecorator[str]):
    """A ``TEXT`` column whose value is sealed on write and opened on read.

    Encrypting in the type rather than at the call sites means every writer of the
    column -- Graph sync, the REST API, a future integration -- is covered by
    construction, and every reader keeps seeing cleartext.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, _dialect: object) -> str | None:
        return None if value is None else encrypt_text(value)

    def process_result_value(self, value: str | None, _dialect: object) -> str | None:
        return None if value is None else decrypt_text(value)
