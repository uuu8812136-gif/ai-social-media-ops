"""add publish task params

Revision ID: 005_publish_task_params
Revises: 004_social_crawler
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "005_publish_task_params"
down_revision = "004_social_crawler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_tasks", sa.Column("publish_params", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("publish_tasks", "publish_params")
