"""Content publishing package generation and data backflow API routes.

Naming convention: "publish" here means "生成发布包 / 模拟发布状态 / 人工发布回填".
In production, this does NOT auto-publish to any platform. It creates a publish
package that a human operator can then use to manually post, or it records the
result of a manual publish (回填). The mock provider simulates the full flow for
development purposes only.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.content import Content
from app.models.user import User
from app.services.social_provider import get_social_provider
from app.services.analytics_provider import get_analytics_provider
from app.services.notify_provider import get_notify_provider
from app.utils.response import success
from app.utils.social_text import sanitize_publish_text

router = APIRouter(prefix="/publish", tags=["publish"])

# 允许进入发布流程的状态：风控通过或已审核
_PUBLISH_ALLOWED_STATUSES = {"risk_checked", "approved", "human_reviewed"}
_REPORT_ALLOWED_STATUSES = {"risk_checked", "approved", "human_reviewed", "scheduled"}


@router.post("/{content_id}/prepare")
async def prepare_publish_package(
    content_id: uuid.UUID,
    platform: str = Query(
        ..., description="Target platform: douyin|xiaohongshu|wechat_video|wechat_mp"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """生成发布包：模拟将内容打包到指定平台（开发阶段 mock）。

    生产环境中，此接口生成发布素材包，由人工确认后手动发布。
    Mock 模式下模拟完整发布流程，返回平台回填信息。
    """
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    if content.status not in _PUBLISH_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"内容状态为「{content.status}」，需先通过风控审核和人工审核才能生成发布包。允许的状态：{', '.join(_PUBLISH_ALLOWED_STATUSES)}",
        )

    provider = get_social_provider()
    publish_result = await provider.publish(
        platform=platform,
        content_id=str(content.id),
        title=content.title,
        body_text=sanitize_publish_text(content.body_text),
        media_urls=content.media_urls or [],
        account_id=str(content.account_id),
    )

    # Update content status — use new dict to ensure JSONB change tracking
    # Mock 模式：prepare 只推进到 scheduled，published 由 /report 回填
    # 小红书 pending_agent 状态：等待 AI 助手通过 skill 发布后回填
    if publish_result.status in ("published", "reviewing"):
        content.status = "scheduled"
        if publish_result.publish_url:
            new_stats = dict(content.platform_stats or {})
            new_stats[publish_result.platform] = {
                "external_post_id": publish_result.external_post_id,
                "publish_url": publish_result.publish_url,
                "prepared_at": publish_result.scheduled_at,
            }
            content.platform_stats = new_stats  # 赋新 dict 确保 SQLAlchemy 追踪变更
    elif publish_result.status == "pending_agent":
        # 小红书：等待 AI 助手通过 browser-use skill 发布
        content.status = "scheduled"
        new_stats = dict(content.platform_stats or {})
        new_stats[publish_result.platform] = {
            "external_post_id": publish_result.external_post_id,
            "prepared_at": publish_result.scheduled_at,
            "publish_mode": "agent",  # 标记由 AI 助手发布
        }
        content.platform_stats = new_stats
    else:
        content.status = "publish_failed"

    await db.commit()

    # Send notification
    notify_provider = get_notify_provider()
    if publish_result.status in ("published", "reviewing", "pending_agent"):
        await notify_provider.send_publish_success(
            content.title, platform, str(current_user.id)
        )

    return success(
        {
            "content_id": str(content.id),
            "platform": platform,
            "publish_result": publish_result.to_dict(),
            "content_status": content.status,
        }
    )


@router.post("/{content_id}/report")
async def report_manual_publish(
    content_id: uuid.UUID,
    platform: str = Query(
        ..., description="Platform that content was manually published to"
    ),
    external_post_id: str = Query(..., description="Post ID returned by the platform"),
    publish_url: str | None = Query(
        default=None, description="Public URL of the published post"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """人工发布回填：运营手动在平台发布后，将发布结果回填到系统。

    此接口不调用任何第三方 API，仅记录人工发布结果。
    """
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    if content.status not in _REPORT_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"内容状态为「{content.status}」，无法回填发布结果",
        )

    content.status = "published"
    new_stats = dict(content.platform_stats or {})
    new_stats[platform] = {
        "external_post_id": external_post_id,
        "publish_url": publish_url,
        "published_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
        "published_by": str(current_user.id),
    }
    content.platform_stats = new_stats  # 赋新 dict 确保 SQLAlchemy 追踪变更

    await db.commit()

    return success(
        {
            "content_id": str(content.id),
            "platform": platform,
            "content_status": content.status,
        }
    )


@router.post("/{content_id}/sync-stats")
async def sync_content_stats(
    content_id: uuid.UUID,
    platform: str = Query(..., description="Platform to sync stats from"),
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """同步内容数据回流：从平台拉取内容表现数据（mock 模式下生成模拟数据）。"""
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    analytics = get_analytics_provider()
    stats = await analytics.get_content_stats(str(content.id), platform, days)

    # Update content with synced stats — 赋新 dict 确保 SQLAlchemy 追踪变更
    new_stats = dict(content.platform_stats or {})
    new_stats[f"{platform}_stats"] = stats.get("stats", {})
    new_stats[f"{platform}_daily"] = stats.get("daily", [])
    content.platform_stats = new_stats

    if content.status == "published":
        content.status = "stats_synced"

    await db.commit()

    return success(stats)


@router.get("/dashboard")
async def get_dashboard(
    days: int = Query(default=7, ge=1, le=30),
    platform: str | None = None,
    account_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """Get dashboard-level stats across all platforms (mock)."""
    analytics = get_analytics_provider()
    stats = await analytics.get_dashboard_stats(
        days=days,
        platform=platform,
        account_id=str(account_id) if account_id else None,
    )
    return success(stats)


@router.get("/account/{account_id}/stats")
async def get_account_stats(
    account_id: uuid.UUID,
    platform: str = Query(default="douyin"),
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """Get account-level stats (mock data backflow)."""
    analytics = get_analytics_provider()
    stats = await analytics.get_account_stats(str(account_id), platform, days)
    return success(stats)


# ===== 小红书 AI 助手发布端点 =====
# 小红书官方开放平台已暂停接入，采用「AI 助手浏览器自动化」模式：
# 1. AI 助手 GET /publish/{content_id}/xhs/content 拿到待发布内容包（标题/正文/图片）
# 2. AI 助手通过 browser-use skill 操作浏览器在小红书网页版发布
# 3. AI 助手 POST /publish/{content_id}/xhs/callback 回填 note_id


class XhsCallbackRequest(BaseModel):
    note_id: str
    publish_url: str | None = None


@router.get("/{content_id}/xhs/content")
async def get_xhs_publish_content(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """获取小红书待发布内容包。

    AI 助手用 browser-use skill 操作浏览器发布时，先调此接口拿到内容包：
    - title: 笔记标题
    - content: 笔记正文
    - images: 图片 URL 列表（图文笔记）
    - video: 视频 URL（视频笔记）
    - note_type: normal(图文) | video(视频)
    """
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    media_urls = content.media_urls or []
    images = [
        u
        for u in media_urls
        if not any(u.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv"))
    ]
    videos = [
        u
        for u in media_urls
        if any(u.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv"))
    ]
    note_type = "video" if videos else "normal"

    return success(
        {
            "content_id": str(content.id),
            "title": content.title,
            "content": sanitize_publish_text(content.body_text),
            "images": images,
            "video": videos[0] if videos else "",
            "note_type": note_type,
            "publish_url": "https://www.xiaohongshu.com/publish/bliss",  # 小红书网页版发布页
        }
    )


@router.post("/{content_id}/xhs/callback")
async def xhs_publish_callback(
    content_id: uuid.UUID,
    payload: XhsCallbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """小红书 AI 助手发布完成回调。

    AI 助手通过 browser-use skill 完成发布后，将小红书返回的 note_id 回填到系统，
    标记内容为已发布（小红书笔记会进入审核，状态置为 reviewing）。
    """
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    publish_url = (
        payload.publish_url or f"https://www.xiaohongshu.com/explore/{payload.note_id}"
    )

    content.status = "reviewing"  # 小红书笔记发布后进入审核
    new_stats = dict(content.platform_stats or {})
    new_stats["xiaohongshu"] = {
        "external_post_id": payload.note_id,
        "publish_url": publish_url,
        "published_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
        "published_by": str(current_user.id),
        "publish_mode": "agent",
    }
    content.platform_stats = new_stats

    await db.commit()

    return success(
        {
            "content_id": str(content.id),
            "platform": "xiaohongshu",
            "note_id": payload.note_id,
            "publish_url": publish_url,
            "content_status": content.status,
        }
    )
