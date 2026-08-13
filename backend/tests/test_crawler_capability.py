"""采集能力收口测试。

覆盖：
1. crawler_type 校验：xhs/dy 只允许 search，creator/detail/comment 返回 400
2. save_dir 不重复：_get_save_dir 不在 save_dir_var 已含 platform 时再追加 platform
3. media_urls 字符串转 list：_normalize_media_urls 辅助函数
"""

import json as _json
import socket as _socket
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.v1.crawler import (
    CreateCrawlerJobRequest,
    _PLATFORM_SUPPORTED_MODES,
    create_crawler_job,
)
from app.core.config import get_settings as _get_settings


# ============================================================
# 测试：crawler_type 校验
# ============================================================


def test_supported_modes_constant():
    """校验能力常量：xhs/dy 只支持 search。"""
    assert _PLATFORM_SUPPORTED_MODES["xhs"] == {"search"}
    assert _PLATFORM_SUPPORTED_MODES["dy"] == {"search"}
    assert "creator" not in _PLATFORM_SUPPORTED_MODES["xhs"]
    assert "detail" not in _PLATFORM_SUPPORTED_MODES["dy"]
    assert "comment" not in _PLATFORM_SUPPORTED_MODES["xhs"]


@pytest.mark.asyncio
async def test_crawler_type_creator_rejected_for_xhs():
    """xhs + creator 应在请求模型层返回 422，不能进 worker。"""
    with pytest.raises(ValidationError):
        CreateCrawlerJobRequest(platform="xhs", crawler_type="creator")


@pytest.mark.asyncio
async def test_crawler_type_detail_rejected_for_dy():
    """dy + detail 应在请求模型层返回 422。"""
    with pytest.raises(ValidationError):
        CreateCrawlerJobRequest(platform="dy", crawler_type="detail")


@pytest.mark.asyncio
async def test_crawler_type_comment_rejected_for_dy():
    """dy + comment 应在请求模型层返回 422。"""
    with pytest.raises(ValidationError):
        CreateCrawlerJobRequest(platform="dy", crawler_type="comment")


@pytest.mark.asyncio
async def test_unsupported_platform_rejected():
    """ks（快手）采集器未接入，应在请求模型层返回 422。"""
    with pytest.raises(ValidationError):
        CreateCrawlerJobRequest(platform="ks", crawler_type="search")


@pytest.mark.asyncio
async def test_bili_search_passes_validation():
    """bili（B站）search 已接入，不应被能力校验拒绝。"""
    body = CreateCrawlerJobRequest(
        platform="bili", crawler_type="search", params={"keywords": ["test"]}
    )
    try:
        await create_crawler_job(body, db=None, current_user=None)
    except HTTPException as e:
        assert e.status_code != 400, f"bili search 不应被校验拒绝: {e.detail}"
    except Exception:
        pass


@pytest.mark.asyncio
async def test_search_mode_passes_validation():
    """xhs + search 应通过校验（不抛 400；后续 DB 操作可能失败但不是校验错误）。"""
    body = CreateCrawlerJobRequest(
        platform="xhs", crawler_type="search", params={"keywords": ["test"]}
    )
    try:
        await create_crawler_job(body, db=None, current_user=None)
    except HTTPException as e:
        # search 不应触发 400 校验错误
        assert e.status_code != 400, f"search 模式不应被校验拒绝: {e.detail}"
    except Exception:
        # 其他异常（DB 不可用等）说明校验已通过
        pass


# ============================================================
# 测试：save_dir 不重复 platform
# ============================================================


def test_get_save_dir_no_duplicate_platform(tmp_path):
    """_get_save_dir 不应在 save_dir_var 已含 platform 时再追加 platform。

    场景：service 层设置 save_dir = data/mediacrawler/xhs（已含 platform），
    base._get_save_dir 应直接使用，不应变成 data/mediacrawler/xhs/xhs。
    """
    from app.integrations.mediacrawler_engine.embedded.crawlers.base import (
        BaseEmbeddedCrawler,
    )
    from app.integrations.mediacrawler_engine.embedded.var import save_dir_var

    # 模拟 service 层设置的 save_dir（已含 platform，是最终目录）
    save_dir = str(tmp_path / "data" / "mediacrawler" / "xhs")
    save_dir_var.set(save_dir)
    try:
        crawler = BaseEmbeddedCrawler(platform="xhs")
        result = crawler._get_save_dir()
        result_str = str(result).replace("\\", "/")
        # 不应出现 xhs/xhs 重复路径
        assert "xhs/xhs" not in result_str, f"save_dir 出现 platform 重复: {result_str}"
        # 应该就是 save_dir 本身
        assert result_str == save_dir.replace("\\", "/")
    finally:
        save_dir_var.set("")


