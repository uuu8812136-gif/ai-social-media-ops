import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.asset import RiskCheckHistory, RiskWord
from app.models.user import User
from app.schemas.common import (
    RiskBatchCheckRequest,
    RiskCheckRequest,
    RiskWordCreate,
    RiskWordUpdate,
)
from app.services.risk_check import RiskCheckService
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/check")
async def check_content(
    body: RiskCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    service = RiskCheckService(db)
    result = await service.check(body.content, body.platform)
    await service.save_history(body.content, result, body.content_id, current_user.id)
    return success(result.to_dict())


@router.get("/words")
async def list_risk_words(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(RiskWord)
    if category:
        query = query.where(RiskWord.category == category)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = [
        {
            "id": str(w.id),
            "word": w.word,
            "category": w.category,
            "severity": w.severity,
            "platform": w.platform,
            "suggestion": w.suggestion,
            "is_active": w.is_active,
        }
        for w in result.scalars().all()
    ]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/words")
async def create_risk_word(
    body: RiskWordCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    word = RiskWord(**body.model_dump())
    db.add(word)
    await db.commit()
    await db.refresh(word)
    return success({"id": str(word.id), "word": word.word})


@router.put("/words/{word_id}")
async def update_risk_word(
    word_id: uuid.UUID,
    body: RiskWordUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    result = await db.execute(select(RiskWord).where(RiskWord.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(status_code=404, detail="风控词不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(word, field, value)
    await db.commit()
    return success(message="更新成功")


@router.delete("/words/{word_id}")
async def delete_risk_word(
    word_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    result = await db.execute(select(RiskWord).where(RiskWord.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(status_code=404, detail="风控词不存在")
    await db.delete(word)
    await db.commit()
    return success(message="删除成功")


@router.post("/check/batch")
async def batch_check(
    body: RiskBatchCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    service = RiskCheckService(db)
    results = []
    for item in body.contents:
        text = item if isinstance(item, str) else item.content
        result = await service.check(text)
        await service.save_history(text, result, checked_by=current_user.id)
        results.append(result.to_dict())
    return success({"results": results})


@router.get("/history")
async def check_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(RiskCheckHistory)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(RiskCheckHistory.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        {
            "id": str(h.id),
            "content_id": str(h.content_id) if h.content_id else None,
            "content_text": h.content_text[:200],
            "result": h.result,
            "created_at": h.created_at.isoformat(),
        }
        for h in result.scalars().all()
    ]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )
