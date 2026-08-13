import asyncio
import uuid

from app.core.database import AsyncSessionLocal
from app.services.content_gen import ContentGenerationService, ScriptRequest
from app.tasks.celery_app import celery_app


@celery_app.task(name="generate_script_async")
def generate_script_async(payload: dict) -> list:
    async def _run():
        async with AsyncSessionLocal() as db:
            service = ContentGenerationService(db)
            req = ScriptRequest(
                account_id=uuid.UUID(payload["account_id"]),
                topic=payload["topic"],
                strategy_type=payload["strategy_type"],
                duration=payload.get("duration", "30s"),
                style=payload.get("style", ""),
                local_cities=payload.get("local_cities"),
                count=payload.get("count", 1),
            )
            return await service.generate_script(req)

    return asyncio.run(_run())
