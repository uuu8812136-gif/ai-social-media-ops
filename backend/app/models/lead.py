import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, desc, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("idx_leads_pool_status", "pool_type", "status"),
        Index("idx_leads_dealer", "assigned_dealer_id", "status"),
        Index("idx_leads_created", desc("created_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pool_type: Mapped[str] = mapped_column(String(20))
    source_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(50))
    customer_phone: Mapped[str] = mapped_column(String(200))
    city_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    house_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assigned_dealer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    response_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signed_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LeadFollowup(Base):
    __tablename__ = "lead_followups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    operator: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
