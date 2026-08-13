import asyncio
import uuid

from app.core.database import AsyncSessionLocal
from app.services.lead_distribute import LeadDistributionService
from app.tasks.celery_app import celery_app


@celery_app.task(name="check_lead_timeout")
def check_lead_timeout(lead_id: str) -> None:
    async def _run():
        async with AsyncSessionLocal() as db:
            service = LeadDistributionService(db)
            await service.handle_timeout(uuid.UUID(lead_id))

    asyncio.run(_run())
