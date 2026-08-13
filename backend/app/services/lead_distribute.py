import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dealer import Dealer
from app.models.lead import Lead
from app.services.wecom_notify import WeComNotifyService

logger = logging.getLogger(__name__)


class LeadDistributionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wecom = WeComNotifyService(db)

    async def get_by_city(
        self, city_id: uuid.UUID, level_priority: list[str], status: str = "active"
    ) -> list[Dealer]:
        result = await self.db.execute(
            select(Dealer).where(Dealer.city_id == city_id, Dealer.status == status)
        )
        dealers = list(result.scalars().all())
        level_order = {level: idx for idx, level in enumerate(level_priority)}
        dealers.sort(key=lambda d: level_order.get(d.level, 999))
        return dealers

    async def current_month_lead_count(self, dealer_id: uuid.UUID) -> int:
        now = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = (
            select(func.count())
            .select_from(Lead)
            .where(Lead.assigned_dealer_id == dealer_id, Lead.assigned_at >= start)
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def distribute(self, lead: Lead) -> Lead:
        if not lead.city_id:
            lead.status = "pending"
            await self.notify_admin(lead)
            await self.db.commit()
            return lead

        city_dealers = await self.get_by_city(
            lead.city_id, level_priority=["A", "B", "C"], status="active"
        )
        if not city_dealers:
            lead.status = "pending"
            await self.notify_admin(lead)
            await self.db.commit()
            return lead

        counts = {d.id: await self.current_month_lead_count(d.id) for d in city_dealers}
        target = min(city_dealers, key=lambda d: counts[d.id])

        lead.assigned_dealer_id = target.id
        lead.status = "assigned"
        lead.assigned_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(lead)

        await self.wecom.send_lead_notification(
            dealer_wecom_id=target.wecom_id or "", lead=lead
        )
        await self.schedule_timeout_check(lead.id, minutes=60)
        return lead

    async def notify_admin(self, lead: Lead) -> None:
        logger.info("Notify admin: lead %s pending assignment", lead.id)

    async def notify_admin_timeout(self, lead: Lead) -> None:
        logger.info("Notify admin timeout: lead %s", lead.id)

    async def schedule_timeout_check(
        self, lead_id: uuid.UUID, minutes: int = 60
    ) -> None:
        from app.tasks.lead_tasks import check_lead_timeout

        check_lead_timeout.apply_async(args=[str(lead_id)], countdown=minutes * 60)

    async def handle_timeout(self, lead_id: uuid.UUID) -> None:
        result = await self.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead or lead.status != "assigned":
            return
        await self.notify_admin_timeout(lead)
        await self.redistribute(lead)

    async def redistribute(self, lead: Lead) -> None:
        if not lead.city_id:
            return
        city_dealers = await self.get_by_city(
            lead.city_id, level_priority=["A", "B", "C"], status="active"
        )
        others = [d for d in city_dealers if d.id != lead.assigned_dealer_id]
        if not others:
            return
        counts = {d.id: await self.current_month_lead_count(d.id) for d in others}
        target = min(others, key=lambda d: counts[d.id])
        lead.assigned_dealer_id = target.id
        lead.assigned_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.wecom.send_lead_notification(
            dealer_wecom_id=target.wecom_id or "", lead=lead
        )

    async def find_latest_pending(self, dealer_wecom_id: str) -> Lead | None:
        dealer_result = await self.db.execute(
            select(Dealer).where(Dealer.wecom_id == dealer_wecom_id)
        )
        dealer = dealer_result.scalar_one_or_none()
        if not dealer:
            return None
        query = (
            select(Lead)
            .where(
                Lead.assigned_dealer_id == dealer.id,
                Lead.status.in_(
                    [
                        "assigned",
                        "contacted",
                        "appointment_measured",
                        "measured",
                        "quoted",
                    ]
                ),
            )
            .order_by(Lead.assigned_at.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
