"""add publish idempotency and manual confirmation fields

Revision ID: 010_publish_idempotency
Revises: 009_publish_verification
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "010_publish_idempotency"
down_revision = "009_publish_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publish_batches",
        sa.Column("request_key", sa.String(length=100), nullable=True),
    )
    op.create_unique_constraint(
        "uq_publish_batches_request_key", "publish_batches", ["request_key"]
    )

    op.add_column(
        "publish_tasks",
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("execution_token", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("confirmation_outcome", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("confirmation_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column(
            "confirmed_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "publish_tasks",
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_index(
        "ix_publish_tasks_content_fingerprint",
        "publish_tasks",
        ["content_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publish_tasks_content_fingerprint",
        table_name="publish_tasks",
    )
    op.drop_column("publish_tasks", "confirmed_at")
    op.drop_column("publish_tasks", "confirmed_by")
    op.drop_column("publish_tasks", "confirmation_note")
    op.drop_column("publish_tasks", "confirmation_outcome")
    op.drop_column("publish_tasks", "started_at")
    op.drop_column("publish_tasks", "execution_token")
    op.drop_column("publish_tasks", "content_fingerprint")
    op.drop_constraint(
        "uq_publish_batches_request_key",
        "publish_batches",
        type_="unique",
    )
    op.drop_column("publish_batches", "request_key")
