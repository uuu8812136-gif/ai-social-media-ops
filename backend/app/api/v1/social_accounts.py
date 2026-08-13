"""社媒账号 API - 可视网页登录、Cookie 状态、账号管理。

所有路由前缀：/social/accounts
- GET /                列表
- POST /login/start    启动可视网页登录（返回站内浏览器会话）
- GET  /login/status   轮询登录状态
- POST /login/cancel   取消登录
- POST /{id}/validate  校验 Cookie 状态
- POST /{id}/sync      同步账号信息
- DELETE /{id}         删除账号 + cookie
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.social_account import (
    PublishTask,
    PublishTaskLog,
    SocialAccount,
    SocialPostMetric,
)
from app.models.user import User
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/social/accounts", tags=["social-accounts"])


# ===== Schemas =====


class LoginStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    platform: Literal["xiaohongshu", "douyin", "channels", "kuaishou", "bilibili"]
    account_id: str | None = Field(default=None, min_length=1, max_length=100)


class PostVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Literal["public", "friends", "private"]


class SocialAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    remark: str | None = Field(default=None, max_length=1000)
    linked_account_id: uuid.UUID | None = None
    status: Literal["active", "disabled"] | None = None
    owner_id: uuid.UUID | None = None


class SocialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    platform_uid: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    cookie_status: str
    last_validated_at: datetime | None = None
    user_info: dict[str, Any] | None = None
    linked_account_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    remark: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    red_id: str | None = None
    username: str | None = None
    login_ip: str | None = None
    current_ip: str | None = None


# ===== 路由 =====


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for") if request.headers else None
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    real_ip = request.headers.get("x-real-ip") if request.headers else None
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None


def _merge_user_info_dict(old: dict | None, new: dict | None) -> dict | None:
    merged: dict[str, Any] = {"extra": {}}
    for part in (old or {}, new or {}):
        for key, value in part.items():
            if key == "extra" and isinstance(value, dict):
                for ek, ev in value.items():
                    if ev not in (None, ""):
                        merged["extra"][ek] = ev
            elif value not in (None, ""):
                merged[key] = value
    if not merged.get("extra"):
        merged.pop("extra", None)
    return merged if merged else None


def _account_out(account: SocialAccount, *, current_ip: str | None = None) -> dict:
    data = SocialAccountOut.model_validate(account).model_dump()
    info = data.get("user_info") or {}
    extra = info.get("extra") or {}
    data["red_id"] = extra.get("red_id")
    data["username"] = info.get("username") or extra.get("username")
    data["login_ip"] = (
        extra.get("last_login_ip")
        or extra.get("last_validated_ip")
        or extra.get("last_seen_ip")
    )
    data["current_ip"] = current_ip
    return data


def _refresh_account_metadata_from_cookie(account: SocialAccount) -> bool:
    """Repair nickname/platform_uid/avatar/user_info from saved Playwright storage_state."""
    if not account.platform_uid:
        return False
    from app.integrations.synapse_engine.service import (
        EmbeddedSynapseService,
        extract_user_info_from_storage_state,
    )

    service = EmbeddedSynapseService()
    state = service.cookie_manager.load(account.platform, account.platform_uid)
    if not state:
        if account.cookie_status == "valid":
            account.cookie_status = "invalid"
            return True
        return False
    meta = extract_user_info_from_storage_state(account.platform, state)
    if not meta:
        return False

    changed = False
    extra = meta.get("extra") or {}
    real_uid = meta.get("user_id") or extra.get("user_id") or extra.get("red_id")
    if (
        real_uid
        and account.platform_uid.startswith("temp_")
        and str(real_uid) != account.platform_uid
    ):
        old_uid = account.platform_uid
        service.cookie_manager.save(account.platform, str(real_uid), state)
        service.cookie_manager.delete(account.platform, old_uid)
        account.platform_uid = str(real_uid)
        account.cookie_file = f"{account.platform}_{real_uid}.json"
        changed = True

    merged = _merge_user_info_dict(account.user_info, meta)
    if merged != account.user_info:
        account.user_info = merged
        changed = True
    display_name = (meta.get("name") or "").strip()
    if not display_name and not account.nickname:
        display_name = (meta.get("username") or "").strip()
    if display_name and account.nickname != display_name:
        account.nickname = display_name
        changed = True
    avatar = meta.get("avatar")
    if avatar and account.avatar_url != avatar:
        account.avatar_url = avatar
        changed = True
    return changed


@router.get("/")
async def list_social_accounts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(SocialAccount)
    if platform:
        query = query.where(SocialAccount.platform == platform)
    if status:
        query = query.where(SocialAccount.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(SocialAccount.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    accounts = list(result.scalars().all())
    changed = False
    current_ip = _client_ip(request)
    for account in accounts:
        changed = _refresh_account_metadata_from_cookie(account) or changed
        if current_ip:
            info = account.user_info or {}
            extra = dict((info.get("extra") or {}) if isinstance(info, dict) else {})
            if extra.get("last_seen_ip") != current_ip:
                extra["last_seen_ip"] = current_ip
                account.user_info = _merge_user_info_dict(info, {"extra": extra})
                changed = True
    if changed:
        await db.commit()
        for account in accounts:
            await db.refresh(account)
    items = [_account_out(a, current_ip=current_ip) for a in accounts]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/platforms")
async def list_platforms(
    _: User = Depends(require_roles("admin", "operator")),
):
    """列出支持发布 / 扫码登录的平台及其真实能力状态（verified/beta/planned）。"""
    from app.integrations.platform_capabilities import publish_platforms

    return success(publish_platforms())


def _check_playwright_browser() -> None:
    """预检 Playwright Chromium 浏览器是否已安装，未安装时抛出 HTTPException(400)。

    避免把 Playwright 的英文 stack trace（含超长路径）原样丢给前端。
    """
    from app.core.config import get_settings
    from app.integrations.synapse_engine.utils.playwright_provider import (
        PlaywrightBrowserMissingError,
        assert_chromium_ready,
        friendly_playwright_error,
    )

    settings = get_settings()
    try:
        assert_chromium_ready(
            settings.SYNAPSE_LOCAL_CHROME_PATH,
            headless=settings.SYNAPSE_PLAYWRIGHT_HEADLESS,
        )
    except PlaywrightBrowserMissingError as e:
        raise HTTPException(
            status_code=400,
            detail=friendly_playwright_error(e),
        )


@router.post("/login/start")
async def start_login(
    body: LoginStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """启动账号网页登录流程；原生模式会在 Mac 上直接弹出 Chrome。"""
    # 预检 Playwright 浏览器，避免 500 + 英文 stack
    _check_playwright_browser()

    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    service = EmbeddedSynapseService()
    try:
        result = await service.start_login(
            platform=body.platform,
            account_id=body.account_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        from app.integrations.synapse_engine.utils.playwright_provider import (
            friendly_playwright_error,
            is_playwright_browser_missing_error,
        )

        if is_playwright_browser_missing_error(e):
            raise HTTPException(
                status_code=400,
                detail=friendly_playwright_error(e),
            )
        # 其它错误截断，避免超长英文堆栈
        short_msg = friendly_playwright_error(e)
        raise HTTPException(status_code=500, detail=f"启动登录浏览器失败：{short_msg}")

    return success(
        {
            "session_id": result["session_id"],
            "platform": result["platform"],
            "platform_name": result.get("platform_name"),
            "login_mode": result.get("login_mode") or "visual_browser",
            "presentation": result.get("presentation") or "embedded_vnc",
            "qr_image": result["qr_image"],
            "qr_url": result["qr_url"],
            "expires_in": result["expires_in"],
            "manual_verification": result.get("manual_verification") or {
                "available": False
            },
        }
    )


@router.get("/login/status")
async def poll_login_status(
    request: Request,
    session_id: str = Query(
        ..., min_length=1, max_length=100, description="登录会话 ID"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """轮询网页登录状态。登录成功会自动创建 SocialAccount 记录。"""
    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    service = EmbeddedSynapseService()
    try:
        result = await service.poll_login_status(session_id)
    except Exception as e:
        # 轮询异常时清理 session，避免前端一直轮询无效 session
        try:
            await service.cancel_login(session_id)
        except Exception:
            pass
        short_msg = str(e).split("\n")[0][:200]
        raise HTTPException(status_code=500, detail=f"查询登录状态失败：{short_msg}")

    # 登录成功时落库
    if result.get("status") == "confirmed":
        platform = result["platform"]
        account_id_str = result["account_id"]
        user_info = result.get("user_info") or {}
        client_ip = _client_ip(request)
        if client_ip:
            extra = dict(user_info.get("extra") or {})
            extra["last_login_ip"] = client_ip
            user_info["extra"] = extra

        # 用 account_id_str 作为 platform_uid 查重
        existing = await db.execute(
            select(SocialAccount).where(
                SocialAccount.platform == platform,
                SocialAccount.platform_uid == account_id_str,
            )
        )
        account = existing.scalar_one_or_none()
        if account is None:
            # Reuse the latest stale temp_* row for this platform/user to avoid duplicate rows
            # after a re-login repairs the real platform uid.
            reusable = await db.execute(
                select(SocialAccount)
                .where(
                    SocialAccount.platform == platform,
                    SocialAccount.owner_id == current_user.id,
                    SocialAccount.platform_uid.like("temp_%"),
                )
                .order_by(SocialAccount.created_at.desc())
            )
            account = reusable.scalar_one_or_none()

        if account is None:
            account = SocialAccount(
                platform=platform,
                platform_uid=account_id_str,
                nickname=user_info.get("name") or user_info.get("username"),
                avatar_url=user_info.get("avatar"),
                cookie_file=f"{platform}_{account_id_str}.json",
                cookie_status="valid",
                last_validated_at=datetime.now(timezone.utc),
                user_info=user_info,
                owner_id=current_user.id,
                status="active",
            )
            db.add(account)
        else:
            account.platform_uid = account_id_str
            account.cookie_file = f"{platform}_{account_id_str}.json"
            account.cookie_status = "valid"
            account.last_validated_at = datetime.now(timezone.utc)
            account.user_info = user_info
            if user_info.get("name"):
                account.nickname = user_info["name"]
            if user_info.get("avatar"):
                account.avatar_url = user_info["avatar"]
        await db.commit()
        await db.refresh(account)
        result["social_account_id"] = str(account.id)

    return success(result)


@router.post("/login/cancel")
async def cancel_login(
    session_id: str = Query(
        ..., min_length=1, max_length=100, description="登录会话 ID"
    ),
    _: User = Depends(require_roles("admin", "operator")),
):
    """取消网页登录会话。"""
    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    service = EmbeddedSynapseService()
    result = await service.cancel_login(session_id)
    return success(result)


@router.post("/{account_id}/validate")
async def validate_account_cookie(
    account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """校验账号 Cookie 状态（同步调用，会启动浏览器，可能慢）。"""
    result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not account.platform_uid:
        raise HTTPException(
            status_code=400, detail="账号缺少 platform_uid，无法校验 Cookie"
        )

    _refresh_account_metadata_from_cookie(account)

    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    service = EmbeddedSynapseService()
    result = await service.validate_account_cookie(
        account.platform, account.platform_uid
    )

    account.cookie_status = "valid" if result.get("valid") else "invalid"
    account.last_validated_at = datetime.now(timezone.utc)

    # Merge online metadata returned by Playwright validation. This repairs
    # temp_* ids and replaces generic page titles with the real account name.
    result_user_info = result.get("user_info") or {}
    if result.get("valid") and result_user_info:
        extra = result_user_info.get("extra") or {}
        real_uid = (
            result_user_info.get("user_id")
            or extra.get("user_id")
            or extra.get("mid")
            or extra.get("kwai_id")
            or extra.get("douyin_unique_id")
        )
        should_replace_uid = bool(
            real_uid
            and account.platform_uid
            and str(real_uid) != account.platform_uid
            and (
                account.platform_uid.startswith("temp_")
                or account.platform in {"douyin", "bilibili", "kuaishou", "channels"}
            )
        )
        if should_replace_uid:
            old_uid = account.platform_uid
            state = service.cookie_manager.load(account.platform, old_uid)
            if state:
                service.cookie_manager.save(account.platform, str(real_uid), state)
                service.cookie_manager.delete(account.platform, old_uid)
            account.platform_uid = str(real_uid)
            account.cookie_file = f"{account.platform}_{real_uid}.json"
        merged = _merge_user_info_dict(account.user_info, result_user_info)
        if merged:
            account.user_info = merged
        display_name = (result_user_info.get("name") or "").strip()
        if not display_name and not account.nickname:
            display_name = (result_user_info.get("username") or "").strip()
        if display_name:
            account.nickname = display_name
        avatar = result_user_info.get("avatar")
        if avatar:
            account.avatar_url = avatar

    ip = _client_ip(request)
    if ip:
        info = account.user_info or {}
        extra = dict((info.get("extra") or {}) if isinstance(info, dict) else {})
        extra["last_validated_ip"] = ip
        account.user_info = _merge_user_info_dict(info, {"extra": extra})
    await db.commit()
    await db.refresh(account)

    return success(
        {
            "account_id": str(account.id),
            "platform": account.platform,
            "account": _account_out(account, current_ip=ip),
            **result,
        }
    )


@router.post("/{account_id}/validate-async")
async def validate_account_cookie_async(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """异步派发 Cookie 校验到 Celery worker（不阻塞 API）。"""
    result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not account.platform_uid:
        raise HTTPException(status_code=400, detail="账号缺少 platform_uid")

    from app.integrations.synapse_engine.workers.tasks import run_cookie_validate

    async_result = run_cookie_validate.delay(account.platform, account.platform_uid)

    return success(
        {
            "account_id": str(account.id),
            "celery_task_id": getattr(async_result, "id", ""),
            "message": "Cookie 校验已派发到 worker，请稍后查看 cookie_status 字段",
        }
    )


@router.post("/{account_id}/sync")
async def sync_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """同步账号信息（重新加载 cookie + 校验）。"""
    result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    # 触发异步校验
    from app.integrations.synapse_engine.workers.tasks import run_cookie_validate

    async_result = run_cookie_validate.delay(
        account.platform, account.platform_uid or ""
    )
    return success(
        {
            "account_id": str(account.id),
            "celery_task_id": getattr(async_result, "id", ""),
            "message": "已派发同步任务到 worker",
        }
    )


@router.delete("/{account_id}")
async def delete_social_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """删除社媒账号 + 删除本地 cookie 文件。"""
    result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    # 删除 cookie 文件
    if account.platform_uid:
        from app.integrations.synapse_engine.service import EmbeddedSynapseService

        service = EmbeddedSynapseService()
        service.delete_account_cookie(account.platform, account.platform_uid)

    await db.delete(account)
    await db.commit()
    return success({"account_id": str(account_id), "deleted": True})


@router.put("/{account_id}")
async def update_social_account(
    account_id: uuid.UUID,
    body: SocialAccountUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """更新社媒账号信息（备注、关联账号等）。"""
    result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    for field in body.model_fields_set:
        setattr(account, field, getattr(body, field))
    await db.commit()
    await db.refresh(account)
    return success(SocialAccountOut.model_validate(account).model_dump())


# ===== 账号发布内容 + 指标 =====


@router.get("/{account_id}/posts")
async def list_account_posts(
    account_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """获取社媒账号发布过的任务列表，附带指标数据。"""
    # 确认账号存在
    acc_result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    query = select(PublishTask).where(PublishTask.social_account_id == account_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(PublishTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    tasks = result.scalars().all()

    # 批量加载指标
    task_ids = [t.id for t in tasks]
    metrics_map: dict = {}
    if task_ids:
        metrics_result = await db.execute(
            select(SocialPostMetric).where(SocialPostMetric.task_id.in_(task_ids))
        )
        for m in metrics_result.scalars().all():
            metrics_map[str(m.task_id)] = {
                "metrics": m.metrics,
                "sync_status": m.sync_status,
                "last_synced_at": m.last_synced_at.isoformat()
                if m.last_synced_at
                else None,
                "error_message": m.error_message,
            }

    items = []
    for t in tasks:
        items.append(
            {
                "id": str(t.id),
                "social_account_id": str(t.social_account_id)
                if t.social_account_id
                else None,
                "title": t.title,
                "description": (t.description or "")[:200],
                "platform": t.platform,
                "status": t.status,
                "publish_mode": t.publish_mode,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "external_post_id": t.external_post_id,
                "publish_url": t.publish_url,
                "error_message": t.error_message,
                "media_count": len(t.media_paths or []),
                "tags": t.tags or [],
                "publish_params": t.publish_params or {},
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                "metrics": metrics_map.get(str(t.id), {}).get("metrics"),
                "metric_sync_status": metrics_map.get(str(t.id), {}).get("sync_status"),
                "metric_last_synced": metrics_map.get(str(t.id), {}).get(
                    "last_synced_at"
                ),
                "metric_error": metrics_map.get(str(t.id), {}).get("error_message"),
            }
        )

    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/{account_id}/posts/{task_id}")
async def get_account_post_detail(
    account_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """获取单条发布任务详情、日志、素材、指标。"""
    result = await db.execute(
        select(PublishTask).where(
            PublishTask.id == task_id,
            PublishTask.social_account_id == account_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")

    # 加载日志
    logs_result = await db.execute(
        select(PublishTaskLog)
        .where(PublishTaskLog.task_id == task_id)
        .order_by(PublishTaskLog.created_at)
    )
    logs = [
        {
            "level": log.level,
            "message": log.message,
            "extra": log.extra,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs_result.scalars().all()
    ]

    # 加载指标
    metric_result = await db.execute(
        select(SocialPostMetric).where(SocialPostMetric.task_id == task_id)
    )
    metric = metric_result.scalar_one_or_none()
    metric_data = None
    raw_data = None
    if metric:
        metric_data = {
            "metrics": metric.metrics,
            "sync_status": metric.sync_status,
            "source": metric.source,
            "last_synced_at": metric.last_synced_at.isoformat()
            if metric.last_synced_at
            else None,
            "error_message": metric.error_message,
        }
        raw_data = metric.raw_data

    return success(
        {
            "id": str(task.id),
            "social_account_id": str(task.social_account_id)
            if task.social_account_id
            else None,
            "title": task.title,
            "description": task.description,
            "platform": task.platform,
            "status": task.status,
            "publish_mode": task.publish_mode,
            "scheduled_at": task.scheduled_at.isoformat()
            if task.scheduled_at
            else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "external_post_id": task.external_post_id,
            "publish_url": task.publish_url,
            "error_message": task.error_message,
            "media_paths": task.media_paths or [],
            "cover_path": task.cover_path,
            "tags": task.tags or [],
            "publish_params": task.publish_params or {},
            "retry_count": task.retry_count,
            "celery_task_id": task.celery_task_id,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "logs": logs,
            "metric": metric_data,
            "raw_data": raw_data,
        }
    )


@router.post("/{account_id}/posts/{task_id}/delete")
async def delete_account_post(
    account_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """删除/下架单条已发布内容（通过平台网页自动化执行）。"""
    acc_result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not account.platform_uid:
        raise HTTPException(
            status_code=400, detail="账号缺少 platform_uid，无法读取 Cookie"
        )

    task_result = await db.execute(
        select(PublishTask).where(
            PublishTask.id == task_id,
            PublishTask.social_account_id == account_id,
        )
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    if task.status not in {"published", "reviewing"}:
        raise HTTPException(
            status_code=400, detail=f"任务状态 {task.status} 不能执行平台删除"
        )

    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    service = EmbeddedSynapseService()
    result = await service.delete_published_content(
        platform=task.platform,
        account_id=account.platform_uid,
        publish_url=task.publish_url,
        external_post_id=task.external_post_id,
        title=task.title,
    )

    ok = bool(result.get("success"))
    task_log = PublishTaskLog(
        task_id=task.id,
        level="info" if ok else "error",
        message=result.get("message") or result.get("error") or "平台内容删除操作完成",
        extra=result,
    )
    db.add(task_log)

    if ok:
        task.status = "deleted"
        task.error_message = None
        task.finished_at = datetime.now(timezone.utc)
        metric_result = await db.execute(
            select(SocialPostMetric).where(SocialPostMetric.task_id == task.id)
        )
        metric = metric_result.scalar_one_or_none()
        if metric:
            metric.sync_status = "unavailable"
            metric.error_message = "内容已删除/下架"
    else:
        task.error_message = result.get("error") or "平台内容删除失败"

    await db.commit()
    if not ok:
        raise HTTPException(status_code=400, detail=task.error_message)
    return success(
        {
            "task_id": str(task.id),
            "status": task.status,
            "deleted": True,
            "result": result,
        }
    )


@router.post("/{account_id}/posts/{task_id}/visibility")
async def update_account_post_visibility(
    account_id: uuid.UUID,
    task_id: uuid.UUID,
    body: PostVisibilityRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """调整单条已发布内容可见性（通过平台网页自动化执行）。"""
    visibility = body.visibility

    acc_result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not account.platform_uid:
        raise HTTPException(
            status_code=400, detail="账号缺少 platform_uid，无法读取 Cookie"
        )

    task_result = await db.execute(
        select(PublishTask).where(
            PublishTask.id == task_id,
            PublishTask.social_account_id == account_id,
        )
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    if task.status not in {"published", "reviewing"}:
        raise HTTPException(
            status_code=400, detail=f"任务状态 {task.status} 不能调整平台可见性"
        )
    if task.platform == "bilibili" and visibility != "public":
        raise HTTPException(
            status_code=400,
            detail="B站网页发布/管理页没有稳定的仅自己可见选项，请按公开内容处理",
        )

    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    service = EmbeddedSynapseService()
    result = await service.update_published_visibility(
        platform=task.platform,
        account_id=account.platform_uid,
        visibility=visibility,
        publish_url=task.publish_url,
        external_post_id=task.external_post_id,
        title=task.title,
    )

    ok = bool(result.get("success"))
    db.add(
        PublishTaskLog(
            task_id=task.id,
            level="info" if ok else "error",
            message=result.get("message")
            or result.get("error")
            or "平台内容可见性调整完成",
            extra=result,
        )
    )

    if ok:
        params = dict(task.publish_params or {})
        params["visibility"] = visibility
        task.publish_params = params
        task.error_message = None
    else:
        task.error_message = result.get("error") or "平台内容可见性调整失败"

    await db.commit()
    if not ok:
        raise HTTPException(status_code=400, detail=task.error_message)
    return success(
        {
            "task_id": str(task.id),
            "visibility": visibility,
            "result": result,
        }
    )


@router.post("/{account_id}/posts/{task_id}/sync-metrics")
async def sync_post_metrics(
    account_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """派发 Celery 任务同步单条内容的指标数据。"""
    result = await db.execute(
        select(PublishTask).where(
            PublishTask.id == task_id,
            PublishTask.social_account_id == account_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")

    from app.integrations.synapse_engine.workers.tasks import run_sync_post_metrics

    async_result = run_sync_post_metrics.delay(
        str(task.id),
        str(account_id),
        task.platform,
        task.publish_url or "",
        task.external_post_id or "",
    )

    # 更新 metric 状态为 pending
    metric_result = await db.execute(
        select(SocialPostMetric).where(SocialPostMetric.task_id == task_id)
    )
    metric = metric_result.scalar_one_or_none()
    if metric is None:
        metric = SocialPostMetric(
            task_id=task.id,
            social_account_id=account_id,
            content_id=task.content_id,
            platform=task.platform,
            external_post_id=task.external_post_id,
            publish_url=task.publish_url,
            source="browser",
            sync_status="pending",
        )
        db.add(metric)
    else:
        metric.sync_status = "pending"
        metric.error_message = None
    await db.commit()

    return success(
        {
            "task_id": str(task.id),
            "celery_task_id": getattr(async_result, "id", ""),
            "sync_status": "pending",
            "message": "指标同步任务已派发到 worker",
        }
    )


@router.post("/{account_id}/sync-posts")
async def sync_account_posts(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """批量同步该账号近期发布内容的指标（结构预留，当前派发最近 20 条 pending 的任务）。"""
    acc_result = await db.execute(
        select(SocialAccount).where(SocialAccount.id == account_id)
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    # 查找该账号最近 20 条已发布但 metric 为 pending 或无 metric 的任务
    result = await db.execute(
        select(PublishTask)
        .where(
            PublishTask.social_account_id == account_id,
            PublishTask.status.in_(["published", "reviewing"]),
        )
        .order_by(PublishTask.created_at.desc())
        .limit(20)
    )
    tasks = result.scalars().all()

    from app.integrations.synapse_engine.workers.tasks import run_sync_post_metrics

    dispatched = 0
    for task in tasks:
        metric_result = await db.execute(
            select(SocialPostMetric).where(SocialPostMetric.task_id == task.id)
        )
        metric = metric_result.scalar_one_or_none()
        if metric is None:
            metric = SocialPostMetric(
                task_id=task.id,
                social_account_id=account_id,
                content_id=task.content_id,
                platform=task.platform,
                external_post_id=task.external_post_id,
                publish_url=task.publish_url,
                source="browser",
                sync_status="pending",
            )
            db.add(metric)
        elif metric.sync_status == "synced":
            continue  # 已同步的跳过
        else:
            metric.sync_status = "pending"
            metric.error_message = None

        run_sync_post_metrics.delay(
            str(task.id),
            str(account_id),
            task.platform,
            task.publish_url or "",
            task.external_post_id or "",
        )
        dispatched += 1

    await db.commit()

    return success(
        {
            "account_id": str(account_id),
            "total_tasks": len(tasks),
            "dispatched": dispatched,
            "message": f"已派发 {dispatched} 个指标同步任务到 worker",
        }
    )
