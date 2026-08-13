"""add social post metrics

Revision ID: 006_social_post_metrics
Revises: 005_publish_task_params
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "006_social_post_metrics"
down_revision = "005_publish_task_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_post_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("social_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("external_post_id", sa.String(length=200), nullable=True),
        sa.Column("publish_url", sa.String(length=500), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="browser"),
        sa.Column("sync_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_social_post_metrics_task_id", "social_post_metrics", ["task_id"])
    op.create_index("ix_social_post_metrics_social_account_id", "social_post_metrics", ["social_account_id"])
    op.create_index("ix_social_post_metrics_content_id", "social_post_metrics", ["content_id"])
    op.create_index("ix_social_post_metrics_platform", "social_post_metrics", ["platform"])
    op.create_index("ix_social_post_metrics_external_post_id", "social_post_metrics", ["external_post_id"])
    op.create_unique_constraint("uq_social_post_metrics_task_id", "social_post_metrics", ["task_id"])


def downgrade() -> None:
    op.drop_constraint("uq_social_post_metrics_task_id", "social_post_metrics", type_="unique")
    op.drop_index("ix_social_post_metrics_external_post_id", table_name="social_post_metrics")
    op.drop_index("ix_social_post_metrics_platform", table_name="social_post_metrics")
    op.drop_index("ix_social_post_metrics_content_id", table_name="social_post_metrics")
    op.drop_index("ix_social_post_metrics_social_account_id", table_name="social_post_metrics")
    op.drop_index("ix_social_post_metrics_task_id", table_name="social_post_metrics")
    op.drop_table("social_post_metrics")
