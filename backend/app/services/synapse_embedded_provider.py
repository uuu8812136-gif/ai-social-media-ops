"""EmbeddedSynapseSocialProvider - 兼容既有 SocialProvider 接口的 Synapse 内嵌实现。

把 EmbeddedSynapseService 适配到项目既有的 SocialProvider 接口，
让 publish.py 的 prepare_publish_package 不需要改动。

要点：
1. publish() 是同步 async 方法，会派发 Celery 任务到 worker 异步执行真正的 Playwright 发布
2. 立即返回 status=pending_agent + celery_task_id，让 publish.py 把 content 标记为 scheduled
3. 真实的发布结果由 worker 回写到 publish_tasks 表（通过 /social/publish 路由创建的任务）
4. 旧的 /publish 路由通过本 Provider 派发任务，前端发布状态以 /social/publish 路由为准
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.services.social_provider import SocialPublishResult

logger = logging.getLogger(__name__)


class EmbeddedSynapseSocialProvider:
    """Synapse 内嵌发布 Provider。

    通过 Celery worker 异步执行真正的 Playwright 发布，立即返回 pending_agent 状态。
    publish.py 收到 pending_agent 后会把 content.status 设为 scheduled（不会误判为失败）。
    """

    SUPPORTED_PLATFORMS = {
        "xiaohongshu",
        "douyin",
        "channels",
        "kuaishou",
        "bilibili",
        # 兼容既有 publish.py 中传入的别名
        "wechat_video",
        "wechat_mp",
    }

    PLATFORM_ALIASES = {
        "wechat_video": "channels",
        "wechat_mp": "channels",
    }

    def __init__(self, platform: str | None = None, account_id: str | None = None):
        self.platform = platform
        self.account_id = account_id

    def _normalize_platform(self, platform: str) -> str:
        return self.PLATFORM_ALIASES.get(platform, platform)

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
        """派发发布任务到 Celery worker，立即返回 pending_agent 状态。

        返回 pending_agent 而非 pending，让 publish.py 把 content.status 设为 scheduled
        （pending 会被 publish.py 误判为失败并设为 publish_failed）。
        """
        platform = self._normalize_platform(platform)
        external_id = f"synapse_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info(
            "EmbeddedSynapseSocialProvider.publish platform=%s content_id=%s account_id=%s",
            platform,
            content_id,
            account_id,
        )

        # 派发 Celery 任务（延迟导入避免循环依赖）
        try:
            from app.integrations.synapse_engine.workers.tasks import run_publish_task

            task_spec = {
                "task_id": external_id,
                "platform": platform,
                "account_id": account_id or self.account_id or "",
                "title": title,
                "description": body_text,
                "tags": [],
                "media_paths": media_urls or [],
                "cover_path": None,
                "publish_mode": "schedule" if scheduled_at else "direct",
                "scheduled_at": scheduled_at,
                "content_id": content_id,
            }

            run_publish_task.delay(task_spec)

            # 返回 pending_agent：publish.py 会把 content.status 设为 scheduled
            # 实际发布结果由 worker 写回 publish_tasks 表（如果通过 /social/publish 创建了任务）
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="pending_agent",
                publish_url=None,
                scheduled_at=scheduled_at or now,
                error_message=None,
            )
        except Exception as e:
            logger.exception("EmbeddedSynapseSocialProvider 派发任务失败")
            return SocialPublishResult(
                platform=platform,
                external_post_id=external_id,
                status="publish_failed",
                error_message=f"派发发布任务失败: {e}",
            )


__all__ = ["EmbeddedSynapseSocialProvider"]
