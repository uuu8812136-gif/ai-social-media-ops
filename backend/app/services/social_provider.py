"""Mock social media publishing provider.

Simulates publishing to Douyin, Xiaohongshu, WeChat Video, WeChat Official Account.
Supports scenarios: success, reviewing, publish_fail, token_expired, content_violation.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SocialPublishResult:
    def __init__(
        self,
        platform: str,
        external_post_id: str,
        status: str,
        publish_url: str | None = None,
        scheduled_at: str | None = None,
        error_message: str | None = None,
    ):
        self.platform = platform
        self.external_post_id = external_post_id
        self.status = status
        self.publish_url = publish_url
        self.scheduled_at = scheduled_at
        self.error_message = error_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "external_post_id": self.external_post_id,
            "status": self.status,
            "publish_url": self.publish_url,
            "scheduled_at": self.scheduled_at,
            "error_message": self.error_message,
        }


class MockSocialProvider:
    """Mock social media publishing provider."""

    PLATFORMS = {
        "douyin": {"name": "抖音", "url_prefix": "https://www.douyin.com/video/"},
        "xiaohongshu": {
            "name": "小红书",
            "url_prefix": "https://www.xiaohongshu.com/explore/",
        },
        "wechat_video": {
            "name": "视频号",
            "url_prefix": "https://channels.weixin.qq.com/",
        },
        "wechat_mp": {"name": "公众号", "url_prefix": "https://mp.weixin.qq.com/s/"},
    }

    async def publish(
        self,
        platform: str,
        content_id: str,
        title: str,
        body_text: str,
        media_urls: list[str] | None = None,
        scheduled_at: str | None = None,
        account_id: str | None = None,
    ) -> SocialPublishResult:
        scenario = settings.MOCK_SCENARIO
        external_id = f"{platform}_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info(
            "SocialProvider.publish platform=%s content_id=%s scenario=%s",
            platform,
            content_id,
            scenario,
        )

        if scenario == "publish_fail":
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_failed",
                error_message="模拟发布失败：平台接口返回错误",
            )
        if scenario == "token_expired":
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="token_expired",
                error_message="模拟Token失效：需要重新授权",
            )
        if scenario == "content_violation":
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="content_violation",
                error_message="模拟内容违规：包含敏感信息，已被平台拦截",
            )
        if scenario == "timeout":
            import asyncio

            await asyncio.sleep(0.1)
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_timeout",
                error_message="模拟发布超时",
            )

        # Normal success
        platform_info = self.PLATFORMS.get(
            platform, {"name": platform, "url_prefix": "https://example.com/"}
        )
        publish_url = f"{platform_info['url_prefix']}{external_id}"

        if platform == "xiaohongshu":
            # 小红书官方开放平台已暂停接入，采用「AI 助手浏览器自动化」模式：
            # 后端返回 pending_agent + 待发布内容包，AI 助手用 browser-use skill 发布后回填 note_id
            result = SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="pending_agent",
                publish_url="",
                scheduled_at=scheduled_at or now,
            )
        else:
            status = "reviewing" if platform == "wechat_mp" else "published"
            result = SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status=status,
                publish_url=publish_url,
                scheduled_at=scheduled_at or now,
            )

        logger.info(
            "SocialProvider.publish result platform=%s status=%s external_id=%s",
            platform,
            result.status,
            external_id,
        )
        return result


class RealSocialProvider:
    """真实社媒平台发布 Provider。

    支持 douyin / xiaohongshu / wechat_video / wechat_mp 四个平台。
    通过 httpx.AsyncClient 调用各平台开放 API。

    access_token 说明：
        实际生产应通过 publish() 的 account_id 参数从 DB Account 表的
        access_token 字段查询（OAuth 授权后落库）。Provider 层不直接访问 DB
        以避免与 repository/service 层循环依赖，因此 token 应由上层 service
        在创建 Provider 后通过实例属性 access_token 注入，或由调用方在构造时传入。
    """

    PLATFORMS = MockSocialProvider.PLATFORMS

    # 各平台发布接口的 path（相对 base_url）
    _ENDPOINTS = {
        "douyin": "/api/douyin/v1/video/create_video/",
        "xiaohongshu": "/api/sns/web/v1/note",
        "wechat_video": "/cgi-bin/videos/post",
        "wechat_mp_draft": "/cgi-bin/draft/add",
        "wechat_mp_publish": "/cgi-bin/freepublish/submit",
    }

    def __init__(self, platform: str, access_token: str | None = None):
        self.platform = platform
        # TODO: 实际生产应通过 account_id 从 DB Account 表的 access_token 字段读取。
        # 此处允许调用方在实例化时或之后通过 self.access_token 注入 token。
        self.access_token = access_token

    def _get_base_url(self, platform: str) -> str:
        if platform == "douyin":
            return settings.DOUYIN_OPEN_BASE_URL
        if platform == "xiaohongshu":
            return settings.XIAOHONGSHU_OPEN_BASE_URL
        if platform == "wechat_video":
            return settings.WECHAT_VIDEO_BASE_URL
        if platform == "wechat_mp":
            return settings.WECHAT_MP_BASE_URL
        return ""

    async def publish(
        self,
        platform: str,
        content_id: str,
        title: str,
        body_text: str,
        media_urls: list[str] | None = None,
        scheduled_at: str | None = None,
        account_id: str | None = None,
    ) -> SocialPublishResult:
        external_id = f"{platform}_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info(
            "RealSocialProvider.publish platform=%s content_id=%s account_id=%s",
            platform,
            content_id,
            account_id,
        )

        # TODO: 实际生产中应根据 account_id 从 DB Account 表查询 access_token。
        # Provider 层不直接访问 DB，token 应由上层 service 注入到 self.access_token。
        access_token = self.access_token
        if not access_token:
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="token_required",
                error_message=f"平台 {platform} 未获取到 access_token，请先完成 OAuth 授权或通过 account_id 关联账号",
            )

        base_url = self._get_base_url(platform)
        if not base_url:
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="config_missing",
                error_message=f"平台 {platform} 的 API base URL 未配置",
            )

        try:
            if platform == "douyin":
                return await self._publish_douyin(
                    base_url,
                    access_token,
                    platform,
                    external_id,
                    title,
                    body_text,
                    media_urls,
                    scheduled_at,
                    now,
                )
            if platform == "xiaohongshu":
                return await self._publish_xiaohongshu(
                    base_url,
                    access_token,
                    platform,
                    external_id,
                    title,
                    body_text,
                    media_urls,
                    scheduled_at,
                    now,
                )
            if platform == "wechat_video":
                return await self._publish_wechat_video(
                    base_url,
                    access_token,
                    platform,
                    external_id,
                    title,
                    body_text,
                    media_urls,
                    scheduled_at,
                    now,
                )
            if platform == "wechat_mp":
                return await self._publish_wechat_mp(
                    base_url,
                    access_token,
                    platform,
                    external_id,
                    title,
                    body_text,
                    media_urls,
                    scheduled_at,
                    now,
                )
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_failed",
                error_message=f"不支持的平台: {platform}",
            )
        except httpx.TimeoutException:
            logger.exception("RealSocialProvider.publish timeout platform=%s", platform)
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_failed",
                error_message=f"平台 {platform} 发布请求超时（10s）",
            )
        except httpx.HTTPStatusError as e:
            logger.exception(
                "RealSocialProvider.publish http error platform=%s", platform
            )
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_failed",
                error_message=f"平台 {platform} HTTP 错误: {e.response.status_code} {e.response.text[:200]}",
            )
        except Exception as e:
            logger.exception("RealSocialProvider.publish error platform=%s", platform)
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_failed",
                error_message=str(e),
            )

    async def _publish_douyin(
        self,
        base_url: str,
        access_token: str,
        platform: str,
        external_id: str,
        title: str,
        body_text: str,
        media_urls: list[str] | None,
        scheduled_at: str | None,
        now: str,
    ) -> SocialPublishResult:
        url = f"{base_url.rstrip('/')}{self._ENDPOINTS['douyin']}"
        first_media = media_urls[0] if media_urls else None
        payload = {
            "access_token": access_token,
            "title": title,
            "cover_url": first_media,
            "video_url": first_media,
            "text": body_text,
            "scheduled_at": scheduled_at,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        item_id = (
            data.get("item_id") or data.get("data", {}).get("item_id") or external_id
        )
        publish_url = f"https://www.douyin.com/video/{item_id}"
        return SocialPublishResult(
            platform=platform,
            external_post_id=str(item_id),
            status="published",
            publish_url=publish_url,
            scheduled_at=scheduled_at or now,
        )

    async def _publish_xiaohongshu(
        self,
        base_url: str,
        access_token: str,
        platform: str,
        external_id: str,
        title: str,
        body_text: str,
        media_urls: list[str] | None,
        scheduled_at: str | None,
        now: str,
    ) -> SocialPublishResult:
        """小红书发布。

        小红书官方开放平台已暂停接入，采用「AI 助手浏览器自动化」模式：
        - 后端返回 pending_agent 状态 + 待发布内容包
        - AI 助手通过 browser-use / xiaohongshu-mcp skill 操作浏览器完成发布
        - 发布完成后由 AI 助手回调 /publish/{content_id}/xhs/callback 回填 note_id

        这样不在 Docker 里跑重型浏览器，规避 headless 风控检测。
        """
        return SocialPublishResult(
            platform=platform,
            external_post_id=external_id,
            status="pending_agent",
            publish_url="",
            scheduled_at=scheduled_at or now,
            error_message=None,
        )

    async def _publish_wechat_video(
        self,
        base_url: str,
        access_token: str,
        platform: str,
        external_id: str,
        title: str,
        body_text: str,
        media_urls: list[str] | None,
        scheduled_at: str | None,
        now: str,
    ) -> SocialPublishResult:
        url = f"{base_url.rstrip('/')}{self._ENDPOINTS['wechat_video']}"
        first_media = media_urls[0] if media_urls else None
        params = {"access_token": access_token}
        payload = {
            "title": title,
            "content": body_text,
            "video_url": first_media,
            "cover_url": first_media,
            "scheduled_at": scheduled_at,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()
        video_id = (
            data.get("video_id") or data.get("data", {}).get("video_id") or external_id
        )
        publish_url = f"https://channels.weixin.qq.com/{video_id}"
        return SocialPublishResult(
            platform=platform,
            external_post_id=str(video_id),
            status="published",
            publish_url=publish_url,
            scheduled_at=scheduled_at or now,
        )

    async def _publish_wechat_mp(
        self,
        base_url: str,
        access_token: str,
        platform: str,
        external_id: str,
        title: str,
        body_text: str,
        media_urls: list[str] | None,
        scheduled_at: str | None,
        now: str,
    ) -> SocialPublishResult:
        # 公众号：先创建草稿，再提交发布
        params = {"access_token": access_token}
        first_media = media_urls[0] if media_urls else None

        draft_url = f"{base_url.rstrip('/')}{self._ENDPOINTS['wechat_mp_draft']}"
        draft_payload = {
            "title": title,
            "content": body_text,
            "thumb_media_id": first_media,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(draft_url, params=params, json=draft_payload)
            resp.raise_for_status()
            draft_data = resp.json()
        media_id = (
            draft_data.get("media_id")
            or draft_data.get("data", {}).get("media_id")
            or external_id
        )

        publish_url = f"{base_url.rstrip('/')}{self._ENDPOINTS['wechat_mp_publish']}"
        publish_payload = {"media_id": media_id}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(publish_url, params=params, json=publish_payload)
            resp.raise_for_status()
            data = resp.json()
        post_id = (
            data.get("publish_id") or data.get("data", {}).get("publish_id") or media_id
        )
        # 公众号提交后进入审核
        return SocialPublishResult(
            platform=platform,
            external_post_id=str(post_id),
            status="reviewing",
            publish_url=f"https://mp.weixin.qq.com/s/{post_id}",
            scheduled_at=scheduled_at or now,
        )


def get_social_provider():
    p = settings.SOCIAL_PROVIDER
    if p == "mock":
        return MockSocialProvider()
    if p in ("douyin", "xiaohongshu", "wechat_video", "wechat_mp"):
        return RealSocialProvider(platform=p)
    if p == "synapse_embedded":
        # 内嵌 Synapse 发布引擎：通过 Celery worker 调用 Playwright 发布
        from app.services.synapse_embedded_provider import EmbeddedSynapseSocialProvider

        return EmbeddedSynapseSocialProvider()
    raise NotImplementedError(f"Social provider '{p}' not implemented.")