def test_get_save_dir_fallback_appends_platform(tmp_path):
    """save_dir_var 未设置时回退到 SAVE_DATA_DIR/{platform}。"""
    from app.integrations.mediacrawler_engine.embedded.crawlers.base import (
        BaseEmbeddedCrawler,
    )
    from app.integrations.mediacrawler_engine.embedded.var import save_dir_var

    save_dir_var.set("")
    try:
        crawler = BaseEmbeddedCrawler(platform="dy")
        result = crawler._get_save_dir()
        result_str = str(result).replace("\\", "/")
        # 回退路径应以 /dy 结尾
        assert result_str.endswith("/dy"), f"回退路径应含 platform: {result_str}"
    finally:
        save_dir_var.set("")


# ============================================================
# 测试：media_urls 字符串转 list
# ============================================================


def test_normalize_media_urls_image_list():
    """image_list 是 list 时直接用。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _normalize_media_urls,
    )

    assert _normalize_media_urls(["a.jpg", "b.jpg"], None) == ["a.jpg", "b.jpg"]


def test_normalize_media_urls_video_url_string():
    """video_url 是字符串时转成 [video_url]。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _normalize_media_urls,
    )

    result = _normalize_media_urls(None, "https://example.com/video.mp4")
    assert result == ["https://example.com/video.mp4"]
    assert isinstance(result, list)


def test_normalize_media_urls_both_none():
    """都没有则 []。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _normalize_media_urls,
    )

    assert _normalize_media_urls(None, None) == []


def test_normalize_media_urls_image_list_takes_priority():
    """image_list 优先于 video_url。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _normalize_media_urls,
    )

    assert _normalize_media_urls(["a.jpg"], "v.mp4") == ["a.jpg"]


def test_normalize_media_urls_filters_empty_strings():
    """过滤掉空字符串和 None。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _normalize_media_urls,
    )

    assert _normalize_media_urls(["a.jpg", "", None], None) == ["a.jpg"]


def test_normalize_media_urls_video_url_list():
    """video_url 是 list 时也正确处理。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _normalize_media_urls,
    )

    assert _normalize_media_urls(None, ["v1.mp4", "v2.mp4"]) == ["v1.mp4", "v2.mp4"]


