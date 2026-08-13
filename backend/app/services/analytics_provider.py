"""Mock analytics provider for content performance data backflow.

Simulates views, likes, comments, favorites, shares, leads, conversion_rate.
"""

import hashlib
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MockAnalyticsProvider:
    """Mock analytics data backflow provider."""

    # Stable seed-based random for predictable results
    def _stable_random(self, seed_str: str, min_val: float, max_val: float) -> float:
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return rng.uniform(min_val, max_val)

    def _stable_int(self, seed_str: str, min_val: int, max_val: int) -> int:
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return rng.randint(min_val, max_val)

    async def get_content_stats(
        self,
        content_id: str,
        platform: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get mock stats for a single content item."""
        if settings.MOCK_SCENARIO == "empty":
            return {
                "content_id": content_id,
                "platform": platform,
                "stats": {},
                "daily": [],
            }

        now = datetime.now(timezone.utc)
        daily = []
        total_views = 0
        total_likes = 0
        total_comments = 0
        total_favorites = 0
        total_shares = 0
        total_leads = 0

        for i in range(days):
            day = now - timedelta(days=days - 1 - i)
            day_str = day.strftime("%Y-%m-%d")
            seed_base = f"{content_id}_{platform}_{day_str}"

            views = self._stable_int(seed_base + "_views", 100, 5000)
            likes = self._stable_int(
                seed_base + "_likes", int(views * 0.03), int(views * 0.15)
            )
            comments = self._stable_int(
                seed_base + "_comments", int(likes * 0.05), int(likes * 0.3)
            )
            favorites = self._stable_int(
                seed_base + "_favorites", int(likes * 0.1), int(likes * 0.4)
            )
            shares = self._stable_int(
                seed_base + "_shares", int(likes * 0.02), int(likes * 0.15)
            )
            leads = self._stable_int(
                seed_base + "_leads", 0, max(1, int(views * 0.005))
            )

            daily.append(
                {
                    "date": day_str,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "favorites": favorites,
                    "shares": shares,
                    "leads": leads,
                }
            )
            total_views += views
            total_likes += likes
            total_comments += comments
            total_favorites += favorites
            total_shares += shares
            total_leads += leads

        conversion_rate = round(total_leads / max(total_views, 1) * 100, 2)

        logger.info(
            "AnalyticsProvider.get_content_stats content_id=%s platform=%s views=%d",
            content_id,
            platform,
            total_views,
        )

        return {
            "content_id": content_id,
            "platform": platform,
            "stats": {
                "views": total_views,
                "likes": total_likes,
                "comments": total_comments,
                "favorites": total_favorites,
                "shares": total_shares,
                "leads": total_leads,
                "conversion_rate": conversion_rate,
            },
            "daily": daily,
        }

    async def get_account_stats(
        self,
        account_id: str,
        platform: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get mock aggregated stats for an account."""
        if settings.MOCK_SCENARIO == "empty":
            return {
                "account_id": account_id,
                "platform": platform,
                "stats": {},
                "daily": [],
            }

        now = datetime.now(timezone.utc)
        daily = []
        for i in range(days):
            day = now - timedelta(days=days - 1 - i)
            day_str = day.strftime("%Y-%m-%d")
            seed_base = f"account_{account_id}_{platform}_{day_str}"

            daily.append(
                {
                    "date": day_str,
                    "views": self._stable_int(seed_base + "_views", 500, 20000),
                    "likes": self._stable_int(seed_base + "_likes", 50, 2000),
                    "comments": self._stable_int(seed_base + "_comments", 10, 500),
                    "favorites": self._stable_int(seed_base + "_favorites", 20, 800),
                    "shares": self._stable_int(seed_base + "_shares", 5, 300),
                    "leads": self._stable_int(seed_base + "_leads", 0, 20),
                }
            )

        totals = {
            k: sum(d.get(k, 0) for d in daily)
            for k in ["views", "likes", "comments", "favorites", "shares", "leads"]
        }
        totals["conversion_rate"] = round(
            totals["leads"] / max(totals["views"], 1) * 100, 2
        )

        return {
            "account_id": account_id,
            "platform": platform,
            "stats": totals,
            "daily": daily,
        }

    async def get_dashboard_stats(
        self,
        days: int = 7,
        platform: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Get mock dashboard-level stats."""
        if settings.MOCK_SCENARIO == "empty":
            return {"total_stats": {}, "platform_stats": [], "daily": []}

        platforms = (
            [platform]
            if platform
            else ["douyin", "xiaohongshu", "wechat_video", "wechat_mp"]
        )
        platform_stats = []
        total = {
            "views": 0,
            "likes": 0,
            "comments": 0,
            "favorites": 0,
            "shares": 0,
            "leads": 0,
        }

        for p in platforms:
            seed_base = f"dashboard_{p}_{days}"
            p_stats = {
                "platform": p,
                "views": self._stable_int(seed_base + "_views", 2000, 50000),
                "likes": self._stable_int(seed_base + "_likes", 200, 5000),
                "comments": self._stable_int(seed_base + "_comments", 50, 1000),
                "favorites": self._stable_int(seed_base + "_favorites", 100, 2000),
                "shares": self._stable_int(seed_base + "_shares", 30, 800),
                "leads": self._stable_int(seed_base + "_leads", 5, 100),
            }
            p_stats["conversion_rate"] = round(
                p_stats["leads"] / max(p_stats["views"], 1) * 100, 2
            )
            platform_stats.append(p_stats)
            for k in total:
                total[k] += p_stats.get(k, 0)

        total["conversion_rate"] = round(
            total["leads"] / max(total["views"], 1) * 100, 2
        )

        return {
            "total_stats": total,
            "platform_stats": platform_stats,
            "days": days,
        }


class RealAnalyticsProvider:
    """真实数据分析 Provider，聚合各社媒平台数据回流 API。

    各平台数据 API 需平台审核接入，当前为框架实现：
    - 抖音/小红书/视频号/公众号 数据回流端点用 TODO 标注
    - access_token 应从 DB Account 表读取（OAuth 授权后存入）
    - 未配置凭证时返回空 stats，与 MOCK_SCENARIO=empty 行为一致
    """

    # 平台 API base 映射
    PLATFORM_BASE_URL: dict[str, str] = {
        "douyin": settings.DOUYIN_OPEN_BASE_URL,
        "xiaohongshu": settings.XIAOHONGSHU_OPEN_BASE_URL,
        "wechat_video": settings.WECHAT_VIDEO_BASE_URL,
        "wechat_mp": settings.WECHAT_MP_BASE_URL,
    }

    def _get_access_token(self, platform: str) -> str | None:
        """获取平台 access_token。

        TODO: 从 DB Account 表读取 OAuth 授权后存入的 access_token。
        当前未接入 DB，返回 None，调用方据此降级返回空 stats。
        """
        # 框架占位：实际应查询 Account 表 platform + status=active 的 access_token
        return None

    async def _fetch_platform_stats(
        self,
        platform: str,
        path: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """统一调用平台数据回流 API 并解析为标准 stats 格式。

        Returns:
            含 views/likes/comments/favorites/shares/leads 的 dict；失败返回空 dict。
        """
        token = self._get_access_token(platform)
        if not token:
            logger.warning(
                "RealAnalyticsProvider 未获取到 %s 的 access_token，跳过数据回流",
                platform,
            )
            return {}

        base_url = self.PLATFORM_BASE_URL.get(platform)
        if not base_url:
            logger.warning("RealAnalyticsProvider 未配置 %s 的 base_url", platform)
            return {}

        url = f"{base_url}{path}"
        request_params = {**params, "access_token": token}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # TODO: 抖音 open.douyin.com 数据回流 API 需平台审核
                # TODO: 小红书 edith.xiaohongshu.com 数据回流 API 需平台审核
                # TODO: 视频号/公众号 api.weixin.qq.com 数据分析 API
                resp = await client.get(url, params=request_params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.error(
                "RealAnalyticsProvider 调用 %s 数据 API 失败: %s", platform, exc
            )
            return {}
        except Exception as exc:
            logger.error("RealAnalyticsProvider 解析 %s 数据失败: %s", platform, exc)
            return {}

        # 各平台返回结构不同，此处做统一格式转换
        # TODO: 按平台实际返回字段映射
        try:
            raw = data.get("data", {})
            stats = {
                "views": int(raw.get("views", 0)),
                "likes": int(raw.get("likes", 0)),
                "comments": int(raw.get("comments", 0)),
                "favorites": int(raw.get("favorites", 0)),
                "shares": int(raw.get("shares", 0)),
                "leads": int(raw.get("leads", 0)),
            }
            stats["conversion_rate"] = round(
                stats["leads"] / max(stats["views"], 1) * 100, 2
            )
            return stats
        except Exception as exc:
            logger.error("RealAnalyticsProvider %s 字段映射失败: %s", platform, exc)
            return {}

    async def get_content_stats(
        self,
        content_id: str,
        platform: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """获取单条内容在指定平台的真实统计数据。"""
        # TODO: 各平台单内容数据端点
        #   抖音: /data/external/item_data?item_id={content_id}
        #   小红书: /api/note/stats?note_id={content_id}
        stats = await self._fetch_platform_stats(
            platform,
            path="/data/external/item_data",  # TODO: 按平台实际端点
            params={"content_id": content_id, "days": days},
        )
        if not stats:
            return {
                "content_id": content_id,
                "platform": platform,
                "stats": {},
                "daily": [],
            }

        logger.info(
            "RealAnalyticsProvider.get_content_stats content_id=%s platform=%s views=%d",
            content_id,
            platform,
            stats.get("views", 0),
        )
        return {
            "content_id": content_id,
            "platform": platform,
            "stats": stats,
            "daily": [],  # TODO: 各平台按日数据需额外端点
        }

    async def get_account_stats(
        self,
        account_id: str,
        platform: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """获取账号在指定平台的真实聚合统计数据。"""
        # TODO: 各平台账号级数据端点
        #   抖音: /data/external/account_data?account_id={account_id}
        stats = await self._fetch_platform_stats(
            platform,
            path="/data/external/account_data",  # TODO: 按平台实际端点
            params={"account_id": account_id, "days": days},
        )
        if not stats:
            return {
                "account_id": account_id,
                "platform": platform,
                "stats": {},
                "daily": [],
            }

        return {
            "account_id": account_id,
            "platform": platform,
            "stats": stats,
            "daily": [],  # TODO: 各平台按日数据需额外端点
        }

    async def get_dashboard_stats(
        self,
        days: int = 7,
        platform: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """获取看板级统计：遍历平台列表聚合各平台真实数据。"""
        platforms = [platform] if platform else list(self.PLATFORM_BASE_URL.keys())
        platform_stats = []
        total = {
            "views": 0,
            "likes": 0,
            "comments": 0,
            "favorites": 0,
            "shares": 0,
            "leads": 0,
        }

        for p in platforms:
            # TODO: 各平台看板聚合数据端点
            p_stats = await self._fetch_platform_stats(
                p,
                path="/data/external/dashboard",  # TODO: 按平台实际端点
                params={"days": days, "account_id": account_id or ""},
            )
            if not p_stats:
                continue
            p_stats["platform"] = p
            platform_stats.append(p_stats)
            for k in total:
                total[k] += p_stats.get(k, 0)

        if not platform_stats:
            return {"total_stats": {}, "platform_stats": [], "daily": []}

        total["conversion_rate"] = round(
            total["leads"] / max(total["views"], 1) * 100, 2
        )
        return {
            "total_stats": total,
            "platform_stats": platform_stats,
            "days": days,
        }


def get_analytics_provider() -> MockAnalyticsProvider | RealAnalyticsProvider:
    if settings.ANALYTICS_PROVIDER == "mock":
        return MockAnalyticsProvider()
    if settings.ANALYTICS_PROVIDER == "real":
        return RealAnalyticsProvider()
    raise NotImplementedError(
        f"Analytics provider '{settings.ANALYTICS_PROVIDER}' not implemented."
    )
