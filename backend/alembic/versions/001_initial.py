"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(50), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("dealer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "cities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("region", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
    )
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("account_name", sa.String(100), nullable=False),
        sa.Column("platform_id", sa.String(100), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("strategy_engine", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), default="active"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "dealers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("contact_name", sa.String(50), nullable=False),
        sa.Column("contact_phone", sa.String(20), nullable=False),
        sa.Column("wecom_id", sa.String(100), nullable=True),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("level", sa.String(10), default="C"),
        sa.Column("annual_sales", sa.Numeric(15, 2), nullable=True),
        sa.Column("status", sa.String(20), default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "contents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("strategy_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("media_urls", postgresql.JSONB(), nullable=True),
        sa.Column("ai_model", sa.String(50), nullable=True),
        sa.Column("ai_prompt_snapshot", sa.Text(), nullable=True),
        sa.Column("risk_check_result", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("platform_stats", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_contents_account_status", "contents", ["account_id", "status"])
    op.create_index("idx_contents_created", "contents", [sa.text("created_at DESC")])
    op.create_table(
        "content_calendar",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("scheduled_time", sa.Time(), nullable=True),
        sa.Column("publish_status", sa.String(20), default="pending"),
        sa.Column("remind_sent", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pool_type", sa.String(20), nullable=False),
        sa.Column("source_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_platform", sa.String(20), nullable=True),
        sa.Column("customer_name", sa.String(50), nullable=False),
        sa.Column("customer_phone", sa.String(200), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requirement", sa.Text(), nullable=True),
        sa.Column("house_info", postgresql.JSONB(), nullable=True),
        sa.Column("assigned_dealer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("response_minutes", sa.Integer(), nullable=True),
        sa.Column("signed_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("lost_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_leads_pool_status", "leads", ["pool_type", "status"])
    op.create_index("idx_leads_dealer", "leads", ["assigned_dealer_id", "status"])
    op.create_index("idx_leads_created", "leads", [sa.text("created_at DESC")])
    op.create_table(
        "lead_followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "asset_library",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("is_public", sa.Boolean(), default=False),
        sa.Column("download_count", sa.Integer(), default=0),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_asset_type", "asset_library", ["asset_type", "category"])
    op.create_table(
        "risk_words",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("word", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
    )
    op.create_index("idx_risk_words_category", "risk_words", ["category", "is_active"])
    op.create_table(
        "risk_check_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("checked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("risk_check_history")
    op.drop_table("risk_words")
    op.drop_table("asset_library")
    op.drop_table("lead_followups")
    op.drop_table("leads")
    op.drop_table("content_calendar")
    op.drop_table("contents")
    op.drop_table("dealers")
    op.drop_table("accounts")
    op.drop_table("cities")
    op.drop_table("users")
