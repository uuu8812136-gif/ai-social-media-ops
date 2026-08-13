"""Synapse 内嵌引擎的 Celery 任务定义。

设计原则：
1. Celery 任务是同步函数，内部用 asyncio.run() 启动 event loop 执行协程
2. 任务执行后直接通过 AsyncSessionLocal 写回 publish_tasks 表，不依赖 /result API
3. 单任务单 worker 单浏览器，避免 Playwright 资源竞争
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在 Celery worker 中安全运行协程。

    Windows 上需要 ProactorEventLoop 才能跑 Playwright subprocess。
    """
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        # Celery prefork keeps the Python process alive, but this helper creates
        # a new event loop for every Playwright task. The SQLAlchemy asyncpg
        # engine is process-global; keeping pooled connections from an old loop
        # causes later tasks to fail with "Future attached to a different loop"
        # / "Event loop is closed" while marking or writing back publish state.
        # Dispose the pool on the same loop before closing it.
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
    name="synapse.publish_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=1140,
    time_limit=1200,
)
def run_publish_task(self, task_spec: dict) -> dict:
    """发布任务执行：必须新建独立 event loop，避免污染 running 状态和 DB 写回。

    必须用 new_event_loop()，AsyncEngine/asyncpg 会缓存 loop 引用，
    否则会 "Future attached to a different loop"，所以不能复用 running loop。
    """
    task_id = task_spec.get("task_id", "unknown")
    execution_token = str(getattr(self.request, "id", "") or "")
    logger.info("[SynapseWorker] 开始执行发布任务 task_id=%s", task_id)

    async def _execute() -> dict:
        try:
            claimed = await _claim_publish_task(task_id, execution_token)
        except Exception as claim_err:
            # 无法确认数据库抢占时绝不能继续点击平台发布，宁可安全失败。
            logger.exception(
                "[SynapseWorker] 抢占发布任务失败 task_id=%s: %s",
                task_id,
                claim_err,
            )
            raise RuntimeError(
                "无法确认任务执行权，已阻止发布以避免重复内容"
            ) from claim_err
        if not claimed:
            logger.warning(
                "[SynapseWorker] 忽略重复或已终止的 Celery 消息 task_id=%s token=%s",
                task_id,
                execution_token,
            )
            return {
                "task_id": task_id,
                "success": False,
                "status": "duplicate_delivery_ignored",
                "message": "重复任务消息已安全忽略",
            }

        try:
            from app.integrations.synapse_engine.publish import Publisher
            from app.integrations.synapse_engine.utils.playwright_provider import (
                configure_windows_event_loop,
            )

            configure_windows_event_loop()
            # 把 task_id 绑定到当前协程上下文，供 builtin.py 验证流程读取
            # （无需改动 service/publisher 的 publish_content 签名）
            from app.integrations.synapse_engine.verification.manager import (
                reset_current_task_id,
                set_current_task_id,
            )
            _task_id_token = set_current_task_id(str(task_id))
            try:
                publisher = Publisher()
                result = await publisher.run(task_spec)
            finally:
                reset_current_task_id(_task_id_token)
            result["_execution_token"] = execution_token
            logger.info(
                "[SynapseWorker] 发布任务完成 task_id=%s success=%s status=%s",
                task_id,
                result.get("success"),
                result.get("status"),
            )
        except Exception as e:
            logger.exception("[SynapseWorker] 发布任务失败 task_id=%s", task_id)
            result = {
                "task_id": task_id,
                "success": False,
                "status": "worker_error",
                "error": str(e),
                "platform": task_spec.get("platform", ""),
            }

        if result.get("status") != "duplicate_delivery_ignored":
            try:
                await _writeback_safe(task_id, result)
            except Exception as wb_err:
                logger.exception(
                    "[SynapseWorker] 回写 DB 失败 task_id=%s: %s", task_id, wb_err
                )
        return result

    try:
        return _run_async(_execute())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _claim_publish_task(task_id: str, execution_token: str) -> bool:
    """原子抢占发布任务；重复 Celery 消息只有一个能进入真实发布流程。"""
    import uuid as _uuid
    from datetime import datetime, timezone

    try:
        publish_task_id = _uuid.UUID(str(task_id))
    except (ValueError, TypeError):
        # 兼容没有 PublishTask 记录的旧式 synapse_xxxx 调用。
        return True

    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.social_account import PublishTask

    async with AsyncSessionLocal() as db:
        claimed = await db.execute(
            update(PublishTask)
            .where(
                PublishTask.id == publish_task_id,
                PublishTask.status.in_(("queued", "scheduled", "pending")),
            )
            .values(
                status="running",
                execution_token=execution_token or None,
                started_at=datetime.now(timezone.utc),
                finished_at=None,
                error_message=None,
            )
            .returning(PublishTask.id)
        )
        task = claimed.scalar_one_or_none()
        await db.commit()
        return task is not None


