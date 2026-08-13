import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

settings = get_settings()


def _redis_client() -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )


def _session_cutoff_key(subject: str) -> str:
    return f"auth:session:invalid_before:{subject}"


async def revoke_refresh_token(
    payload: dict[str, Any], *, reject_if_already_revoked: bool
) -> bool:
    """Atomically revoke a refresh-token JTI until its natural expiration."""
    jti = payload.get("jti")
    expires_at = payload.get("exp")
    if not isinstance(jti, str) or not jti or not isinstance(expires_at, (int, float)):
        return False

    ttl = max(1, int(expires_at - time.time()))
    subject = payload.get("sub")
    issued_at = payload.get("iat")
    if not isinstance(subject, str) or not subject:
        return False
    if not isinstance(issued_at, (int, float)):
        return False

    client = _redis_client()
    try:
        key = f"auth:refresh:revoked:{jti}"
        if reject_if_already_revoked:
            script = """
            local cutoff = redis.call('GET', KEYS[1])
            if cutoff and tonumber(ARGV[1]) < tonumber(cutoff) then
                return 0
            end
            local stored = redis.call('SET', KEYS[2], '1', 'EX', ARGV[2], 'NX')
            if stored then return 1 end
            return 0
            """
            result = await client.eval(
                script,
                2,
                _session_cutoff_key(subject),
                key,
                float(issued_at),
                ttl,
            )
            return bool(result)
        await client.set(key, "1", ex=ttl)
        return True
    except RedisError as exc:
        raise RuntimeError("会话存储服务不可用") from exc
    finally:
        await client.aclose()


async def revoke_all_user_tokens(subject: str) -> None:
    """Invalidate every access and refresh token issued before this instant."""
    if not subject:
        raise RuntimeError("无效的会话用户")
    client = _redis_client()
    try:
        ttl = max(1, settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60)
        await client.set(_session_cutoff_key(subject), str(time.time()), ex=ttl)
    except RedisError as exc:
        raise RuntimeError("会话存储服务不可用") from exc
    finally:
        await client.aclose()


async def is_user_token_current(payload: dict[str, Any]) -> bool:
    """Return false when a token predates logout or a security-sensitive change."""
    subject = payload.get("sub")
    issued_at = payload.get("iat")
    if not isinstance(subject, str) or not subject:
        return False
    if not isinstance(issued_at, (int, float)):
        return False

    client = _redis_client()
    try:
        cutoff = await client.get(_session_cutoff_key(subject))
        return cutoff is None or float(issued_at) >= float(cutoff)
    except (RedisError, TypeError, ValueError) as exc:
        raise RuntimeError("会话存储服务不可用") from exc
    finally:
        await client.aclose()
