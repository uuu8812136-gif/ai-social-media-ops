"""社媒发布内容指标采集器。

设计原则：
1. 优先用账号 Cookie + Playwright 打开发布链接/创作者后台读取数据
2. 平台网页不暴露数据时返回 sync_status=unavailable，不造假
3. 没有 publish_url 或 external_post_id 时明确返回不可同步原因
4. 指标字段统一：views/likes/comments/favorites/shares
5. 保留 raw_data 方便后续接 MediaCrawler
6. 中文单位解析：万、亿

模块独立，不与项目业务模型强绑定，可复制到其他项目复用。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ===== 中文数字解析 =====

_WAN = 10000
_YI = 100_000_000

_CN_NUM_MAP = {
    "万": _WAN,
    "亿": _YI,
    "w": _WAN,
    "W": _WAN,
    "k": 1000,
    "K": 1000,
    "M": 1_000_000,
    "m": 1_000_000,
}


def parse_cn_count(text: str | None) -> int | None:
    """解析中文/英文缩写数字，如 '1.2万' -> 12000, '3.5亿' -> 350000000。

    无法解析时返回 None。
    """
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    # 纯数字
    try:
        return int(s)
    except ValueError:
        pass
    # 带小数+单位
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*([万亿wkKMm]?)$", s)
    if m:
        base = float(m.group(1))
        unit = m.group(2)
        multiplier = _CN_NUM_MAP.get(unit, 1)
        return int(base * multiplier)
    # 去掉逗号再试
    s_clean = s.replace(",", "")
    try:
        return int(s_clean)
    except ValueError:
        pass
    m2 = re.match(r"^(-?\d+(?:\.\d+)?)\s*([万亿wkKMm]?)$", s_clean)
    if m2:
        base = float(m2.group(1))
        unit = m2.group(2)
        multiplier = _CN_NUM_MAP.get(unit, 1)
        return int(base * multiplier)
    return None


# ===== 采集结果 =====


class MetricResult:
    """指标采集结果。"""

    def __init__(
        self,
        sync_status: str = "pending",
        metrics: dict[str, Any] | None = None,
        raw_data: dict[str, Any] | None = None,
        error_message: str | None = None,
    ):
        self.sync_status = sync_status  # pending|synced|unavailable|failed
        self.metrics = metrics
        self.raw_data = raw_data
        self.error_message = error_message

    def to_dict(self) -> dict:
        return {
            "sync_status": self.sync_status,
            "metrics": self.metrics,
            "raw_data": self.raw_data,
            "error_message": self.error_message,
        }


# ===== 平台采集器 =====


async def _collect_xiaohongshu(
    publish_url: str, external_post_id: str | None, cookie_storage_state: dict | None
) -> MetricResult:
    """小红书指标采集：用 Cookie 打开笔记页面读取互动数据。"""
    from app.integrations.synapse_engine.utils.playwright_provider import (
        async_playwright,
    )

    if not publish_url and not external_post_id:
        return MetricResult(
            sync_status="unavailable",
            error_message="缺少 publish_url 和 external_post_id，无法采集小红书指标",
        )

    url = publish_url or f"https://www.xiaohongshu.com/explore/{external_post_id}"

    browser = None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = (
                await browser.new_context(storage_state=cookie_storage_state)
                if cookie_storage_state
                else await browser.new_context()
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # 尝试读取互动数据
            raw: dict[str, Any] = {}
            metrics: dict[str, Any] = {}

            # 点赞数
            like_text = await _try_text(
                page, ".like-wrapper .count, .like-text, [class*='like'] .count"
            )
            if like_text:
                raw["like_text"] = like_text
                v = parse_cn_count(like_text)
                if v is not None:
                    metrics["likes"] = v

            # 收藏数
            collect_text = await _try_text(
                page,
                ".collect-wrapper .count, .collect-text, [class*='collect'] .count",
            )
            if collect_text:
                raw["collect_text"] = collect_text
                v = parse_cn_count(collect_text)
                if v is not None:
                    metrics["favorites"] = v

            # 评论数
            comment_text = await _try_text(
                page, ".chat-wrapper .count, .comment-text, [class*='comment'] .count"
            )
            if comment_text:
                raw["comment_text"] = comment_text
                v = parse_cn_count(comment_text)
                if v is not None:
                    metrics["comments"] = v

            # 阅读量（小红书部分笔记展示）
            view_text = await _try_text(
                page, ".views-count, [class*='view'] .count, .read-count"
            )
            if view_text:
                raw["view_text"] = view_text
                v = parse_cn_count(view_text)
                if v is not None:
                    metrics["views"] = v

            if not metrics:
                return MetricResult(
                    sync_status="unavailable",
                    raw_data=raw,
                    error_message="小红书页面未暴露互动数据（可能需要登录或页面结构变更）",
                )

            return MetricResult(sync_status="synced", metrics=metrics, raw_data=raw)

    except Exception as e:
        logger.warning("小红书指标采集失败 url=%s: %s", url, e)
        return MetricResult(
            sync_status="failed", error_message=f"小红书指标采集失败：{e}"
        )
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


async def _collect_douyin(
    publish_url: str, external_post_id: str | None, cookie_storage_state: dict | None
) -> MetricResult:
    """抖音指标采集：用 Cookie 打开视频页面读取播放/点赞/评论。"""
    from app.integrations.synapse_engine.utils.playwright_provider import (
        async_playwright,
    )

    if not publish_url and not external_post_id:
        return MetricResult(
            sync_status="unavailable",
            error_message="缺少 publish_url 和 external_post_id，无法采集抖音指标",
        )

    url = publish_url or f"https://www.douyin.com/video/{external_post_id}"

    browser = None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = (
                await browser.new_context(storage_state=cookie_storage_state)
                if cookie_storage_state
                else await browser.new_context()
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            raw: dict[str, Any] = {}
            metrics: dict[str, Any] = {}

            # 播放量
            view_text = await _try_text(
                page, "[data-e2e='video-views'], .video-views, [class*='play'] .count"
            )
            if view_text:
                raw["view_text"] = view_text
                v = parse_cn_count(view_text)
                if v is not None:
                    metrics["views"] = v

            # 点赞数
            like_text = await _try_text(
                page,
                "[data-e2e='video-like-count'], .like-count, [class*='like'] .count",
            )
            if like_text:
                raw["like_text"] = like_text
                v = parse_cn_count(like_text)
                if v is not None:
                    metrics["likes"] = v

            # 评论数
            comment_text = await _try_text(
                page,
                "[data-e2e='video-comment-count'], .comment-count, [class*='comment'] .count",
            )
            if comment_text:
                raw["comment_text"] = comment_text
                v = parse_cn_count(comment_text)
                if v is not None:
                    metrics["comments"] = v

            # 收藏数
            collect_text = await _try_text(
                page,
                "[data-e2e='video-collect-count'], .collect-count, [class*='collect'] .count",
            )
            if collect_text:
                raw["collect_text"] = collect_text
                v = parse_cn_count(collect_text)
                if v is not None:
                    metrics["favorites"] = v

            # 分享数
            share_text = await _try_text(
                page,
                "[data-e2e='video-share-count'], .share-count, [class*='share'] .count",
            )
            if share_text:
                raw["share_text"] = share_text
                v = parse_cn_count(share_text)
                if v is not None:
                    metrics["shares"] = v

            if not metrics:
                return MetricResult(
                    sync_status="unavailable",
                    raw_data=raw,
                    error_message="抖音页面未暴露互动数据（可能需要登录或页面结构变更）",
                )

            return MetricResult(sync_status="synced", metrics=metrics, raw_data=raw)

    except Exception as e:
        logger.warning("抖音指标采集失败 url=%s: %s", url, e)
        return MetricResult(
            sync_status="failed", error_message=f"抖音指标采集失败：{e}"
        )
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


# 平台 -> 采集函数映射
_COLLECTORS = {
    "xiaohongshu": _collect_xiaohongshu,
    "douyin": _collect_douyin,
}


async def collect_metrics(
    platform: str,
    publish_url: str | None,
    external_post_id: str | None,
    cookie_storage_state: dict | None = None,
) -> MetricResult:
    """采集单条发布内容的指标数据。

    Args:
        platform: 平台代码
        publish_url: 发布链接
        external_post_id: 平台内容 ID
        cookie_storage_state: 账号 Cookie（storage_state 格式）

    Returns:
        MetricResult: 采集结果，sync_status 为 synced/unavailable/failed
    """
    if not publish_url and not external_post_id:
        return MetricResult(
            sync_status="unavailable",
            error_message="缺少 publish_url 和 external_post_id，无法采集指标",
        )

    collector = _COLLECTORS.get(platform)
    if collector is None:
        return MetricResult(
            sync_status="unavailable",
            error_message=f"平台 {platform} 暂不支持指标采集（未实现采集器）",
        )

    return await collector(publish_url or "", external_post_id, cookie_storage_state)


async def _try_text(page, selectors: str) -> str | None:
    """尝试多个选择器，返回第一个找到的文本内容。"""
    for sel in selectors.split(", "):
        sel = sel.strip()
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.text_content()
                if text and text.strip():
                    return text.strip()
        except Exception:
            continue
    return None


__all__ = ["collect_metrics", "parse_cn_count", "MetricResult"]
