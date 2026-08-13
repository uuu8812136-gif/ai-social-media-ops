import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, String, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContentCalendar(Base):
    __tablename__ = "content_calendar"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    publish_status: Mapped[str] = mapped_column(String(20), default="pending")
    remind_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
