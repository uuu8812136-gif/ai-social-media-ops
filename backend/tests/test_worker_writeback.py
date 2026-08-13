"""Worker 写回服务测试。

测试场景：
1. 发布任务 queued → success/failed 写回（含 filled 视为失败、cancelled 不覆盖、非 UUID 跳过）
2. 批次统计更新（全部成功 → completed、部分失败 → partial_failed、全部失败 → failed）
3. 采集任务写回（成功 → succeeded、失败 → failed、非 UUID 跳过）
4. 外部源码路径不存在时仍能运行本项目内置代码（降级测试）

依赖：DB 测试用例需要可用的 PostgreSQL 数据库（与 test_api.py 一致）；
     降级测试用例不依赖 DB，始终可运行。
"""

import os
import socket
import uuid

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.crawler import CrawlerItem, CrawlerJob
from app.models.social_account import PublishBatch, PublishTask, PublishTaskLog

# 检查 DB 是否可用（DATABASE_URL 中的主机能否解析 + 端口能否连通）
_settings = get_settings()
_db_url = _settings.DATABASE_URL
# 简单解析 postgresql+asyncpg://user:pass@host:port/db
try:
    _db_host = _db_url.split("@")[-1].split(":")[0].split("/")[0]
    _db_port = int(_db_url.split("@")[-1].split(":")[1].split("/")[0])
except Exception:
    _db_host, _db_port = "postgres", 5432


def _db_reachable() -> bool:
    """快速检查 DB 主机端口是否可达（超时 1 秒）。"""
    try:
        with socket.create_connection((_db_host, _db_port), timeout=1):
            return True
    except OSError:
        return False


_DB_AVAILABLE = _db_reachable()
_skip_no_db = pytest.mark.skipif(
    not _DB_AVAILABLE, reason=f"DB {_db_host}:{_db_port} 不可达"
)


# ============ 辅助函数 ============


async def _create_publish_task(
    *,
    platform: str = "xiaohongshu",
    status: str = "queued",
    batch_id=None,
) -> PublishTask:
    """创建测试用 PublishTask 并返回（含 id）。"""
    task = PublishTask(
        platform=platform,
        status=status,
        title="测试发布任务",
        batch_id=batch_id,
    )
    async with AsyncSessionLocal() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)
    return task


async def _create_batch(*, total: int = 1) -> PublishBatch:
    """创建测试用 PublishBatch。"""
    batch = PublishBatch(
        content_id=uuid.uuid4(),
        title_snapshot="测试批次",
        publish_mode="direct",
        status="running",
        total=total,
        success_count=0,
        failed_count=0,
    )
    async with AsyncSessionLocal() as db:
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
    return batch


async def _create_crawler_job(
    *, platform: str = "xhs", status: str = "queued"
) -> CrawlerJob:
    """创建测试用 CrawlerJob。"""
    job = CrawlerJob(
        platform=platform,
        crawler_type="search",
        status=status,
        params={"keywords": ["测试关键词"]},
    )
    async with AsyncSessionLocal() as db:
        db.add(job)
        await db.commit()
        await db.refresh(job)
    return job


async def _cleanup_publish_task(task_id: uuid.UUID) -> None:
    """删除测试创建的 PublishTask 及其日志。"""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(PublishTaskLog).where(PublishTaskLog.task_id == task_id)
        )
        await db.execute(delete(PublishTask).where(PublishTask.id == task_id))
        await db.commit()


async def _cleanup_batch(batch_id: uuid.UUID) -> None:
    """删除测试创建的 PublishBatch。"""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PublishBatch).where(PublishBatch.id == batch_id))
        await db.commit()


async def _cleanup_crawler_job(job_id: uuid.UUID) -> None:
    """删除测试创建的 CrawlerJob 及其条目。"""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CrawlerItem).where(CrawlerItem.job_id == job_id))
        await db.execute(delete(CrawlerJob).where(CrawlerJob.id == job_id))
        await db.commit()


async def _get_publish_task(task_id: uuid.UUID) -> PublishTask | None:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PublishTask).where(PublishTask.id == task_id))
        return res.scalar_one_or_none()


async def _get_publish_batch(batch_id: uuid.UUID) -> PublishBatch | None:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PublishBatch).where(PublishBatch.id == batch_id))
        return res.scalar_one_or_none()


