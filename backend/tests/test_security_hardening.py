import base64
import hashlib
import uuid

import bcrypt
import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

from app.api.v1.leads import _ensure_lead_access
from app.api.v1.social_publish import _publish_fingerprint, _validate_media_reference
from app.api.v1.wecom import _pkcs7_unpad, verify_wecom_signature
from app.core.config import Settings, _validate_production_settings
from app.core.exceptions import public_validation_errors
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    password_needs_rehash,
    verify_password,
    verify_token,
)
from app.integrations.synapse_engine.publish.publisher import Publisher
from app.integrations.synapse_engine.cookie.manager import CookieManager
from app.models.lead import Lead
from app.models.user import User
from app.services.notify_provider import DisabledNotifyProvider
from app.utils.url_safety import normalize_public_http_url


def test_password_hash_supports_long_unicode_and_legacy_hashes():
    password = "长密码-" + "a1" * 80
    encoded = get_password_hash(password)
    assert verify_password(password, encoded)
    assert not verify_password(password + "x", encoded)
    assert not password_needs_rehash(encoded)

    legacy_password = "Legacy-pass-123"
    legacy_hash = bcrypt.hashpw(legacy_password.encode(), bcrypt.gensalt()).decode()
    assert verify_password(legacy_password, legacy_hash)
    assert password_needs_rehash(legacy_hash)


def test_access_and_refresh_tokens_cannot_be_interchanged():
    subject = str(uuid.uuid4())
    access = create_access_token(subject)
    refresh = create_refresh_token(subject)
    assert verify_token(access, "access")["sub"] == subject
    assert verify_token(refresh, "refresh")["sub"] == subject
    assert verify_token(refresh, "refresh")["jti"]
    assert verify_token(access, "refresh") is None
    assert verify_token(refresh, "access") is None
    assert verify_token(access + "tampered", "access") is None


def test_production_settings_accept_complete_strong_configuration():
    password = "DatabasePass-123456"
    redis_password = "RedisPass-123456789"
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        APP_DEBUG=False,
        APP_SECRET_KEY="a" * 64,
        PHONE_ENCRYPTION_KEY="b" * 64,
        COOKIE_ENCRYPTION_KEY="c" * 64,
        POSTGRES_USER="ai_app",
        POSTGRES_PASSWORD=password,
        POSTGRES_DB="ai_social_media",
        DATABASE_URL=f"postgresql+asyncpg://ai_app:{password}@postgres:5432/ai_social_media",
        REDIS_PASSWORD=redis_password,
        REDIS_URL=f"redis://:{redis_password}@redis:6379/0",
        MINIO_ACCESS_KEY="ai-storage",
        MINIO_SECRET_KEY="MinioSecret-123456789",
        CORS_ORIGINS="https://social.example.com",
        ALLOWED_HOSTS="social.example.com",
        HEALTHCHECK_HOST="social.example.com",
        LLM_PROVIDER="deepseek",
        DEEPSEEK_API_KEY="test-key",
        DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
        SOCIAL_PROVIDER="synapse_embedded",
        ANALYTICS_PROVIDER="database",
        NOTIFY_PROVIDER="disabled",
        EMBEDDING_PROVIDER="disabled",
        MAP_PROVIDER="disabled",
        CRAWLER_PROVIDER="mediacrawler_embedded",
        BOOTSTRAP_ADMIN_ENABLED=False,
    )
    _validate_production_settings(settings)


def test_production_settings_reject_insecure_defaults():
    # 显式传入不安全默认值，避免开发机/CI 的真实环境变量覆盖被测场景。
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        APP_SECRET_KEY="change-me-in-production",
        PHONE_ENCRYPTION_KEY="phone-encryption-key-32bytes!!",
        COOKIE_ENCRYPTION_KEY="cookie-encryption-key-change-me",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD="postgres",
        DATABASE_URL=(
            "postgresql+asyncpg://postgres:postgres@postgres:5432/"
            "ai_social_media"
        ),
        REDIS_PASSWORD="",
        REDIS_URL="redis://redis:6379/0",
        MINIO_ACCESS_KEY="minioadmin",
        MINIO_SECRET_KEY="minioadmin",
        CORS_ORIGINS="*",
        ALLOWED_HOSTS="*",
        SEED_ADMIN_PASSWORD="admin123",
    )
    with pytest.raises(RuntimeError) as exc_info:
        _validate_production_settings(settings)
    message = str(exc_info.value)
    assert "APP_SECRET_KEY" in message
    assert "REDIS_PASSWORD" in message
    assert "CORS_ORIGINS" in message
    assert "ALLOWED_HOSTS" in message
    assert "COOKIE_ENCRYPTION_KEY" in message


