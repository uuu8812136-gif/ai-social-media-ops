import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, desc, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Content(Base):
    __tablename__ = "contents"
    __table_args__ = (
        Index("idx_contents_account_status", "account_id", "status"),
        Index("idx_contents_created", desc("created_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    content_type: Mapped[str] = mapped_column(String(20))
    strategy_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    body_text: Mapped[str] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    media_urls: Mapped[list | None] = mapped_column(JSONB, default=list)
    ai_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_prompt_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_check_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    knowledge_references: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )  # draft -> ai_generated -> risk_checked -> approved/human_reviewed -> scheduled -> published -> stats_synced
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    platform_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
