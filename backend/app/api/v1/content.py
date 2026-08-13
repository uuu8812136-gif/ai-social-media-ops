import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.content import Content
from app.models.social_account import SocialAccount
from app.models.user import User
from app.schemas.content import (
    ContentOut,
    ContentRiskRewriteRequest,
    ContentUpdate,
    CopywritingGenerateRequest,
    LocalizeRequest,
    ScriptGenerateRequest,
)
from app.services.content_gen import (
    ContentGenerationService,
    CopywritingRequest,
    ScriptRequest,
)
from app.services.risk_check import RiskCheckService
from app.utils.response import PaginationMeta, success
from app.utils.social_text import sanitize_publish_text

router = APIRouter(prefix="/content", tags=["content"])

_TERMINAL_CONTENT_STATUSES = {"scheduled", "published", "stats_synced"}
_APPROVED_CONTENT_STATUSES = {"approved", "human_reviewed"}


async def _require_active_social_account(
    db: AsyncSession, account_id: uuid.UUID
) -> SocialAccount:
    account = await db.scalar(
        select(SocialAccount).where(
            SocialAccount.id == account_id,
            SocialAccount.status == "active",
        )
    )
    if account is None:
        raise HTTPException(status_code=422, detail="社媒账号不存在或已停用")
    return account


def _format_body_text(content_type: str, body_text: str) -> str:
    del content_type  # 结构标签对任何社媒内容类型都不应出现在最终正文。
    return sanitize_publish_text(body_text)


def _serialize_content(c: Content) -> dict:
    item = ContentOut.model_validate(c).model_dump()
    item["body_text"] = _format_body_text(c.content_type, c.body_text)
    return item


def _risk_text(c: Content) -> str:
    return f"{c.title}\n{_format_body_text(c.content_type, c.body_text)}"


def _set_risk_status(content: Content, passed: bool) -> None:
    if content.status not in _TERMINAL_CONTENT_STATUSES:
        content.status = "risk_checked" if passed else "risk_failed"


def _apply_content_update(content: Content, body: ContentUpdate) -> None:
    updates = body.model_dump(exclude_unset=True)
    changed_fields = {"title", "body_text", "tags"}.intersection(updates)
    requested_status = updates.pop("status", None)

    if "title" in updates and not str(updates["title"] or "").strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    if "body_text" in updates:
        updates["body_text"] = sanitize_publish_text(updates["body_text"])
        if not updates["body_text"]:
            raise HTTPException(status_code=400, detail="正文不能为空")

    for field, value in updates.items():
        setattr(content, field, value)

    if changed_fields:
        content.risk_check_result = None
        content.status = "ai_generated"

    if requested_status is not None:
        if changed_fields and requested_status in _APPROVED_CONTENT_STATUSES:
            raise HTTPException(
                status_code=400, detail="内容已修改，请重新通过风控后再审核"
            )
        if requested_status in _APPROVED_CONTENT_STATUSES:
            if not content.risk_check_result or not content.risk_check_result.get(
                "passed"
            ):
                raise HTTPException(status_code=400, detail="风控未通过，不能审核发布")
        content.status = requested_status


