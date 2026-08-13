import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet_from_secret(secret: str) -> Fernet:
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _get_fernet() -> Fernet:
    return _fernet_from_secret(get_settings().PHONE_ENCRYPTION_KEY)


def encrypt_phone(phone: str) -> str:
    return encrypt_secret(phone)


def decrypt_phone(encrypted: str) -> str:
    return decrypt_secret(encrypted)


def encrypt_secret(value: str) -> str:
    """Encrypt application secrets before persisting them."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt application secrets inside the backend process only."""
    return _get_fernet().decrypt(encrypted.encode()).decode()


def encrypt_cookie_payload(value: str) -> str:
    """Encrypt browser session state with its own rotation boundary."""
    return (
        _fernet_from_secret(get_settings().COOKIE_ENCRYPTION_KEY)
        .encrypt(value.encode())
        .decode()
    )


def decrypt_cookie_payload(encrypted: str) -> str:
    return (
        _fernet_from_secret(get_settings().COOKIE_ENCRYPTION_KEY)
        .decrypt(encrypted.encode())
        .decode()
    )


def mask_phone(phone: str) -> str:
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return phone
