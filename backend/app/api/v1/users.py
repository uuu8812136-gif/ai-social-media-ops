import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.core.security import get_password_hash
from app.core.token_store import revoke_all_user_tokens
from app.models.dealer import Dealer
from app.models.user import User
from app.schemas.user_management import (
    SystemUserCreate,
    SystemUserPasswordReset,
    SystemUserUpdate,
)
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/users", tags=["system-users"])


def _serialize(user: User, dealer_name: str | None = None) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "dealer_id": str(user.dealer_id) if user.dealer_id else None,
        "dealer_name": dealer_name,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


async def _validate_dealer(db: AsyncSession, dealer_id: uuid.UUID | None) -> None:
    if dealer_id is None:
        return
    dealer = await db.scalar(select(Dealer).where(Dealer.id == dealer_id))
    if dealer is None:
        raise HTTPException(status_code=422, detail="绑定的经销商不存在")


@router.get("")
async def list_users(
    q: str | None = Query(default=None, max_length=100),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    conditions = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(User.username.ilike(pattern), User.full_name.ilike(pattern))
        )
    if role:
        if role not in {"admin", "operator", "dealer"}:
            raise HTTPException(status_code=422, detail="无效的账号角色")
        conditions.append(User.role == role)
    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))

    total_query = select(func.count(User.id))
    list_query = select(User, Dealer.company_name).outerjoin(
        Dealer, Dealer.id == User.dealer_id
    )
    if conditions:
        total_query = total_query.where(*conditions)
        list_query = list_query.where(*conditions)
    total = await db.scalar(total_query) or 0
    rows = (
        await db.execute(
            list_query.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [_serialize(user, dealer_name) for user, dealer_name in rows]
    return success(
        items, pagination=PaginationMeta(page=page, page_size=page_size, total=total)
    )


@router.post("")
async def create_user(
    body: SystemUserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    exists = await db.scalar(
        select(User.id).where(func.lower(User.username) == body.username)
    )
    if exists:
        raise HTTPException(status_code=409, detail="用户名已存在")
    dealer_id = body.dealer_id if body.role == "dealer" else None
    if body.role == "dealer" and dealer_id is None:
        raise HTTPException(status_code=422, detail="经销商角色必须绑定经销商")
    await _validate_dealer(db, dealer_id)
    user = User(
        username=body.username,
        full_name=body.full_name,
        role=body.role,
        dealer_id=dealer_id,
        password_hash=get_password_hash(body.password),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    dealer_name = None
    if user.dealer_id:
        dealer_name = await db.scalar(
            select(Dealer.company_name).where(Dealer.id == user.dealer_id)
        )
    return success(_serialize(user, dealer_name), message="账号创建成功")


@router.put("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: SystemUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if user.id == current_user.id:
        if body.is_active is False:
            raise HTTPException(status_code=400, detail="不能停用当前登录账号")
        if body.role is not None and body.role != "admin":
            raise HTTPException(status_code=400, detail="不能降低当前登录管理员的角色")

    removes_active_admin = (
        user.role == "admin"
        and user.is_active
        and (
            (body.role is not None and body.role != "admin") or body.is_active is False
        )
    )
    if removes_active_admin:
        active_admin_ids = (
            await db.scalars(
                select(User.id)
                .where(User.role == "admin", User.is_active.is_(True))
                .with_for_update()
            )
        ).all()
        if len(active_admin_ids) <= 1:
            raise HTTPException(
                status_code=409, detail="系统必须保留至少一个启用的管理员账号"
            )

    role_changed = body.role is not None and body.role != user.role
    next_role = body.role or user.role
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if next_role == "dealer":
        dealer_id = (
            body.dealer_id if "dealer_id" in body.model_fields_set else user.dealer_id
        )
        if dealer_id is None:
            raise HTTPException(status_code=422, detail="经销商角色必须绑定经销商")
        await _validate_dealer(db, dealer_id)
        user.dealer_id = dealer_id
    else:
        user.dealer_id = None

    if role_changed or body.is_active is False:
        try:
            await revoke_all_user_tokens(str(user.id))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(user)
    dealer_name = None
    if user.dealer_id:
        dealer_name = await db.scalar(
            select(Dealer.company_name).where(Dealer.id == user.dealer_id)
        )
    return success(_serialize(user, dealer_name), message="账号已更新")


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: uuid.UUID,
    body: SystemUserPasswordReset,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        await revoke_all_user_tokens(str(user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    user.password_hash = get_password_hash(body.new_password)
    await db.commit()
    return success(message="密码已重置")
