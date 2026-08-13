import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.dealer import City, Dealer
from app.models.lead import Lead, LeadFollowup
from app.models.user import User
from app.schemas.common import (
    FollowupCreate,
    LeadAssign,
    LeadCreate,
    LeadOut,
    LeadUpdate,
)
from app.services.lead_distribute import LeadDistributionService
from app.utils.encryption import decrypt_phone, encrypt_phone, mask_phone
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/leads", tags=["leads"])


def _lead_out(lead: Lead) -> dict:
    data = LeadOut.model_validate(lead).model_dump()
    try:
        data["customer_phone_masked"] = mask_phone(decrypt_phone(lead.customer_phone))
    except Exception:
        data["customer_phone_masked"] = "****"
    return data


def _ensure_lead_access(current_user: User, lead: Lead) -> None:
    if current_user.role != "dealer":
        return
    if (
        current_user.dealer_id is None
        or lead.assigned_dealer_id != current_user.dealer_id
    ):
        raise HTTPException(status_code=403, detail="无权访问该线索")


@router.get("/")
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    pool_type: str | None = None,
    status: str | None = None,
    assigned_dealer_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    query = select(Lead)
    if pool_type:
        query = query.where(Lead.pool_type == pool_type)
    if status:
        query = query.where(Lead.status == status)
    if assigned_dealer_id:
        query = query.where(Lead.assigned_dealer_id == assigned_dealer_id)
    if current_user.role == "dealer":
        if current_user.dealer_id is None:
            raise HTTPException(status_code=403, detail="当前账号未绑定经销商")
        query = query.where(Lead.assigned_dealer_id == current_user.dealer_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_lead_out(lead) for lead in result.scalars().all()]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/")
async def create_lead(
    body: LeadCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    if body.city_id:
        city = await db.scalar(select(City).where(City.id == body.city_id))
        if not city:
            raise HTTPException(status_code=422, detail="城市不存在")
    lead = Lead(
        **body.model_dump(exclude={"customer_phone"}),
        customer_phone=encrypt_phone(body.customer_phone),
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return success(_lead_out(lead))


@router.get("/stats")
async def lead_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    total = await db.scalar(select(func.count()).select_from(Lead))
    assigned = await db.scalar(select(func.count()).where(Lead.status == "assigned"))
    signed = await db.scalar(select(func.count()).where(Lead.status == "signed"))
    lost = await db.scalar(select(func.count()).where(Lead.status == "lost"))
    return success(
        {
            "total": total or 0,
            "assigned": assigned or 0,
            "signed": signed or 0,
            "lost": lost or 0,
            "conversion_rate": round((signed or 0) / (total or 1) * 100, 2),
        }
    )


@router.get("/stats/funnel")
async def lead_funnel(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stages = [
        "pending",
        "assigned",
        "contacted",
        "appointment_measured",
        "measured",
        "quoted",
        "signed",
        "lost",
    ]
    funnel = []
    for stage in stages:
        count = await db.scalar(
            select(func.count()).where(Lead.status == stage, Lead.created_at >= cutoff)
        )
        funnel.append({"stage": stage, "count": count or 0})
    return success({"funnel": funnel, "days": days})


@router.get("/cities")
async def list_cities(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    from app.models.dealer import City

    result = await db.execute(select(City).order_by(City.name))
    cities = result.scalars().all()
    return success([{"id": str(c.id), "name": c.name} for c in cities])


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    _ensure_lead_access(current_user, lead)
    return success(_lead_out(lead))


@router.put("/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    await db.commit()
    await db.refresh(lead)
    return success(_lead_out(lead))


@router.post("/{lead_id}/assign")
async def assign_lead(
    lead_id: uuid.UUID,
    body: LeadAssign,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    dealer_result = await db.execute(select(Dealer).where(Dealer.id == body.dealer_id))
    dealer = dealer_result.scalar_one_or_none()
    if not dealer:
        raise HTTPException(status_code=404, detail="经销商不存在")
    from datetime import datetime, timezone

    lead.assigned_dealer_id = body.dealer_id
    lead.status = "assigned"
    lead.assigned_at = datetime.now(timezone.utc)
    followup = LeadFollowup(
        lead_id=lead.id,
        operator="system",
        action="assigned",
        note=f"分配给{dealer.company_name}",
    )
    db.add(followup)
    await db.commit()
    service = LeadDistributionService(db)
    await service.wecom.send_lead_notification(dealer.wecom_id or "", lead)
    return success(_lead_out(lead))


@router.post("/{lead_id}/auto-assign")
async def auto_assign_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    service = LeadDistributionService(db)
    lead = await service.distribute(lead)
    return success(_lead_out(lead))


@router.get("/{lead_id}/followups")
async def list_followups(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    lead = await db.scalar(select(Lead).where(Lead.id == lead_id))
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    _ensure_lead_access(current_user, lead)
    result = await db.execute(
        select(LeadFollowup)
        .where(LeadFollowup.lead_id == lead_id)
        .order_by(LeadFollowup.created_at.desc())
    )
    items = [
        {
            "id": str(f.id),
            "operator": f.operator,
            "action": f.action,
            "note": f.note,
            "created_at": f.created_at.isoformat(),
        }
        for f in result.scalars().all()
    ]
    return success(items)


@router.post("/{lead_id}/followups")
async def add_followup(
    lead_id: uuid.UUID,
    body: FollowupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    _ensure_lead_access(current_user, lead)
    followup = LeadFollowup(
        lead_id=lead_id,
        operator=current_user.full_name,
        action=body.action,
        note=body.note,
    )
    lead.status = body.action
    db.add(followup)
    await db.commit()
    return success(message="跟进记录已添加")
