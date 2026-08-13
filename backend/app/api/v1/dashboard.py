from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.dealer import Dealer
from app.models.content import Content
from app.models.crawler import CrawlerJob
from app.models.lead import Lead
from app.models.social_account import (
    PublishTask,
    SocialAccount,
    SocialPostMetric,
)
from app.models.user import User
from app.utils.response import success

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _status_counts(
    db: AsyncSession, model, *, cutoff: datetime | None = None
) -> dict[str, int]:
    query = select(model.status, func.count()).group_by(model.status)
    if cutoff is not None:
        query = query.where(model.created_at >= cutoff)
    rows = await db.execute(query)
    return {str(status): int(count) for status, count in rows.all()}


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    accounts = await db.scalar(
        select(func.count()).where(SocialAccount.status == "active")
    )
    contents = await db.scalar(select(func.count()).select_from(Content))
    leads = await db.scalar(select(func.count()).select_from(Lead))
    dealers = await db.scalar(select(func.count()).select_from(Dealer))
    signed = await db.scalar(select(func.count()).where(Lead.status == "signed"))
    return success(
        {
            "accounts": accounts or 0,
            "contents": contents or 0,
            "leads": leads or 0,
            "dealers": dealers or 0,
            "signed_leads": signed or 0,
        }
    )


@router.get("/operations")
async def operations_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """发布、账号与采集的运营健康摘要。

    只报告数据库已确认的状态；publish_unknown 单列为待人工确认，
    不会混入成功或失败率。
    """
    from app.integrations.platform_capabilities import all_capabilities

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    publish = await _status_counts(db, PublishTask, cutoff=cutoff)
    crawler = await _status_counts(db, CrawlerJob, cutoff=cutoff)

    account_rows = await db.execute(
        select(SocialAccount.cookie_status, func.count())
        .where(SocialAccount.status == "active")
        .group_by(SocialAccount.cookie_status)
    )
    accounts = {
        str(status): int(count) for status, count in account_rows.all()
    }

    failed_statuses = {
        "failed",
        "publish_error",
        "dispatch_failed",
        "cookie_missing",
        "cookie_invalid",
        "account_restricted",
        "media_required",
        "not_published",
    }
    verification_statuses = {
        "needs_phone_captcha",
        "needs_human_captcha",
        "awaiting_resume",
    }
    published = publish.get("published", 0)
    failed = sum(publish.get(status, 0) for status in failed_statuses)
    unknown = publish.get("publish_unknown", 0)
    verification = sum(
        publish.get(status, 0) for status in verification_statuses
    )
    determinate = published + failed
    active_accounts = sum(accounts.values())
    invalid_accounts = sum(
        count for status, count in accounts.items() if status != "valid"
    )

    alerts: list[dict[str, object]] = []
    if unknown:
        alerts.append(
            {
                "severity": "warning",
                "code": "publish_unknown",
                "count": unknown,
                "message": f"{unknown} 个发布结果需要人工核对",
            }
        )
    if verification:
        alerts.append(
            {
                "severity": "warning",
                "code": "verification_required",
                "count": verification,
                "message": f"{verification} 个任务正在等待人工验证",
            }
        )
    if invalid_accounts:
        alerts.append(
            {
                "severity": "danger",
                "code": "account_cookie_invalid",
                "count": invalid_accounts,
                "message": f"{invalid_accounts} 个账号登录状态需处理",
            }
        )
    if crawler.get("failed", 0):
        alerts.append(
            {
                "severity": "danger",
                "code": "crawler_failed",
                "count": crawler["failed"],
                "message": f"{crawler['failed']} 个采集任务失败",
            }
        )

    return success(
        {
            "period_days": days,
            "publish": {
                "total": sum(publish.values()),
                "published": published,
                "failed": failed,
                "in_progress": publish.get("running", 0)
                + publish.get("queued", 0)
                + publish.get("scheduled", 0),
                "unknown": unknown,
                "verification_required": verification,
                "success_rate": round(
                    published / determinate * 100, 2
                )
                if determinate
                else 0,
                "by_status": publish,
            },
            "accounts": {
                "active": active_accounts,
                "valid": accounts.get("valid", 0),
                "needs_attention": invalid_accounts,
                "by_cookie_status": accounts,
            },
            "crawler": {
                "total": sum(crawler.values()),
                "succeeded": crawler.get("succeeded", 0),
                "failed": crawler.get("failed", 0),
                "in_progress": crawler.get("running", 0)
                + crawler.get("queued", 0)
                + crawler.get("pending", 0),
                "by_status": crawler,
            },
            "alerts": alerts,
            "platforms": all_capabilities(),
        }
    )
