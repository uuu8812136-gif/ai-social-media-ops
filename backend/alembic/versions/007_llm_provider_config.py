"""add encrypted llm provider config

Revision ID: 007_llm_provider_config
Revises: 006_social_post_metrics
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_llm_provider_config"
down_revision = "006_social_post_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("config_key", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False, server_default="自定义模型"),
        sa.Column("protocol", sa.String(length=30), nullable=False, server_default="chat_completions"),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_key_hint", sa.String(length=20), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("config_key", name="uq_llm_provider_configs_config_key"),
    )
    op.create_index("ix_llm_provider_configs_config_key", "llm_provider_configs", ["config_key"])


def downgrade() -> None:
    op.drop_index("ix_llm_provider_configs_config_key", table_name="llm_provider_configs")
    op.drop_table("llm_provider_configs")
