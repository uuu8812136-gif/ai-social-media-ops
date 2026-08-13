"""MediaCrawler Celery 任务。

任务执行后直接通过 AsyncSessionLocal 写回 crawler_jobs 状态，
不依赖 Celery result backend 和 /result API。
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        # 每次任务都创建独立事件循环；连接池里的 asyncpg 连接如果留给
        # 下一次调用，会绑定在已经关闭的旧 loop 上。
        try:
            from app.core.database import engine

            loop.run_until_complete(engine.dispose())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


@celery_app.task(
    name="mediacrawler.crawl",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=840,
    time_limit=900,
)
def run_crawl_task(self, task_spec: dict) -> dict:
    """执行采集任务并直接写回 crawler_jobs 表。

    Args:
        task_spec: 见 EmbeddedMediaCrawlerService.run_crawl 文档

    Returns:
        dict: 采集结果（同时已写回 DB，调用方无需再调 /result API）
    """
    job_id = task_spec.get("job_id", "unknown")
    platform = task_spec.get("platform", "")
    execution_token = str(getattr(self.request, "id", "") or "")
    logger.info(
        "[MediaCrawlerWorker] 开始采集任务 job_id=%s platform=%s", job_id, platform
    )

    try:
        claimed = _run_async(_claim_crawl_job(job_id, execution_token))
    except Exception as claim_err:
        logger.exception(
            "[MediaCrawlerWorker] 抢占任务失败 job_id=%s: %s", job_id, claim_err
        )
        raise self.retry(exc=claim_err)
    if not claimed:
        logger.warning("[MediaCrawlerWorker] 重复任务消息已忽略 job_id=%s", job_id)
        return {
            "job_id": job_id,
            "success": False,
            "status": "duplicate_delivery_ignored",
        }

    try:
        from app.integrations.mediacrawler_engine.service import (
            EmbeddedMediaCrawlerService,
        )

        async def _run():
            service = EmbeddedMediaCrawlerService()
            return await service.run_crawl(
                platform=platform,
                crawler_type=task_spec.get("crawler_type", "search"),
                params=task_spec.get("params") or {},
                config_overrides=task_spec.get("config_overrides"),
                save_dir=task_spec.get("save_dir"),
            )

        result = _run_async(_run())
        logger.info(
            "[MediaCrawlerWorker] 采集任务完成 job_id=%s success=%s items=%d",
            job_id,
            result.get("success"),
            result.get("items_count", 0),
        )
    except Exception as e:
        logger.exception("[MediaCrawlerWorker] 采集任务异常 job_id=%s", job_id)
        result = {
            "job_id": job_id,
            "success": False,
            "error": str(e),
            "platform": platform,
            "items_count": 0,
            "output_files": [],
        }
    result["_execution_token"] = execution_token

    # 直接写回 DB（不依赖 /result API）
    try:
        _run_async(_writeback_safe(job_id, result))
    except Exception as wb_err:
        logger.exception(
            "[MediaCrawlerWorker] 写回 DB 失败 job_id=%s: %s", job_id, wb_err
        )

    return result


async def _claim_crawl_job(job_id: str, execution_token: str) -> bool:
    """原子领取采集任务，重复 Celery 消息不会重复抓取。"""
    import uuid as _uuid

    try:
        crawl_job_id = _uuid.UUID(str(job_id))
    except (ValueError, TypeError):
        return True

    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.crawler import CrawlerJob

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(CrawlerJob)
            .where(
                CrawlerJob.id == crawl_job_id,
                CrawlerJob.status.in_(("queued", "pending")),
            )
            .values(
                status="running",
                started_at=datetime.now(timezone.utc),
                finished_at=None,
                error_message=None,
                execution_token=execution_token or None,
            )
            .returning(CrawlerJob.id)
        )
        claimed = result.scalar_one_or_none()
        await db.commit()
        return claimed is not None


async def _writeback_safe(job_id: str, result: dict) -> None:
    """调用 writeback_crawl_result。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        writeback_crawl_result,
    )

    await writeback_crawl_result(job_id, result)


__all__ = ["run_crawl_task"]
