import re
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.llm_config import LLMProviderConfig
from app.models.user import User
from app.schemas.llm_config import LLMConfigPayload
from app.services.llm_client import (
    LLMClient,
    LLMConfigurationError,
    LLMRuntimeConfig,
    ensure_safe_llm_base_url,
)
from app.utils.encryption import decrypt_secret, encrypt_secret
from app.utils.response import success

router = APIRouter(prefix="/settings/llm", tags=["llm-settings"])


async def _record(db: AsyncSession) -> LLMProviderConfig | None:
    result = await db.execute(
        select(LLMProviderConfig).where(LLMProviderConfig.config_key == "default")
    )
    return result.scalar_one_or_none()


def _record_view(record: LLMProviderConfig) -> dict:
    return {
        "source": "database",
        "provider_name": record.provider_name,
        "protocol": record.protocol,
        "base_url": record.base_url,
        "model": record.model,
        "api_key_configured": bool(record.api_key_encrypted),
        "api_key_hint": record.api_key_hint,
        "timeout_seconds": record.timeout_seconds,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _environment_view(client: LLMClient) -> dict:
    try:
        config = client.environment_config()
    except LLMConfigurationError:
        # LLM_PROVIDER=database 时，删除数据库配置代表“暂时未配置”，
        # 不应把一次正常的重置操作变成 503。
        return {
            "source": "environment",
            "provider_name": "未配置",
            "protocol": "chat_completions",
            "base_url": "",
            "model": "",
            "api_key_configured": False,
            "api_key_hint": None,
            "timeout_seconds": None,
            "updated_at": None,
        }
    return {
        "source": "environment",
        "provider_name": config.provider_name,
        "protocol": config.protocol,
        "base_url": config.base_url,
        "model": config.model,
        "api_key_configured": bool(config.api_key),
        "api_key_hint": None,
        "timeout_seconds": config.timeout_seconds,
        "updated_at": None,
    }


async def _validate_public_endpoint(base_url: str) -> None:
    try:
        await ensure_safe_llm_base_url(base_url)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    record = await _record(db)
    return success(_record_view(record) if record else _environment_view(LLMClient()))


@router.put("")
async def save_llm_config(
    body: LLMConfigPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    await _validate_public_endpoint(body.base_url)
    record = await _record(db)
    api_key = body.api_key
    if record is None and not api_key:
        raise HTTPException(status_code=422, detail="首次保存必须填写 API Key")

    if record is None:
        record = LLMProviderConfig(config_key="default", api_key_encrypted="")
        db.add(record)

    record.provider_name = body.provider_name
    record.protocol = body.protocol
    record.base_url = body.base_url
    record.model = body.model
    record.timeout_seconds = body.timeout_seconds
    record.is_active = True
    record.updated_by = current_user.id
    if api_key:
        record.api_key_encrypted = encrypt_secret(api_key)
        record.api_key_hint = f"****{api_key[-4:]}" if len(api_key) >= 4 else "****"

    await db.commit()
    await db.refresh(record)
    return success(_record_view(record), message="模型配置已保存并立即生效")


@router.post("/test")
async def test_llm_config(
    body: LLMConfigPayload,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    await _validate_public_endpoint(body.base_url)
    api_key = body.api_key
    if not api_key:
        record = await _record(db)
        if record and record.api_key_encrypted:
            try:
                api_key = decrypt_secret(record.api_key_encrypted)
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail="已保存的 API Key 无法解密，请重新填写"
                ) from exc
    if not api_key:
        raise HTTPException(status_code=422, detail="测试连接需要填写 API Key")

    runtime = LLMRuntimeConfig(
        provider_name=body.provider_name,
        protocol=body.protocol,
        base_url=body.base_url,
        model=body.model,
        api_key=api_key,
        timeout_seconds=body.timeout_seconds,
        source="test",
    )
    started = time.perf_counter()
    result = await LLMClient(runtime_override=runtime).generate(
        prompt="请只回复 OK",
        n=1,
        temperature=0,
        max_tokens=32,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    preview = re.sub(r"\s+", " ", result[0]).strip()[:200]
    return success(
        {
            "ok": True,
            "provider_name": body.provider_name,
            "model": body.model,
            "protocol": body.protocol,
            "latency_ms": latency_ms,
            "preview": preview,
        },
        message="模型连接测试成功",
    )


@router.delete("")
async def restore_environment_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    record = await _record(db)
    if record:
        await db.delete(record)
        await db.commit()
    return success(_environment_view(LLMClient()), message="已恢复环境变量配置")
