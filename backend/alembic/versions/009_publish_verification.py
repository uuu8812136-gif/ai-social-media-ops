"""add verification_meta to publish_tasks

Revision ID: 009_publish_verification
Revises: 008_schema_alignment
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009_publish_verification"
down_revision = "008_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publish_tasks",
        sa.Column("verification_meta", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publish_tasks", "verification_meta")
