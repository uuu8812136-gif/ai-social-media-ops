"""Add knowledge_references to contents

Revision ID: add_knowledge_refs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "add_knowledge_refs"
down_revision = "002_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contents", sa.Column("knowledge_references", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("contents", "knowledge_references")
