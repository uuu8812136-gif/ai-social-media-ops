"""采集任务模型。

crawler_jobs: 采集任务（一次 MediaCrawler 任务）
crawler_items: 采集到的笔记/视频条目
crawler_import_logs: 导入到 contents/assets 的日志
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CrawlerJob(Base):
    __tablename__ = "crawler_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 任务名（用户自定义）
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 平台：xiaohongshu|douyin|bilibili
    platform: Mapped[str] = mapped_column(String(20), index=True)
    # 采集类型：search|creator|detail|comment
    crawler_type: Mapped[str] = mapped_column(String(20), default="search")
    # 采集参数（关键字、URL、creator_id 等）
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 配置（headless、save_format、max_notes 等）
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 任务状态：pending|running|succeeded|failed|cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 采集到的条目数
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    # 输出文件路径（相对 MEDIACRAWLER_DATA_DIR）
    output_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Celery task id
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 原子任务领取令牌，阻止重复 Celery 消息重复执行采集。
    execution_token: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CrawlerItem(Base):
    """采集到的单条数据（笔记/视频）。"""

    __tablename__ = "crawler_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    # 平台原始 note_id/video_id
    platform_item_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    # 笔记/视频类型
    item_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 作者信息
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 互动数据
    liked_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    share_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 媒体 URL（图片/视频）
    media_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 原始 JSON 数据
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 采集时间
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CrawlerImportLog(Base):
    """采集数据导入到 contents/assets 的日志。"""

    __tablename__ = "crawler_import_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # 导入目标：content|asset
    target: Mapped[str] = mapped_column(String(20), default="content")
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 导入状态：success|failed|skipped
    status: Mapped[str] = mapped_column(String(20), default="success")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
