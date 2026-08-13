import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.dealer import City, Dealer
from app.models.lead import Lead
from app.models.user import User
from app.schemas.common import DealerCreate, DealerLevelUpdate, DealerOut, DealerUpdate
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/dealers", tags=["dealers"])


async def _validate_city(db: AsyncSession, city_id: uuid.UUID | None) -> None:
    if city_id is None:
        return
    city = await db.scalar(
        select(City).where(City.id == city_id, City.is_active.is_(True))
    )
    if city is None:
        raise HTTPException(status_code=422, detail="城市不存在或已停用")


async def _get_dealer_or_404(db: AsyncSession, dealer_id: uuid.UUID) -> Dealer:
    dealer = await db.scalar(select(Dealer).where(Dealer.id == dealer_id))
    if dealer is None:
        raise HTTPException(status_code=404, detail="经销商不存在")
    return dealer


@router.get("/")
async def list_dealers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    level: str | None = Query(default=None, pattern=r"^[ABC]$"),
    status: str | None = Query(default=None, pattern=r"^(active|paused|disabled)$"),
    city_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    query = select(Dealer)
    if level:
        query = query.where(Dealer.level == level)
    if status:
        query = query.where(Dealer.status == status)
    if city_id:
        query = query.where(Dealer.city_id == city_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Dealer.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [DealerOut.model_validate(d).model_dump() for d in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/")
async def create_dealer(
    body: DealerCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    await _validate_city(db, body.city_id)
    dealer = Dealer(**body.model_dump())
    db.add(dealer)
    await db.commit()
    await db.refresh(dealer)
    return success(DealerOut.model_validate(dealer).model_dump())


@router.get("/{dealer_id}")
async def get_dealer(
    dealer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    dealer = await _get_dealer_or_404(db, dealer_id)
    return success(DealerOut.model_validate(dealer).model_dump())


@router.put("/{dealer_id}")
async def update_dealer(
    dealer_id: uuid.UUID,
    body: DealerUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    dealer = await _get_dealer_or_404(db, dealer_id)
    if "city_id" in body.model_fields_set:
        await _validate_city(db, body.city_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(dealer, field, value)
    await db.commit()
    await db.refresh(dealer)
    return success(DealerOut.model_validate(dealer).model_dump())


@router.put("/{dealer_id}/level")
async def update_dealer_level(
    dealer_id: uuid.UUID,
    body: DealerLevelUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    dealer = await _get_dealer_or_404(db, dealer_id)
    dealer.level = body.level
    await db.commit()
    return success(DealerOut.model_validate(dealer).model_dump())


@router.get("/{dealer_id}/leads")
async def dealer_leads(
    dealer_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    await _get_dealer_or_404(db, dealer_id)
    query = select(Lead).where(Lead.assigned_dealer_id == dealer_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    from app.api.v1.leads import _lead_out

    items = [_lead_out(lead) for lead in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/{dealer_id}/stats")
async def dealer_stats(
    dealer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    await _get_dealer_or_404(db, dealer_id)
    total = await db.scalar(
        select(func.count()).where(Lead.assigned_dealer_id == dealer_id)
    )
    signed = await db.scalar(
        select(func.count()).where(
            Lead.assigned_dealer_id == dealer_id, Lead.status == "signed"
        )
    )
    contacted = await db.scalar(
        select(func.count()).where(
            Lead.assigned_dealer_id == dealer_id, Lead.status == "contacted"
        )
    )
    status_rows = (
        await db.execute(
            select(Lead.status, func.count())
            .where(Lead.assigned_dealer_id == dealer_id)
            .group_by(Lead.status)
        )
    ).all()
    status_breakdown = {s: c for s, c in status_rows}
    return success(
        {
            "dealer_id": str(dealer_id),
            "total_leads": total or 0,
            "signed_leads": signed or 0,
            "signed_count": signed or 0,
            "contacted_leads": contacted or 0,
            "sign_rate": round((signed or 0) / (total or 1) * 100, 2),
            "signing_rate": round((signed or 0) / (total or 1) * 100, 2),
            "status_breakdown": status_breakdown,
        }
    )
