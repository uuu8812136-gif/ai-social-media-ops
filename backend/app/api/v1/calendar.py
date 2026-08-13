import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.calendar import ContentCalendar
from app.models.content import Content
from app.models.social_account import SocialAccount
from app.models.user import User
from app.schemas.common import (
    CalendarCreate,
    CalendarOut,
    CalendarRemindRequest,
    CalendarStatusUpdate,
    CalendarUpdate,
)
from app.services.wecom_notify import WeComNotifyService
from app.utils.response import success

router = APIRouter(prefix="/calendar", tags=["calendar"])


async def _validate_calendar_references(
    db: AsyncSession,
    account_id: uuid.UUID,
    content_id: uuid.UUID | None,
) -> None:
    account = await db.scalar(
        select(SocialAccount).where(
            SocialAccount.id == account_id,
            SocialAccount.status == "active",
        )
    )
    if account is None:
        raise HTTPException(status_code=422, detail="排期账号不存在或已停用")
    if content_id is None:
        return
    content = await db.scalar(select(Content).where(Content.id == content_id))
    if content is None:
        raise HTTPException(status_code=422, detail="排期内容不存在")
    if content.account_id != account_id:
        raise HTTPException(status_code=422, detail="排期内容与所选账号不匹配")


@router.get("/")
async def list_calendar(
    month: str | None = Query(
        None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"
    ),
    week_start: date | None = None,
    account_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(ContentCalendar)
    if account_id:
        query = query.where(ContentCalendar.account_id == account_id)
    if month:
        year, mon = map(int, month.split("-"))
        start = date(year, mon, 1)
        end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
        query = query.where(
            and_(
                ContentCalendar.scheduled_date >= start,
                ContentCalendar.scheduled_date < end,
            )
        )
    if week_start:
        from datetime import timedelta

        query = query.where(
            and_(
                ContentCalendar.scheduled_date >= week_start,
                ContentCalendar.scheduled_date < week_start + timedelta(days=7),
            )
        )
    result = await db.execute(query.order_by(ContentCalendar.scheduled_date))
    items = [CalendarOut.model_validate(c).model_dump() for c in result.scalars().all()]
    return success(items)


@router.post("/")
async def create_calendar(
    body: CalendarCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    await _validate_calendar_references(db, body.account_id, body.content_id)
    item = ContentCalendar(**body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return success(CalendarOut.model_validate(item).model_dump())


@router.put("/{calendar_id}")
async def update_calendar(
    calendar_id: uuid.UUID,
    body: CalendarUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(ContentCalendar).where(ContentCalendar.id == calendar_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="排期不存在")
    if "content_id" in body.model_fields_set:
        await _validate_calendar_references(db, item.account_id, body.content_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return success(CalendarOut.model_validate(item).model_dump())


@router.delete("/{calendar_id}")
async def delete_calendar(
    calendar_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(ContentCalendar).where(ContentCalendar.id == calendar_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="排期不存在")
    await db.delete(item)
    await db.commit()
    return success(message="排期已删除")


@router.put("/{calendar_id}/status")
async def update_publish_status(
    calendar_id: uuid.UUID,
    body: CalendarStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(ContentCalendar).where(ContentCalendar.id == calendar_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="排期不存在")
    item.publish_status = body.publish_status
    await db.commit()
    return success(CalendarOut.model_validate(item).model_dump())


@router.post("/remind")
async def send_remind(
    body: CalendarRemindRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    wecom = WeComNotifyService(db)
    result = await wecom.send_remind(
        user_id=body.user_id,
        content_title=body.content_title,
        scheduled_time=body.scheduled_time,
    )
    if body.calendar_id:
        cal_result = await db.execute(
            select(ContentCalendar).where(ContentCalendar.id == body.calendar_id)
        )
        cal = cal_result.scalar_one_or_none()
        if cal:
            cal.remind_sent = True
            await db.commit()
    return success(result)
