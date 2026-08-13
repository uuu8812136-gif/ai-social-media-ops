"""社媒发布任务 API。

路由前缀：/social/publish
- POST /                创建发布批次 + 派发任务到 Celery worker
- GET  /tasks           任务列表
- GET  /tasks/{id}      任务详情
- POST /tasks/{id}/retry 重试任务
- POST /tasks/{id}/cancel 取消任务
- GET  /batches         批次列表
- GET  /batches/{id}    批次详情
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.content import Content
from app.models.social_account import (
    PublishBatch,
    PublishTask,
    PublishTaskLog,
    SocialAccount,
)
from app.models.user import User
from app.utils.url_safety import normalize_public_http_url
from app.integrations.synapse_engine.verification.manager import (
    VerificationError,
    VerificationTimeout,
    verification_manager,
)
from app.utils.response import PaginationMeta, success
from app.utils.social_text import sanitize_publish_text

router = APIRouter(prefix="/social/publish", tags=["social-publish"])
logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
_MEDIA_REQUIRED_PLATFORMS = {
    "xiaohongshu",
    "douyin",
    "kuaishou",
    "bilibili",
    "channels",
}
_VIDEO_ONLY_PLATFORMS = {"douyin", "kuaishou", "bilibili", "channels"}
_PLATFORM_LABELS = {
    "xiaohongshu": "xiaohongshu",
    "douyin": "douyin",
    "kuaishou": "kuaishou",
    "bilibili": "bilibili",
    "channels": "channels",
}
_PUBLISHABLE_CONTENT_STATUSES = {"approved", "human_reviewed"}
_DUPLICATE_ACTIVE_STATUSES = {
    "pending",
    "scheduled",
    "queued",
    "running",
    "needs_phone_captcha",
    "needs_human_captcha",
    "awaiting_resume",
    "publish_unknown",
    "published",
    "reviewing",
}
_RETRYABLE_TASK_STATUSES = {
    "failed",
    "cancelled",
    "media_required",
    "publish_error",
    "cookie_missing",
    "cookie_invalid",
    "dispatch_failed",
    "account_restricted",
    "pending",
    "not_published",
}


def _validate_media_reference(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError("素材地址不能为空")
    parsed = urlparse(value)
    if value.startswith("/"):
        if value.startswith("//") or "\\" in value or ".." in parsed.path.split("/"):
            raise ValueError("站内素材地址格式非法")
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("素材地址必须是 HTTP(S) URL 或站内相对路径")
    if parsed.username or parsed.password:
        raise ValueError("素材地址不能包含 URL 凭证")
    return value


def _content_media_urls(content: Content) -> list[str]:
    return [str(x).strip() for x in (content.media_urls or []) if str(x or "").strip()]


def _is_video_url(url: str) -> bool:
    return Path(urlparse(str(url)).path).suffix.lower() in _VIDEO_EXTS


def _clean_str_list(items: list[Any] | None) -> list[str]:
    return [str(x).strip() for x in (items or []) if str(x or "").strip()]


def _assert_media_urls_ready(platform: str, media_urls: list[str] | None) -> list[str]:
    try:
        media_urls = [
            _validate_media_reference(item) for item in _clean_str_list(media_urls)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    platform_label = _PLATFORM_LABELS.get(platform, platform)
    if platform in _MEDIA_REQUIRED_PLATFORMS and not media_urls:
        raise HTTPException(
            status_code=400,
            detail=f"{platform_label} publish blocked: no image/video media attached. Please choose media from Asset Library before publishing.",
        )
    if platform in _VIDEO_ONLY_PLATFORMS and not any(
        _is_video_url(u) for u in media_urls
    ):
        raise HTTPException(
            status_code=400,
            detail=f"{platform_label} publish blocked: this publishing entry requires video media such as mp4/mov.",
        )
    return media_urls


def _assert_publish_media_ready(
    platform: str, content: Content, override_media_urls: list[str] | None = None
) -> list[str]:
    media_urls = (
        _clean_str_list(override_media_urls)
        if override_media_urls is not None
        else _content_media_urls(content)
    )
    return _assert_media_urls_ready(platform, media_urls)


def _normalize_publish_params(params: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(params or {})
    if data.get("topics") is None:
        data["topics"] = []
    if isinstance(data.get("topics"), str):
        data["topics"] = [
            x.strip().lstrip("#") for x in data["topics"].split(",") if x.strip()
        ]
    if data.get("tags") is None:
        data["tags"] = []
    if isinstance(data.get("tags"), str):
        data["tags"] = [
            x.strip().lstrip("#") for x in data["tags"].split(",") if x.strip()
        ]
    visibility = str(data.get("visibility") or "public").strip()
    if visibility not in {"public", "friends", "private"}:
        visibility = "public"
    data["visibility"] = visibility
    return data


def _publish_fingerprint(
    *,
    account_id: uuid.UUID,
    platform: str,
    title: str,
    description: str,
    tags: list[str],
    media_paths: list[str],
    cover_path: str | None,
    publish_params: dict[str, Any],
) -> str:
    """生成稳定发布摘要，用于识别同账号的重复投递。"""
    payload = {
        "account_id": str(account_id),
        "platform": platform,
        "title": title.strip(),
        "description": description.strip(),
        "tags": sorted(set(tags)),
        "media_paths": sorted(set(media_paths)),
        "cover_path": cover_path or "",
        "publish_params": publish_params,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _task_to_spec(task: PublishTask) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "platform": task.platform,
        "account_id": task.account_ref or "",
        "title": task.title or "",
        "description": task.description or "",
        "tags": task.tags or [],
        "media_paths": task.media_paths or [],
        "cover_path": task.cover_path,
        "publish_mode": "direct",
        "scheduled_at": None,
        "content_id": str(task.content_id) if task.content_id else "",
        "publish_params": task.publish_params or {},
    }


def _can_edit_task_status(status: str) -> bool:
    return status in {
        "pending",
        "scheduled",
        "queued",
        "failed",
        "cancelled",
        "media_required",
        "publish_error",
        "cookie_missing",
        "cookie_invalid",
        "dispatch_failed",
        "account_restricted",
        "not_published",
    }


# 本地时区：前端传裸时间（无时区）时按此时区解释
_LOCAL_TZ_NAME = "Asia/Shanghai"


def _parse_scheduled_at(raw: str | None) -> datetime | None:
    """解析定时时间为带时区的 UTC datetime。

    - 支持 ISO 字符串（含末尾 'Z'）。
    - 无时区信息时按 Asia/Shanghai 解释，再转 UTC。
    - 解析失败抛 400。
    """
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"定时时间格式非法: {raw}")
    if dt.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo(_LOCAL_TZ_NAME))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ===== Schemas =====


class PublishTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    social_account_id: uuid.UUID
    platform: Literal["xiaohongshu", "douyin", "kuaishou", "bilibili", "channels"]


class CreatePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content_id: uuid.UUID
    targets: list[PublishTarget] = Field(min_length=1, max_length=20)
    publish_mode: Literal["direct", "schedule"] = "direct"
    scheduled_at: str | None = None
    # 可选：覆盖内容自身媒体 URL；来自素材库选择或上传素材。
    media_urls: list[str] | None = Field(default=None, max_length=20)
    cover_path: str | None = Field(default=None, max_length=2048)
    # 可选：覆盖内容文案。
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=50)
    # 平台发布参数：visibility/location/topics/allow_download/allow_comment 等。
    publish_params: dict[str, Any] | None = None
    # 同一次点击/网络重试复用同一个键，服务端只创建一个批次。
    request_key: str | None = Field(default=None, min_length=16, max_length=100)
    # 明确需要重复投放同一内容时由运营主动开启。
    allow_duplicate: bool = False


class UpdatePublishTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=50)
    media_paths: list[str] | None = Field(default=None, max_length=20)
    cover_path: str | None = Field(default=None, max_length=2048)
    publish_mode: Literal["direct", "schedule"] | None = None
    scheduled_at: str | None = None
    publish_params: dict[str, Any] | None = None


class ConfirmPublishTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    outcome: Literal["published", "not_published"]
    publish_url: str | None = Field(default=None, max_length=2000)
    external_post_id: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class PublishTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID | None = None
    content_id: uuid.UUID | None = None
    social_account_id: uuid.UUID | None = None
    platform: str
    account_ref: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list | None = None
    media_paths: list | None = None
    cover_path: str | None = None
    publish_params: dict | None = None
    publish_mode: str
    scheduled_at: datetime | None = None
    status: str
    external_post_id: str | None = None
    publish_url: str | None = None
    error_message: str | None = None
    celery_task_id: str | None = None
    retry_count: int = 0
    content_fingerprint: str | None = None
    execution_token: str | None = None
    started_at: datetime | None = None
    confirmation_outcome: str | None = None
    confirmation_note: str | None = None
    confirmed_by: uuid.UUID | None = None
    confirmed_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("publish_url", mode="before")
    @classmethod
    def sanitize_publish_url(cls, value: object) -> str | None:
        return normalize_public_http_url(value)

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, value: object) -> str | None:
        return None if value is None else sanitize_publish_text(value)


class PublishBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_id: uuid.UUID
    creator_id: uuid.UUID | None = None
    title_snapshot: str | None = None
    publish_mode: str
    scheduled_at: datetime | None = None
    status: str
    total: int
    success_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime


async def _existing_batch_response(
    db: AsyncSession, batch: PublishBatch
) -> dict:
    rows = await db.execute(
        select(PublishTask)
        .where(PublishTask.batch_id == batch.id)
        .order_by(PublishTask.created_at.asc())
    )
    tasks = rows.scalars().all()
    return success(
        {
            "batch_id": str(batch.id),
            "content_id": str(batch.content_id),
            "total": batch.total,
            "scheduled": batch.publish_mode == "schedule",
            "scheduled_at": (
                batch.scheduled_at.isoformat() if batch.scheduled_at else None
            ),
            "dispatch_failures": sum(
                task.status == "dispatch_failed" for task in tasks
            ),
            "tasks": [
                {
                    "task_id": str(task.id),
                    "celery_task_id": task.celery_task_id,
                    "status": task.status,
                }
                for task in tasks
            ],
            "reused": True,
        },
        message="重复请求已复用原发布批次",
    )


# ===== 路由 =====


@router.post("/")
async def create_publish_batch(
    body: CreatePublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """创建发布批次 + 派发发布任务到 Celery worker。"""
    if body.request_key:
        existing_batch = await db.scalar(
            select(PublishBatch).where(
                PublishBatch.request_key == body.request_key
            )
        )
        if existing_batch is not None:
            if existing_batch.creator_id != current_user.id:
                raise HTTPException(status_code=409, detail="发布请求标识已被使用")
            return await _existing_batch_response(db, existing_batch)

    # 1. 加载内容
    result = await db.execute(select(Content).where(Content.id == body.content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")
    if content.status not in _PUBLISHABLE_CONTENT_STATUSES:
        raise HTTPException(
            status_code=400, detail="内容必须通过风控并完成人工审核后才能自动发布"
        )
    if not content.risk_check_result or not content.risk_check_result.get("passed"):
        raise HTTPException(status_code=400, detail="内容风控未通过，禁止自动发布")

    # 2. 解析定时：仅当 schedule 模式且时间在未来时才走 eta 调度
    eta_utc = _parse_scheduled_at(body.scheduled_at)
    is_scheduled = body.publish_mode == "schedule"
    if is_scheduled and eta_utc is None:
        raise HTTPException(status_code=400, detail="定时发布必须提供 scheduled_at")
    if is_scheduled and eta_utc <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="定时发布时间必须晚于当前时间")
    if body.cover_path:
        try:
            cover_path = _validate_media_reference(body.cover_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        cover_path = None

    task_title = (body.title or content.title or "").strip()
    task_description = (
        body.description if body.description is not None else content.body_text
    ) or ""
    task_description = sanitize_publish_text(task_description)
    base_tags = body.tags if body.tags is not None else (content.tags or [])
    publish_params = _normalize_publish_params(body.publish_params)
    extra_topics = _clean_str_list(publish_params.get("topics") or [])
    extra_tags = _clean_str_list(publish_params.get("tags") or [])
    task_tags = list(
        dict.fromkeys([*_clean_str_list(base_tags), *extra_topics, *extra_tags])
    )

    # 3. 先校验全部目标，避免部分 Celery 任务已投递后才发现后续目标非法。
    target_ids = [target.social_account_id for target in body.targets]
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(status_code=400, detail="发布目标不能重复")
    account_rows = await db.execute(
        select(SocialAccount).where(SocialAccount.id.in_(target_ids))
    )
    accounts = {account.id: account for account in account_rows.scalars().all()}
    validated_targets: list[tuple[SocialAccount, list[str], str]] = []
    for target in body.targets:
        account = accounts.get(target.social_account_id)
        if not account:
            raise HTTPException(
                status_code=404, detail=f"社媒账号 {target.social_account_id} 不存在"
            )
        if account.platform != target.platform:
            raise HTTPException(
                status_code=400,
                detail=f"账号 {account.id} 平台不匹配：期望 {target.platform}，实际 {account.platform}",
            )
        if account.cookie_status != "valid":
            raise HTTPException(
                status_code=400,
                detail=f"账号 {account.nickname or account.id} 的登录状态无效，请先重新扫码登录",
            )
        media_urls = _assert_publish_media_ready(
            account.platform, content, body.media_urls
        )
        fingerprint = _publish_fingerprint(
            account_id=account.id,
            platform=account.platform,
            title=task_title,
            description=task_description,
            tags=task_tags,
            media_paths=media_urls,
            cover_path=cover_path,
            publish_params=publish_params,
        )
        if not body.allow_duplicate:
            duplicate_since = datetime.now(timezone.utc) - timedelta(hours=24)
            duplicate = await db.scalar(
                select(PublishTask)
                .where(
                    PublishTask.social_account_id == account.id,
                    PublishTask.platform == account.platform,
                    PublishTask.content_fingerprint == fingerprint,
                    PublishTask.status.in_(_DUPLICATE_ACTIVE_STATUSES),
                    PublishTask.created_at >= duplicate_since,
                )
                .order_by(PublishTask.created_at.desc())
                .limit(1)
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "duplicate_publish",
                        "message": (
                            f"检测到同账号 24 小时内已有相同发布任务，"
                            f"状态为 {duplicate.status}。请先确认平台结果；"
                            "确需重复投放时开启“允许重复发布”。"
                        ),
                        "task_id": str(duplicate.id),
                        "status": duplicate.status,
                    },
                )
        validated_targets.append((account, media_urls, fingerprint))

    # 4. 先把批次和全部任务持久化，再投递到 Celery，确保 worker 一定能查到任务记录。
    batch = PublishBatch(
        content_id=content.id,
        creator_id=current_user.id,
        request_key=body.request_key,
        title_snapshot=task_title or content.title,
        publish_mode=body.publish_mode,
        scheduled_at=eta_utc,
        status="scheduled" if is_scheduled else "running",
        total=len(body.targets),
        success_count=0,
        failed_count=0,
    )
    db.add(batch)
    try:
        await db.flush()  # 拿到 batch.id
    except IntegrityError:
        await db.rollback()
        if body.request_key:
            existing_batch = await db.scalar(
                select(PublishBatch).where(
                    PublishBatch.request_key == body.request_key
                )
            )
            if (
                existing_batch is not None
                and existing_batch.creator_id == current_user.id
            ):
                return await _existing_batch_response(db, existing_batch)
        raise

    tasks: list[PublishTask] = []
    for account, media_urls, fingerprint in validated_targets:
        task = PublishTask(
            batch_id=batch.id,
            content_id=content.id,
            social_account_id=account.id,
            platform=account.platform,
            account_ref=account.platform_uid or str(account.id),
            title=task_title,
            description=task_description,
            tags=task_tags,
            media_paths=media_urls,
            cover_path=cover_path,
            content_fingerprint=fingerprint,
            publish_params=publish_params,
            publish_mode=body.publish_mode,
            scheduled_at=eta_utc,
            status="scheduled" if is_scheduled else "queued",
        )
        db.add(task)
        await db.flush()
        tasks.append(task)

    content.status = "scheduled"
    await db.commit()

    # 5. 数据已提交后再派发；单个目标投递失败会保留可重试的任务记录。
    from app.integrations.synapse_engine.workers.tasks import run_publish_task

    created_tasks: list[dict] = []
    dispatch_failures = 0
    for task in tasks:
        task_spec = _task_to_spec(task)
        try:
            if is_scheduled:
                async_result = run_publish_task.apply_async(
                    args=[task_spec], eta=eta_utc
                )
            else:
                async_result = run_publish_task.delay(task_spec)
            task.celery_task_id = getattr(async_result, "id", "")
        except Exception:
            dispatch_failures += 1
            task.status = "dispatch_failed"
            task.error_message = "任务队列暂不可用，请稍后在任务列表重试"
            task.finished_at = datetime.now(timezone.utc)
            logger.exception("发布任务投递失败 task_id=%s", task.id)
        created_tasks.append(
            {
                "task_id": str(task.id),
                "celery_task_id": task.celery_task_id,
                "status": task.status,
            }
        )

    if dispatch_failures:
        from app.integrations.synapse_engine.workers.writeback import (
            _recompute_batch_stats,
        )

        await db.flush()
        await _recompute_batch_stats(db, batch)
    await db.commit()

    return success(
        {
            "batch_id": str(batch.id),
            "content_id": str(content.id),
            "total": batch.total,
            "scheduled": is_scheduled,
            "scheduled_at": eta_utc.isoformat() if is_scheduled else None,
            "dispatch_failures": dispatch_failures,
            "tasks": created_tasks,
        },
        message="发布任务已创建"
        if not dispatch_failures
        else "部分任务队列投递失败，可在任务列表重试",
    )


@router.get("/tasks")
async def list_publish_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    batch_id: uuid.UUID | None = None,
    content_id: uuid.UUID | None = None,
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """发布任务列表。"""
    query = select(PublishTask)
    if batch_id:
        query = query.where(PublishTask.batch_id == batch_id)
    if content_id:
        query = query.where(PublishTask.content_id == content_id)
    if platform:
        query = query.where(PublishTask.platform == platform)
    if status:
        query = query.where(PublishTask.status == status)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(PublishTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        PublishTaskOut.model_validate(t).model_dump() for t in result.scalars().all()
    ]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/tasks/{task_id}")
async def get_publish_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """发布任务详情。"""
    result = await db.execute(select(PublishTask).where(PublishTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    return success(PublishTaskOut.model_validate(task).model_dump())


@router.put("/tasks/{task_id}")
async def update_publish_task(
    task_id: uuid.UUID,
    body: UpdatePublishTaskRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """编辑发布任务内容、素材和发布参数。

    已发布/审核中/执行中的任务不能改；失败、缺素材、已取消、定时待发任务可以改。
    如果任务仍在排队/定时队列中，会先撤销旧 Celery 任务并把状态改成 pending，保存后再点“重新发布”。
    """
    result = await db.execute(select(PublishTask).where(PublishTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    if not _can_edit_task_status(task.status):
        raise HTTPException(
            status_code=400, detail=f"任务状态 {task.status} 不允许编辑"
        )

    if task.celery_task_id and task.status in {"scheduled", "queued", "pending"}:
        try:
            from app.tasks.celery_app import celery_app

            celery_app.control.revoke(task.celery_task_id)
        except Exception as exc:
            logger.warning("撤销旧发布任务失败 task_id=%s: %s", task.id, exc)
        task.celery_task_id = None
        task.status = "pending"

    data = body.model_dump(exclude_unset=True)
    if "title" in data:
        task.title = (data.get("title") or "").strip()
    if "description" in data:
        task.description = sanitize_publish_text(data.get("description"))
    if "tags" in data:
        task.tags = _clean_str_list(data.get("tags") or [])
    if "media_paths" in data:
        task.media_paths = _assert_media_urls_ready(
            task.platform, data.get("media_paths") or []
        )
    if "cover_path" in data:
        raw_cover = data.get("cover_path") or None
        if raw_cover:
            try:
                raw_cover = _validate_media_reference(raw_cover)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        task.cover_path = raw_cover
    if "publish_mode" in data:
        mode = data.get("publish_mode") or "direct"
        task.publish_mode = mode
    if "scheduled_at" in data:
        task.scheduled_at = _parse_scheduled_at(data.get("scheduled_at"))
    if "publish_params" in data:
        params = _normalize_publish_params(data.get("publish_params") or {})
        # topics/tags 属于发布页话题；同步合并进任务 tags，worker 会追加到正文/话题区。
        merged_tags = list(
            dict.fromkeys(
                [
                    *_clean_str_list(task.tags or []),
                    *_clean_str_list(params.get("topics") or []),
                    *_clean_str_list(params.get("tags") or []),
                ]
            )
        )
        task.tags = merged_tags
        task.publish_params = params

    if task.publish_mode == "schedule":
        if task.scheduled_at is None or task.scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400, detail="定时任务必须设置晚于当前时间的发布时间"
            )

    if task.social_account_id:
        task.content_fingerprint = _publish_fingerprint(
            account_id=task.social_account_id,
            platform=task.platform,
            title=task.title or "",
            description=task.description or "",
            tags=_clean_str_list(task.tags or []),
            media_paths=_clean_str_list(task.media_paths or []),
            cover_path=task.cover_path,
            publish_params=_normalize_publish_params(task.publish_params),
        )
    task.error_message = None
    task.finished_at = None
    await db.commit()
    await db.refresh(task)
    return success(PublishTaskOut.model_validate(task).model_dump())


@router.post("/tasks/{task_id}/retry")
async def retry_publish_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """重试发布任务。"""
    result = await db.execute(select(PublishTask).where(PublishTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    if task.status == "publish_unknown":
        raise HTTPException(
            status_code=409,
            detail=(
                "该任务可能已经发布成功。请先使用“确认已发布”或"
                "“确认未发布”，未经确认禁止重发。"
            ),
        )
    if task.status not in _RETRYABLE_TASK_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"任务状态 {task.status} 不允许重试",
        )

    from app.integrations.synapse_engine.workers.tasks import run_publish_task

    _assert_media_urls_ready(task.platform, task.media_paths or [])
    task_spec = _task_to_spec(task)

    eta_utc = (
        task.scheduled_at
        if task.publish_mode == "schedule" and task.scheduled_at
        else None
    )
    try:
        if eta_utc and eta_utc > datetime.now(timezone.utc):
            async_result = run_publish_task.apply_async(args=[task_spec], eta=eta_utc)
            task.status = "scheduled"
        else:
            async_result = run_publish_task.delay(task_spec)
            task.status = "queued"
        task.celery_task_id = getattr(async_result, "id", "")
    except Exception as exc:
        task.status = "dispatch_failed"
        task.error_message = "任务队列暂不可用，请稍后重试"
        task.finished_at = datetime.now(timezone.utc)
        await db.commit()
        logger.exception("重试任务投递失败 task_id=%s", task.id)
        raise HTTPException(
            status_code=503, detail="任务队列暂不可用，任务已保留，请稍后重试"
        ) from exc
    task.retry_count += 1
    task.execution_token = None
    task.started_at = None
    task.confirmation_outcome = None
    task.confirmation_note = None
    task.confirmed_by = None
    task.confirmed_at = None
    task.error_message = None
    if task.batch_id:
        from app.integrations.synapse_engine.workers.writeback import (
            _recompute_batch_stats,
        )

        batch = await db.scalar(
            select(PublishBatch).where(PublishBatch.id == task.batch_id)
        )
        if batch is not None:
            await _recompute_batch_stats(db, batch)
    await db.commit()

    return success(
        {
            "task_id": str(task.id),
            "celery_task_id": task.celery_task_id,
            "status": task.status,
            "retry_count": task.retry_count,
        }
    )


@router.post("/tasks/{task_id}/confirm")
async def confirm_publish_task(
    task_id: uuid.UUID,
    body: ConfirmPublishTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """人工确认 publish_unknown 的真实平台结果。

    只有确认未发布后任务才可重试，防止未知结果直接重发造成重复作品。
    """
    task = await db.scalar(
        select(PublishTask).where(PublishTask.id == task_id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    if task.status != "publish_unknown":
        raise HTTPException(
            status_code=400,
            detail=f"任务状态 {task.status} 不需要人工确认",
        )

    task.confirmation_outcome = body.outcome
    task.confirmation_note = body.note
    task.confirmed_by = current_user.id
    task.confirmed_at = datetime.now(timezone.utc)
    await db.commit()

    if body.outcome == "published":
        from app.integrations.synapse_engine.workers.writeback import (
            writeback_publish_result,
        )

        await writeback_publish_result(
            str(task.id),
            {
                "success": True,
                "status": "published",
                "message": body.note or "运营人员已在平台后台确认发布成功",
                "publish_url": normalize_public_http_url(body.publish_url),
                "external_post_id": body.external_post_id,
                "confirmation": "manual",
            },
        )
    else:
        task = await db.scalar(
            select(PublishTask).where(PublishTask.id == task_id)
        )
        if task is None:
            raise HTTPException(status_code=404, detail="发布任务不存在")
        task.status = "not_published"
        task.error_message = "已人工确认平台未发布，可以安全重试"
        task.finished_at = datetime.now(timezone.utc)
        if task.batch_id:
            from app.integrations.synapse_engine.workers.writeback import (
                _recompute_batch_stats,
            )

            batch = await db.scalar(
                select(PublishBatch).where(PublishBatch.id == task.batch_id)
            )
            if batch is not None:
                await _recompute_batch_stats(db, batch)
        await db.commit()

    refreshed = await db.scalar(
        select(PublishTask).where(PublishTask.id == task_id)
    )
    return success(PublishTaskOut.model_validate(refreshed).model_dump())


@router.post("/tasks/{task_id}/cancel")
async def cancel_publish_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """取消发布任务（标记为 cancelled，Celery 任务无法强制终止）。"""
    result = await db.execute(select(PublishTask).where(PublishTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")
    if task.status not in ("queued", "pending", "running", "scheduled"):
        raise HTTPException(status_code=400, detail=f"任务状态 {task.status} 无法取消")

    previous_status = task.status
    task.status = "cancelled"
    task.finished_at = datetime.now(timezone.utc)
    # 先落库，worker 即使同时回写也会看到 cancelled 并拒绝覆盖。
    await db.commit()

    # 排队任务撤销消息；运行中任务终止当前 worker 子进程，Celery 会自动补充。
    if task.celery_task_id:
        try:
            from app.tasks.celery_app import celery_app

            celery_app.control.revoke(
                task.celery_task_id,
                terminate=previous_status == "running",
                signal="SIGTERM",
            )
        except Exception as exc:  # 撤销失败不阻断状态更新
            logger.warning("撤销发布任务失败 task_id=%s: %s", task.id, exc)

    native_session_id = str(
        (task.verification_meta or {}).get("native_session_id")
        or (task.verification_meta or {}).get("session_id")
        or (task.verification_meta or {}).get("vnc_session_id")
        or ""
    )
    if native_session_id:
        try:
            from app.integrations.synapse_engine.native_browser import (
                native_browser_manager,
            )

            await native_browser_manager.release(native_session_id)
        except Exception as exc:
            logger.warning(
                "取消任务后关闭原生浏览器失败 task_id=%s session=%s: %s",
                task.id,
                native_session_id,
                exc,
            )
    return success({"task_id": str(task.id), "status": task.status})


@router.post("/tasks/{task_id}/result")
async def writeback_publish_result(
    task_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    """Worker 回写发布结果。

    由 Celery worker 在任务执行完成后调用（也可手动调用）。
    """
    result = await db.execute(select(PublishTask).where(PublishTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="发布任务不存在")

    from app.integrations.synapse_engine.workers.writeback import (
        _normalize_task_status,
        _recompute_batch_stats,
    )

    success_flag = bool(body.get("success", False))
    raw_status = body.get("status", "unknown")
    status = _normalize_task_status(raw_status, success_flag)

    # 复用 worker writeback 规则：filled 视为未完成（只填表未发布），不算成功
    if raw_status == "filled":
        success_flag = False
        status = _normalize_task_status(raw_status, success_flag)

    task.status = status
    task.external_post_id = body.get("external_post_id") or task.external_post_id
    task.publish_url = (
        normalize_public_http_url(body.get("publish_url")) or task.publish_url
    )
    task.error_message = body.get("error") or task.error_message
    task.finished_at = datetime.now(timezone.utc)

    # 写日志
    log = PublishTaskLog(
        task_id=task.id,
        level="info" if success_flag else "error",
        message=body.get("message") or body.get("error") or f"任务状态: {status}",
        extra=body,
    )
    db.add(log)

    # 按所有任务当前状态重算批次，重复回写和重试不会重复累计。
    if task.batch_id:
        batch_result = await db.execute(
            select(PublishBatch).where(PublishBatch.id == task.batch_id)
        )
        batch = batch_result.scalar_one_or_none()
        if batch:
            await db.flush()
            await _recompute_batch_stats(db, batch)

    await db.commit()
    return success({"task_id": str(task.id), "status": task.status})


@router.get("/batches")
async def list_publish_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    content_id: uuid.UUID | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """发布批次列表。"""
    query = select(PublishBatch)
    if content_id:
        query = query.where(PublishBatch.content_id == content_id)
    if status:
        query = query.where(PublishBatch.status == status)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(PublishBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        PublishBatchOut.model_validate(b).model_dump() for b in result.scalars().all()
    ]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/batches/{batch_id}")
async def get_publish_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """发布批次详情（含任务列表）。"""
    result = await db.execute(select(PublishBatch).where(PublishBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="发布批次不存在")

    tasks_result = await db.execute(
        select(PublishTask)
        .where(PublishTask.batch_id == batch_id)
        .order_by(PublishTask.created_at)
    )
    tasks = [
        PublishTaskOut.model_validate(t).model_dump()
        for t in tasks_result.scalars().all()
    ]

    return success(
        {
            **PublishBatchOut.model_validate(batch).model_dump(),
            "tasks": tasks,
        }
    )


# ===== 验证码 / 人机验证 / noVNC 远程桌面 =====


class SubmitCaptchaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=20)


@router.get("/verifications/pending")
async def list_pending_verifications(
    _: User = Depends(require_roles("admin", "operator")),
):
    """待处理的验证码 / 人机验证任务列表（供前端验证铃铛轮询）。"""
    data = await verification_manager.pending_verifications()
    return success(data)


@router.post("/tasks/{task_id}/captcha")
async def submit_captcha(
    task_id: uuid.UUID,
    body: SubmitCaptchaRequest,
    _: User = Depends(require_roles("admin", "operator")),
):
    """提交验证码并等待平台真实校验结果，避免旧弹窗被重复识别。"""
    try:
        await verification_manager.submit_captcha(str(task_id), body.code)
        result = await verification_manager.wait_for_captcha_validation(
            str(task_id), timeout=20
        )
    except VerificationTimeout as exc:
        raise HTTPException(status_code=504, detail="平台校验验证码超时，请重试") from exc
    except VerificationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result.get("accepted"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("error") or "验证码不正确，请重新输入"),
        )
    return success({"task_id": str(task_id), "accepted": True})


@router.get("/tasks/{task_id}/verification/screenshot")
async def get_verification_screenshot(
    task_id: uuid.UUID,
    _: User = Depends(require_roles("admin", "operator")),
):
    """读取 worker 保存的验证页面截图（需登录，避免验证信息公开暴露）。"""
    path = await verification_manager.get_screenshot_path(str(task_id))
    if path is None:
        raise HTTPException(status_code=404, detail="验证截图不存在或已失效")
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"verification-{task_id}.png",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/tasks/{task_id}/resume")
async def resume_publish(
    task_id: uuid.UUID,
    _: User = Depends(require_roles("admin", "operator")),
):
    """人机验证完成后用户点"继续发布"。"""
    await verification_manager.resume(str(task_id))
    return success({"task_id": str(task_id)})


@router.get("/tasks/{task_id}/vnc-session")
async def get_vnc_session(
    task_id: uuid.UUID,
    _: User = Depends(require_roles("admin", "operator")),
):
    """获取该任务的 noVNC 会话信息（session_id + vnc_password）。"""
    data = await verification_manager.get_vnc_session(str(task_id))
    return success(data)


@router.post("/tasks/{task_id}/verification/dismiss")
async def dismiss_verification(
    task_id: uuid.UUID,
    _: User = Depends(require_roles("admin", "operator")),
):
    """忽略验证（worker 会抛 VerificationDismissed，任务失败释放）。"""
    await verification_manager.dismiss(str(task_id))
    return success({"task_id": str(task_id)})
