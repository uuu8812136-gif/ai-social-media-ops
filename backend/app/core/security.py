import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import bcrypt

from app.core.config import get_settings

settings = get_settings()
_BCRYPT_SHA256_PREFIX = "$bcrypt-sha256$"


def _password_material(password: str) -> bytes:
    """Pre-hash to avoid bcrypt's 72-byte truncation while keeping a fixed input size."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        if hashed_password.startswith(_BCRYPT_SHA256_PREFIX):
            stored_hash = hashed_password[len(_BCRYPT_SHA256_PREFIX) :]
            return bcrypt.checkpw(
                _password_material(plain_password), stored_hash.encode("ascii")
            )
        # Backward compatibility for hashes created by the previous passlib/bcrypt setup.
        plain_bytes = plain_password.encode("utf-8")
        if len(plain_bytes) > 72:
            return False
        return bcrypt.checkpw(plain_bytes, hashed_password.encode("ascii"))
    except (TypeError, ValueError, UnicodeError):
        return False


def get_password_hash(password: str) -> str:
    encoded = bcrypt.hashpw(
        _password_material(password), bcrypt.gensalt(rounds=12)
    ).decode("ascii")
    return _BCRYPT_SHA256_PREFIX + encoded


def password_needs_rehash(hashed_password: str) -> bool:
    return not hashed_password.startswith(_BCRYPT_SHA256_PREFIX)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,
        "type": "access",
        "iat": issued_at.timestamp(),
        "exp": expire,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(
        payload, settings.APP_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def create_refresh_token(subject: str) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        # Keep sub-second precision so a password-change revocation cutoff can
        # distinguish tokens issued immediately before and after the change.
        "iat": issued_at.timestamp(),
        "exp": expire,
    }
    return jwt.encode(
        payload, settings.APP_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token, settings.APP_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )


def verify_token(token: str, token_type: str = "access") -> dict[str, Any] | None:
    try:
        payload = decode_token(token)
        if payload.get("type") != token_type:
            return None
        return payload
    except jwt.InvalidTokenError:
        return None
