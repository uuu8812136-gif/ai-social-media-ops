"""add crawler execution token

Revision ID: 011_crawler_execution_token
Revises: 010_publish_idempotency
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "011_crawler_execution_token"
down_revision = "010_publish_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawler_jobs",
        sa.Column("execution_token", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crawler_jobs", "execution_token")
