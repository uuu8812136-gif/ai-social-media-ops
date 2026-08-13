"""Minimal application bootstrap without demo business data."""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.security import get_password_hash
from app.models.user import User


async def seed_data() -> None:
    settings = get_settings()

    # Local development can start without running Alembic manually. Production
    # relies exclusively on the migration step in entrypoint.sh.
    if not settings.is_production:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    if not settings.BOOTSTRAP_ADMIN_ENABLED:
        return

    async with AsyncSessionLocal() as db:
        admin = await db.scalar(
            select(User).where(User.username == settings.BOOTSTRAP_ADMIN_USERNAME)
        )
        if admin:
            return

        db.add(
            User(
                username=settings.BOOTSTRAP_ADMIN_USERNAME,
                password_hash=get_password_hash(settings.SEED_ADMIN_PASSWORD),
                role="admin",
                full_name=settings.BOOTSTRAP_ADMIN_NAME,
                is_active=True,
            )
        )
        await db.commit()
