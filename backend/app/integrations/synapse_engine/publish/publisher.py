"""Publisher - 高级发布编排器。

由 Celery worker 调用。接收一个发布任务规格（task spec），
准备发布输入（媒体文件本地路径），调用 EmbeddedSynapseService 执行发布，
并返回结果给 worker 用于回写 publish_tasks 表。

不直接访问 DB（避免与 repository 层循环依赖）。
"""

from __future__ import annotations

import ipaddress
import logging
import mimetypes
import shutil
import socket
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.synapse_engine.service import EmbeddedSynapseService
from app.integrations.synapse_engine.utils.media_tools import ensure_publishable_video
from app.utils.social_text import sanitize_publish_text

logger = logging.getLogger(__name__)


_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VIDEO_ONLY_PLATFORMS = {"douyin", "kuaishou", "bilibili", "channels"}
_MEDIA_REQUIRED_PLATFORMS = _VIDEO_ONLY_PLATFORMS | {"xiaohongshu"}


class Publisher:
    """高级发布编排器（worker 内部使用）。"""

    def __init__(self, service: EmbeddedSynapseService | None = None):
        self.service = service or EmbeddedSynapseService()

    async def run(self, task_spec: dict) -> dict:
        """执行发布任务。

        Args:
            task_spec: 发布任务规格，包含字段：
                - task_id: 任务 ID
                - platform: 平台
                - account_id: 账号 ID
                - title: 标题
                - description: 正文
                - tags: 标签列表
                - media_paths: 媒体文件本地路径列表
                - cover_path: 封面图本地路径
                - publish_mode: direct|schedule
                - scheduled_at: 定时发布时间（ISO）

        Returns:
            {
                "task_id": "...",
                "success": True/False,
                "status": "published|filled|cookie_missing|publish_error|...",
                "platform": "...",
                "external_post_id": "...",  # 可能没有
                "publish_url": "...",       # 可能没有
                "error": "...",             # 失败时
            }
        """
        task_id = task_spec.get("task_id")
        platform = task_spec.get("platform", "")
        account_id = task_spec.get("account_id", "")
        title = task_spec.get("title", "")
        # 最终出口再清理一次，保证修复前已创建的待发布任务和重试任务
        # 也不会把“钩子/正文/CTA”等内部结构标签投递到平台。
        description = sanitize_publish_text(task_spec.get("description", ""))
        tags = task_spec.get("tags") or []
        media_paths = task_spec.get("media_paths") or []
        cover_path = task_spec.get("cover_path")
        publish_mode = task_spec.get("publish_mode", "direct")
        scheduled_at = task_spec.get("scheduled_at")
        publish_params = task_spec.get("publish_params") or {}
        temp_dir: str | None = None

        logger.info(
            "Publisher.run task_id=%s platform=%s account_id=%s media_count=%d",
            task_id,
            platform,
            account_id,
            len(media_paths),
        )

        try:
            media_paths, temp_dir = self._prepare_media_files(
                platform, task_id, media_paths, publish_params
            )
            if cover_path:
                if not temp_dir:
                    temp_dir = self._make_temp_dir(
                        prefix=f"synapse_media_{task_id or 'task'}_"
                    )
                cover_path = self._resolve_media_item(str(cover_path), temp_dir, 999)
            result = await self.service.publish_content(
                platform=platform,
                account_id=account_id,
                title=title,
                description=description,
                tags=tags,
                media_paths=media_paths,
                cover_path=cover_path,
                publish_mode=publish_mode,
                scheduled_at=scheduled_at,
                publish_params=publish_params,
            )
        except Exception as e:
            logger.exception("Publisher 执行异常 task_id=%s", task_id)
            return {
                "task_id": task_id,
                "success": False,
                "status": "publish_error",
                "error": str(e),
                "platform": platform,
            }
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

        # 统一返回字段
        success = bool(result.get("success"))
        status = result.get("status", "unknown")
        return {
            "task_id": task_id,
            "success": success,
            "status": status,
            "platform": platform,
            "external_post_id": result.get("external_post_id"),
            "publish_url": result.get("publish_url"),
            "message": result.get("message"),
            "error": result.get("error"),
            "screenshots": result.get("screenshots") or [],
        }

    def _prepare_media_files(
        self,
        platform: str,
        task_id: str | None,
        media_paths: list[str],
        publish_params: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None]:
        """Convert DB media_urls into local files accepted by Playwright set_input_files().

        The UI stores media as URLs (MinIO URL, relative /assets URL, or crawler URL),
        while Playwright upload requires real local paths inside the worker container.
        """
        items = [str(x).strip() for x in (media_paths or []) if str(x or "").strip()]
        if platform in _MEDIA_REQUIRED_PLATFORMS and not items:
            return self._media_error(
                platform,
                "当前内容没有图片/视频素材。小红书、抖音、快手、B站、视频号发布前必须先在内容里绑定素材。",
            )

        if platform in _VIDEO_ONLY_PLATFORMS and not any(
            self._looks_like_video(x) for x in items
        ):
            return self._media_error(
                platform,
                f"{platform} 当前发布入口是视频发布页，必须绑定 mp4/mov 等视频素材。",
            )

        if not items:
            return [], None

        temp_dir = self._make_temp_dir(
            prefix=f"synapse_media_{task_id or 'task'}_"
        )
        local_paths: list[str] = []
        params = publish_params or {}
        require_audio = not bool(params.get("allow_silent_video"))
        transcode_video = params.get("transcode_video", True) is not False
        try:
            for i, item in enumerate(items):
                local_path = self._resolve_media_item(item, temp_dir, i)
                if self._looks_like_video(local_path):
                    local_path = ensure_publishable_video(
                        local_path,
                        temp_dir,
                        require_audio=require_audio,
                        transcode=transcode_video,
                    )
                local_paths.append(local_path)
            return local_paths, temp_dir
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _media_error(self, platform: str, message: str) -> tuple[list[str], None]:
        raise ValueError(message)

    @staticmethod
    def _make_temp_dir(prefix: str) -> str:
        """为 native_host 发布创建 Mac/容器同路径的临时素材目录。"""
        settings = get_settings()
        browser_mode = (
            settings.SYNAPSE_PUBLISH_BROWSER_MODE or "worker"
        ).strip().lower()
        if browser_mode != "native_host":
            return tempfile.mkdtemp(prefix=prefix)

        shared_root = Path(
            settings.SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR
            or "/tmp/ai-social-native-media"
        )
        if not shared_root.is_absolute():
            raise ValueError(
                "SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR 必须是绝对路径"
            )
        shared_root.mkdir(parents=True, exist_ok=True)
        shared_root.chmod(0o755)
        temp_dir = tempfile.mkdtemp(prefix=prefix, dir=str(shared_root))
        # Docker 中创建者通常是 root；宿主 Chrome 以当前 Mac 用户运行，
        # 需要目录可遍历。文件仍使用默认 0644，并在任务结束后立即删除。
        Path(temp_dir).chmod(0o755)
        return temp_dir

    def _resolve_media_item(self, item: str, temp_dir: str, index: int) -> str:
        parsed = urllib.parse.urlparse(item)

        # Local paths are disabled by default because API-provided paths could
        # otherwise make the worker upload arbitrary host files to a platform.
        if parsed.scheme == "file":
            raise ValueError("不允许使用 file:// 本地素材地址")
        if parsed.scheme == "" and Path(item).exists():
            settings = get_settings()
            candidate = Path(item).resolve()
            if not settings.SYNAPSE_ALLOW_LOCAL_MEDIA:
                raise ValueError("本地素材路径已禁用，请先上传到素材库")
            if (
                settings.SYNAPSE_PUBLISH_BROWSER_MODE or "worker"
            ).strip().lower() == "native_host":
                suffix = candidate.suffix.lower() or ".bin"
                staged = Path(temp_dir) / f"media_{index}{suffix}"
                shutil.copy2(candidate, staged)
                staged.chmod(0o644)
                return str(staged)
            return str(candidate)

        # Relative seeded/static URL; try app containers before failing.
        if item.startswith("/"):
            for base in ("http://frontend", "http://nginx", "http://backend:8000"):
                try:
                    return self._download_media(
                        base + item, temp_dir, index, allow_private=True
                    )
                except Exception:
                    continue
            raise FileNotFoundError(f"无法解析相对素材路径：{item}")

        if parsed.scheme in ("http", "https"):
            if self._is_minio_asset_url(parsed):
                return self._download_minio_asset(parsed, temp_dir, index)
            return self._download_media(item, temp_dir, index)

        if parsed.scheme == "mock":
            raise ValueError(
                f"素材 {item} 是 mock 地址，不能用于真实平台发布，请重新上传真实文件。"
            )

        raise FileNotFoundError(f"素材路径不存在或不支持：{item}")

    def _is_minio_asset_url(self, parsed: urllib.parse.ParseResult) -> bool:
        settings = get_settings()
        endpoint_host = urllib.parse.urlparse(
            ("https://" if settings.MINIO_SECURE else "http://")
            + settings.MINIO_ENDPOINT
        ).netloc
        host = parsed.netloc
        path = parsed.path.lstrip("/")
        return bool(
            host == endpoint_host and path.startswith(f"{settings.MINIO_BUCKET}/")
        )

    def _download_minio_asset(
        self, parsed: urllib.parse.ParseResult, temp_dir: str, index: int
    ) -> str:
        """Download private MinIO object with credentials instead of anonymous HTTP.

        MinIO file_url is stored as http://minio:9000/<bucket>/<object>. Buckets are
        intentionally private, so anonymous urllib gets HTTP 403. The worker runs
        inside the trusted backend network and can use configured MinIO credentials.
        """
        from minio import Minio

        settings = get_settings()
        prefix = f"{settings.MINIO_BUCKET}/"
        object_name = parsed.path.lstrip("/")
        if object_name.startswith(prefix):
            object_name = object_name[len(prefix) :]
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        response = client.get_object(settings.MINIO_BUCKET, object_name)
        try:
            data = response.read(settings.UPLOAD_MAX_SIZE + 1)
            if len(data) > settings.UPLOAD_MAX_SIZE:
                raise ValueError("素材文件超过允许大小")
            content_type = getattr(response, "headers", {}).get("content-type", "")
        finally:
            response.close()
            response.release_conn()

        suffix = Path(urllib.parse.unquote(object_name)).suffix.lower()
        if not suffix:
            suffix = (
                mimetypes.guess_extension((content_type or "").split(";")[0].strip())
                or ".bin"
            )
        target = Path(temp_dir) / f"media_{index}{suffix}"
        target.write_bytes(data)
        return str(target)

    @staticmethod
    def _assert_safe_remote_url(
        url: str, *, allow_private: bool = False
    ) -> urllib.parse.ParseResult:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("远程素材地址必须使用 HTTP(S)")
        if parsed.username or parsed.password:
            raise ValueError("远程素材地址不能包含 URL 凭证")
        if allow_private:
            return parsed
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                )
            }
        except socket.gaierror as exc:
            raise ValueError("远程素材域名无法解析") from exc
        if not addresses:
            raise ValueError("远程素材域名无法解析")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError("禁止从本机或内网地址下载素材")
        return parsed

    def _download_media(
        self, url: str, temp_dir: str, index: int, *, allow_private: bool = False
    ) -> str:
        settings = get_settings()
        current_url = url
        data = bytearray()
        content_type = ""
        with httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False
        ) as client:
            for _ in range(4):
                self._assert_safe_remote_url(current_url, allow_private=allow_private)
                with client.stream(
                    "GET", current_url, headers={"User-Agent": "Mozilla/5.0"}
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("素材下载重定向缺少目标地址")
                        current_url = urllib.parse.urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    declared_size = response.headers.get("content-length")
                    if declared_size and int(declared_size) > settings.UPLOAD_MAX_SIZE:
                        raise ValueError("素材文件超过允许大小")
                    content_type = (
                        response.headers.get("content-type", "").split(";")[0].strip()
                    )
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > settings.UPLOAD_MAX_SIZE:
                            raise ValueError("素材文件超过允许大小")
                    break
            else:
                raise ValueError("素材下载重定向次数过多")
        if not data:
            raise ValueError("下载到的素材文件为空")
        parsed = urllib.parse.urlparse(current_url)
        suffix = Path(parsed.path).suffix.lower()
        if not suffix:
            suffix = mimetypes.guess_extension(content_type) or ".bin"
        target = Path(temp_dir) / f"media_{index}{suffix}"
        target.write_bytes(bytes(data))
        return str(target)

    def _looks_like_video(self, item: str) -> bool:
        path = urllib.parse.urlparse(str(item)).path
        return Path(path).suffix.lower() in _VIDEO_EXTS


__all__ = ["Publisher"]
