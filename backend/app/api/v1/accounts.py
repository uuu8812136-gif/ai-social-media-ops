import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.account import Account
from app.models.content import Content
from app.models.user import User
from app.schemas.common import AccountCreate, AccountOut, AccountUpdate
from app.utils.response import PaginationMeta, success

# 历史通用账号表路由，当前社媒矩阵账号已迁移到 social_accounts；后续可评估删除。
router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/")
async def list_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(Account)
    if platform:
        query = query.where(Account.platform == platform)
    if status:
        query = query.where(Account.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Account.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [AccountOut.model_validate(a).model_dump() for a in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/")
async def create_account(
    body: AccountCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    account = Account(**body.model_dump())
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return success(AccountOut.model_validate(account).model_dump())


@router.get("/{account_id}")
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    return success(AccountOut.model_validate(account).model_dump())


@router.put("/{account_id}")
async def update_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    await db.commit()
    await db.refresh(account)
    return success(AccountOut.model_validate(account).model_dump())


@router.delete("/{account_id}")
async def disable_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    account.status = "disabled"
    await db.commit()
    return success(message="账号已停用")


@router.get("/{account_id}/stats")
async def account_stats(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    total = await db.scalar(
        select(func.count()).where(Content.account_id == account_id)
    )
    published = await db.scalar(
        select(func.count()).where(
            Content.account_id == account_id, Content.status == "published"
        )
    )
    ai_generated = await db.scalar(
        select(func.count()).where(
            Content.account_id == account_id, Content.status == "ai_generated"
        )
    )
    status_rows = (
        await db.execute(
            select(Content.status, func.count())
            .where(Content.account_id == account_id)
            .group_by(Content.status)
        )
    ).all()
    status_breakdown = {s: c for s, c in status_rows}
    return success(
        {
            "account_id": str(account_id),
            "total_contents": total or 0,
            "published_contents": published or 0,
            "published_count": published or 0,
            "ai_generated_count": ai_generated or 0,
            "status_breakdown": status_breakdown,
            "status": account.status,
        }
    )
