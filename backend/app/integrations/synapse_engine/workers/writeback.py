"""发布任务结果回写服务（worker 直接写库，不依赖 /result API）。

Celery worker 在任务执行完成后调用 writeback_publish_result()，
直接通过 AsyncSessionLocal 写入 publish_tasks / publish_batches / publish_task_logs 表。

task_id 可能的形态：
1. UUID 字符串（来自 /social/publish 路由创建的 PublishTask.id）→ 正常写回
2. "synapse_xxxx" 形态（来自 synapse_embedded_provider 派发的任务）→ 找不到记录，只记日志
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.social_account import (
    PublishBatch,
    PublishTask,
    PublishTaskLog,
    SocialPostMetric,
)
from app.utils.url_safety import normalize_public_http_url

logger = logging.getLogger(__name__)


def _normalize_task_status(raw_status: Any, success: bool) -> str:
    """Map adapter status values to values that fit publish_tasks.status."""
    status = str(raw_status or "unknown").strip() or "unknown"
    if status == "filled":
        return "publish_error"
    if len(status) <= 20:
        return status
    if success:
        return "published"
    return "publish_error"


async def writeback_publish_result(task_id: str, result: dict[str, Any]) -> None:
    """把发布结果写回 publish_tasks 表。

    Args:
        task_id: 任务 ID（UUID 字符串或 synapse_xxxx）
        result: Publisher.run 返回的结果 dict，字段：
            - success: bool
            - status: published|filled|cookie_missing|publish_error|...
            - external_post_id: str | None
            - publish_url: str | None
            - error: str | None
            - message: str | None
    """
    # 解析 task_id 为 UUID；解析失败说明是 synapse_embedded_provider 派发的旧式任务
    try:
        publish_task_id = uuid.UUID(str(task_id))
    except (ValueError, TypeError):
        logger.warning(
            "writeback_publish_result: task_id=%s 不是合法 UUID，"
            "可能来自 synapse_embedded_provider 派发的任务，跳过 DB 写回",
            task_id,
        )
        return

    success_flag = bool(result.get("success"))
    raw_status = result.get("status", "unknown")
    status = _normalize_task_status(raw_status, success_flag)
    # 把 "filled" 视为发布未完成（builtin 适配器只填表没点击发布）→ 不算成功
    if raw_status == "filled":
        success_flag = False
        status = _normalize_task_status(raw_status, success_flag)

    async with AsyncSessionLocal() as db:
        # 加载任务
        task_result = await db.execute(
            select(PublishTask).where(PublishTask.id == publish_task_id)
        )
        task = task_result.scalar_one_or_none()
        if task is None:
            logger.warning(
                "writeback_publish_result: PublishTask %s 不存在，跳过写回",
                publish_task_id,
            )
            return

        result_execution_token = str(result.get("_execution_token") or "")
        if (
            result_execution_token
            and task.execution_token
            and result_execution_token != task.execution_token
        ):
            logger.warning(
                "writeback_publish_result: 忽略过期执行结果 task_id=%s result_token=%s current_token=%s",
                publish_task_id,
                result_execution_token,
                task.execution_token,
            )
            return

        # 任务已被取消则不覆盖状态
        if task.status == "cancelled":
            logger.info(
                "writeback_publish_result: 任务 %s 已取消，不覆盖状态",
                publish_task_id,
            )
            return

        # 更新任务状态
        task.status = status
        if "external_post_id" in result:
            task.external_post_id = result.get("external_post_id")
        if "publish_url" in result:
            task.publish_url = normalize_public_http_url(result.get("publish_url"))
        if success_flag:
            task.error_message = None
        else:
            task.error_message = (
                result.get("error") or result.get("message") or task.error_message
            )
        task.finished_at = datetime.now(timezone.utc)

        # 写日志
        log_level = "info" if success_flag else "error"
        log_message = (
            result.get("message")
            or result.get("error")
            or f"任务执行完成，状态: {status}"
        )
        db.add(
            PublishTaskLog(
                task_id=task.id,
                level=log_level,
                message=log_message,
                extra={**result, "raw_status": raw_status, "stored_status": status},
            )
        )

        # 更新批次统计
        if task.batch_id:
            batch_result = await db.execute(
                select(PublishBatch).where(PublishBatch.id == task.batch_id)
            )
            batch = batch_result.scalar_one_or_none()
            if batch is not None:
                await db.flush()
                await _recompute_batch_stats(db, batch)

        # 发布成功时创建 pending SocialPostMetric，等待后续指标采集
        existing_metric_result = await db.execute(
            select(SocialPostMetric).where(SocialPostMetric.task_id == task.id)
        )
        existing_metric = existing_metric_result.scalar_one_or_none()
        if success_flag and status in ("published", "reviewing"):
            try:
                if existing_metric is None:
                    metric = SocialPostMetric(
                        task_id=task.id,
                        social_account_id=task.social_account_id,
                        content_id=task.content_id,
                        platform=task.platform,
                        external_post_id=task.external_post_id,
                        publish_url=task.publish_url,
                        metrics=None,
                        raw_data=None,
                        source="browser",
                        sync_status="pending",
                        error_message=None,
                        last_synced_at=None,
                    )
                    db.add(metric)
                    await db.commit()
                    logger.info(
                        "writeback_publish_result: 已为任务 %s 创建 pending SocialPostMetric",
                        publish_task_id,
                    )
                else:
                    existing_metric.external_post_id = task.external_post_id
                    existing_metric.publish_url = task.publish_url
                    if existing_metric.sync_status in {"failed", "unavailable"}:
                        existing_metric.sync_status = "pending"
                        existing_metric.error_message = None
            except Exception as metric_err:
                logger.warning(
                    "writeback_publish_result: 创建 SocialPostMetric 失败（不影响发布结果）: %s",
                    metric_err,
                )
        elif existing_metric is not None:
            existing_metric.sync_status = "failed"
            existing_metric.error_message = (
                task.error_message or "发布任务失败，未生成可采集的平台内容"
            )
            existing_metric.external_post_id = task.external_post_id
            existing_metric.publish_url = task.publish_url

        await db.commit()
        logger.info(
            "writeback_publish_result: 任务 %s 写回成功 status=%s success=%s",
            publish_task_id,
            status,
            success_flag,
        )


async def _recompute_batch_stats(db, batch: PublishBatch) -> None:
    """按任务当前最终状态重算批次，保证重试和重复回写保持幂等。"""
    result = await db.execute(
        select(PublishTask.status).where(PublishTask.batch_id == batch.id)
    )
    statuses = [str(value or "") for value in result.scalars().all()]
    success_statuses = {"published", "reviewing"}
    # 验证码/人机验证等待中的状态也视为 active，避免批次被提前结算为失败
    active_statuses = {
        "pending", "scheduled", "queued", "running",
        "needs_phone_captcha", "needs_human_captcha", "awaiting_resume",
    }
    success_count = sum(value in success_statuses for value in statuses)
    failed_count = sum(
        value not in success_statuses | active_statuses for value in statuses
    )

    batch.success_count = success_count
    batch.failed_count = failed_count
    finished = success_count + failed_count
    total = batch.total or len(statuses)
    if finished >= total and total > 0:
        if failed_count == 0:
            batch.status = "completed"
        elif success_count == 0:
            batch.status = "failed"
        else:
            batch.status = "partial_failed"
    elif finished > 0:
        batch.status = "running"
    else:
        batch.status = "pending"

    if batch.content_id:
        from app.models.content import Content

        content = await db.scalar(select(Content).where(Content.id == batch.content_id))
        if content is not None:
            if success_count > 0 and finished >= total:
                content.status = "published"
                if content.published_at is None:
                    content.published_at = datetime.now(timezone.utc)
            elif failed_count >= total and total > 0:
                content.status = "publish_failed"
            elif content.status in {"approved", "human_reviewed", "publish_failed"}:
                content.status = "scheduled"


__all__ = ["writeback_publish_result"]