async def _get_crawler_job(job_id: uuid.UUID) -> CrawlerJob | None:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(CrawlerJob).where(CrawlerJob.id == job_id))
        return res.scalar_one_or_none()


async def _count_task_logs(task_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(PublishTaskLog).where(PublishTaskLog.task_id == task_id)
        )
        return len(res.scalars().all())


# ============================================================
# 测试：发布任务写回（queued → success/failed）
# ============================================================


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_publish_success():
    """发布成功写回：queued → published，记录日志，写入 external_post_id。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    task = await _create_publish_task(status="queued")
    try:
        result = {
            "success": True,
            "status": "published",
            "external_post_id": "note_abc123",
            "publish_url": "https://www.xiaohongshu.com/note/abc123",
        }
        await writeback_publish_result(str(task.id), result)

        saved = await _get_publish_task(task.id)
        assert saved is not None
        assert saved.status == "published"
        assert saved.external_post_id == "note_abc123"
        assert saved.publish_url == "https://www.xiaohongshu.com/note/abc123"
        assert saved.finished_at is not None

        log_count = await _count_task_logs(task.id)
        assert log_count >= 1
    finally:
        await _cleanup_publish_task(task.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_publish_failed():
    """发布失败写回：queued → publish_error，记录错误信息。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    task = await _create_publish_task(status="queued")
    try:
        result = {
            "success": False,
            "status": "publish_error",
            "error": "发布按钮未找到",
        }
        await writeback_publish_result(str(task.id), result)

        saved = await _get_publish_task(task.id)
        assert saved is not None
        assert saved.status == "publish_error"
        assert "发布按钮未找到" in (saved.error_message or "")
        assert saved.finished_at is not None
    finally:
        await _cleanup_publish_task(task.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_account_restricted_uses_customer_facing_failure_status():
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    task = await _create_publish_task(status="queued")
    try:
        await writeback_publish_result(
            str(task.id),
            {
                "success": False,
                "status": "account_restricted",
                "error": "快手账号已被封禁或限制使用",
            },
        )

        saved = await _get_publish_task(task.id)
        assert saved.status == "account_restricted"
        assert saved.error_message == "快手账号已被封禁或限制使用"
    finally:
        await _cleanup_publish_task(task.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_publish_filled_treated_as_failure():
    """filled 状态视为失败：success=True 但 status=filled → batch 统计算失败。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    batch = await _create_batch(total=1)
    task = await _create_publish_task(status="queued", batch_id=batch.id)
    try:
        # 即使 success=True，status=filled 也应被视作失败
        result = {"success": True, "status": "filled"}
        await writeback_publish_result(str(task.id), result)

        saved = await _get_publish_task(task.id)
        assert saved is not None
        assert saved.status == "publish_error"

        b = await _get_publish_batch(batch.id)
        # filled 不算成功，所以 success_count=0, failed_count=1
        assert b.success_count == 0
        assert b.failed_count == 1
        assert b.status == "failed"
    finally:
        await _cleanup_publish_task(task.id)
        await _cleanup_batch(batch.id)


@pytest.mark.asyncio
async def test_writeback_publish_invalid_task_id_skipped():
    """非 UUID 的 task_id（synapse_embedded_provider 派发的旧式任务）应静默跳过。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    # 不应抛异常
    await writeback_publish_result(
        "synapse_abc123", {"success": True, "status": "published"}
    )
    await writeback_publish_result("not-a-uuid", {"success": False, "status": "error"})


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_publish_cancelled_not_overwritten():
    """已取消的任务不应被写回覆盖。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    task = await _create_publish_task(status="cancelled")
    try:
        await writeback_publish_result(
            str(task.id),
            {"success": True, "status": "published", "external_post_id": "xxx"},
        )

        saved = await _get_publish_task(task.id)
        assert saved is not None
        assert saved.status == "cancelled"  # 未被覆盖
        assert saved.external_post_id is None  # 未被写入
    finally:
        await _cleanup_publish_task(task.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_publish_task_claim_is_atomic():
    """重复 Celery 消息只能有一个抢占到真实发布执行权。"""
    from app.integrations.synapse_engine.workers.tasks import _claim_publish_task

    task = await _create_publish_task(status="queued")
    try:
        assert await _claim_publish_task(str(task.id), "delivery-first") is True
        assert await _claim_publish_task(str(task.id), "delivery-second") is False

        saved = await _get_publish_task(task.id)
        assert saved is not None
        assert saved.status == "running"
        assert saved.execution_token == "delivery-first"
        assert saved.started_at is not None
    finally:
        await _cleanup_publish_task(task.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_stale_execution_result_is_ignored():
    """重试后的新 worker 已接管时，旧 worker 结果不能覆盖当前任务。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    task = await _create_publish_task(status="running")
    try:
        async with AsyncSessionLocal() as db:
            saved = await db.scalar(
                select(PublishTask).where(PublishTask.id == task.id)
            )
            saved.execution_token = "current-delivery"
            await db.commit()

        await writeback_publish_result(
            str(task.id),
            {
                "success": True,
                "status": "published",
                "external_post_id": "stale-result",
                "_execution_token": "old-delivery",
            },
        )

        saved = await _get_publish_task(task.id)
        assert saved is not None
        assert saved.status == "running"
        assert saved.external_post_id is None
    finally:
        await _cleanup_publish_task(task.id)


# ============================================================
# 测试：批次统计
# ============================================================


@_skip_no_db
@pytest.mark.asyncio
async def test_batch_stats_all_success_completed():
    """批次全部成功 → completed。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    batch = await _create_batch(total=2)
    t1 = await _create_publish_task(status="queued", batch_id=batch.id)
    t2 = await _create_publish_task(status="queued", batch_id=batch.id)
    try:
        await writeback_publish_result(
            str(t1.id), {"success": True, "status": "published"}
        )
        await writeback_publish_result(
            str(t2.id), {"success": True, "status": "published"}
        )

        b = await _get_publish_batch(batch.id)
        assert b.success_count == 2
        assert b.failed_count == 0
        assert b.status == "completed"
    finally:
        await _cleanup_publish_task(t1.id)
        await _cleanup_publish_task(t2.id)
        await _cleanup_batch(batch.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_batch_stats_partial_failed():
    """批次部分失败 → partial_failed。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    batch = await _create_batch(total=2)
    t1 = await _create_publish_task(status="queued", batch_id=batch.id)
    t2 = await _create_publish_task(status="queued", batch_id=batch.id)
    try:
        await writeback_publish_result(
            str(t1.id), {"success": True, "status": "published"}
        )
        await writeback_publish_result(
            str(t2.id), {"success": False, "status": "publish_error", "error": "失败"}
        )

        b = await _get_publish_batch(batch.id)
        assert b.success_count == 1
        assert b.failed_count == 1
        assert b.status == "partial_failed"
    finally:
        await _cleanup_publish_task(t1.id)
        await _cleanup_publish_task(t2.id)
        await _cleanup_batch(batch.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_batch_stats_all_failed():
    """批次全部失败 → failed。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    batch = await _create_batch(total=2)
    t1 = await _create_publish_task(status="queued", batch_id=batch.id)
    t2 = await _create_publish_task(status="queued", batch_id=batch.id)
    try:
        await writeback_publish_result(
            str(t1.id), {"success": False, "status": "publish_error", "error": "x"}
        )
        await writeback_publish_result(
            str(t2.id), {"success": False, "status": "publish_error", "error": "y"}
        )

        b = await _get_publish_batch(batch.id)
        assert b.success_count == 0
        assert b.failed_count == 2
        assert b.status == "failed"
    finally:
        await _cleanup_publish_task(t1.id)
        await _cleanup_publish_task(t2.id)
        await _cleanup_batch(batch.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_batch_stats_retry_replaces_previous_result():
    """同一任务失败后重试成功，批次只能保留最终成功状态。"""
    from app.integrations.synapse_engine.workers.writeback import (
        writeback_publish_result,
    )

    batch = await _create_batch(total=1)
    task = await _create_publish_task(status="queued", batch_id=batch.id)
    try:
        await writeback_publish_result(
            str(task.id),
            {"success": False, "status": "publish_error", "error": "首次失败"},
        )
        await writeback_publish_result(
            str(task.id), {"success": True, "status": "published"}
        )

        saved = await _get_publish_batch(batch.id)
        assert saved.success_count == 1
        assert saved.failed_count == 0
        assert saved.status == "completed"
    finally:
        await _cleanup_publish_task(task.id)
        await _cleanup_batch(batch.id)


# ============================================================
# 测试：采集任务写回
# ============================================================


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_crawl_success():
    """采集成功写回：queued → succeeded，记录 items_count。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        writeback_crawl_result,
    )

    job = await _create_crawler_job(status="queued")
    try:
        result = {
            "success": True,
            "platform": "xhs",
            "items_count": 5,
            "output_files": [],  # 不带文件，避免触发 parse_data_file
        }
        await writeback_crawl_result(str(job.id), result)

        saved = await _get_crawler_job(job.id)
        assert saved is not None
        assert saved.status == "succeeded"
        assert saved.items_count == 5
        assert saved.finished_at is not None
    finally:
        await _cleanup_crawler_job(job.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_crawl_failed():
    """采集失败写回：queued → failed，记录 error_message。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        writeback_crawl_result,
    )

    job = await _create_crawler_job(status="queued")
    try:
        result = {
            "success": False,
            "error": "浏览器启动失败",
            "platform": "xhs",
            "items_count": 0,
            "output_files": [],
        }
        await writeback_crawl_result(str(job.id), result)

        saved = await _get_crawler_job(job.id)
        assert saved is not None
        assert saved.status == "failed"
        assert "浏览器启动失败" in (saved.error_message or "")
    finally:
        await _cleanup_crawler_job(job.id)


@pytest.mark.asyncio
async def test_writeback_crawl_invalid_id_skipped():
    """非 UUID 的 job_id 应静默跳过。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        writeback_crawl_result,
    )

    await writeback_crawl_result("not-a-uuid", {"success": True, "items_count": 1})
    await writeback_crawl_result("mc_xyz", {"success": False, "error": "test"})


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_crawl_cancelled_not_overwritten():
    """已取消的采集任务不应被写回覆盖。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        writeback_crawl_result,
    )

    job = await _create_crawler_job(status="cancelled")
    try:
        await writeback_crawl_result(
            str(job.id),
            {
                "success": True,
                "items_count": 100,
                "platform": "xhs",
                "output_files": [],
            },
        )

        saved = await _get_crawler_job(job.id)
        assert saved is not None
        assert saved.status == "cancelled"  # 未被覆盖
        assert saved.items_count == 0  # 未被写入
    finally:
        await _cleanup_crawler_job(job.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_crawl_job_claim_is_atomic():
    """重复采集消息只能有一个 worker 获得执行权。"""
    from app.integrations.mediacrawler_engine.workers.tasks import (
        _claim_crawl_job,
    )

    job = await _create_crawler_job(status="queued")
    try:
        assert await _claim_crawl_job(str(job.id), "crawl-first") is True
        assert await _claim_crawl_job(str(job.id), "crawl-second") is False

        saved = await _get_crawler_job(job.id)
        assert saved is not None
        assert saved.status == "running"
        assert saved.execution_token == "crawl-first"
        assert saved.started_at is not None
    finally:
        await _cleanup_crawler_job(job.id)


@_skip_no_db
@pytest.mark.asyncio
async def test_writeback_stale_crawl_result_is_ignored():
    """新 worker 接管采集任务后，旧 worker 结果不能覆盖新状态。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        writeback_crawl_result,
    )

    job = await _create_crawler_job(status="running")
    try:
        async with AsyncSessionLocal() as db:
            saved = await db.scalar(
                select(CrawlerJob).where(CrawlerJob.id == job.id)
            )
            saved.execution_token = "current-crawl"
            await db.commit()

        await writeback_crawl_result(
            str(job.id),
            {
                "success": True,
                "items_count": 9,
                "output_files": [],
                "_execution_token": "old-crawl",
            },
        )

        saved = await _get_crawler_job(job.id)
        assert saved is not None
        assert saved.status == "running"
        assert saved.items_count == 0
    finally:
        await _cleanup_crawler_job(job.id)


# ============================================================
# 测试：外部源码路径不存在时降级（不依赖 DB）
# ============================================================


def test_synapse_loader_without_external_source():
    """SYNAPSE_SRC_DIR 为空时仍能获取内置适配器。"""
    from app.integrations.synapse_engine.platforms import get_platform_adapter

    adapter = get_platform_adapter("xiaohongshu", {"headless": True})
    assert adapter is not None
    # 内置适配器应实现 publish_content / get_qrcode 方法
    assert hasattr(adapter, "publish_content")
    assert hasattr(adapter, "get_qrcode")


def test_synapse_adapter_supports_all_platforms():
    """内置适配器应支持所有平台。"""
    from app.integrations.synapse_engine.platforms import get_platform_adapter

    expected_classes = {
        "xiaohongshu": "XiaohongshuAdapter",
        "channels": "ChannelsAdapter",
        "douyin": "DouyinAdapter",
        "kuaishou": "KuaishouAdapter",
        "bilibili": "BilibiliAdapter",
    }
    for platform, class_name in expected_classes.items():
        adapter = get_platform_adapter(platform, {"headless": True})
        assert adapter is not None, f"平台 {platform} 没有适配器"
        assert adapter.__class__.__name__ == class_name


@pytest.mark.asyncio
async def test_xiaohongshu_published_query_wins_over_false_verification(monkeypatch):
    """小红书回到 published=true 上传页时应直接判成功，不再误弹 noVNC。"""
    from app.integrations.synapse_engine.platforms import get_platform_adapter

    adapter = get_platform_adapter("xiaohongshu", {"headless": True})
    detector_calls = 0

    async def false_positive_verification(_page):
        nonlocal detector_calls
        detector_calls += 1
        return ("human",)

    monkeypatch.setattr(adapter, "_detect_verification", false_positive_verification)

    class PublishedPage:
        url = (
            "https://creator.xiaohongshu.com/publish/publish"
            "?source=&published=true"
        )

    result = await adapter._wait_for_publish_success(PublishedPage(), timeout=1)

    assert result is True
    assert detector_calls == 0


def test_mediacrawler_loader_without_external_source():
    """MEDIACRAWLER_SRC_DIR 为空时仍能加载内嵌工厂。"""
    from app.integrations.mediacrawler_engine.loader import (
        ensure_loaded,
        get_crawler_factory,
    )

    # ensure_loaded 始终返回 True（内嵌源码随项目分发）
    assert ensure_loaded() is True

    factory_cls = get_crawler_factory()
    assert factory_cls is not None

    factory = factory_cls()
    platforms = factory.list_supported_platforms()
    # 返回 dict 列表，检查 xhs 在其中
    platform_codes = [p["platform"] for p in platforms]
    assert "xhs" in platform_codes
    # xhs 应标记为可用
    xhs = next(p for p in platforms if p["platform"] == "xhs")
    assert xhs["crawler_available"] is True


def test_config_deprecated_src_dirs_default_empty():
    """SYNAPSE_SRC_DIR / MEDIACRAWLER_SRC_DIR 默认值应为空字符串。"""
    from app.core.config import Settings

    # 临时清空环境变量，确保读到默认值
    old_synapse = os.environ.pop("SYNAPSE_SRC_DIR", None)
    old_media = os.environ.pop("MEDIACRAWLER_SRC_DIR", None)
    try:
        settings = Settings(_env_file=None)
        assert settings.SYNAPSE_SRC_DIR == ""
        assert settings.MEDIACRAWLER_SRC_DIR == ""
    finally:
        if old_synapse is not None:
            os.environ["SYNAPSE_SRC_DIR"] = old_synapse
        if old_media is not None:
            os.environ["MEDIACRAWLER_SRC_DIR"] = old_media


def test_synapse_no_sys_path_mutation():
    """验证加载 synapse_engine 不会向 sys.path 注入外部路径。"""
    import sys

    # 记录加载前的 sys.path
    path_before = list(sys.path)
    # 重新导入 platforms 模块
    import importlib

    from app.integrations.synapse_engine import platforms as platforms_mod

    importlib.reload(platforms_mod)
    # sys.path 不应被修改
    assert sys.path == path_before, "synapse_engine 加载修改了 sys.path"
    # 不应有 D:\social-auto-stack 在 sys.path 中
    assert not any("social-auto-stack" in p for p in sys.path)


def test_mediacrawler_no_sys_path_mutation():
    """验证加载 mediacrawler_engine 不会向 sys.path 注入外部路径。"""
    import sys

    path_before = list(sys.path)
    import importlib

    from app.integrations.mediacrawler_engine import loader as loader_mod

    importlib.reload(loader_mod)
    assert sys.path == path_before, "mediacrawler_engine 加载修改了 sys.path"
    assert not any("social-auto-stack" in p for p in sys.path)