async def _writeback_safe(task_id: str, result: dict) -> None:
    """调用 writeback_publish_result。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    await writeback_publish_result(task_id, result)


@celery_app.task(
    name="synapse.validate_cookie", soft_time_limit=150, time_limit=180
)
def run_cookie_validate(platform: str, account_id: str) -> dict:
    """异步校验账号 cookie，必须新建独立 event loop 执行。"""
    logger.info(
        "[SynapseWorker] 开始校验 cookie platform=%s account_id=%s",
        platform,
        account_id,
    )

    async def _execute() -> dict:
        try:
            from app.integrations.synapse_engine.service import EmbeddedSynapseService
            from app.integrations.synapse_engine.utils.playwright_provider import (
                configure_windows_event_loop,
            )

            configure_windows_event_loop()
            service = EmbeddedSynapseService()
            result = await service.validate_account_cookie(platform, account_id)
        except Exception as e:
            logger.exception("[SynapseWorker] cookie 校验失败 platform=%s", platform)
            result = {"valid": False, "reason": f"worker 异常: {e}"}

        try:
            await _writeback_cookie_validate(platform, account_id, result)
        except Exception as wb_err:
            logger.exception(
                "[SynapseWorker] cookie 校验回写 DB 失败 platform=%s account_id=%s: %s",
                platform,
                account_id,
                wb_err,
            )
        return result

    return _run_async(_execute())


async def _writeback_cookie_validate(
    platform: str, account_id: str, result: dict
) -> None:
    """Write async cookie validation result back to social_accounts."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.social_account import SocialAccount

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(SocialAccount).where(
                SocialAccount.platform == platform,
                SocialAccount.platform_uid == account_id,
            )
        )
        account = rows.scalar_one_or_none()
        if account is None:
            return
        account.cookie_status = "valid" if result.get("valid") else "invalid"
        account.last_validated_at = datetime.now(timezone.utc)
        await db.commit()


@celery_app.task(
    name="synapse.sync_post_metrics", soft_time_limit=270, time_limit=300
)
def run_sync_post_metrics(
    task_id: str,
    social_account_id: str = "",
    platform: str = "",
    publish_url: str = "",
    external_post_id: str = "",
) -> dict:
    """异步采集发布内容指标。

    用账号 Cookie + Playwright 打开发布链接读取互动数据。
    采集结果写回 social_post_metrics 表。
    """
    logger.info(
        "[SynapseWorker] 指标采集开始 task_id=%s platform=%s",
        task_id,
        platform,
    )

    async def _execute() -> dict:
        import uuid as _uuid
        from datetime import datetime, timezone

        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.integrations.synapse_engine.cookie import CookieManager
        from app.integrations.synapse_engine.metrics.collector import collect_metrics
        from app.models.social_account import (
            PublishTask,
            SocialAccount,
            SocialPostMetric,
        )

        async with AsyncSessionLocal() as db:
            # 加载 metric 记录
            try:
                tid = _uuid.UUID(str(task_id))
            except (ValueError, TypeError):
                return {"sync_status": "failed", "error": f"task_id 非法: {task_id}"}

            metric_result = await db.execute(
                select(SocialPostMetric).where(SocialPostMetric.task_id == tid)
            )
            metric = metric_result.scalar_one_or_none()
            if metric is None:
                # 没有 metric 记录，尝试创建
                task_result = await db.execute(
                    select(PublishTask).where(PublishTask.id == tid)
                )
                task = task_result.scalar_one_or_none()
                if task is None:
                    return {
                        "sync_status": "failed",
                        "error": f"PublishTask {task_id} 不存在",
                    }

                metric = SocialPostMetric(
                    task_id=task.id,
                    social_account_id=task.social_account_id,
                    content_id=task.content_id,
                    platform=task.platform,
                    external_post_id=task.external_post_id,
                    publish_url=task.publish_url,
                    source="browser",
                    sync_status="pending",
                )
                db.add(metric)
                await db.flush()

            # 获取账号 Cookie
            cookie_state = None
            if metric.social_account_id:
                acc_result = await db.execute(
                    select(SocialAccount).where(
                        SocialAccount.id == metric.social_account_id
                    )
                )
                account = acc_result.scalar_one_or_none()
                if account and account.platform_uid:
                    cookie_manager = CookieManager()
                    cookie_state = cookie_manager.load(
                        account.platform, account.platform_uid
                    )

            # 采集指标
            result = await collect_metrics(
                platform=metric.platform,
                publish_url=metric.publish_url,
                external_post_id=metric.external_post_id,
                cookie_storage_state=cookie_state,
            )

            # 写回 metric
            metric.sync_status = result.sync_status
            metric.metrics = result.metrics
            metric.raw_data = result.raw_data
            metric.error_message = result.error_message
            metric.last_synced_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(
                "[SynapseWorker] 指标采集完成 task_id=%s status=%s",
                task_id,
                result.sync_status,
            )
            return result.to_dict()

    return _run_async(_execute())