def test_cookie_state_is_encrypted_and_legacy_plaintext_is_migrated(tmp_path):
    manager = CookieManager(tmp_path)
    state = {
        "cookies": [{"name": "session", "value": "sensitive-cookie"}],
        "origins": [],
    }
    path = manager.save("douyin", "account-1", state)
    assert path.stat().st_mode & 0o777 == 0o600
    assert "sensitive-cookie" not in path.read_text(encoding="utf-8")

    fresh_manager = CookieManager(tmp_path)
    assert fresh_manager.load("douyin", "account-1") == state

    legacy_path = fresh_manager._path("douyin", "legacy")
    legacy_path.write_text(
        '{"cookies":[{"name":"legacy","value":"plaintext"}]}', encoding="utf-8"
    )
    legacy_state = fresh_manager.load("douyin", "legacy")
    assert legacy_state["cookies"][0]["value"] == "plaintext"
    assert "plaintext" not in legacy_path.read_text(encoding="utf-8")


def test_validation_error_details_do_not_echo_sensitive_input():
    exc = RequestValidationError(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "password"),
                "msg": "String should have at least 8 characters",
                "input": "secret-value",
                "ctx": {"min_length": 8},
                "url": "https://errors.pydantic.dev/example",
            }
        ]
    )
    details = public_validation_errors(exc)
    assert details == [
        {
            "type": "string_too_short",
            "loc": ("body", "password"),
            "msg": "String should have at least 8 characters",
        }
    ]
    assert "secret-value" not in str(details)


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,test",
        "https://user:password@example.com/post",
        "http://127.0.0.1/private",
        "http://[::1]/private",
    ],
)
def test_browser_links_reject_unsafe_urls(value):
    assert normalize_public_http_url(value) is None


def test_browser_links_allow_public_https_urls():
    assert (
        normalize_public_http_url("https://www.douyin.com/video/123")
        == "https://www.douyin.com/video/123"
    )


def test_publish_fingerprint_is_stable_and_account_scoped():
    account_id = uuid.uuid4()
    params = {"visibility": "public", "topics": ["门窗"]}
    common = {
        "platform": "douyin",
        "title": "项目案例",
        "description": "这是正文",
        "tags": ["案例", "门窗"],
        "media_paths": ["https://cdn.example.com/demo.mp4"],
        "cover_path": None,
        "publish_params": params,
    }
    first = _publish_fingerprint(account_id=account_id, **common)
    reordered = _publish_fingerprint(
        account_id=account_id,
        **{**common, "tags": ["门窗", "案例"]},
    )
    other_account = _publish_fingerprint(account_id=uuid.uuid4(), **common)

    assert first == reordered
    assert first != other_account
    assert len(first) == 64


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "/../etc/passwd",
        "https://user:password@example.com/file.jpg",
        "ftp://example.com/file.jpg",
        "relative/file.jpg",
    ],
)
def test_publish_media_reference_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        _validate_media_reference(value)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://[::1]/private",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1/private",
    ],
)
def test_publisher_blocks_private_network_media_urls(url):
    with pytest.raises(ValueError):
        Publisher._assert_safe_remote_url(url)


def test_wecom_signature_and_padding_validation():
    values = ["token", "1710000000", "nonce", "ciphertext"]
    signature = hashlib.sha1("".join(sorted(values)).encode()).hexdigest()  # nosec B324
    verify_wecom_signature(values[0], values[1], values[2], values[3], signature)
    with pytest.raises(HTTPException) as exc_info:
        verify_wecom_signature(values[0], values[1], values[2], values[3], "bad")
    assert exc_info.value.status_code == 401

    assert _pkcs7_unpad(b"payload" + bytes([3, 3, 3])) == b"payload"
    with pytest.raises(HTTPException):
        _pkcs7_unpad(base64.b64decode("YmFkAA=="))


def test_dealer_cannot_access_another_dealers_lead():
    dealer_id = uuid.uuid4()
    user = User(role="dealer", dealer_id=dealer_id)
    own_lead = Lead(assigned_dealer_id=dealer_id)
    other_lead = Lead(assigned_dealer_id=uuid.uuid4())
    _ensure_lead_access(user, own_lead)
    with pytest.raises(HTTPException) as exc_info:
        _ensure_lead_access(user, other_lead)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_disabled_notification_provider_is_explicit_successful_noop():
    result = await DisabledNotifyProvider().send_publish_success(
        "标题", "douyin", "user-id"
    )
    assert result.success is True
    assert result.channel == "disabled"