@router.get("/")
async def list_contents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = None,
    content_type: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """统一内容列表。

    社媒发布中心会调用 `/content/` 拉取可发布内容；原项目只有
    `/content/scripts` 和 `/content/copywriting`，导致发布弹窗内容为空/404。
    """
    query = select(Content)
    if account_id:
        query = query.where(Content.account_id == account_id)
    if content_type:
        query = query.where(Content.content_type == content_type)
    if status:
        query = query.where(Content.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Content.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize_content(c) for c in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/scripts/generate")
async def generate_scripts(
    body: ScriptGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    await _require_active_social_account(db, body.account_id)
    service = ContentGenerationService(db)
    req = ScriptRequest(
        account_id=body.account_id,
        topic=body.topic,
        strategy_type=body.strategy_type,
        duration=body.duration,
        style=body.style,
        local_cities=body.local_cities,
        count=body.count,
    )
    scripts = await service.generate_script(req)
    return success({"scripts": scripts})


@router.post("/copywriting/generate")
async def generate_copywriting(
    body: CopywritingGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    await _require_active_social_account(db, body.account_id)
    service = ContentGenerationService(db)
    req = CopywritingRequest(
        account_id=body.account_id,
        topic=body.topic,
        strategy_type=body.strategy_type,
        platform=body.platform,
        count=body.count,
    )
    items = await service.generate_copywriting(req)
    return success({"copywriting": items})


@router.post("/copywriting/localize")
async def localize_copywriting(
    body: LocalizeRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    if body.account_id is not None:
        await _require_active_social_account(db, body.account_id)
    if body.content_id is not None:
        source = await db.scalar(select(Content).where(Content.id == body.content_id))
        if source is None:
            raise HTTPException(status_code=404, detail="待本地化内容不存在")
    service = ContentGenerationService(db)
    localizations = await service.localize(
        cities=body.cities,
        content_id=body.content_id,
        content_text=body.content,
        strategy_type=body.strategy_type,
        account_id=body.account_id,
    )
    return success({"localizations": localizations})


@router.get("/scripts")
async def list_scripts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(Content).where(Content.content_type == "video_script")
    if account_id:
        query = query.where(Content.account_id == account_id)
    if status:
        query = query.where(Content.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Content.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize_content(c) for c in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/scripts/{content_id}")
async def get_script(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(Content).where(
            Content.id == content_id, Content.content_type == "video_script"
        )
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return success(_serialize_content(content))


@router.put("/scripts/{content_id}")
async def update_script(
    content_id: uuid.UUID,
    body: ContentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(Content).where(
            Content.id == content_id, Content.content_type == "video_script"
        )
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="脚本不存在")
    _apply_content_update(content, body)
    await db.commit()
    await db.refresh(content)
    return success(_serialize_content(content))


@router.post("/scripts/{content_id}/risk-check")
async def script_risk_check(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(Content).where(
            Content.id == content_id, Content.content_type == "video_script"
        )
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="脚本不存在")
    service = RiskCheckService(db)
    text = _risk_text(content)
    check_result = await service.check(text)
    content.risk_check_result = check_result.to_dict()
    _set_risk_status(content, check_result.passed)
    await service.save_history(text, check_result, content_id, current_user.id)
    await db.commit()
    return success(check_result.to_dict())


@router.get("/copywriting")
async def list_copywriting(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(Content).where(Content.content_type.in_(["image_text", "note"]))
    if account_id:
        query = query.where(Content.account_id == account_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Content.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize_content(c) for c in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/copywriting/{content_id}")
async def get_copywriting(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(Content).where(
            Content.id == content_id, Content.content_type.in_(["image_text", "note"])
        )
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="文案不存在")
    return success(_serialize_content(content))


@router.put("/copywriting/{content_id}")
async def update_copywriting(
    content_id: uuid.UUID,
    body: ContentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(Content).where(
            Content.id == content_id, Content.content_type.in_(["image_text", "note"])
        )
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="文案不存在")
    _apply_content_update(content, body)
    await db.commit()
    await db.refresh(content)
    return success(_serialize_content(content))


@router.post("/copywriting/{content_id}/risk-check")
async def copywriting_risk_check(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(Content).where(
            Content.id == content_id, Content.content_type.in_(["image_text", "note"])
        )
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="文案不存在")
    service = RiskCheckService(db)
    text = _risk_text(content)
    check_result = await service.check(text)
    content.risk_check_result = check_result.to_dict()
    _set_risk_status(content, check_result.passed)
    await service.save_history(text, check_result, content_id, current_user.id)
    await db.commit()
    return success(check_result.to_dict())


@router.post("/items/{content_id}/rewrite-risk")
async def rewrite_content_risk(
    content_id: uuid.UUID,
    body: ContentRiskRewriteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")
    if content.status in _TERMINAL_CONTENT_STATUSES:
        raise HTTPException(
            status_code=400, detail="内容已进入发布流程，不能再执行AI风控改写"
        )

    service = ContentGenerationService(db)
    rewrite = await service.rewrite_content_for_risk(
        content,
        max_attempts=body.max_attempts,
        platform=body.platform,
        checked_by=current_user.id,
    )
    return success(
        {
            "content": _serialize_content(rewrite["content"]),
            "attempts": rewrite["attempts"],
            "risk_result": rewrite["risk_result"],
            "passed": bool(rewrite["risk_result"].get("passed")),
        }
    )


@router.get("/trending")
async def trending(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    service = ContentGenerationService(db)
    topics = await service.get_trending()
    return success({"topics": topics})
