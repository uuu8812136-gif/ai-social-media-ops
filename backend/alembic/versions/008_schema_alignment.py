"""align core constraints and indexes

Revision ID: 008_schema_alignment
Revises: 007_llm_provider_config
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op

revision = "008_schema_alignment"
down_revision = "007_llm_provider_config"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("accounts", "status", sa.String(length=20), "'active'"),
    ("accounts", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("accounts", "updated_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("asset_library", "is_public", sa.Boolean(), "false"),
    ("asset_library", "download_count", sa.Integer(), "0"),
    ("asset_library", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("cities", "is_active", sa.Boolean(), "true"),
    ("content_calendar", "publish_status", sa.String(length=20), "'pending'"),
    ("content_calendar", "remind_sent", sa.Boolean(), "false"),
    ("content_calendar", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("contents", "status", sa.String(length=20), "'draft'"),
    ("contents", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("contents", "updated_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("dealers", "level", sa.String(length=10), "'C'"),
    ("dealers", "status", sa.String(length=20), "'active'"),
    ("dealers", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("dealers", "updated_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("lead_followups", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("leads", "status", sa.String(length=20), "'pending'"),
    ("leads", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("leads", "updated_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    (
        "risk_check_history",
        "created_at",
        sa.DateTime(timezone=True),
        "CURRENT_TIMESTAMP",
    ),
    ("risk_words", "is_active", sa.Boolean(), "true"),
    ("users", "is_active", sa.Boolean(), "true"),
    ("users", "created_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
    ("users", "updated_at", sa.DateTime(timezone=True), "CURRENT_TIMESTAMP"),
)


def upgrade() -> None:
    # Older deployments allowed NULL in defaulted lifecycle fields. Backfill first
    # so the constraint upgrade remains safe for existing production data.
    for table, column, column_type, fallback_sql in _COLUMNS:
        op.execute(
            sa.text(
                f'UPDATE "{table}" SET "{column}" = {fallback_sql} WHERE "{column}" IS NULL'
            )
        )
        op.alter_column(table, column, existing_type=column_type, nullable=False)

    op.create_index(
        "ix_content_calendar_account_id", "content_calendar", ["account_id"]
    )
    op.create_index("ix_lead_followups_lead_id", "lead_followups", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_followups_lead_id", table_name="lead_followups")
    op.drop_index("ix_content_calendar_account_id", table_name="content_calendar")
    for table, column, column_type, _ in reversed(_COLUMNS):
        op.alter_column(table, column, existing_type=column_type, nullable=True)
