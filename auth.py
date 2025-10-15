from __future__ import annotations

import hashlib
import os
import secrets
from typing import Tuple

HASH_NAME = "sha256"
ITERATIONS = 150_000
SALT_SIZE = 16
SESSION_TOKEN_BYTES = 32


def normalize_email(email: str) -> str:
    """Normalize email casing and whitespace."""
    return email.strip().lower()


def hash_password(password: str) -> str:
    """Return a PBKDF2 hashed password."""
    salt = os.urandom(SALT_SIZE)
    key = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, ITERATIONS)
    return f"{HASH_NAME}${ITERATIONS}${salt.hex()}${key.hex()}"


def _parse_hash(encoded: str) -> Tuple[str, int, bytes, bytes]:
    algorithm, iterations, salt_hex, key_hex = encoded.split("$", 3)
    return (
        algorithm,
        int(iterations),
        bytes.fromhex(salt_hex),
        bytes.fromhex(key_hex),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    try:
        algorithm, iterations, salt, expected_key = _parse_hash(encoded)
    except (ValueError, TypeError):
        return False

    if algorithm != HASH_NAME:
        return False

    derived = hashlib.pbkdf2_hmac(
        algorithm,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(derived, expected_key)


def create_session_token() -> str:
    """Generate a random session token."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)

