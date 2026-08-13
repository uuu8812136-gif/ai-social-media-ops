"""采集任务结果回写服务（worker 直接写库，不依赖 /result API）。

Celery worker 在采集任务执行完成后调用 writeback_crawl_result()，
直接通过 AsyncSessionLocal 写入 crawler_jobs / crawler_items 表。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.crawler import CrawlerItem, CrawlerJob

logger = logging.getLogger(__name__)


async def writeback_crawl_result(job_id: str, result: dict[str, Any]) -> None:
    """把采集结果写回 crawler_jobs 表，并解析采集文件写入 crawler_items 表。

    Args:
        job_id: 采集任务 ID（UUID 字符串）
        result: EmbeddedMediaCrawlerService.run_crawl 返回的结果 dict，字段：
            - success: bool
            - platform: str
            - items_count: int
            - output_files: list[dict] | list[str]
            - error: str | None
    """
    # 解析 job_id 为 UUID
    try:
        crawl_job_id = uuid.UUID(str(job_id))
    except (ValueError, TypeError):
        logger.warning(
            "writeback_crawl_result: job_id=%s 不是合法 UUID，跳过 DB 写回",
            job_id,
        )
        return

    success_flag = bool(result.get("success"))
    items_count = int(result.get("items_count") or 0)
    output_files = result.get("output_files") or []
    error_message = result.get("error")

    async with AsyncSessionLocal() as db:
        # 加载任务
        job_result = await db.execute(
            select(CrawlerJob).where(CrawlerJob.id == crawl_job_id)
        )
        job = job_result.scalar_one_or_none()
        if job is None:
            logger.warning(
                "writeback_crawl_result: CrawlerJob %s 不存在，跳过写回",
                crawl_job_id,
            )
            return

        result_execution_token = str(result.get("_execution_token") or "")
        if (
            result_execution_token
            and job.execution_token
            and result_execution_token != job.execution_token
        ):
            logger.warning(
                "writeback_crawl_result: 忽略过期执行结果 job_id=%s",
                crawl_job_id,
            )
            return

        # 任务已被取消则不覆盖状态
        if job.status == "cancelled":
            logger.info(
                "writeback_crawl_result: 任务 %s 已取消，不覆盖状态",
                crawl_job_id,
            )
            return

        # 更新任务状态
        job.status = "succeeded" if success_flag else "failed"
        job.items_count = items_count
        job.output_files = output_files
        job.error_message = error_message
        job.finished_at = datetime.now(timezone.utc)
        if job.started_at is None:
            job.started_at = job.finished_at

        # 解析采集文件并写入 crawler_items 表
        if success_flag and output_files:
            from app.integrations.mediacrawler_engine.stores import (
                parse_data_file,
                resolve_data_file,
            )

            await db.execute(
                delete(CrawlerItem).where(CrawlerItem.job_id == crawl_job_id)
            )
            inserted = 0
            for f in output_files:
                file_path = f.get("path") if isinstance(f, dict) else f
                if not file_path:
                    continue
                try:
                    items = parse_data_file(resolve_data_file(file_path))
                except Exception as e:
                    logger.warning(
                        "writeback_crawl_result: 解析文件 %s 失败: %s",
                        file_path,
                        e,
                    )
                    continue
                for item in items:
                    ci = _build_crawler_item(job, item)
                    if ci is not None:
                        db.add(ci)
                        inserted += 1
            # 以实际写入条目数为准（避免 items_count 与实际写入不一致）
            if inserted > 0 and job.items_count == 0:
                job.items_count = inserted

        await db.commit()
        logger.info(
            "writeback_crawl_result: 任务 %s 写回成功 status=%s items=%s",
            crawl_job_id,
            job.status,
            job.items_count,
        )


def _build_crawler_item(job: CrawlerJob, item: dict) -> CrawlerItem | None:
    """把采集到的单条 dict 转换为 CrawlerItem ORM 对象。"""
    # 标题：优先 title，其次 desc 前 200 字符
    title = item.get("title")
    if not title:
        desc = item.get("desc")
        if isinstance(desc, str):
            title = desc[:200]

    title = str(title)[:500] if title is not None else None
    item_type = str(item.get("type") or "")[:20] or None
    author_name = str(item.get("nickname") or item.get("author") or "")[:200] or None

    try:
        return CrawlerItem(
            job_id=job.id,
            platform=job.platform,
            platform_item_id=str(
                item.get("note_id") or item.get("video_id") or item.get("id") or ""
            ),
            item_type=item_type,
            title=title,
            desc=item.get("desc"),
            author_name=author_name,
            author_id=str(item.get("user_id") or item.get("author_id") or "")[:200],
            liked_count=_safe_int(item.get("liked_count") or item.get("like_count")),
            collected_count=_safe_int(item.get("collected_count")),
            comment_count=_safe_int(item.get("comment_count")),
            share_count=_safe_int(item.get("share_count")),
            media_urls=_normalize_media_urls(
                item.get("image_list"), item.get("video_url")
            ),
            raw_data=item,
        )
    except Exception as e:
        logger.warning("构建 CrawlerItem 失败: %s", e)
        return None


def _safe_int(value) -> int | None:
    """安全转 int，失败返回 None。"""
    if value is None:
        return None
    try:
        parsed = int(value)
        return max(-(2**31), min(parsed, 2**31 - 1))
    except (TypeError, ValueError):
        return None


def _normalize_media_urls(image_list: Any, video_url: Any) -> list:
    """把 image_list / video_url 规范化为 list。

    - image_list 是 list 时直接用（过滤掉空字符串）
    - 否则若 video_url 是字符串，转成 [video_url]
    - 都没有则返回 []
    """
    if isinstance(image_list, list):
        return [u for u in image_list if u]
    if isinstance(video_url, str) and video_url:
        return [video_url]
    if isinstance(video_url, list):
        return [u for u in video_url if u]
    return []


__all__ = ["writeback_crawl_result"]