@router.get("/content/stats")
async def content_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    total = await db.scalar(select(func.count()).select_from(Content))
    published = await db.scalar(
        select(func.count()).where(Content.status.in_(["published", "stats_synced"]))
    )
    ai_generated = await db.scalar(
        select(func.count()).where(Content.status == "ai_generated")
    )
    return success(
        {
            "total": total or 0,
            "published": published or 0,
            "ai_generated": ai_generated or 0,
            "publish_rate": round((published or 0) / (total or 1) * 100, 2),
        }
    )


@router.get("/lead/stats")
async def lead_stats_dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    total = await db.scalar(select(func.count()).select_from(Lead))
    pending = await db.scalar(select(func.count()).where(Lead.status == "pending"))
    assigned = await db.scalar(select(func.count()).where(Lead.status == "assigned"))
    signed = await db.scalar(select(func.count()).where(Lead.status == "signed"))
    return success(
        {
            "total": total or 0,
            "pending": pending or 0,
            "assigned": assigned or 0,
            "signed": signed or 0,
            "conversion_rate": round((signed or 0) / (total or 1) * 100, 2),
        }
    )


@router.get("/dealer/stats")
async def dealer_stats_dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    total = await db.scalar(select(func.count()).select_from(Dealer))
    active = await db.scalar(select(func.count()).where(Dealer.status == "active"))
    level_a = await db.scalar(select(func.count()).where(Dealer.level == "A"))
    return success(
        {"total": total or 0, "active": active or 0, "level_a": level_a or 0}
    )


@router.get("/social/stats")
async def social_stats(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """Aggregate real metrics collected for published social posts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(SocialPostMetric).where(
            SocialPostMetric.created_at >= cutoff,
            SocialPostMetric.sync_status == "synced",
            SocialPostMetric.metrics.is_not(None),
        )
    )

    metric_keys = ("views", "likes", "comments", "favorites", "shares", "leads")
    totals = {key: 0 for key in metric_keys}
    by_platform: dict[str, dict] = {}

    for row in result.scalars().all():
        platform = row.platform or "unknown"
        target = by_platform.setdefault(
            platform,
            {"platform": platform, **{key: 0 for key in metric_keys}},
        )
        metrics = row.metrics or {}
        for key in metric_keys:
            try:
                value = int(float(metrics.get(key) or 0))
            except (TypeError, ValueError):
                value = 0
            target[key] += value
            totals[key] += value

    for item in by_platform.values():
        item["conversion_rate"] = round(item["leads"] / max(item["views"], 1) * 100, 2)
    totals["conversion_rate"] = round(
        totals["leads"] / max(totals["views"], 1) * 100, 2
    )

    return success(
        {
            "total_stats": totals,
            "platform_stats": sorted(
                by_platform.values(), key=lambda item: item["views"], reverse=True
            ),
            "days": days,
        }
    )


@router.get("/trend")
async def trend(
    period: str = Query("day", pattern="^(day|week|month)$"),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    today = date.today()
    start = today - timedelta(days=days - 1)

    lead_counts = (
        await db.execute(
            select(func.date(Lead.created_at), func.count())
            .where(func.date(Lead.created_at) >= start)
            .group_by(func.date(Lead.created_at))
        )
    ).all()
    content_counts = (
        await db.execute(
            select(func.date(Content.created_at), func.count())
            .where(func.date(Content.created_at) >= start)
            .group_by(func.date(Content.created_at))
        )
    ).all()

    lead_map = {d: c for d, c in lead_counts}
    content_map = {d: c for d, c in content_counts}

    trends = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        trends.append(
            {
                "date": d.isoformat(),
                "leads": lead_map.get(d, 0),
                "contents": content_map.get(d, 0),
            }
        )
    return success({"period": period, "trends": trends})
