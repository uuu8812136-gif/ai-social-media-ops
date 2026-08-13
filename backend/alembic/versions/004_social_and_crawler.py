"""social and crawler tables

Revision ID: 004_social_crawler
Revises: add_knowledge_refs
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_social_crawler"
down_revision = "add_knowledge_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== social_accounts =====
    op.create_table(
        "social_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("platform_uid", sa.String(length=100), nullable=True),
        sa.Column("nickname", sa.String(length=200), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("cookie_file", sa.String(length=255), nullable=True),
        sa.Column("cookie_status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_info", postgresql.JSONB(), nullable=True),
        sa.Column("linked_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_social_accounts_platform", "social_accounts", ["platform"])
    op.create_index("ix_social_accounts_platform_uid", "social_accounts", ["platform_uid"])
    op.create_index("ix_social_accounts_linked_account_id", "social_accounts", ["linked_account_id"])
    op.create_index("ix_social_accounts_owner_id", "social_accounts", ["owner_id"])

    # ===== publish_batches =====
    op.create_table(
        "publish_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title_snapshot", sa.String(length=200), nullable=True),
        sa.Column("publish_mode", sa.String(length=20), nullable=False, server_default="direct"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_publish_batches_content_id", "publish_batches", ["content_id"])

    # ===== publish_tasks =====
    op.create_table(
        "publish_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("social_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_ref", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("media_paths", postgresql.JSONB(), nullable=True),
        sa.Column("cover_path", sa.String(length=500), nullable=True),
        sa.Column("publish_mode", sa.String(length=20), nullable=False, server_default="direct"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("external_post_id", sa.String(length=200), nullable=True),
        sa.Column("publish_url", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=100), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_publish_tasks_batch_id", "publish_tasks", ["batch_id"])
    op.create_index("ix_publish_tasks_content_id", "publish_tasks", ["content_id"])
    op.create_index("ix_publish_tasks_social_account_id", "publish_tasks", ["social_account_id"])
    op.create_index("ix_publish_tasks_platform", "publish_tasks", ["platform"])
    op.create_index("ix_publish_tasks_status", "publish_tasks", ["status"])

    # ===== publish_task_logs =====
    op.create_table(
        "publish_task_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_publish_task_logs_task_id", "publish_task_logs", ["task_id"])

    # ===== crawler_jobs =====
    op.create_table(
        "crawler_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("crawler_type", sa.String(length=20), nullable=False, server_default="search"),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("items_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_files", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=100), nullable=True),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_crawler_jobs_platform", "crawler_jobs", ["platform"])
    op.create_index("ix_crawler_jobs_status", "crawler_jobs", ["status"])
    op.create_index("ix_crawler_jobs_creator_id", "crawler_jobs", ["creator_id"])

    # ===== crawler_items =====
    op.create_table(
        "crawler_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("platform_item_id", sa.String(length=200), nullable=True),
        sa.Column("item_type", sa.String(length=20), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("desc", sa.Text(), nullable=True),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("author_id", sa.String(length=200), nullable=True),
        sa.Column("liked_count", sa.Integer(), nullable=True),
        sa.Column("collected_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("share_count", sa.Integer(), nullable=True),
        sa.Column("media_urls", postgresql.JSONB(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_crawler_items_job_id", "crawler_items", ["job_id"])
    op.create_index("ix_crawler_items_platform", "crawler_items", ["platform"])
    op.create_index("ix_crawler_items_platform_item_id", "crawler_items", ["platform_item_id"])

    # ===== crawler_import_logs =====
    op.create_table(
        "crawler_import_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target", sa.String(length=20), nullable=False, server_default="content"),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="success"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_crawler_import_logs_job_id", "crawler_import_logs", ["job_id"])
    op.create_index("ix_crawler_import_logs_item_id", "crawler_import_logs", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_crawler_import_logs_item_id", table_name="crawler_import_logs")
    op.drop_index("ix_crawler_import_logs_job_id", table_name="crawler_import_logs")
    op.drop_table("crawler_import_logs")

    op.drop_index("ix_crawler_items_platform_item_id", table_name="crawler_items")
    op.drop_index("ix_crawler_items_platform", table_name="crawler_items")
    op.drop_index("ix_crawler_items_job_id", table_name="crawler_items")
    op.drop_table("crawler_items")

    op.drop_index("ix_crawler_jobs_creator_id", table_name="crawler_jobs")
    op.drop_index("ix_crawler_jobs_status", table_name="crawler_jobs")
    op.drop_index("ix_crawler_jobs_platform", table_name="crawler_jobs")
    op.drop_table("crawler_jobs")

    op.drop_index("ix_publish_task_logs_task_id", table_name="publish_task_logs")
    op.drop_table("publish_task_logs")

    op.drop_index("ix_publish_tasks_status", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_platform", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_social_account_id", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_content_id", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_batch_id", table_name="publish_tasks")
    op.drop_table("publish_tasks")

    op.drop_index("ix_publish_batches_content_id", table_name="publish_batches")
    op.drop_table("publish_batches")

    op.drop_index("ix_social_accounts_owner_id", table_name="social_accounts")
    op.drop_index("ix_social_accounts_linked_account_id", table_name="social_accounts")
    op.drop_index("ix_social_accounts_platform_uid", table_name="social_accounts")
    op.drop_index("ix_social_accounts_platform", table_name="social_accounts")
    op.drop_table("social_accounts")
