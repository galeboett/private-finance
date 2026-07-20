from __future__ import annotations

import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ENCRYPTED_MAGIC = b"PFENC01\x00"
SALT_SIZE = 16
NONCE_SIZE = 12


class EncryptionError(ValueError):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 12:
        raise EncryptionError("Use an encryption passphrase with at least 12 characters")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        type=Type.ID,
    )


def encrypt_payload(payload: bytes, passphrase: str) -> bytes:
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = _derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, payload, ENCRYPTED_MAGIC)
    return ENCRYPTED_MAGIC + salt + nonce + ciphertext


def decrypt_payload(payload: bytes, passphrase: str) -> bytes:
    minimum_size = len(ENCRYPTED_MAGIC) + SALT_SIZE + NONCE_SIZE + 16
    if len(payload) < minimum_size or not payload.startswith(ENCRYPTED_MAGIC):
        raise EncryptionError("This is not an encrypted private-finance archive")
    offset = len(ENCRYPTED_MAGIC)
    salt = payload[offset:offset + SALT_SIZE]
    nonce = payload[offset + SALT_SIZE:offset + SALT_SIZE + NONCE_SIZE]
    ciphertext = payload[offset + SALT_SIZE + NONCE_SIZE:]
    try:
        return AESGCM(_derive_key(passphrase, salt)).decrypt(nonce, ciphertext, ENCRYPTED_MAGIC)
    except InvalidTag as error:
        raise EncryptionError("The encryption passphrase is incorrect or the archive is damaged") from error
