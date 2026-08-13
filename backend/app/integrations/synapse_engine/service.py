"""EmbeddedSynapseService - Synapse 内嵌发布引擎对外服务。

统一封装：
1. 可视网页登录：start_login / poll_login_status / sync_account
2. Cookie 校验：validate_account_cookie
3. 内容发布：publish_content（异步 worker 调用）
4. 平台适配器加载：通过 platforms.get_platform_adapter

所有方法均为进程内 Python 调用，不走 HTTP，不开子进程。
Playwright 操作放进 Celery worker 异步执行，不阻塞 FastAPI 请求。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from app.core.config import get_settings
from app.integrations.synapse_engine.cookie import CookieManager
from app.integrations.synapse_engine.platforms import get_platform_adapter
from app.integrations.synapse_engine.platforms.base import (
    LoginResult,
    LoginStatus,
    QRCodeData,
    PlatformAdapter,
)
from app.integrations.synapse_engine.platforms.codes import (
    PLATFORM_CODES,
    PLATFORM_NAMES,
    normalize_platform,
)

logger = logging.getLogger(__name__)


class EmbeddedSynapseService:
    """Synapse 内嵌引擎服务（单例）。

    线程安全：内部状态用 dict + asyncio.Lock 保护。
    """

    _instance: "EmbeddedSynapseService | None" = None
    _init_lock = asyncio.Lock()

    def __new__(cls) -> "EmbeddedSynapseService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        # 只有全部依赖初始化成功后才标记完成。此前 Cookie 目录等初始化
        # 一旦抛错，单例会永久停在缺少属性的“半初始化”状态。
        self.settings = get_settings()
        self.cookie_manager = CookieManager()
        # 进行中的网页登录会话：<session_id, {adapter, platform, account_id, started_at}>
        self._login_sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._initialized = True

    # ===== 可视网页登录 =====

    @staticmethod
    def _manual_verification_payload(sess: dict[str, Any] | None) -> dict[str, Any]:
        vnc = (sess or {}).get("vnc_session") or {}
        session_id = str(vnc.get("session_id") or "")
        return {
            "available": bool(session_id),
            "session_id": session_id,
            "vnc_password": str(vnc.get("vnc_password") or ""),
            "connection_scheme": "managed_session",
        }

    async def start_login(self, platform: str, account_id: str | None = None) -> dict:
        """启动可视网页登录流程。

        Args:
            platform: 平台代码（xiaohongshu/douyin/...）
            account_id: 可选，账号 ID（用于关联 cookie 文件）

        Returns:
            {
                "session_id": "...",
                "platform": "...",
                "login_mode": "visual_browser",
                "manual_verification": {...},
                "expires_in": 300,
            }

        Notes:
            session_id 由 adapter.start_visual_login() 内部生成并返回，
            service 直接复用该 ID 作为会话标识，确保 poll_login_status 能找到
            adapter 内部的浏览器会话。
        """
        platform = normalize_platform(platform)
        if not platform:
            raise ValueError("platform 不能为空")

        adapter = get_platform_adapter(platform, config={"headless": True})
        login_request_id = uuid.uuid4().hex
        requested_account_id = account_id or f"login_{login_request_id[:12]}"
        vnc_session: dict[str, Any] | None = None
        native_session: dict[str, Any] | None = None
        login_mode = "visual_browser"

        # 账号授权优先在 Mac 宿主机弹出真实 Chrome。CDP 仍由平台适配器
        # 接管，因此登录成功后的 storage_state 保存逻辑无需爬取二维码或验证码。
        # vnc 模式仅作为兼容回退；发布也可使用同一宿主浏览器桥。
        set_remote_cdp = getattr(adapter, "set_remote_cdp_url", None)
        if callable(set_remote_cdp):
            try:
                browser_mode = (
                    self.settings.SYNAPSE_LOGIN_BROWSER_MODE or "vnc"
                ).strip().lower()
                if browser_mode == "native_host":
                    from app.integrations.synapse_engine.native_browser import (
                        native_browser_manager,
                    )

                    native_session = await native_browser_manager.acquire(
                        platform=platform,
                        account_id=requested_account_id,
                        task_id=f"login:{login_request_id}",
                        ttl_seconds=360,
                        purpose="login",
                    )
                    native_cdp_url = str(native_session.get("cdp_url") or "")
                    try:
                        set_remote_cdp(
                            native_cdp_url,
                            reuse_default_context=True,
                        )
                    except TypeError:
                        # 兼容第三方适配器仍采用旧的一参数签名。
                        set_remote_cdp(native_cdp_url)
                    login_mode = "native_browser"
                else:
                    from app.integrations.synapse_engine.verification.manager import (
                        verification_manager,
                    )

                    vnc_session = (
                        await verification_manager.acquire_vnc_session_from_manager(
                            platform=platform,
                            account_id=requested_account_id,
                            task_id=f"login:{login_request_id}",
                        )
                    )
                    set_remote_cdp(vnc_session.get("cdp_url"))
            except Exception as exc:
                target = "Mac 原生浏览器服务" if browser_mode == "native_host" else "browser-vnc"
                raise RuntimeError(
                    f"登录浏览器服务不可用，请检查 {target}：{exc}"
                ) from exc

        try:
            start_visual_login = getattr(adapter, "start_visual_login", None)
            if callable(start_visual_login):
                qr: QRCodeData = await start_visual_login()
            else:
                # 兼容尚未升级的第三方适配器。
                qr = await adapter.get_qrcode()
        except Exception:
            if native_session:
                from app.integrations.synapse_engine.native_browser import (
                    native_browser_manager,
                )

                await native_browser_manager.release(
                    str(native_session.get("session_id") or "")
                )
            if vnc_session:
                from app.integrations.synapse_engine.verification.manager import (
                    verification_manager,
                )

                await verification_manager.release_vnc_session(
                    str(vnc_session.get("session_id") or "")
                )
            raise

        # 统一使用 qr.session_id，确保 poll_status 能找到 adapter 内部会话
        session_id = qr.session_id
        account_id = account_id or f"temp_{session_id[:8]}"

        async with self._lock:
            self._login_sessions[session_id] = {
                "adapter": adapter,
                "platform": platform,
                "account_id": account_id,
                "qr_data": qr,
                "started_at": time.time(),
                "last_result": None,
                "vnc_session": vnc_session,
                "native_session": native_session,
                "login_mode": login_mode,
            }

        logger.info(
            "start_login platform=%s session_id=%s account_id=%s",
            platform,
            session_id,
            account_id,
        )

        payload = {
            "session_id": session_id,
            "platform": platform,
            "platform_name": PLATFORM_NAMES.get(platform, platform),
            "account_id": account_id,
            "login_mode": login_mode,
            "presentation": (
                "native_window" if login_mode == "native_browser" else "embedded_vnc"
            ),
            "qr_image": qr.qr_image,
            "qr_url": qr.qr_url,
            "expires_in": qr.expires_in,
        }
        payload["manual_verification"] = self._manual_verification_payload(
            {"vnc_session": vnc_session}
        )
        return payload

    async def poll_login_status(self, session_id: str) -> dict:
        """轮询网页登录状态。

        Args:
            session_id: start_login 返回的 session_id（与 adapter 内部会话 ID 一致）

        Returns:
            {
                "status": "waiting|scanned|confirmed|failed|expired",
                "message": "...",
                "platform": "...",
                "account_id": "...",
                "user_info": {...} | None,
                "saved": bool,
            }
        """
        async with self._lock:
            sess = self._login_sessions.get(session_id)
        if not sess:
            return {
                "status": LoginStatus.EXPIRED.value,
                "message": "session 不存在或已过期",
            }

        # 超时
        if time.time() - sess["started_at"] > 300:
            await self._cleanup_session(session_id)
            return {
                "status": LoginStatus.EXPIRED.value,
                "message": "登录会话已超时，请重新打开",
            }

        adapter: PlatformAdapter = sess["adapter"]
        native_session = sess.get("native_session") or {}
        if native_session.get("session_id"):
            from app.integrations.synapse_engine.native_browser import (
                native_browser_manager,
            )

            await native_browser_manager.heartbeat(
                str(native_session["session_id"])
            )
        vnc_session = sess.get("vnc_session") or {}
        if vnc_session.get("session_id"):
            from app.integrations.synapse_engine.verification.manager import (
                verification_manager,
            )

            await verification_manager.heartbeat_vnc_session(
                str(vnc_session["session_id"])
            )
        # session_id 与 adapter 内部会话 ID 一致，poll_status 能找到会话
        result: LoginResult = await adapter.poll_status(session_id)
        sess["last_result"] = result

        if result.status == LoginStatus.CONFIRMED:
            # 登录成功，保存 storage_state
            platform = sess["platform"]
            account_id = sess["account_id"]
            base_user_info = _user_info_to_dict(result.user_info)
            storage_user_info = extract_user_info_from_storage_state(
                platform, result.full_state
            )
            user_info = _merge_user_info(base_user_info, storage_user_info)

            real_account_id = (
                (user_info or {}).get("user_id")
                or ((user_info or {}).get("extra") or {}).get("user_id")
                or ((user_info or {}).get("extra") or {}).get("red_id")
            )
            # If start_login used a temporary id, replace it with the platform's real uid.
            if real_account_id and str(account_id).startswith("temp_"):
                account_id = str(real_account_id)

            if result.full_state:
                self.cookie_manager.save(platform, account_id, result.full_state)
            # ???????????
            await self._cleanup_session(session_id)

            return {
                "status": LoginStatus.CONFIRMED.value,
                "message": result.message or "????",
                "platform": platform,
                "account_id": account_id,
                "user_info": user_info,
                "saved": True,
            }

        payload = {
            "status": result.status.value,
            "message": result.message or "",
            "platform": sess["platform"],
            "account_id": sess["account_id"],
        }
        payload["manual_verification"] = self._manual_verification_payload(sess)
        return payload

    async def cancel_login(self, session_id: str) -> dict:
        """取消网页登录会话。"""
        await self._cleanup_session(session_id)
        return {"session_id": session_id, "status": "cancelled"}

    async def _cleanup_session(self, session_id: str) -> None:
        async with self._lock:
            sess = self._login_sessions.pop(session_id, None)
        if not sess:
            return
        adapter: PlatformAdapter = sess["adapter"]
        try:
            await adapter.cleanup_session(session_id)
        except Exception as e:
            logger.warning("清理 session %s 失败: %s", session_id, e)
        vnc_session = sess.get("vnc_session") or {}
        if vnc_session.get("session_id"):
            try:
                from app.integrations.synapse_engine.verification.manager import (
                    verification_manager,
                )

                await verification_manager.release_vnc_session(
                    str(vnc_session["session_id"])
                )
            except Exception as e:
                logger.warning("清理登录 VNC session %s 失败: %s", session_id, e)
        native_session = sess.get("native_session") or {}
        if native_session.get("session_id"):
            try:
                from app.integrations.synapse_engine.native_browser import (
                    native_browser_manager,
                )

                await native_browser_manager.release(
                    str(native_session["session_id"])
                )
            except Exception as e:
                logger.warning("清理原生登录浏览器 session %s 失败: %s", session_id, e)

    # ===== Cookie 校验 =====

    async def validate_account_cookie(self, platform: str, account_id: str) -> dict:
        """校验账号 cookie 是否仍有效。"""
        platform = normalize_platform(platform)
        storage_state = self.cookie_manager.load(platform, account_id)
        if not storage_state:
            return {"valid": False, "reason": "未找到本地会话，请先登录账号"}

        adapter = get_platform_adapter(platform)
        result = await adapter.validate_cookie(storage_state)
        refreshed_state = result.pop("storage_state", None)
        if result.get("valid"):
            if refreshed_state:
                self.cookie_manager.save(platform, account_id, refreshed_state)
        else:
            # Keep invalid cookies for diagnostics/retry. 账号是否失效由数据库
            # cookie_status 标记；不要在“校验失败 / 网络失败 / 页面结构变化”
            # 时直接删除本地 cookie，否则会导致用户必须重新登录。
            pass
        return result

    # ===== 内容发布 =====

    async def publish_content(
        self,
        platform: str,
        account_id: str,
        title: str,
        description: str,
        tags: list[str] | None = None,
        media_paths: list[str] | None = None,
        cover_path: str | None = None,
        publish_mode: str = "direct",
        scheduled_at: str | None = None,
        publish_params: dict[str, Any] | None = None,
    ) -> dict:
        """发布内容到指定平台。

        实际由 Celery worker 调用本方法。Playwright 操作在 worker 进程中执行，
        不会阻塞 FastAPI 主进程的普通 API 请求。
        """
        platform = normalize_platform(platform)
        storage_state = self.cookie_manager.load(platform, account_id)
        if not storage_state:
            return {
                "success": False,
                "status": "cookie_missing",
                "error": f"未找到 {platform} 账号 {account_id} 的会话，请先登录账号",
            }

        adapter = get_platform_adapter(platform)
        native_session_id = ""
        native_heartbeat_task: asyncio.Task | None = None
        try:
            publish_browser_mode = (
                self.settings.SYNAPSE_PUBLISH_BROWSER_MODE or "worker"
            ).strip().lower()
            if publish_browser_mode == "native_host":
                from app.integrations.synapse_engine.native_browser import (
                    native_browser_manager,
                )
                from app.integrations.synapse_engine.verification.manager import (
                    get_current_task_id,
                )

                set_remote_cdp = getattr(adapter, "set_remote_cdp_url", None)
                if not callable(set_remote_cdp):
                    raise RuntimeError(
                        f"平台 {platform} 暂不支持宿主机真实浏览器发布"
                    )
                task_id = get_current_task_id() or f"publish:{uuid.uuid4().hex}"
                native_session = await native_browser_manager.acquire(
                    platform=platform,
                    account_id=account_id,
                    task_id=task_id,
                    ttl_seconds=1800,
                    visible=False,
                    purpose="publish",
                )
                native_session_id = str(native_session.get("session_id") or "")
                native_cdp_url = str(native_session.get("cdp_url") or "")
                try:
                    set_remote_cdp(
                        native_cdp_url,
                        reuse_default_context=False,
                    )
                except TypeError:
                    set_remote_cdp(native_cdp_url)
                set_native_session = getattr(
                    adapter, "set_native_publish_session", None
                )
                if callable(set_native_session):
                    set_native_session(native_session_id)
                logger.info(
                    "发布任务已接管宿主 Chrome task=%s platform=%s session=%s",
                    task_id,
                    platform,
                    native_session_id,
                )

                async def keep_native_session_alive() -> None:
                    while True:
                        await asyncio.sleep(45)
                        try:
                            await native_browser_manager.heartbeat(
                                native_session_id
                            )
                        except Exception as exc:
                            logger.warning(
                                "发布宿主浏览器心跳失败 session=%s: %s",
                                native_session_id,
                                exc,
                            )

                native_heartbeat_task = asyncio.create_task(
                    keep_native_session_alive()
                )

            result = await adapter.publish_content(
                storage_state=storage_state,
                title=title,
                description=description,
                tags=tags or [],
                media_paths=media_paths or [],
                cover_path=cover_path,
                publish_mode=publish_mode,
                scheduled_at=scheduled_at,
                account_id=account_id,
                publish_params=publish_params or {},
            )
            # 发布成功后 cookie 可能已更新（页面刷新 cookie），尝试重新保存
            # 这里不强制更新，因为多数情况下 storage_state 不变
            return result
        except Exception as e:
            logger.exception("发布到 %s 失败", platform)
            return {
                "success": False,
                "status": "publish_error",
                "error": str(e),
            }
        finally:
            if native_heartbeat_task is not None:
                native_heartbeat_task.cancel()
                await asyncio.gather(
                    native_heartbeat_task, return_exceptions=True
                )
            if native_session_id:
                try:
                    from app.integrations.synapse_engine.native_browser import (
                        native_browser_manager,
                    )

                    await native_browser_manager.release(native_session_id)
                except Exception as exc:
                    logger.warning(
                        "关闭发布宿主浏览器 session=%s 失败: %s",
                        native_session_id,
                        exc,
                    )

    async def delete_published_content(
        self,
        platform: str,
        account_id: str,
        publish_url: str | None = None,
        external_post_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        """通过平台网页删除或下架已发布内容。"""
        platform = normalize_platform(platform)
        storage_state = self.cookie_manager.load(platform, account_id)
        if not storage_state:
            return {
                "success": False,
                "status": "cookie_missing",
                "error": f"未找到 {platform} 账号 {account_id} 的会话，请先登录账号",
            }
        adapter = get_platform_adapter(platform)
        delete_fn = getattr(adapter, "delete_published_content", None)
        if delete_fn is None:
            return {
                "success": False,
                "status": "unsupported",
                "error": f"平台 {platform} 暂未接入内容删除能力",
            }
        try:
            return await delete_fn(
                storage_state=storage_state,
                publish_url=publish_url,
                external_post_id=external_post_id,
                title=title,
                account_id=account_id,
            )
        except Exception as e:
            logger.exception("删除 %s 内容失败", platform)
            return {"success": False, "status": "remote_action_failed", "error": str(e)}

    async def update_published_visibility(
        self,
        platform: str,
        account_id: str,
        visibility: str,
        publish_url: str | None = None,
        external_post_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        """通过平台网页调整已发布内容可见性。"""
        platform = normalize_platform(platform)
        storage_state = self.cookie_manager.load(platform, account_id)
        if not storage_state:
            return {
                "success": False,
                "status": "cookie_missing",
                "error": f"未找到 {platform} 账号 {account_id} 的会话，请先登录账号",
            }
        adapter = get_platform_adapter(platform)
        update_fn = getattr(adapter, "update_published_visibility", None)
        if update_fn is None:
            return {
                "success": False,
                "status": "unsupported",
                "error": f"平台 {platform} 暂未接入内容可见性调整能力",
            }
        try:
            return await update_fn(
                storage_state=storage_state,
                visibility=visibility,
                publish_url=publish_url,
                external_post_id=external_post_id,
                title=title,
                account_id=account_id,
            )
        except Exception as e:
            logger.exception("修改 %s 内容可见性失败", platform)
            return {"success": False, "status": "remote_action_failed", "error": str(e)}

    # ===== 账号管理 =====

    def list_saved_accounts(self, platform: str | None = None) -> list[dict]:
        """列出已保存 cookie 的账号。"""
        return self.cookie_manager.list_accounts(platform)

    def get_account_cookie_path(self, platform: str, account_id: str) -> str | None:
        """获取账号 cookie 文件路径。"""
        p = self.cookie_manager._path(platform, account_id)
        return str(p) if p.exists() else None

    def delete_account_cookie(self, platform: str, account_id: str) -> bool:
        """删除账号 cookie 文件。"""
        return self.cookie_manager.delete(platform, account_id)

    # ===== 平台元数据 =====

    @staticmethod
    def list_platforms() -> list[dict]:
        """返回支持的平台列表。"""
        return [
            {
                "code": code,
                "platform": plat,
                "name": PLATFORM_NAMES.get(plat, plat),
            }
            for plat, code in PLATFORM_CODES.items()
        ]

    @staticmethod
    def resolve_platform(code_or_name: str) -> str | None:
        """把平台 code（数字或名字）规范化为 platform 字符串。"""
        return normalize_platform(code_or_name)


def _json_loads_safe(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else None
    except Exception:
        return None


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = str(phone)
    if len(digits) < 7:
        return digits
    return f"{digits[:3]}****{digits[-4:]}"


def _cookie_lookup(storage_state: dict | None, names: set[str]) -> str | None:
    if not storage_state:
        return None
    for cookie in storage_state.get("cookies") or []:
        name = str(cookie.get("name") or "")
        if name in names:
            value = cookie.get("value")
            if value:
                return str(value)
    return None


def extract_user_info_from_storage_state(
    platform: str, storage_state: dict | None
) -> dict | None:
    """Extract platform account identity from Playwright storage_state.

    Xiaohongshu stores accurate creator account info in localStorage.USER_INFO_FOR_BIZ.
    Keeping this parser server-side lets old temp_* rows be repaired without another login.
    """
    if not storage_state:
        return None

    info: dict[str, Any] = {"extra": {}}
    for origin in storage_state.get("origins") or []:
        for item in origin.get("localStorage") or []:
            key = item.get("name")
            value = item.get("value")
            if key == "USER_INFO_FOR_BIZ":
                data = _json_loads_safe(value) or {}
                if data.get("userId"):
                    info["user_id"] = str(data.get("userId"))
                    info["extra"]["user_id"] = str(data.get("userId"))
                if data.get("userName"):
                    info["name"] = str(data.get("userName"))
                    info["username"] = str(data.get("userName"))
                if data.get("userAvatar"):
                    info["avatar"] = str(data.get("userAvatar"))
                if data.get("redId"):
                    info["extra"]["red_id"] = str(data.get("redId"))
                if data.get("role"):
                    info["extra"]["role"] = str(data.get("role"))
                if data.get("zone"):
                    info["extra"]["zone"] = str(data.get("zone"))
                if "realNameVerified" in data:
                    info["extra"]["real_name_verified"] = bool(
                        data.get("realNameVerified")
                    )
                masked = _mask_phone(data.get("phone"))
                if masked:
                    info["extra"]["phone_masked"] = masked
            elif key == "USER_INFO":
                data = _json_loads_safe(value) or {}
                nested = (
                    ((data.get("user") or {}).get("value") or {})
                    if isinstance(data.get("user"), dict)
                    else {}
                )
                if nested.get("userId") and not info.get("user_id"):
                    info["user_id"] = str(nested.get("userId"))
                    info["extra"]["user_id"] = str(nested.get("userId"))
                if nested.get("loginUserType"):
                    info["extra"]["login_user_type"] = str(nested.get("loginUserType"))

    if platform == "xiaohongshu":
        cookie_uid = _cookie_lookup(
            storage_state, {"x-user-id-creator.xiaohongshu.com"}
        )
        if cookie_uid and not info.get("user_id"):
            info["user_id"] = cookie_uid
            info["extra"]["user_id"] = cookie_uid
        client_id = _cookie_lookup(storage_state, {"customerClientId"})
        if client_id:
            info["extra"]["customer_client_id"] = client_id

    if platform == "bilibili":
        mid = _cookie_lookup(storage_state, {"DedeUserID"})
        if mid:
            info["user_id"] = mid
            info["extra"]["mid"] = mid
            info["extra"]["user_id"] = mid

    if platform == "douyin":
        for origin in storage_state.get("origins") or []:
            for item in origin.get("localStorage") or []:
                key = item.get("name")
                value = item.get("value")
                if key == "SLARDARdouyin_creator_longvideo":
                    data = _json_loads_safe(value) or {}
                    if data.get("userId"):
                        info["user_id"] = str(data.get("userId"))
                        info["extra"]["user_id"] = str(data.get("userId"))
                    if data.get("deviceId"):
                        info["extra"]["device_id"] = str(data.get("deviceId"))
        cookie_uid = _cookie_lookup(storage_state, {"uid_tt", "uid_tt_ss"})
        if cookie_uid:
            info["extra"]["uid_tt"] = cookie_uid

    if platform == "kuaishou":
        uid = _cookie_lookup(storage_state, {"userId"})
        if uid:
            info["user_id"] = uid
            info["extra"]["kwai_id"] = uid
            info["extra"]["user_id"] = uid

    if platform == "channels":
        uid = _cookie_lookup(storage_state, {"finder_username", "wxuin", "uin"})
        if uid:
            info["user_id"] = uid
            info["extra"]["user_id"] = uid

    return (
        info
        if any(v for k, v in info.items() if k != "extra") or info.get("extra")
        else None
    )


def _merge_user_info(*parts: dict | None) -> dict | None:
    merged: dict[str, Any] = {"extra": {}}
    has_value = False
    for part in parts:
        if not part:
            continue
        for key, value in part.items():
            if key == "extra" and isinstance(value, dict):
                for ek, ev in value.items():
                    if ev not in (None, ""):
                        merged["extra"][ek] = ev
                        has_value = True
            elif value not in (None, ""):
                merged[key] = value
                has_value = True
    if not merged.get("extra"):
        merged.pop("extra", None)
    return merged if has_value else None


def _user_info_to_dict(user_info) -> dict | None:
    if user_info is None:
        return None
    return {
        "user_id": user_info.user_id,
        "name": user_info.name,
        "username": user_info.username,
        "avatar": user_info.avatar,
        "extra": user_info.extra or {},
    }


__all__ = ["EmbeddedSynapseService", "extract_user_info_from_storage_state"]
