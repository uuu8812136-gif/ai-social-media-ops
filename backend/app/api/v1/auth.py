import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    password_needs_rehash,
    verify_password,
    verify_token,
)
from app.core.token_store import revoke_all_user_tokens, revoke_refresh_token
from app.models.user import User
from app.schemas.auth import LoginRequest, PasswordUpdate, RefreshTokenRequest, UserOut
from app.utils.response import success

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    username = body.username.strip().lower()
    result = await db.execute(select(User).where(func.lower(User.username) == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已禁用")
    if password_needs_rehash(user.password_hash):
        user.password_hash = get_password_hash(body.password)
        await db.commit()
    access = create_access_token(str(user.id), {"role": user.role})
    refresh = create_refresh_token(str(user.id))
    return success(
        {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}
    )


@router.post("/refresh")
async def refresh_token(body: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = verify_token(body.refresh_token, "refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Refresh Token无效")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Refresh Token无效") from None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    try:
        consumed = await revoke_refresh_token(payload, reject_if_already_revoked=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not consumed:
        raise HTTPException(status_code=401, detail="Refresh Token 已失效或已使用")
    access = create_access_token(str(user.id), {"role": user.role})
    refresh = create_refresh_token(str(user.id))
    return success(
        {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
        }
    )


@router.post("/logout")
async def logout(body: RefreshTokenRequest):
    payload = verify_token(body.refresh_token, "refresh")
    if payload and isinstance(payload.get("sub"), str):
        try:
            await revoke_refresh_token(payload, reject_if_already_revoked=False)
            await revoke_all_user_tokens(payload["sub"])
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return success(message="已退出登录")


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return success(UserOut.model_validate(current_user).model_dump())


@router.put("/me/password")
async def update_password(
    body: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    try:
        await revoke_all_user_tokens(str(current_user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    current_user.password_hash = get_password_hash(body.new_password)
    await db.commit()
    return success(message="密码修改成功")
