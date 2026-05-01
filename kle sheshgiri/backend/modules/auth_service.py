from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone


PBKDF2_ITERATIONS = 600_000
RESET_CODE_TTL_MINUTES = 15


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(candidate, digest)


def generate_reset_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def reset_code_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=RESET_CODE_TTL_MINUTES)
