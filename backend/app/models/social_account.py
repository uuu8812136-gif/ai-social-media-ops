"""社媒账号模型。

social_accounts 表是系统唯一的社媒账号来源，存储扫码登录后的账号信息、
Cookie 状态、用户信息，并供内容生产、日历、发布和数据回流统一引用。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 平台代码：xiaohongshu|channels|douyin|kuaishou|bilibili
    platform: Mapped[str] = mapped_column(String(20), index=True)
    # 平台原始账号 ID（从 cookie 中解析得到，可能为空）
    platform_uid: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    # 账号显示名
    nickname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # cookie 文件名（不含路径），实际路径 = SYNAPSE_COOKIE_DIR/<cookie_file>
    cookie_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # cookie 状态：valid|invalid|expired|unknown
    cookie_status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 用户信息（user_id, name, username, avatar, extra）
    user_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 关联到 accounts 表（如果用户绑定了既有账号）
    linked_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # 备注
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active|disabled|deleted
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PublishBatch(Base):
    """发布批次：一次"发布到社媒"操作可能产生多个发布任务（多账号/多平台）。"""

    __tablename__ = "publish_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    # 操作发起人
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 前端每次提交生成的幂等键；网络重试不会重复创建整个发布批次。
    request_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    # 批次标题（冗余，方便列表展示）
    title_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 发布模式：direct|schedule
    publish_mode: Mapped[str] = mapped_column(String(20), default="direct")
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 批次状态：pending|running|completed|partial_failed|failed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PublishTask(Base):
    """单个发布任务（一批中的一个账号 + 平台组合）。"""

    __tablename__ = "publish_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    social_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), index=True)
    # 冗余存账号 ID 字符串（cookie 文件查找用）
    account_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 发布内容快照（标题、正文、标签、媒体路径）
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    media_paths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 账号 + 平台 + 文案 + 素材 + 参数的稳定摘要，用于阻止短期重复投递。
    content_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # 平台发布参数：可见性、定位、话题、封面策略、互动开关等。
    # 示例：{"visibility":"public","location":"广州","topics":["门窗"],"allow_download":true}
    publish_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 发布模式
    publish_mode: Mapped[str] = mapped_column(String(20), default="direct")
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 任务状态：pending|queued|running|published|failed|cancelled|reviewing
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 平台返回的笔记/视频 ID
    external_post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    publish_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Celery task id（用于取消任务）
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Celery 消息抢占令牌；同一 task_id 的重复消息只能有一个真正执行。
    execution_token: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 重试次数
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    # 完成时间
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 验证码/人机验证相关元数据：
    # {verification_type, vnc_session_id, cdp_url, vnc_password,
    #  captcha_hint, screenshot_path, appeared_at, ...}
    verification_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # publish_unknown 必须由人工确认后才能重试，避免重复发布。
    confirmation_outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    confirmation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 验证状态机：needs_phone_captcha|needs_human_captcha|awaiting_resume
    # （也写进 status 字段，这里是冗余便于查询，不单独建列）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PublishTaskLog(Base):
    """发布任务执行日志（一个任务可有多条日志）。"""

    __tablename__ = "publish_task_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    # log level: info|warning|error
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    # 详细数据（如平台返回的原始响应）
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SocialPostMetric(Base):
    """社媒发布内容的数据快照。

    以 PublishTask 为主线关联账号和内容。指标来源可以是：
    - browser：用账号 Cookie 打开平台网页直接读取
    - crawler：后续接 MediaCrawler / Douyin_TikTok_Download_API
    - manual/import：外部导入
    """

    __tablename__ = "social_post_metrics"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_social_post_metrics_task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    social_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), index=True)
    external_post_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    publish_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="browser")
    sync_status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending|synced|unavailable|failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