@celery_app.task(
    name="synapse.enqueue_due_metric_sync", soft_time_limit=90, time_limit=120
)
def enqueue_due_metric_sync(limit: int = 20) -> dict:
    """每六小时补投一小批过期作品指标同步任务。"""

    async def _execute() -> list[str]:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import or_, select

        from app.core.database import AsyncSessionLocal
        from app.models.social_account import PublishTask, SocialPostMetric

        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(PublishTask.id)
                .outerjoin(
                    SocialPostMetric,
                    SocialPostMetric.task_id == PublishTask.id,
                )
                .where(
                    PublishTask.status == "published",
                    or_(
                        SocialPostMetric.id.is_(None),
                        SocialPostMetric.last_synced_at.is_(None),
                        SocialPostMetric.last_synced_at < cutoff,
                    ),
                )
                .order_by(PublishTask.finished_at.desc().nullslast())
                .limit(max(1, min(int(limit), 100)))
            )
            return [str(task_id) for task_id in rows.scalars().all()]

    task_ids = _run_async(_execute())
    for task_id in task_ids:
        run_sync_post_metrics.apply_async(args=[task_id])
    return {"enqueued": len(task_ids), "task_ids": task_ids}


@celery_app.task(
    name="synapse.recover_stale_tasks", soft_time_limit=90, time_limit=120
)
def recover_stale_tasks() -> dict:
    """回收卡死的发布/采集任务。

    发布任务可能已在平台完成，因此超时后进入 publish_unknown，绝不自动重发。
    采集任务无外部写入副作用，标记 failed 后可重新创建。
    """

    async def _execute() -> dict:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.integrations.synapse_engine.native_browser import (
            native_browser_manager,
        )
        from app.integrations.synapse_engine.workers.writeback import (
            _recompute_batch_stats,
        )
        from app.models.crawler import CrawlerJob
        from app.models.social_account import PublishBatch, PublishTask

        now = datetime.now(timezone.utc)
        publish_cutoff = now - timedelta(minutes=25)
        queued_cutoff = now - timedelta(minutes=30)
        crawl_cutoff = now - timedelta(minutes=20)
        recovered_publish = 0
        recovered_queued = 0
        recovered_crawl = 0
        native_sessions: list[str] = []

        async with AsyncSessionLocal() as db:
            publish_rows = (
                await db.execute(
                    select(PublishTask).where(
                        PublishTask.status == "running",
                        PublishTask.started_at.is_not(None),
                        PublishTask.started_at < publish_cutoff,
                    )
                )
            ).scalars().all()
            affected_batches = set()
            for task in publish_rows:
                task.status = "publish_unknown"
                task.error_message = (
                    "任务执行超时，平台可能已收到发布操作，请人工核对后再决定是否重试"
                )
                task.finished_at = now
                recovered_publish += 1
                if task.batch_id:
                    affected_batches.add(task.batch_id)
                meta = task.verification_meta or {}
                if meta.get("presentation") == "native_window":
                    session_id = str(
                        meta.get("vnc_session_id")
                        or meta.get("native_session_id")
                        or ""
                    )
                    if session_id:
                        native_sessions.append(session_id)

            queued_rows = (
                await db.execute(
                    select(PublishTask).where(
                        PublishTask.status == "queued",
                        PublishTask.updated_at < queued_cutoff,
                    )
                )
            ).scalars().all()
            for task in queued_rows:
                task.status = "dispatch_failed"
                task.error_message = "任务长时间未被 worker 领取，请人工重试"
                task.finished_at = now
                recovered_queued += 1
                if task.batch_id:
                    affected_batches.add(task.batch_id)

            crawl_rows = (
                await db.execute(
                    select(CrawlerJob).where(
                        CrawlerJob.status == "running",
                        CrawlerJob.started_at.is_not(None),
                        CrawlerJob.started_at < crawl_cutoff,
                    )
                )
            ).scalars().all()
            for job in crawl_rows:
                job.status = "failed"
                job.error_message = "采集任务执行超时，已由系统回收"
                job.finished_at = now
                recovered_crawl += 1

            for batch_id in affected_batches:
                batch = await db.scalar(
                    select(PublishBatch).where(PublishBatch.id == batch_id)
                )
                if batch is not None:
                    await db.flush()
                    await _recompute_batch_stats(db, batch)
            await db.commit()

        for session_id in native_sessions:
            try:
                await native_browser_manager.release(session_id)
            except Exception:
                logger.warning(
                    "[SynapseWorker] 回收卡死任务时关闭浏览器失败 session=%s",
                    session_id,
                    exc_info=True,
                )
        return {
            "publish_unknown": recovered_publish,
            "queued_failed": recovered_queued,
            "crawl_failed": recovered_crawl,
        }

    return _run_async(_execute())


__all__ = [
    "run_publish_task",
    "run_cookie_validate",
    "run_sync_post_metrics",
    "enqueue_due_metric_sync",
    "recover_stale_tasks",
]