def test_build_crawler_item_media_urls_is_list_for_video():
    """_build_crawler_item 处理只有 video_url（字符串）时 media_urls 应为 list。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _build_crawler_item,
    )

    class FakeJob:
        id = uuid.uuid4()
        platform = "dy"

    item = {
        "video_id": "123",
        "title": "测试视频",
        "video_url": "https://example.com/v.mp4",
    }
    ci = _build_crawler_item(FakeJob(), item)
    assert ci is not None
    assert isinstance(ci.media_urls, list)
    assert ci.media_urls == ["https://example.com/v.mp4"]


def test_build_crawler_item_media_urls_is_list_for_image_list():
    """_build_crawler_item 处理 image_list 时 media_urls 应为 list。"""
    from app.integrations.mediacrawler_engine.workers.writeback import (
        _build_crawler_item,
    )

    class FakeJob:
        id = uuid.uuid4()
        platform = "xhs"

    item = {
        "note_id": "abc",
        "title": "测试笔记",
        "image_list": ["1.jpg", "2.jpg"],
    }
    ci = _build_crawler_item(FakeJob(), item)
    assert ci is not None
    assert isinstance(ci.media_urls, list)
    assert ci.media_urls == ["1.jpg", "2.jpg"]


# ============================================================
# 测试：手动回写路由 /jobs/{job_id}/result 路径 media_urls 一致性
# 验证 crawler.py 的 writeback_crawler_result 复用 _normalize_media_urls，
# 与 worker 直写 DB 路径行为一致，video_url 字符串转 list。
# ============================================================

_settings_crawler = _get_settings()
_db_url_crawler = _settings_crawler.DATABASE_URL
try:
    _db_host_crawler = _db_url_crawler.split("@")[-1].split(":")[0].split("/")[0]
    _db_port_crawler = int(_db_url_crawler.split("@")[-1].split(":")[1].split("/")[0])
except Exception:
    _db_host_crawler, _db_port_crawler = "postgres", 5432


def _db_reachable_crawler() -> bool:
    try:
        with _socket.create_connection((_db_host_crawler, _db_port_crawler), timeout=1):
            return True
    except OSError:
        return False


_skip_no_db_crawler = pytest.mark.skipif(
    not _db_reachable_crawler(),
    reason=f"DB {_db_host_crawler}:{_db_port_crawler} 不可达",
)


@_skip_no_db_crawler
@pytest.mark.asyncio
async def test_writeback_result_route_normalizes_video_url_to_list(tmp_path):
    """通过 /jobs/{job_id}/result 路由手动回写时，video_url 字符串应转为 list。

    场景：采集文件里 item 只有 video_url（字符串），没有 image_list。
    手动回写路由应复用 _normalize_media_urls，保证 media_urls 写入 DB 为 list，
    与 worker 直写 DB 路径行为一致。
    """
    from sqlalchemy import delete

    from app.api.v1.crawler import CrawlerResultRequest, writeback_crawler_result
    from app.core.database import AsyncSessionLocal
    from app.models.crawler import CrawlerItem, CrawlerJob

    # 1. 创建临时 JSONL 文件，包含只有 video_url（字符串）的 item
    data_dir = Path(_settings_crawler.MEDIACRAWLER_DATA_DIR).resolve() / "test_runs"
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = data_dir / f"test_dy_{uuid.uuid4().hex}.jsonl"
    item = {
        "video_id": "v123",
        "title": "测试视频",
        "video_url": "https://example.com/v.mp4",
        "type": "video",
        "nickname": "测试作者",
    }
    tmp_file.write_text(_json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2. 创建 CrawlerJob
    job = CrawlerJob(
        platform="dy",
        crawler_type="search",
        status="queued",
        params={"keywords": ["test"]},
    )
    async with AsyncSessionLocal() as db:
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    try:
        # 3. 调用 writeback_crawler_result 路由（手动回写路径）
        body = CrawlerResultRequest(
            **{
                "success": True,
                "items_count": 1,
                "output_files": [{"path": str(tmp_file), "name": "test_dy.jsonl"}],
            }
        )
        async with AsyncSessionLocal() as db:
            await writeback_crawler_result(job_id, body, db=db, _=None)

        # 4. 验证 CrawlerItem.media_urls 是 list
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(CrawlerItem).where(CrawlerItem.job_id == job_id)
            )
            items = res.scalars().all()
            assert len(items) == 1, "应写入 1 条 CrawlerItem"
            assert isinstance(items[0].media_urls, list), (
                f"media_urls 应为 list，实际是 {type(items[0].media_urls)}: {items[0].media_urls}"
            )
            assert items[0].media_urls == ["https://example.com/v.mp4"]
    finally:
        tmp_file.unlink(missing_ok=True)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CrawlerItem).where(CrawlerItem.job_id == job_id))
            await db.execute(delete(CrawlerJob).where(CrawlerJob.id == job_id))
            await db.commit()


@_skip_no_db_crawler
@pytest.mark.asyncio
async def test_writeback_result_route_normalizes_image_list(tmp_path):
    """通过 /jobs/{job_id}/result 路由回写时，image_list 正确转为 list。"""
    from sqlalchemy import delete

    from app.api.v1.crawler import CrawlerResultRequest, writeback_crawler_result
    from app.core.database import AsyncSessionLocal
    from app.models.crawler import CrawlerItem, CrawlerJob

    data_dir = Path(_settings_crawler.MEDIACRAWLER_DATA_DIR).resolve() / "test_runs"
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = data_dir / f"test_xhs_{uuid.uuid4().hex}.jsonl"
    item = {
        "note_id": "nabc",
        "title": "测试笔记",
        "image_list": ["1.jpg", "2.jpg"],
        "type": "note",
    }
    tmp_file.write_text(_json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")

    job = CrawlerJob(
        platform="xhs",
        crawler_type="search",
        status="queued",
        params={"keywords": ["test"]},
    )
    async with AsyncSessionLocal() as db:
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    try:
        body = CrawlerResultRequest(
            **{
                "success": True,
                "items_count": 1,
                "output_files": [{"path": str(tmp_file), "name": "test_xhs.jsonl"}],
            }
        )
        async with AsyncSessionLocal() as db:
            await writeback_crawler_result(job_id, body, db=db, _=None)

        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(CrawlerItem).where(CrawlerItem.job_id == job_id)
            )
            items = res.scalars().all()
            assert len(items) == 1
            assert isinstance(items[0].media_urls, list)
            assert items[0].media_urls == ["1.jpg", "2.jpg"]
    finally:
        tmp_file.unlink(missing_ok=True)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CrawlerItem).where(CrawlerItem.job_id == job_id))
            await db.execute(delete(CrawlerJob).where(CrawlerJob.id == job_id))
            await db.commit()


def test_writeback_result_route_reuses_item_builder():
    """验证手动回写与 worker 复用同一个条目构建器。

    不依赖 DB，纯静态检查，确保两条路径（worker 直写 / 手动 HTTP 回写）
    使用同一个规范化函数，不会出现一个修了一个没修。
    """
    import inspect

    from app.api.v1 import crawler as crawler_mod

    source = inspect.getsource(crawler_mod.writeback_crawler_result)
    assert "_build_crawler_item" in source, (
        "writeback_crawler_result 应复用 _build_crawler_item 统一规范化条目"
    )
    assert 'item.get("image_list") or item.get("video_url")' not in source, (
        "writeback_crawler_result 不应再使用旧的 or 链式表达式"
    )
