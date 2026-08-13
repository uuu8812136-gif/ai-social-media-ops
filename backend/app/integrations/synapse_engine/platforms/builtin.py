"""内置平台适配器（不依赖外部 D:\\social-auto-stack 源码）。

通过 Playwright 直接驱动浏览器完成网页登录和真实发布：
- 网页登录：打开真实登录页 -> 用户在可视浏览器操作 -> 保存完整会话
- 发布内容：加载 storage_state -> 打开发布页 -> 填表 -> 上传素材 -> 点击发布按钮 -> 等待发布成功

各平台发布按钮选择器和成功判定已内置（不再依赖 SYNAPSE_SRC_DIR）。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from app.integrations.synapse_engine.platforms.base import (
    LoginResult,
    LoginStatus,
    PlatformAdapter,
    QRCodeData,
    UserInfo,
)
from app.integrations.synapse_engine.platforms.codes import (
    PLATFORM_AUTH_COOKIE_NAMES,
    PLATFORM_LOGIN_URLS,
    PLATFORM_NAMES,
    PLATFORM_PUBLISH_URLS,
)

logger = logging.getLogger(__name__)


# 各平台发布按钮选择器（按优先级排列，第一个命中的就用）
# 这些选择器来自原 SynapseAutomation 项目 platforms/<platform>/upload.py 的真实实现
_PLATFORM_PUBLISH_BUTTON_SELECTORS: dict[str, list[str]] = {
    "douyin": [
        'button:has-text("发布")',
        'button[class*="primary"][class*="fixed"]',
        "div.publish-btn",
        '.publish-content-btn [class*="publish"]',
    ],
    "xiaohongshu": [
        'button:has-text("发布")',
        "div.publishBtn",
        ".publish-content .btn",
    ],
    "kuaishou": [
        'button:has-text("发布")',
        'button:has-text("发布作品")',
        ".publish-btn",
        'div[class*="publish"] button',
    ],
    "bilibili": [
        'button:has-text("立即投稿")',
        'button:has-text("发布")',
        '.submit-btn [class*="publish"]',
    ],
    "channels": [
        'button:has-text("发表")',
        'button:has-text("发布")',
        ".publish-btn",
    ],
}

# 各平台发布成功后的 URL 片段（用于判断发布是否成功）
_PLATFORM_SUCCESS_URL_PATTERNS: dict[str, list[str]] = {
    # Do not match the generic /creator-micro URL. The upload page itself is
    # also under /creator-micro and was previously producing false "published"
    # results when the sidebar "高清发布" button was clicked.
    "douyin": [
        r"creator-micro/content/manage",
        r"creator-micro/content/(?:video|article)/manage",
    ],
    "xiaohongshu": [
        r"publish/success",
        r"creator\.xiaohongshu\.com/publish/publish\?done",
        r"creator\.xiaohongshu\.com/publish/publish\?.*[?&]published=true(?:&|$)",
    ],
    "kuaishou": [r"cp\.kuaishou\.com/article/publish/success", r"article/manage"],
    "bilibili": [r"member\.bilibili\.com/platform/upload-manager"],
    "channels": [r"channels\.weixin\.qq\.com/platform/post/list"],
}

# 各平台标题输入框选择器（按优先级排列）
_PLATFORM_TITLE_SELECTORS: dict[str, list[str]] = {
    "douyin": [
        'input[placeholder*="标题"]',
        'textarea[placeholder*="标题"]',
        'div[contenteditable="true"].ace-editor',
    ],
    "xiaohongshu": [
        'div[contenteditable="true"][placeholder*="标题"]',
        'input[placeholder*="标题"]',
        ".title input",
    ],
    "kuaishou": [
        'input[placeholder*="标题"]',
        'textarea[placeholder*="标题"]',
        ".title-input input",
    ],
    "bilibili": [
        ".input-title textarea",
        'textarea[placeholder*="标题"]',
        'input[placeholder*="标题"]',
    ],
    "channels": [
        'textarea[placeholder*="标题"]',
        'input[placeholder*="标题"]',
        ".title-input input",
    ],
}

# 各平台正文/描述选择器
_PLATFORM_BODY_SELECTORS: dict[str, list[str]] = {
    "douyin": [
        'div.editor-comp-publish[contenteditable="true"]',
        'div.zone-container[contenteditable="true"]',
        '[class*="editor-comp-publish"][contenteditable="true"]',
        'textarea[placeholder*="描述"]',
        '[contenteditable="true"]',
    ],
    "xiaohongshu": [
        'div[contenteditable="true"][placeholder*="正文"]',
        'div[contenteditable="true"][placeholder*="描述"]',
        ".desc-input [contenteditable]",
    ],
    "kuaishou": [
        "#work-description-edit",
        'textarea[placeholder*="描述"]',
        'div[contenteditable="true"]',
    ],
    "bilibili": [
        '.ql-editor[contenteditable="true"]',
        'textarea[placeholder*="简介"]',
        'div[contenteditable="true"]',
    ],
    "channels": [
        'textarea[placeholder*="描述"]',
        'div[contenteditable="true"]',
    ],
}

# 各平台文件上传 input 选择器
_PLATFORM_FILE_INPUT_SELECTORS: dict[str, list[str]] = {
    "douyin": ['input[type="file"][accept*="video"]', 'input[type="file"]'],
    "xiaohongshu": [
        'input[type="file"][accept*="image"]',
        'input[type="file"][accept*="video"]',
        'input[type="file"]',
    ],
    "kuaishou": ['input[type="file"][accept*="video"]', 'input[type="file"]'],
    "bilibili": ['input[type="file"][accept*="video"]', 'input[type="file"]'],
    "channels": ['input[type="file"][accept*="video"]', 'input[type="file"]'],
}


class BuiltinPlatformAdapter(PlatformAdapter):
    """通用内置平台适配器。

    使用 Playwright 驱动浏览器：
    - 网页登录：打开真实登录页 -> 用户直接操作 -> 轮询登录态
    - 发布内容：加载 storage_state -> 打开发布页 -> 填表 -> 上传素材 -> 点击发布按钮 -> 等待发布成功
    """

    def __init__(self, platform: str, config: dict | None = None):
        self.platform = (platform or "").strip().lower()
        self.config = config or {}
        self.login_url = PLATFORM_LOGIN_URLS.get(self.platform, "")
        self.publish_url = PLATFORM_PUBLISH_URLS.get(self.platform, "")
        self.platform_name = PLATFORM_NAMES.get(self.platform, self.platform)
        # session_id -> {page, context, browser, created_at, last_status}
        self._sessions: dict[str, dict[str, Any]] = {}
        # ===== 验证码/人机验证相关 =====
        # 总开关读取一次即可；运行期改配置需重启 worker
        from app.core.config import get_settings as _get_settings
        self._verification_enabled = bool(
            _get_settings().SYNAPSE_VERIFICATION_ENABLED
        )
        # 远程 CDP 连接地址（人机验证场景下由外部注入）；None 表示用本地 headless
        self._remote_cdp_url: str | None = None
        # 宿主机原生 Chrome 已有一个真实的持久化上下文和可见页面。登录时
        # 复用它才能保持单窗口体验；发布时创建带 storage_state 的隔离上下文。
        self._remote_reuse_default_context = False
        # 当前发布任务上下文（task_id 经 contextvar 传入，account_id 来自 publish_content）
        # 供 _handle_verification_during_publish 调用 verification_manager 使用
        self._current_task_id: str | None = None
        self._current_account_id: str | None = None
        # 发布运行在 Mac 宿主 Chrome 时由 service 注入。自动化阶段窗口保持
        # 隐藏，检测到短信/滑块/安全验证后显示同一个页面供用户操作。
        self._native_publish_session_id: str | None = None
        self._last_verification_check_failed = False

    def set_remote_cdp_url(
        self,
        cdp_url: str | None,
        *,
        reuse_default_context: bool = False,
    ) -> None:
        """让后续浏览器操作接管远程可视 Chromium。"""
        self._remote_cdp_url = (cdp_url or "").strip() or None
        self._remote_reuse_default_context = bool(reuse_default_context)

    def set_native_publish_session(self, session_id: str | None) -> None:
        self._native_publish_session_id = (session_id or "").strip() or None

    async def _launch_browser(
        self, headless: bool | None = None, storage_state: dict | None = None
    ):
        """启动浏览器并返回 (browser, context)。"""
        from app.core.config import get_settings
        from app.integrations.synapse_engine.utils.playwright_provider import (
            PlaywrightBrowserMissingError,
            async_playwright,
            friendly_playwright_error,
            is_playwright_browser_missing_error,
            resolve_chromium_executable,
        )

        settings = get_settings()
        headless = (
            settings.SYNAPSE_PLAYWRIGHT_HEADLESS if headless is None else headless
        )

        pw = await async_playwright().start()

        # ===== 远程 CDP 模式（宿主真实 Chrome 或兼容 browser-vnc）=====
        # 当 self._remote_cdp_url 被设置时，直接 connect_over_cdp 远程浏览器，跳过本地 launch。
        # 注意：connect_over_cdp 后不要调 browser.close()，否则会杀掉远端 Chromium 进程
        # （_close_browser 会判断 _synapse_remote 标记，只断开 pw 连接）。
        if self._remote_cdp_url:
            try:
                browser = await pw.chromium.connect_over_cdp(
                    self._remote_cdp_url,
                    # native publish 的素材位于 Mac/容器同路径 bind mount。
                    # 标记 collocated 后可直接交给 Chrome，绕过远程 CDP
                    # 合计 50MiB 的 buffer 传输上限。
                    is_local=bool(self._native_publish_session_id),
                )
            except Exception as exc:
                try:
                    await pw.stop()
                except Exception:
                    pass
                raise RuntimeError(
                    f"连接远程 CDP 浏览器失败 ({self._remote_cdp_url}): {exc}"
                ) from exc
            if self._remote_reuse_default_context and browser.contexts:
                context = browser.contexts[0]
            else:
                context_kwargs: dict[str, Any] = {
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    ),
                    "viewport": {"width": 1280, "height": 800},
                    "locale": "zh-CN",
                    "timezone_id": "Asia/Shanghai",
                    "ignore_https_errors": True,
                }
                if storage_state:
                    context_kwargs["storage_state"] = storage_state
                context = await browser.new_context(**context_kwargs)
            # 标记为远程连接：_close_browser 只断开 pw，不调 browser.close()
            browser._synapse_pw = pw  # type: ignore[attr-defined]
            browser._synapse_remote = True  # type: ignore[attr-defined]
            return browser, context

        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--lang=zh-CN",
            ],
        }
        try:
            # Always pass an explicit executable_path. This prevents Playwright
            # from defaulting to a missing chromium_headless_shell when the
            # Docker image only contains chromium-*/chrome.
            launch_kwargs["executable_path"] = resolve_chromium_executable(
                settings.SYNAPSE_LOCAL_CHROME_PATH,
                headless=headless,
                allow_regular_fallback=True,
            )
        except PlaywrightBrowserMissingError:
            try:
                await pw.stop()
            except Exception:
                pass
            raise

        # 代理策略：显式代理优先；否则默认强制直连，绕过未启动的系统代理
        # 直连必须同时给 --proxy-server=direct:// 与 --proxy-bypass-list=*，
        # 仅靠 proxy={"server":"direct://"} 或 --no-proxy-server 在存在系统代理时无效。
        browser_proxy = (settings.SYNAPSE_BROWSER_PROXY or "").strip()
        if browser_proxy:
            launch_kwargs["proxy"] = {"server": browser_proxy}
        elif settings.SYNAPSE_BROWSER_NO_PROXY:
            launch_kwargs.setdefault("args", []).extend(
                ["--proxy-server=direct://", "--proxy-bypass-list=*"]
            )

        try:
            browser = await pw.chromium.launch(**launch_kwargs)
        except Exception as exc:
            try:
                await pw.stop()
            except Exception:
                pass
            if is_playwright_browser_missing_error(exc):
                raise PlaywrightBrowserMissingError(
                    friendly_playwright_error(exc)
                ) from exc
            raise
        context_kwargs: dict[str, Any] = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 800},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "ignore_https_errors": True,
        }
        if storage_state:
            context_kwargs["storage_state"] = storage_state
        context = await browser.new_context(**context_kwargs)
        # 登录二维码页只需要页面主体和二维码本身。字体、音视频等重资源会拖慢
        # 抖音/视频号首屏，且不影响二维码识别；发布/校验带 storage_state 的
        # 上下文不启用拦截，避免影响视频上传预览。
        if not storage_state:
            try:

                async def _light_login_route(route):
                    if route.request.resource_type in {"font", "media"}:
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", _light_login_route)
            except Exception:
                pass
        # 把 pw 挂到 browser 上方便后续 stop；标记为本地启动（_close_browser 会关闭）
        browser._synapse_pw = pw  # type: ignore[attr-defined]
        browser._synapse_remote = False  # type: ignore[attr-defined]
        return browser, context

    async def _close_browser(self, browser) -> None:
        pw = getattr(browser, "_synapse_pw", None)
        # 远程 CDP 模式：只断开 playwright 连接，绝不调 browser.close()
        # （关掉会杀掉宿主 Chrome / 兼容远端 Chromium）
        if getattr(browser, "_synapse_remote", False):
            if pw is not None:
                try:
                    await pw.stop()
                except Exception:
                    pass
            return
        try:
            await browser.close()
        except Exception:
            pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass

    @staticmethod
    def _is_transient_navigation_error(exc: Exception | str) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in (
                "err_name_not_resolved",
                "err_timed_out",
                "err_connection_timed_out",
                "err_connection_reset",
                "err_connection_closed",
                "err_network_changed",
                "err_http2_protocol_error",
                "net::",
                "timeout",
            )
        )

    async def _goto_with_retries(
        self,
        page,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ):
        """Navigate with retries for flaky Docker DNS/network failures."""
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                return await page.goto(url, wait_until=wait_until, timeout=timeout)
            except Exception as exc:
                last_exc = exc
                if not self._is_transient_navigation_error(exc) or attempt >= 3:
                    break
                logger.warning(
                    "%s navigation failed on attempt %s/3, retrying: %s",
                    self.platform,
                    attempt,
                    exc,
                )
                await asyncio.sleep(1.5 * attempt)
        assert last_exc is not None
        raise last_exc

    async def get_qrcode(self) -> QRCodeData:
        """打开登录页，截屏整个页面作为二维码图返回。"""
        if not self.login_url:
            raise RuntimeError(f"平台 {self.platform} 未配置登录页 URL")

        session_id = uuid.uuid4().hex
        browser, context = await self._launch_browser(headless=True)
        page = await context.new_page()
        response_qr_future: asyncio.Future[dict[str, Any]] | None = None
        douyin_qr_state: dict[str, Any] | None = None

        # Douyin's QR is returned by an XHR several seconds before the React
        # login widget finishes rendering the visible <img>. Capture that
        # response directly; it cuts startup time and avoids flaky DOM waits.
        # The same page keeps polling check_qrconnect after scan. Keep that
        # state too because Douyin often does not navigate away from the login
        # URL immediately after mobile confirmation.
        if self.platform == "douyin":
            loop = asyncio.get_running_loop()
            response_qr_future = loop.create_future()
            douyin_qr_state = {}

            async def _capture_douyin_qr_response(resp) -> None:
                is_qr_response = "/passport/web/get_qrcode/" in resp.url
                is_status_response = "/passport/web/check_qrconnect/" in resp.url
                if not is_qr_response and not is_status_response:
                    return
                try:
                    text = await resp.text()
                    payload = json.loads(text)
                    data = payload.get("data") or {}
                    if is_qr_response:
                        qrcode = data.get("qrcode")
                        token = data.get("token")
                        if token:
                            douyin_qr_state["token"] = token
                        if (
                            qrcode
                            and response_qr_future
                            and not response_qr_future.done()
                        ):
                            response_qr_future.set_result(
                                {
                                    "qrcode": qrcode,
                                    "qr_url": data.get("qrcode_index_url")
                                    or self.login_url,
                                    "token": token,
                                }
                            )
                    elif is_status_response:
                        status = str(data.get("status") or "").strip().lower()
                        description = str(
                            data.get("description")
                            or data.get("desc")
                            or data.get("message")
                            or payload.get("message")
                            or ""
                        )
                        redirect_url = (
                            data.get("redirect_url")
                            or data.get("redirectUrl")
                            or data.get("url")
                            or payload.get("redirect_url")
                            or payload.get("redirectUrl")
                            or payload.get("url")
                        )
                        schema_url = data.get("schema") or payload.get("schema")
                        ticket = (
                            data.get("ticket")
                            or data.get("auth_ticket")
                            or data.get("login_ticket")
                            or payload.get("ticket")
                            or payload.get("auth_ticket")
                            or payload.get("login_ticket")
                        )
                        token = data.get("token") or payload.get("token")
                        if status:
                            douyin_qr_state["status"] = status
                        if description:
                            douyin_qr_state["description"] = description
                        if redirect_url:
                            douyin_qr_state["redirect_url"] = str(redirect_url)
                        if schema_url:
                            douyin_qr_state["schema"] = str(schema_url)
                        if ticket:
                            douyin_qr_state["ticket"] = str(ticket)
                        if token:
                            douyin_qr_state["check_token"] = str(token)
                        # These fields describe the current check response. Do
                        # not keep them sticky: after the user completes a
                        # challenge, the next response no longer contains the
                        # verification payload and may legitimately confirm.
                        douyin_qr_state["has_user_info"] = bool(
                            data.get("user_info") or payload.get("user_info")
                        )
                        verify_fields = (
                            "verify_ways",
                            "pack_verify_way",
                            "captcha",
                            "verify_scene_desc",
                        )
                        douyin_qr_state["verification_required"] = any(
                            bool(data.get(key) or payload.get(key))
                            for key in verify_fields
                        )
                        douyin_qr_state.update(
                            {
                                "error_code": data.get("error_code"),
                                "updated_at": time.time(),
                                "last_payload_keys": sorted(
                                    set(data.keys()) | set(payload.keys())
                                ),
                            }
                        )
                except Exception as exc:
                    if (
                        is_qr_response
                        and response_qr_future
                        and not response_qr_future.done()
                    ):
                        response_qr_future.set_exception(exc)
                    else:
                        logger.debug("capture douyin QR status failed: %s", exc)

            page.on(
                "response",
                lambda resp: asyncio.create_task(_capture_douyin_qr_response(resp)),
            )

        try:
            await self._goto_with_retries(
                page,
                self.login_url,
                wait_until="commit"
                if self.platform == "douyin"
                else "domcontentloaded",
                timeout=60000,
            )
            qr_url = self.login_url
            qr_base64 = ""
            if response_qr_future is not None:
                try:
                    payload = await asyncio.wait_for(response_qr_future, timeout=12000)
                    qr_base64 = str(payload.get("qrcode") or "")
                    qr_url = str(payload.get("qr_url") or self.login_url)
                except Exception as exc:
                    logger.warning(
                        "douyin fast QR response capture failed, falling back to DOM: %s",
                        exc,
                    )

            if not qr_base64:
                # Avoid waiting for full network-idle; Douyin/Channels keep background
                # requests open. The QR is available much earlier.
                await asyncio.sleep(
                    0.8 if self.platform in {"douyin", "kuaishou", "bilibili"} else 1.5
                )
                await self._reveal_qrcode(page)
                await self._wait_for_qrcode_candidate(page, timeout=12000)
                screenshot = await self._capture_qrcode(page)
                qr_base64 = base64.b64encode(screenshot).decode("ascii")
        except Exception as e:
            await self._close_browser(browser)
            raise RuntimeError(f"获取 {self.platform} 登录二维码失败: {e}") from e

        try:
            auth_cookie_names = await self._auth_cookie_names(context)
        except Exception:
            auth_cookie_names = set()

        self._sessions[session_id] = {
            "browser": browser,
            "context": context,
            "page": page,
            "created_at": time.time(),
            "last_status": LoginStatus.WAITING,
            "cookies": None,
            "douyin_qr_state": douyin_qr_state,
            "auth_cookie_names": auth_cookie_names,
        }

        return QRCodeData(
            session_id=session_id,
            qr_url=qr_url,
            qr_image=f"data:image/png;base64,{qr_base64}",
            expires_in=300,
        )

    async def start_visual_login(self) -> QRCodeData:
        """打开真实平台登录页，不抓取二维码、短信码或验证页面。

        页面始终运行在 browser-vnc 的可视 Chromium 中，用户可在同一页面
        完成扫码、密码、短信、滑块和安全确认。后台只观察登录态并在成功后
        保存整个 Playwright storage_state。
        """
        if not self.login_url:
            raise RuntimeError(f"平台 {self.platform} 未配置登录页 URL")
        if not self._remote_cdp_url:
            raise RuntimeError("可视登录浏览器未就绪，请检查 browser-vnc 服务")

        session_id = uuid.uuid4().hex
        browser, context = await self._launch_browser(headless=False)
        if self._remote_reuse_default_context and context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()

        # 可视登录页必须保持平台原始行为。二维码旧流程为了提速屏蔽了字体/
        # 媒体资源；人工验证可能依赖这些资源，因此在这里取消全部路由拦截。
        try:
            await context.unroute("**/*")
        except Exception:
            pass

        try:
            await self._goto_with_retries(
                page,
                self.login_url,
                wait_until=(
                    "commit"
                    if self.platform in {"douyin", "channels"}
                    else "domcontentloaded"
                ),
                timeout=60000,
            )
        except Exception as exc:
            try:
                await context.close()
            except Exception:
                pass
            await self._close_browser(browser)
            raise RuntimeError(
                f"打开 {self.platform_name} 登录网页失败: {exc}"
            ) from exc

        try:
            auth_cookie_names = await self._auth_cookie_names(context)
        except Exception:
            auth_cookie_names = set()

        self._sessions[session_id] = {
            "browser": browser,
            "context": context,
            "page": page,
            "created_at": time.time(),
            "last_status": LoginStatus.WAITING,
            "cookies": None,
            "douyin_qr_state": {},
            "auth_cookie_names": auth_cookie_names,
            "visual_login": True,
        }
        return QRCodeData(
            session_id=session_id,
            qr_url=self.login_url,
            qr_image="",
            expires_in=300,
        )

    async def _reveal_qrcode(self, page) -> None:
        """Best-effort switch from password/SMS login to QR login."""
        # Kuaishou renders the real switch as a 40x40 div. Its adjacent
        # "扫码登录" tooltip is a different element; clicking the tooltip does
        # not switch modes, which previously caused a full-page screenshot to
        # be returned instead of a QR code.
        if self.platform == "kuaishou":
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    qrcode = page.locator('.qrcode img, [class*="qrcode"] img').first
                    if await qrcode.count() > 0 and await qrcode.is_visible():
                        return
                    switch = page.locator(
                        '.platform-switch, [class~="platform-switch"]'
                    ).first
                    if await switch.count() > 0 and await switch.is_visible():
                        await switch.click(timeout=3000, force=True)
                        await page.locator(
                            '.qrcode img, [class*="qrcode"] img'
                        ).first.wait_for(
                            state="visible",
                            timeout=10000,
                        )
                        return
                except Exception as exc:
                    logger.debug("kuaishou switch-to-QR attempt failed: %s", exc)
                await asyncio.sleep(0.25)

        text_keywords = (
            "\u626b\u7801\u767b\u5f55",  # ????
            "\u4e8c\u7ef4\u7801\u767b\u5f55",  # ?????
            "\u626b\u7801",  # ??
            "QR",
            "qrcode",
        )
        try:
            for kw in text_keywords:
                loc = page.get_by_text(kw, exact=False).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2000)
                    await asyncio.sleep(0.5)
                    return
        except Exception as e:
            logger.debug("%s switch-to-QR by text failed: %s", self.platform, e)

        # Generic DOM fallback: click a visible small tab/button whose text says
        # scan/QR. This helps when hashed class names change.
        try:
            clicked = await page.evaluate(
                """() => {
                  const kws = ['\\u626b\\u7801', '\\u4e8c\\u7ef4\\u7801', 'QR', 'qrcode'];
                  const els = [...document.querySelectorAll('button,a,div,span')].filter(el => {
                    const t = (el.innerText || el.textContent || '').trim();
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && r.width <= 360 && r.height <= 120 && kws.some(k => t.includes(k));
                  });
                  if (els.length) { els[0].click(); return true; }
                  return false;
                }"""
            )
            if clicked:
                await asyncio.sleep(0.5)
                return
        except Exception as e:
            logger.debug("%s switch-to-QR by DOM failed: %s", self.platform, e)

        # Xiaohongshu sometimes uses a small data-image corner switch icon
        # without useful text.
        if self.platform == "xiaohongshu":
            try:
                clicked = await page.evaluate(
                    """() => {
                      const imgs=[...document.querySelectorAll('img')].filter(el=>{
                        const r=el.getBoundingClientRect();
                        return r.width>=50&&r.width<=90&&r.x>900&&r.y<280&&(el.src||'').startsWith('data:');
                      });
                      if(imgs.length){imgs[0].click();return true;}
                      return false;
                    }"""
                )
                if clicked:
                    await asyncio.sleep(0.8)
            except Exception as e:
                logger.debug("xiaohongshu QR icon switch failed: %s", e)

    # QR element selectors: include generic data-image/img because some
    # platforms (notably Xiaohongshu) render the QR with hashed CSS classes.
    _QR_ELEMENT_SELECTORS = [
        ".qrcode img",
        ".qrcode-img img",
        '[class*="qrcode"] img',
        '[class*="qrcode"] canvas',
        '[class*="qr-code"] img',
        '[class*="qr-code"] canvas',
        'img[alt*="qrcode" i]',
        'img[alt*="scan" i]',
        'img[src*="qr"]',
        'img[src^="data:image"]',
        'img[src^="blob:"]',
        "canvas",
        "img",
    ]

    @staticmethod
    async def _data_image_bytes(locator) -> bytes | None:
        """If locator is a base64 data-image <img>, return original image bytes."""
        try:
            tag = (await locator.evaluate("el => el.tagName") or "").lower()
            if tag != "img":
                return None
            src = await locator.get_attribute("src")
            if not src or not src.startswith("data:image") or ";base64," not in src:
                return None
            return base64.b64decode(src.split(",", 1)[1], validate=False)
        except (binascii.Error, Exception):
            return None

    async def _wait_for_qrcode_candidate(self, page, timeout: int = 10000) -> None:
        """Wait briefly until a visible square-ish QR element exists."""
        deadline = time.time() + max(timeout, 1000) / 1000
        while time.time() < deadline:
            try:
                for frame in page.frames:
                    for sel in self._QR_ELEMENT_SELECTORS:
                        locs = frame.locator(sel)
                        count = min(await locs.count(), 12)
                        for idx in range(count):
                            loc = locs.nth(idx)
                            if not await loc.is_visible(timeout=300):
                                continue
                            box = await loc.bounding_box(timeout=300)
                            if not box:
                                continue
                            w = float(box.get("width", 0) or 0)
                            h = float(box.get("height", 0) or 0)
                            if 90 <= w <= 560 and 90 <= h <= 560:
                                ratio = w / h if h else 0
                                if 0.70 <= ratio <= 1.42:
                                    return
            except Exception:
                pass
            await asyncio.sleep(0.35)

    async def _capture_qrcode(self, page) -> bytes:
        """Capture the actual QR image, not the whole login page screenshot.

        The previous fallback returned the complete login page, where the QR was
        too small to scan. We now scan the main page and all frames for visible
        square-ish img/canvas elements, prefer QR/data-image hints, and return
        the original data-image bytes when possible.
        """
        candidates: list[tuple[float, Any]] = []
        seen: set[tuple[int, int, int, int]] = set()
        for frame in page.frames:
            for sel in self._QR_ELEMENT_SELECTORS:
                try:
                    locs = frame.locator(sel)
                    count = min(await locs.count(), 20)
                    for idx in range(count):
                        loc = locs.nth(idx)
                        if not await loc.is_visible(timeout=1000):
                            continue
                        box = await loc.bounding_box(timeout=1000)
                        if not box:
                            continue
                        w = float(box.get("width", 0) or 0)
                        h = float(box.get("height", 0) or 0)
                        if w < 100 or h < 100 or w > 520 or h > 520:
                            continue
                        ratio = w / h if h else 0
                        if ratio < 0.72 or ratio > 1.38:
                            continue
                        key = (
                            round(box.get("x", 0)),
                            round(box.get("y", 0)),
                            round(w),
                            round(h),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        class_name = ""
                        src = ""
                        try:
                            class_name = (
                                await loc.get_attribute("class") or ""
                            ).lower()
                            src = (await loc.get_attribute("src") or "").lower()
                        except Exception:
                            pass
                        square_score = 1.0 - min(abs(1.0 - ratio), 1.0)
                        size_score = min(max(w, h) / 260.0, 1.0)
                        hint_score = 0.0
                        if (
                            "qr" in class_name
                            or "qrcode" in class_name
                            or "code" in class_name
                        ):
                            hint_score += 1.0
                        if src.startswith("data:image") or "qr" in src:
                            hint_score += 0.8
                        candidates.append(
                            (square_score * 2.0 + size_score + hint_score, loc)
                        )
                except Exception:
                    continue

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            best = candidates[0][1]
            raw = await self._data_image_bytes(best)
            if raw:
                return raw
            return await best.screenshot()

        if self.platform == "kuaishou":
            raise RuntimeError("快手登录二维码未加载，请检查网络后重试")
        return await page.screenshot(full_page=False)

    def _run_screenshot_dir(self, run_id: str) -> Path:
        """本次发布的截图目录：<SYNAPSE_STORAGE_DIR>/screenshots/<platform>/<run_id>。"""
        from app.core.config import get_settings

        base = (
            Path(get_settings().SYNAPSE_STORAGE_DIR)
            / "screenshots"
            / self.platform
            / run_id
        )
        base.mkdir(parents=True, exist_ok=True)
        return base

    async def _screenshot_step(
        self, page, run_dir: Path, label: str, shots: list[str]
    ) -> None:
        """对当前页面截图留痕（发布链路排错用），失败不影响主流程。"""
        try:
            path = run_dir / f"{int(time.time() * 1000)}_{label}.png"
            await asyncio.wait_for(
                page.screenshot(path=str(path), full_page=False), timeout=8
            )
            shots.append(str(path))
        except Exception as e:
            logger.warning("%s 截图 %s 失败: %s", self.platform, label, e)

    async def _evaluate_with_timeout(
        self, page, script: str, arg: Any = None, timeout: int = 8
    ) -> Any:
        """Run page.evaluate with a hard timeout.

        Some creator pages (notably Douyin after video upload) keep the main
        thread busy for a long time. A naked ``page.evaluate`` can block the
        worker indefinitely, leaving the publish task in ``running``. Keep all
        non-essential DOM probing bounded so a failed selector becomes a normal
        publish_error instead of a stuck Celery process.
        """
        coro = page.evaluate(script) if arg is None else page.evaluate(script, arg)
        return await asyncio.wait_for(coro, timeout=timeout)

    def _extract_post_id(self, url: str) -> str | None:
        """尽力从发布成功后的 URL 中解析平台内容 ID（解析不到返回 None，不伪造）。"""
        if not url:
            return None
        patterns = [
            r"[?&](?:note_id|noteId|photoId|aweme_id|bvid|vid|aid|id)=([A-Za-z0-9_-]{6,})",
            r"/(?:note|item|video|detail|explore|short-video)/([A-Za-z0-9_-]{8,})",
            r"/(BV[A-Za-z0-9]{8,})",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    def _canonical_content_url(self, content_id: str | None) -> str | None:
        """Build a public content URL from a platform id when the creator page exposes only an id."""
        if not content_id:
            return None
        cid = str(content_id).strip()
        if not cid:
            return None
        if self.platform == "xiaohongshu":
            return f"https://www.xiaohongshu.com/explore/{cid}"
        if self.platform == "douyin":
            return f"https://www.douyin.com/video/{cid}"
        if self.platform == "bilibili":
            return f"https://www.bilibili.com/video/{cid}"
        if self.platform == "kuaishou":
            return f"https://www.kuaishou.com/short-video/{cid}"
        return None

    def _is_content_url(self, url: str | None) -> bool:
        if not url:
            return False
        patterns = {
            "xiaohongshu": r"xiaohongshu\.com/(?:explore|discovery/item)/[A-Za-z0-9_-]{8,}",
            "douyin": r"douyin\.com/(?:video|note)/[A-Za-z0-9_-]{8,}",
            "bilibili": r"bilibili\.com/video/BV[A-Za-z0-9]{8,}",
            "kuaishou": r"kuaishou\.com/(?:short-video|fw/photo)/[A-Za-z0-9_-]{8,}",
        }
        pat = patterns.get(self.platform)
        return bool(pat and re.search(pat, url))

    def _is_creator_manage_url(self, url: str | None) -> bool:
        if not url:
            return False
        return any(
            token in url
            for token in (
                "creator",
                "member.bilibili.com",
                "upload-manager",
                "content/manage",
                "publish",
            )
        )

    async def _extract_douyin_manager_post(
        self, page, title: str | None = None
    ) -> dict | None:
        """Read Douyin creator-manager React card data for the matching post."""
        title_norm = re.sub(r"\s+", "", title or "").lower()
        try:
            hit = await self._evaluate_with_timeout(
                page,
                """(targetNorm) => {
                  const norm = (s) => String(s || '').replace(/\\s+/g, '').toLowerCase();
                  const seen = new Set();
                  const hits = [];
                  const interesting = /aweme|item|video|opus|id|title|desc|share|stat|status|data/i;
                  const read = (obj, fallbackText = '') => {
                    if (!obj || typeof obj !== 'object' || seen.has(obj)) return;
                    seen.add(obj);
                    let keys = [];
                    try { keys = Object.keys(obj); } catch { return; }
                    const awemeId = obj.aweme_id || obj.awemeId || obj.item_id || obj.itemId || obj.group_id;
                    const itemTitle = obj.item_title || obj.title || '';
                    const desc = obj.desc || obj.description || '';
                    const shareUrl = obj.share_url || obj.shareUrl || obj.share_info?.share_url || '';
                    if (awemeId && (itemTitle || desc || fallbackText || shareUrl)) {
                      const hay = norm([itemTitle, desc, fallbackText].join(' '));
                      const score = targetNorm && hay.includes(targetNorm) ? 100 : 10;
                      hits.push({
                        score,
                        aweme_id: String(awemeId),
                        item_title: String(itemTitle || ''),
                        desc: String(desc || ''),
                        share_url: String(shareUrl || '')
                      });
                    }
                    for (const key of keys.slice(0, 100)) {
                      if (!interesting.test(key) && !['props', 'memoizedProps', 'pendingProps', 'memoizedState', 'stateNode', 'return', 'child', 'sibling', 'data', 'list', 'items'].includes(key)) continue;
                      try { read(obj[key], fallbackText); } catch {}
                    }
                  };
                  const cards = [...document.querySelectorAll('[class*=video-card], [class*=card], [class*=item]')];
                  for (const card of cards) {
                    const text = card.innerText || card.textContent || '';
                    if (targetNorm && !norm(text).includes(targetNorm)) continue;
                    const fiberKey = Object.keys(card).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                    const propsKey = Object.keys(card).find(k => k.startsWith('__reactProps$'));
                    if (fiberKey) read(card[fiberKey], text);
                    if (propsKey) read(card[propsKey], text);
                  }
                  hits.sort((a, b) => b.score - a.score);
                  return hits[0] || null;
                }""",
                title_norm,
                timeout=12,
            )
            if hit and hit.get("aweme_id"):
                cid = str(hit.get("aweme_id"))
                return {
                    "external_post_id": cid,
                    "publish_url": hit.get("share_url")
                    or self._canonical_content_url(cid),
                }
        except Exception as exc:
            logger.debug(
                "%s Douyin manager card extraction failed: %s", self.platform, exc
            )
        return None

    async def _extract_xhs_manager_post(
        self, page, title: str | None = None
    ) -> dict | None:
        """Read Xiaohongshu creator note-manager API for the matching note."""
        title_norm = re.sub(r"\s+", "", title or "").lower()
        try:
            hit = await self._evaluate_with_timeout(
                page,
                """async (targetNorm) => {
                  const norm = (s) => String(s || '').replace(/\\s+/g, '').toLowerCase();
                  const urls = [
                    '/api/galaxy/v2/creator/note/user/posted?tab=0&page=0',
                    '/api/galaxy/creator/home/latest_note_data'
                  ];
                  const hits = [];
                  for (const url of urls) {
                    try {
                      const res = await fetch(url, {credentials: 'include'});
                      const data = await res.json();
                      const notes = [];
                      if (Array.isArray(data?.data?.notes)) notes.push(...data.data.notes);
                      if (data?.data?.noteInfo) notes.push(data.data.noteInfo);
                      for (const note of notes) {
                        const id = note.id || note.note_id || note.noteId;
                        const title = note.display_title || note.title || note.desc || '';
                        const desc = note.desc || '';
                        if (!id) continue;
                        const hay = norm([title, desc].join(' '));
                        const score = targetNorm && hay.includes(targetNorm) ? 100 : 10;
                        hits.push({score, id: String(id), title: String(title || ''), desc: String(desc || '')});
                      }
                    } catch {}
                  }
                  hits.sort((a, b) => b.score - a.score);
                  if (targetNorm && (!hits.length || hits[0].score < 100)) return null;
                  return hits[0] || null;
                }""",
                title_norm,
                timeout=12,
            )
            if hit and hit.get("id"):
                cid = str(hit.get("id"))
                return {
                    "external_post_id": cid,
                    "publish_url": self._canonical_content_url(cid),
                }
        except Exception as exc:
            logger.debug(
                "%s Xiaohongshu manager API extraction failed: %s", self.platform, exc
            )
        return None

    def _extract_kuaishou_manager_post(
        self, payloads: list[dict], title: str | None = None
    ) -> dict | None:
        """Extract a matching work from captured Kuaishou work-list responses."""
        title_norm = re.sub(r"\s+", "", title or "").lower()
        hits: list[tuple[int, dict]] = []
        for payload in payloads or []:
            works = ((payload or {}).get("data") or {}).get("list") or []
            for work in works:
                content_id = (
                    work.get("workId") or work.get("photoId") or work.get("photo_id")
                )
                if not content_id:
                    continue
                work_title = str(work.get("title") or "")
                work_norm = re.sub(r"\s+", "", work_title).lower()
                score = 100 if title_norm and title_norm in work_norm else 10
                hits.append((score, work))
        hits.sort(key=lambda item: item[0], reverse=True)
        if not hits or (title_norm and hits[0][0] < 100):
            return None
        work = hits[0][1]
        content_id = str(
            work.get("workId") or work.get("photoId") or work.get("photo_id")
        )
        return {
            "external_post_id": content_id,
            "publish_url": self._canonical_content_url(content_id),
            "metrics": {
                "play_count": work.get("playCount"),
                "comment_count": work.get("commentCount"),
                "like_count": work.get("likeCount"),
            },
        }

    async def _resolve_post_url_after_publish(
        self, page, title: str | None = None
    ) -> str | None:
        """After a successful submit, try to resolve the public post URL from the manager page.

        Creator pages often redirect to a management list instead of the public
        post. This scans anchors and embedded page data for a real content id so
        the admin can click the published item directly.
        """
        if self._is_content_url(page.url):
            return page.url

        title_norm = re.sub(r"\s+", "", title or "").lower()
        if self.platform == "bilibili":
            try:
                await page.goto(
                    "https://member.bilibili.com/platform/upload-manager/article",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await asyncio.sleep(4)
                await self._dismiss_popups(page)
            except Exception as exc:
                logger.debug(
                    "%s open Bilibili upload manager failed: %s", self.platform, exc
                )
        elif self.platform == "xiaohongshu":
            try:
                await page.goto(
                    "https://creator.xiaohongshu.com/new/note-manager",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(5)
                await self._dismiss_popups(page)
                xhs_post = await self._extract_xhs_manager_post(page, title=title)
                if xhs_post and xhs_post.get("publish_url"):
                    return xhs_post["publish_url"]
            except Exception as exc:
                logger.debug(
                    "%s open Xiaohongshu note manager failed: %s", self.platform, exc
                )
        elif self.platform == "douyin":
            try:
                await page.goto(
                    "https://creator.douyin.com/creator-micro/content/manage",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(6)
                await self._dismiss_popups(page)
                douyin_post = await self._extract_douyin_manager_post(page, title=title)
                if douyin_post and douyin_post.get("publish_url"):
                    return douyin_post["publish_url"]
            except Exception as exc:
                logger.debug(
                    "%s open Douyin content manager failed: %s", self.platform, exc
                )
        elif self.platform == "kuaishou":
            payloads: list[dict] = []

            async def capture_work_list(response) -> None:
                if "/rest/cp/works/v2/video/pc/photo/list" not in response.url:
                    return
                try:
                    payload = await response.json()
                    if isinstance(payload, dict):
                        payloads.append(payload)
                except Exception:
                    pass

            try:
                page.on("response", capture_work_list)
                await page.goto(
                    "https://cp.kuaishou.com/article/manage/video?status=0&from=publish",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(8)
                await self._dismiss_popups(page)
                kuaishou_post = self._extract_kuaishou_manager_post(
                    payloads, title=title
                )
                if kuaishou_post and kuaishou_post.get("publish_url"):
                    return kuaishou_post["publish_url"]
            except Exception as exc:
                logger.debug(
                    "%s open Kuaishou content manager failed: %s", self.platform, exc
                )
            finally:
                try:
                    page.remove_listener("response", capture_work_list)
                except Exception:
                    pass
        href_patterns = {
            "xiaohongshu": r"https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/[A-Za-z0-9_-]{8,}",
            "douyin": r"https?://(?:www\.)?douyin\.com/(?:video|note)/[A-Za-z0-9_-]{8,}",
            "bilibili": r"https?://(?:www\.)?bilibili\.com/video/BV[A-Za-z0-9]{8,}",
            "kuaishou": r"https?://(?:www\.)?kuaishou\.com/(?:short-video|fw/photo)/[A-Za-z0-9_-]{8,}",
        }
        id_patterns = {
            "xiaohongshu": [r'"(?:noteId|note_id|id)"\s*:\s*"([A-Za-z0-9_-]{16,})"'],
            "douyin": [
                r'"(?:aweme_id|item_id|itemId)"\s*:\s*"([0-9]{12,})"',
                r"/video/([0-9]{12,})",
            ],
            "bilibili": [r"(BV[A-Za-z0-9]{8,})"],
            "kuaishou": [r'"(?:workId|photoId|photo_id)"\s*:\s*"([A-Za-z0-9_-]{8,})"'],
        }

        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                links = await self._evaluate_with_timeout(
                    page,
                    """() => [...document.querySelectorAll('a[href]')].map(a => ({
                      href: a.href || '',
                      text: (a.innerText || a.textContent || '').trim()
                    })).filter(x => x.href)""",
                    timeout=8,
                )
                candidates: list[tuple[int, str]] = []
                for item in links or []:
                    href = str(item.get("href") or "")
                    text = str(item.get("text") or "")
                    if not self._is_content_url(href):
                        continue
                    score = 10
                    if title_norm and title_norm in re.sub(r"\s+", "", text).lower():
                        score += 100
                    candidates.append((score, href))
                if candidates:
                    candidates.sort(key=lambda x: x[0], reverse=True)
                    if (
                        self.platform == "bilibili"
                        and title_norm
                        and candidates[0][0] < 100
                    ):
                        await asyncio.sleep(1.5)
                        continue
                    return candidates[0][1]
            except Exception as exc:
                logger.debug(
                    "%s scan public links after publish failed: %s", self.platform, exc
                )

            try:
                html = await asyncio.wait_for(page.content(), timeout=8)
                href_pat = href_patterns.get(self.platform)
                if href_pat:
                    m = re.search(href_pat, html)
                    if m:
                        return m.group(0).replace("\\/", "/")
                for pat in id_patterns.get(self.platform, []):
                    m = re.search(pat, html)
                    if m:
                        canonical = self._canonical_content_url(m.group(1))
                        if canonical:
                            return canonical
            except Exception:
                pass
            await asyncio.sleep(1.5)
        return None

    @staticmethod
    def _map_douyin_qr_status(
        raw_status: str | None,
        description: str | None = None,
        body_text: str | None = None,
    ) -> tuple[LoginStatus | None, str]:
        """Map Douyin QR connect status/page text to the shared login status."""
        raw = str(raw_status or "").strip().lower()
        desc = str(description or "").strip()
        body = str(body_text or "")
        visible_text = f"{desc}\n{body}"

        if raw in {
            "confirmed",
            "confirm",
            "success",
            "ok",
            "authorized",
            "login",
            "logged_in",
        }:
            return LoginStatus.CONFIRMED, "登录成功"

        if raw in {"expired", "expire", "timeout"}:
            return LoginStatus.EXPIRED, "二维码已过期"

        if raw in {"cancel", "canceled", "cancelled", "failed", "fail"}:
            return LoginStatus.FAILED, "扫码登录失败或已取消"

        if raw in {"scanned", "scan", "scaned", "confirming"}:
            return LoginStatus.SCANNED, "已扫码，请在手机上确认登录"

        # Page text can still contain a stale success message while the API
        # explicitly says `scanned`. Use visible success text only when the API
        # did not provide a state at all.
        if not raw and any(
            token in visible_text for token in ("登录成功", "授权成功")
        ):
            return LoginStatus.CONFIRMED, "登录成功"

        if any(token in visible_text for token in ("二维码已过期", "已过期", "过期")):
            return LoginStatus.EXPIRED, "二维码已过期"

        if any(
            token in visible_text
            for token in ("已扫码", "扫码成功", "请在手机", "确认登录", "确认授权", "请确认")
        ):
            return LoginStatus.SCANNED, "已扫码，请在手机上确认登录"

        if "已取消" in visible_text:
            return LoginStatus.FAILED, "扫码登录失败或已取消"

        return None, ""

    async def _poll_douyin_qr_status(
        self, page, sess: dict[str, Any]
    ) -> tuple[LoginStatus | None, str]:
        state = sess.get("douyin_qr_state") or {}
        raw_status = state.get("status")
        description = state.get("description")
        try:
            body_text = await page.locator("body").inner_text(timeout=1500)
        except Exception:
            body_text = ""

        mapped_status, mapped_message = self._map_douyin_qr_status(
            raw_status, description, body_text
        )
        if state.get("verification_required"):
            status, message = LoginStatus.SCANNED, "已扫码，请在手机上完成确认或安全验证"
        elif mapped_status == LoginStatus.SCANNED:
            status, message = mapped_status, mapped_message
        elif mapped_status == LoginStatus.CONFIRMED:
            status, message = mapped_status, mapped_message
        elif self._is_browser_redirect_url(state.get("redirect_url")) or state.get(
            "ticket"
        ):
            status, message = LoginStatus.CONFIRMED, "登录成功"
        elif state.get("has_user_info"):
            status, message = LoginStatus.SCANNED, "已扫码，请在手机上完成确认或安全验证"
        else:
            status, message = mapped_status, mapped_message
        if status is None and sess.get("last_status") == LoginStatus.SCANNED:
            status = LoginStatus.SCANNED
            message = "已扫码，请在手机上确认登录"
        payload_keys = ",".join(state.get("last_payload_keys") or [])
        state_key = (
            f"{status.value if status else 'waiting'}:"
            f"{str(raw_status or '').strip().lower()}:{description or ''}:"
            f"{payload_keys}"
        )
        if state_key != sess.get("douyin_last_reported_qr_status"):
            sess["douyin_last_reported_qr_status"] = state_key
            if status is not None:
                logger.info(
                    "douyin QR login state changed: status=%s raw=%s keys=%s message=%s",
                    status.value,
                    raw_status or "",
                    payload_keys,
                    message,
                )
            elif raw_status:
                logger.debug(
                    "douyin QR login raw state: raw=%s keys=%s description=%s",
                    raw_status,
                    payload_keys,
                    description or "",
                )
        return status, message

    async def _auth_cookie_names(self, context) -> set[str]:
        auth_names = PLATFORM_AUTH_COOKIE_NAMES.get(self.platform, set())
        if not auth_names:
            return set()
        cookies = await context.cookies()
        return {
            str(cookie.get("name") or "")
            for cookie in cookies
            if cookie.get("name") in auth_names and cookie.get("value")
        }

    async def _has_new_auth_cookie(self, sess: dict[str, Any]) -> bool:
        current = await self._auth_cookie_names(sess["context"])
        baseline = set(sess.get("auth_cookie_names") or set())
        new_names = current - baseline
        if new_names:
            logger.info(
                "%s login auth cookie detected: %s",
                self.platform,
                ",".join(sorted(new_names)),
            )
            return True
        return False

    @staticmethod
    def _is_browser_redirect_url(url: Any) -> bool:
        value = str(url or "").strip()
        if not value:
            return False
        return value.startswith(("http://", "https://", "/"))

    def _is_visual_login_success_url(self, url: str) -> bool:
        """仅把明确的创作后台页面当作可视登录成功。

        安全验证页经常也会离开原始 login URL，不能沿用旧二维码流程的
        “URL 变化即成功”规则，否则窗口会在用户验证到一半时被关掉。
        """
        value = str(url or "").lower()
        if not value or any(
            token in value
            for token in (
                "login",
                "passport",
                "captcha",
                "verify",
                "verification",
                "challenge",
            )
        ):
            return False
        patterns = {
            "xiaohongshu": (
                r"creator\.xiaohongshu\.com/(?:$|new|home|publish|creator|note)",
            ),
            "channels": (r"channels\.weixin\.qq\.com/(?:$|platform/)",),
            "douyin": (
                r"creator\.douyin\.com/creator-micro/(?:$|home|content|account|publish)",
            ),
            "kuaishou": (
                r"(?:cp|creator)\.kuaishou\.com/(?:$|article|profile|home|content)",
            ),
            "bilibili": (r"member\.bilibili\.com/platform/",),
        }
        return any(
            re.search(pattern, value)
            for pattern in patterns.get(self.platform, ())
        )

    async def _follow_douyin_login_redirect(
        self, page, sess: dict[str, Any]
    ) -> None:
        state = sess.get("douyin_qr_state") or {}
        redirect_url = str(state.get("redirect_url") or "").strip()
        if not self._is_browser_redirect_url(redirect_url):
            return
        target = urljoin(page.url, redirect_url)
        if not target or target == page.url:
            return
        try:
            logger.info("douyin login redirect detected, opening redirect url")
            await self._goto_with_retries(
                page,
                target,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await asyncio.sleep(1.0)
        except Exception as exc:
            logger.warning("douyin login redirect follow failed: %s", exc)

    async def _confirmed_login_result(
        self, sess: dict[str, Any], page, message: str = "登录成功"
    ) -> LoginResult:
        context = sess["context"]
        cookies = await context.cookies()
        storage_state = await context.storage_state()
        sess["cookies"] = cookies
        sess["storage_state"] = storage_state
        sess["last_status"] = LoginStatus.CONFIRMED
        user_info = await self._extract_user_info(page)

        return LoginResult(
            status=LoginStatus.CONFIRMED,
            message=message or "登录成功",
            cookies=cookies,
            user_info=user_info,
            full_state=storage_state,
        )

    async def poll_status(self, session_id: str) -> LoginResult:
        sess = self._sessions.get(session_id)
        if not sess:
            return LoginResult(
                status=LoginStatus.EXPIRED,
                message="会话不存在或已过期",
                cookies=None,
                user_info=None,
            )

        # 超时检查（5 分钟过期）
        if time.time() - sess["created_at"] > 300:
            await self.cleanup_session(session_id)
            return LoginResult(
                status=LoginStatus.EXPIRED,
                message="二维码已过期",
                cookies=None,
                user_info=None,
            )

        page = sess.get("page")
        if page is None or page.is_closed():
            await self.cleanup_session(session_id)
            return LoginResult(
                status=LoginStatus.EXPIRED,
                message="浏览器页面已关闭",
                cookies=None,
                user_info=None,
            )

        try:
            current_url = page.url

            # 可视登录不依赖平台二维码接口或 DOM 结构。强认证 Cookie 一旦
            # 出现就说明真实浏览器已经完成登录，可立即保存会话并关闭窗口。
            if await self._has_new_auth_cookie(sess):
                return await self._confirmed_login_result(
                    sess, page, "登录成功"
                )

            if self.platform == "douyin":
                qr_status, qr_message = await self._poll_douyin_qr_status(page, sess)
                if qr_status == LoginStatus.CONFIRMED:
                    await self._follow_douyin_login_redirect(page, sess)
                    if self.platform == "douyin" and not await self._has_new_auth_cookie(
                        sess
                    ):
                        sess["last_status"] = LoginStatus.SCANNED
                        return LoginResult(
                            status=LoginStatus.SCANNED,
                            message="已扫码，请在手机上完成确认或安全验证",
                            cookies=None,
                            user_info=None,
                        )
                    return await self._confirmed_login_result(
                        sess, page, qr_message or "登录成功"
                    )
                if qr_status == LoginStatus.SCANNED and await self._has_new_auth_cookie(
                    sess
                ):
                    return await self._confirmed_login_result(
                        sess, page, "登录成功"
                    )
                if qr_status in {LoginStatus.SCANNED, LoginStatus.FAILED}:
                    sess["last_status"] = qr_status
                    return LoginResult(
                        status=qr_status,
                        message=qr_message,
                        cookies=None,
                        user_info=None,
                    )
                if qr_status == LoginStatus.EXPIRED:
                    await self.cleanup_session(session_id)
                    return LoginResult(
                        status=LoginStatus.EXPIRED,
                        message=qr_message or "二维码已过期",
                        cookies=None,
                        user_info=None,
                    )

            if sess.get("visual_login"):
                if self._is_visual_login_success_url(current_url):
                    return await self._confirmed_login_result(
                        sess, page, "登录成功"
                    )
            # 旧二维码适配器兼容：URL 变化（离开登录页）= 登录成功。
            elif (
                self.login_url
                and current_url != self.login_url
                and "login" not in current_url.lower()
            ):
                return await self._confirmed_login_result(sess, page, "登录成功")

            # 否则继续等待
            sess["last_status"] = LoginStatus.WAITING
            return LoginResult(
                status=LoginStatus.WAITING,
                message=(
                    "请在当前网页完成登录"
                    if sess.get("visual_login")
                    else "等待扫码"
                ),
                cookies=None,
                user_info=None,
            )
        except Exception as e:
            logger.warning("轮询 %s 登录态失败: %s", self.platform, e)
            return LoginResult(
                status=LoginStatus.WAITING,
                message=f"轮询异常: {e}",
                cookies=None,
                user_info=None,
            )

    async def _extract_user_info(self, page) -> UserInfo:
        """Extract account identity from the logged-in creator page."""
        extra: dict[str, Any] = {"url": page.url}
        try:
            if self.platform == "xiaohongshu":
                data = await page.evaluate(
                    """() => {
                      const parse = (v) => { try { return JSON.parse(v || '{}'); } catch (e) { return {}; } };
                      return parse(localStorage.getItem('USER_INFO_FOR_BIZ'));
                    }"""
                )
                uid = str(data.get("userId") or "")
                name = data.get("userName")
                avatar = data.get("userAvatar")
                red_id = str(data.get("redId") or "")
                extra.update(
                    {
                        "user_id": uid or None,
                        "red_id": red_id or None,
                        "role": data.get("role"),
                        "zone": data.get("zone"),
                        "real_name_verified": data.get("realNameVerified"),
                    }
                )
                return UserInfo(
                    user_id=uid or None,
                    name=name,
                    username=name,
                    avatar=avatar,
                    extra={k: v for k, v in extra.items() if v not in (None, "")},
                )

            if self.platform == "douyin":
                data = await page.evaluate(
                    """async () => {
                      const getJson = async (url) => {
                        try {
                          const r = await fetch(url, {credentials: 'include'});
                          return await r.json();
                        } catch (e) { return null; }
                      };
                      return {
                        pc: await getJson('/aweme/v1/creator/pc/user/info/'),
                        creator: await getJson('/aweme/v1/creator/user/info/'),
                        media: await getJson('/web/api/media/user/info/'),
                        ls: Object.fromEntries(Object.entries(localStorage)
                          .filter(([k]) => /user|login|douyin|slardar/i.test(k))
                          .slice(0, 40))
                      };
                    }"""
                )
                pc = data.get("pc") or {}
                creator = data.get("creator") or {}
                media = data.get("media") or {}
                verify = creator.get("douyin_user_verify_info") or {}
                media_user = media.get("user") or {}
                avatar_obj = (
                    media_user.get("avatar_thumb")
                    or media_user.get("avatar_medium")
                    or media_user.get("avatar_larger")
                    or {}
                )
                avatar = (
                    verify.get("avatar_url")
                    or ((avatar_obj.get("url_list") or [None])[0])
                )
                uid = str(
                    pc.get("uid") or media_user.get("uid") or creator.get("uid") or ""
                )
                unique_id = str(
                    verify.get("douyin_unique_id")
                    or media_user.get("unique_id")
                    or media_user.get("short_id")
                    or ""
                )
                name = (
                    verify.get("nick_name")
                    or media_user.get("nickname")
                    or media_user.get("nickname_raw")
                )
                extra.update(
                    {
                        "user_id": uid or None,
                        "unique_id": unique_id or None,
                        "douyin_unique_id": unique_id or None,
                        "follower_count": verify.get(
                            "follower_count", media_user.get("follower_count")
                        ),
                        "following_count": verify.get(
                            "following_count", media_user.get("following_count")
                        ),
                        "aweme_count": media_user.get("aweme_count"),
                        "login_app": media.get("login_app"),
                    }
                )
                return UserInfo(
                    user_id=uid or None,
                    name=name,
                    username=unique_id or None,
                    avatar=avatar,
                    extra={k: v for k, v in extra.items() if v not in (None, "")},
                )

            if self.platform == "bilibili":
                data = await page.evaluate(
                    """async () => {
                      try {
                        const r = await fetch('https://api.bilibili.com/x/web-interface/nav', {credentials: 'include'});
                        return await r.json();
                      } catch (e) { return null; }
                    }"""
                )
                nav = (data or {}).get("data") or {}
                uid = str(nav.get("mid") or "")
                name = nav.get("uname")
                avatar = nav.get("face")
                level = (nav.get("level_info") or {}).get("current_level")
                extra.update(
                    {
                        "user_id": uid or None,
                        "mid": uid or None,
                        "level": level,
                        "mobile_verified": nav.get("mobile_verified"),
                        "is_login": nav.get("isLogin"),
                        "official": nav.get("official"),
                        "vip": nav.get("vip"),
                    }
                )
                return UserInfo(
                    user_id=uid or None,
                    name=name,
                    username=name,
                    avatar=avatar,
                    extra={k: v for k, v in extra.items() if v not in (None, "")},
                )

            if self.platform == "kuaishou":
                data = await page.evaluate(
                    """() => {
                      const lines = (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
                      const bad = [
                        '平台介绍','机构入驻','视频上传','快手创作者服务平台','立即登录',
                        '平台优势','上传视频','平台热点','机构服务','数据统计','内容推广',
                        '功能简介','常见问题','首页','内容管理','互动管理','成长中心',
                        '创作服务','其他服务','遇到问题','创作者服务','登录'
                      ];
                      const name = (lines.find(s =>
                        s.length >= 2 &&
                        s.length <= 40 &&
                        !bad.some(b => s.includes(b)) &&
                        !/^\\d+$/.test(s)
                      ) || '');
                      const imgs = [...document.querySelectorAll('img')].map(img => {
                        const r = img.getBoundingClientRect();
                        return {src: img.src || '', x: r.x, y: r.y, w: r.width, h: r.height};
                      }).filter(x => x.w > 20 && x.h > 20);
                      const avatar = (imgs.find(x => /uhead|avatar|yximgs/.test(x.src)) || {}).src || '';
                      return {name, avatar, text: lines.slice(0, 20)};
                    }"""
                )
                cookies = await page.context.cookies()
                uid = ""
                for c in cookies:
                    if c.get("name") == "userId" and c.get("value"):
                        uid = str(c.get("value"))
                        break
                extra.update({"user_id": uid or None, "kwai_id": uid or None})
                return UserInfo(
                    user_id=uid or None,
                    name=data.get("name") or None,
                    username=uid or None,
                    avatar=data.get("avatar") or None,
                    extra={k: v for k, v in extra.items() if v not in (None, "")},
                )

            if self.platform == "channels":
                data = await page.evaluate(
                    """() => {
                      const lines = (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
                      const imgs = [...document.querySelectorAll('img')].map(img => {
                        const r = img.getBoundingClientRect();
                        return {src: img.src || '', alt: img.alt || '', x: r.x, y: r.y, w: r.width, h: r.height};
                      }).filter(x => x.w > 20 && x.h > 20);
                      return {lines: lines.slice(0, 40), avatar: (imgs.find(x => /avatar|head|wx|qlogo/i.test(x.src + x.alt)) || {}).src || ''};
                    }"""
                )
                cookies = await page.context.cookies()
                uid = ""
                for c in cookies:
                    if c.get("name") in {"finder_username", "wxuin", "uin"} and c.get(
                        "value"
                    ):
                        uid = str(c.get("value"))
                        break
                name = ""
                for line in data.get("lines") or []:
                    if (
                        line
                        and len(line) <= 40
                        and not any(
                            token in line.lower()
                            for token in ("login", "platform", "assistant")
                        )
                    ):
                        name = line
                        break
                extra.update({"user_id": uid or None})
                return UserInfo(
                    user_id=uid or None,
                    name=name or None,
                    username=uid or None,
                    avatar=data.get("avatar") or None,
                    extra={k: v for k, v in extra.items() if v not in (None, "")},
                )

        except Exception as e:
            logger.debug("%s extract user info failed: %s", self.platform, e)

        try:
            cookies = await page.context.cookies()
            cookie_uid = ""
            for c in cookies:
                if c.get("name") in {
                    "DedeUserID",
                    "uid_tt",
                    "userId",
                    "finder_username",
                    "wxuin",
                    "x-user-id-creator.xiaohongshu.com",
                }:
                    cookie_uid = str(c.get("value") or "")
                    if cookie_uid:
                        break
            if cookie_uid:
                return UserInfo(
                    user_id=cookie_uid,
                    name=None,
                    username=cookie_uid,
                    avatar=None,
                    extra={"url": page.url, "user_id": cookie_uid},
                )
        except Exception:
            pass
        return UserInfo(
            user_id=None, name=None, username=None, avatar=None, extra={"url": page.url}
        )

    async def cleanup_session(self, session_id: str) -> None:
        sess = self._sessions.pop(session_id, None)
        if not sess:
            return
        browser = sess.get("browser")
        if browser is not None:
            await self._close_browser(browser)

    async def validate_cookie(self, storage_state: dict) -> dict:
        """Validate storage_state and return refreshed account metadata."""
        if not storage_state:
            return {"valid": False, "reason": "storage_state is empty"}
        browser, context = await self._launch_browser(
            headless=True, storage_state=storage_state
        )
        try:
            page = await context.new_page()
            test_url = self.publish_url or self.login_url
            await self._goto_with_retries(
                page, test_url, wait_until="domcontentloaded", timeout=60000
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await asyncio.sleep(
                2 if self.platform in {"douyin", "kuaishou", "bilibili"} else 3
            )
            current = page.url
            if "login" in current.lower() or "passport" in current.lower():
                return {
                    "valid": False,
                    "reason": "Cookie invalid: redirected to login page",
                    "page_url": current,
                }
            try:
                body_text = await page.locator("body").inner_text(timeout=8000)
            except Exception:
                body_text = ""
            restriction_reason = self._account_restriction_reason(body_text)
            if restriction_reason:
                return {
                    "valid": False,
                    "status": "account_restricted",
                    "reason": restriction_reason,
                    "page_url": current,
                }
            try:
                file_inputs = await page.locator('input[type="file"]').count()
            except Exception:
                file_inputs = 0
            if self.platform == "kuaishou":
                logged_out_landing = (
                    "立即登录" in body_text
                    or ("快手创作者服务平台" in body_text and file_inputs == 0)
                    or (
                        "平台介绍" in body_text
                        and "视频上传" in body_text
                        and file_inputs == 0
                    )
                )
                if logged_out_landing:
                    return {
                        "valid": False,
                        "reason": "Cookie invalid: Kuaishou publish page shows login/landing page",
                        "page_url": current,
                    }
            user_info = await self._extract_user_info(page)
            refreshed_state = await context.storage_state()
            return {
                "valid": True,
                "reason": "Cookie valid",
                "page_url": current,
                "user_info": {
                    "user_id": user_info.user_id,
                    "name": user_info.name,
                    "username": user_info.username,
                    "avatar": user_info.avatar,
                    "extra": user_info.extra or {},
                },
                "storage_state": refreshed_state,
            }
        except Exception as e:
            return {"valid": False, "reason": f"validate exception: {e}"}
        finally:
            await self._close_browser(browser)

    def _account_restriction_reason(self, body_text: str | None) -> str | None:
        """Return a customer-readable reason when the creator account is restricted."""
        if self.platform != "kuaishou":
            return None
        text = re.sub(r"\s+", "", body_text or "")
        restricted_markers = (
            "账号已被封禁",
            "账号因违规操作已受到限制",
            "无法访问创作者中心",
            "账号被永久封禁",
            "创作者中心功能受限",
        )
        if any(marker in text for marker in restricted_markers):
            return "快手账号已被封禁或限制使用，当前无法访问创作者中心，请在快手 App 查看封禁原因并申诉。"
        return None

    async def publish_content(
        self,
        storage_state: dict,
        title: str,
        description: str,
        tags: list[str] | None = None,
        media_paths: list[str] | None = None,
        cover_path: str | None = None,
        publish_mode: str = "direct",  # direct|schedule
        scheduled_at: str | None = None,
        account_id: str | None = None,
        publish_params: dict | None = None,
    ) -> dict:
        """真实发布流程：打开发布页 -> 填写标题/正文 -> 上传素材 -> 点击发布按钮 -> 等待发布成功。

        各平台 DOM 不同，使用 _PLATFORM_*_SELECTORS 中配置的选择器。
        发布成功判定：URL 跳转到管理页 / 成功页（_PLATFORM_SUCCESS_URL_PATTERNS）。
        全程按关键步骤截图留痕（screenshots），成功时尽力解析 external_post_id。
        """
        if not self.publish_url:
            return {
                "success": False,
                "status": "no_publish_url",
                "error": f"平台 {self.platform} 未配置发布页 URL",
            }

        # ===== 设置验证流程所需的任务上下文（task_id 经 contextvar 传入）=====
        # task_id 由 workers/tasks.py 在调用 publisher.run 前通过 set_current_task_id 绑定，
        # 这里读取后存到 self，供 _handle_verification_during_publish 使用。
        from app.integrations.synapse_engine.verification.manager import (
            get_current_task_id,
        )
        self._current_task_id = get_current_task_id()
        self._current_account_id = account_id

        run_id = f"{(account_id or 'anon')}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        run_dir = self._run_screenshot_dir(run_id)
        shots: list[str] = []
        # native_host 由 service 注入远程 CDP；兼容 worker 模式仍读取
        # settings.SYNAPSE_PLAYWRIGHT_HEADLESS。
        browser, context = await self._launch_browser(
            headless=None, storage_state=storage_state
        )
        try:
            page = await context.new_page()
            await page.goto(
                self.publish_url, wait_until="domcontentloaded", timeout=30000
            )
            await self._wait_for_publish_page_ready(page)
            await asyncio.wait_for(self._dismiss_popups(page), timeout=12)
            await self._screenshot_step(page, run_dir, "01_opened", shots)

            # 若一进发布页就被重定向到登录页，说明 cookie 已失效
            if "login" in page.url.lower() or "passport" in page.url.lower():
                await self._screenshot_step(page, run_dir, "cookie_invalid", shots)
                return {
                    "success": False,
                    "status": "cookie_invalid",
                    "error": "发布页被重定向到登录页，Cookie 已失效，请重新扫码登录",
                    "page_url": page.url,
                    "screenshots": shots,
                }

            # 1. 上传文件（如果有）- 必须先上传，多数平台标题/正文在上传后才出现
            if media_paths:
                logger.info(
                    "%s 开始上传素材 media_count=%d", self.platform, len(media_paths)
                )
                await asyncio.wait_for(
                    self._upload_files(page, media_paths), timeout=90
                )
                logger.info("%s 素材已提交到上传控件，等待平台处理完成", self.platform)
                # 等待上传完成（视频上传较慢，最多等 120 秒）
                await asyncio.wait_for(
                    self._wait_for_upload_complete(page), timeout=240
                )
                logger.info("%s 平台上传处理等待结束", self.platform)
                await asyncio.wait_for(self._dismiss_popups(page), timeout=12)
                await self._screenshot_step(page, run_dir, "02_uploaded", shots)
                logger.info("%s 上传后截图完成", self.platform)

            # 2/3. 填写标题 + 正文/描述。
            # 快手视频发布页当前只有“作品描述”一个主输入框，没有独立标题框；
            # 把标题合并到描述首行，避免标题丢失和无意义的“未找到标题输入框”告警。
            body_text = description
            if self.platform == "kuaishou":
                body_text = "\n".join(part for part in (title, description) if part)
            else:
                await asyncio.wait_for(self._fill_title(page, title), timeout=25)

            if body_text:
                await asyncio.wait_for(self._fill_body(page, body_text), timeout=25)

            # 4. 填写标签/话题（如果提供）
            if tags:
                await self._fill_tags(page, tags)

            # 5. 设置封面（如果提供）
            if cover_path:
                await self._set_cover(page, cover_path)
            elif self.platform == "bilibili":
                await self._ensure_bilibili_cover_selected(page)
            await asyncio.wait_for(
                self._apply_publish_params(page, publish_params or {}), timeout=35
            )
            await self._screenshot_step(page, run_dir, "03_filled", shots)
            logger.info("%s 填写发布参数后截图完成", self.platform)

            # 6. 点击发布按钮（真实点击，不再只是 filled）
            await asyncio.wait_for(self._dismiss_popups(page), timeout=12)
            click_result = await asyncio.wait_for(
                self._click_publish_button(page), timeout=25
            )
            if not click_result["clicked"]:
                await self._screenshot_step(
                    page, run_dir, "publish_button_not_found", shots
                )
                return {
                    "success": False,
                    "status": "publish_button_not_found",
                    "error": click_result.get("error", "未找到发布按钮"),
                    "page_url": page.url,
                    "screenshots": shots,
                }

            # 7. 等待发布成功（URL 跳转）；中途可能遇到验证码/人机验证弹窗。
            #    _wait_for_publish_success 可能返回：True/False 或验证元组
            #    ("phone", hint) / ("human",)。元组交由 _handle_verification_during_publish
            #    处理后继续等待，最多重试 max_verification_rounds 次。
            published = False
            human_captcha_published = False
            verification_handled = 0
            max_verification_rounds = 5
            while True:
                wait_result = await asyncio.wait_for(
                    self._wait_for_publish_success(page), timeout=90
                )
                if wait_result is True:
                    published = True
                    break
                if wait_result is False:
                    published = False
                    break
                if isinstance(wait_result, tuple):
                    verification_handled += 1
                    if verification_handled > max_verification_rounds:
                        logger.warning(
                            "%s 验证次数超限 (%d)，放弃发布",
                            self.platform,
                            verification_handled,
                        )
                        published = False
                        break
                    try:
                        outcome = await self._handle_verification_during_publish(
                            page, wait_result
                        )
                    except Exception as ver_exc:
                        logger.warning(
                            "%s 处理验证失败: %s", self.platform, ver_exc
                        )
                        published = False
                        break
                    if outcome == "published":
                        # 人机验证：用户已在真实平台窗口手动完成发布
                        published = True
                        human_captcha_published = True
                        break
                    if outcome == "resume":
                        # 手机验证码已回填 / 已确认，继续等发布成功
                        continue
                    published = False
                    break
                published = False
                break
            success = published
            await self._screenshot_step(page, run_dir, "04_result", shots)
            if success and human_captcha_published:
                # 人机验证场景：本地浏览器未实际跳转成功页，无法解析 post URL，
                # 返回通用成功；后续 sync-posts 会同步平台真实作品。
                return {
                    "success": True,
                    "status": "published",
                    "message": f"已在真实平台窗口完成 {self.platform_name} 发布",
                    "page_url": page.url,
                    "screenshots": shots,
                }
            if success:
                if self.platform == "kuaishou":
                    try:
                        await self._goto_with_retries(
                            page,
                            "https://cp.kuaishou.com/article/manage/video?status=0&from=publish",
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        await asyncio.sleep(5)
                        await self._screenshot_step(
                            page, run_dir, "05_manage_verified", shots
                        )
                        manage_text = await page.locator("body").inner_text(
                            timeout=10000
                        )
                        restriction_reason = self._account_restriction_reason(
                            manage_text
                        )
                        if restriction_reason:
                            return {
                                "success": False,
                                "status": "account_restricted",
                                "error": restriction_reason,
                                "page_url": page.url,
                                "screenshots": shots,
                            }
                    except Exception as exc:
                        logger.warning("kuaishou 发布后管理页复核失败: %s", exc)
                resolved_url = await self._resolve_post_url_after_publish(
                    page, title=title
                )
                publish_url = resolved_url or page.url
                external_post_id = self._extract_post_id(
                    publish_url
                ) or self._extract_post_id(page.url)
                return {
                    "success": True,
                    "status": "published",
                    "message": f"已成功发布到 {self.platform_name}",
                    "publish_url": publish_url,
                    "page_url": page.url,
                    "external_post_id": external_post_id,
                    "screenshots": shots,
                }
            # URL/提示文案未命中时，再到平台内容管理页按标题核对一次。
            # 只有找到精确匹配的作品才记成功，避免网络抖动导致“实际已发布”
            # 被误判为未知，继而被运营重发成重复内容。
            if (
                self.platform in {"xiaohongshu", "douyin", "kuaishou", "bilibili"}
                and str(title or "").strip()
            ):
                try:
                    resolved_url = await self._resolve_post_url_after_publish(
                        page, title=title
                    )
                    if resolved_url:
                        await self._screenshot_step(
                            page, run_dir, "05_manage_reconciled", shots
                        )
                        return {
                            "success": True,
                            "status": "published",
                            "message": (
                                f"已在 {self.platform_name} 内容管理页"
                                "二次核验到发布作品"
                            ),
                            "publish_url": resolved_url,
                            "page_url": page.url,
                            "external_post_id": self._extract_post_id(resolved_url),
                            "screenshots": shots,
                            "reconciled": True,
                        }
                except Exception as reconcile_exc:
                    logger.warning(
                        "%s 发布后管理页二次核验失败: %s",
                        self.platform,
                        reconcile_exc,
                    )
            # 发布按钮点击了但成功页和管理页都没有找到作品，必须人工确认。
            return {
                "success": False,
                "status": "publish_unknown",
                "error": "已点击发布按钮，但成功页和内容管理页均未确认到作品，请人工核对后再决定是否重试",
                "page_url": page.url,
                "screenshots": shots,
            }
        except Exception as e:
            logger.exception("发布到 %s 失败", self.platform)
            try:
                if "page" in dir() and page and not page.is_closed():
                    await self._screenshot_step(page, run_dir, "error", shots)
            except Exception:
                pass
            return {
                "success": False,
                "status": "publish_error",
                "error": str(e),
                "screenshots": shots,
            }
        finally:
            await self._close_browser(browser)

    def _manage_url_candidates(
        self, publish_url: str | None, external_post_id: str | None
    ) -> list[str]:
        urls: list[str] = []

        def add(url: str | None) -> None:
            if url and url not in urls:
                urls.append(url)

        if self.platform == "xiaohongshu":
            add("https://creator.xiaohongshu.com/new/note-manager")
            add("https://creator.xiaohongshu.com/creator/notes")
        elif self.platform == "douyin":
            add("https://creator.douyin.com/creator-micro/content/manage")
        elif self.platform == "bilibili":
            add("https://member.bilibili.com/platform/upload-manager/article")
            add("https://member.bilibili.com/platform/upload-manager")
        elif self.platform == "kuaishou":
            add("https://cp.kuaishou.com/article/manage")

        add(publish_url)
        add(self._canonical_content_url(external_post_id))
        return urls

    async def delete_published_content(
        self,
        storage_state: dict,
        publish_url: str | None = None,
        external_post_id: str | None = None,
        title: str | None = None,
        account_id: str | None = None,
    ) -> dict:
        """Best-effort delete/unpublish a post from the platform creator UI."""
        run_id = (
            f"delete_{(account_id or 'anon')}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        )
        run_dir = self._run_screenshot_dir(run_id)
        shots: list[str] = []
        browser, context = await self._launch_browser(
            headless=True, storage_state=storage_state
        )
        try:
            page = await context.new_page()
            for url in self._manage_url_candidates(publish_url, external_post_id):
                try:
                    await self._goto_with_retries(
                        page, url, wait_until="domcontentloaded", timeout=45000
                    )
                    await asyncio.sleep(2)
                    await self._dismiss_popups(page)
                    await self._screenshot_step(page, run_dir, "opened", shots)
                    if "login" in page.url.lower() or "passport" in page.url.lower():
                        return {
                            "success": False,
                            "status": "cookie_invalid",
                            "error": "删除内容时被重定向到登录页，Cookie 已失效",
                            "page_url": page.url,
                            "screenshots": shots,
                        }
                    clicked = await self._click_scoped_action(
                        page,
                        labels=["删除", "下架", "移除"],
                        title=title,
                        external_post_id=external_post_id,
                        publish_url=publish_url,
                        pre_open_labels=["更多", "操作", "...", "···"],
                    )
                    if clicked:
                        await asyncio.sleep(0.8)
                        await self._confirm_dialog(
                            page,
                            [
                                "确认删除",
                                "确定删除",
                                "仍要删除",
                                "删除",
                                "确认",
                                "确定",
                            ],
                        )
                        await asyncio.sleep(2)
                        await self._screenshot_step(page, run_dir, "deleted", shots)
                        return {
                            "success": True,
                            "status": "deleted",
                            "message": "平台内容删除/下架操作已提交",
                            "page_url": page.url,
                            "screenshots": shots,
                        }
                except Exception as exc:
                    logger.warning(
                        "%s delete attempt failed url=%s: %s", self.platform, url, exc
                    )
                    continue
            return {
                "success": False,
                "status": "remote_action_failed",
                "error": "未在平台管理页找到匹配内容的删除/下架按钮",
                "screenshots": shots,
            }
        finally:
            await self._close_browser(browser)

    async def update_published_visibility(
        self,
        storage_state: dict,
        visibility: str,
        publish_url: str | None = None,
        external_post_id: str | None = None,
        title: str | None = None,
        account_id: str | None = None,
    ) -> dict:
        """Best-effort adjust visibility for an already published post."""
        visibility = (visibility or "public").strip()
        if self.platform == "bilibili" and visibility != "public":
            return {
                "success": False,
                "status": "unsupported",
                "error": "B站网页视频发布/管理页未提供稳定的“仅自己可见”选项，请按公开内容处理。",
            }

        run_id = f"visibility_{(account_id or 'anon')}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        run_dir = self._run_screenshot_dir(run_id)
        shots: list[str] = []
        browser, context = await self._launch_browser(
            headless=True, storage_state=storage_state
        )
        try:
            page = await context.new_page()
            for url in self._manage_url_candidates(publish_url, external_post_id):
                try:
                    await self._goto_with_retries(
                        page, url, wait_until="domcontentloaded", timeout=45000
                    )
                    await asyncio.sleep(2)
                    await self._dismiss_popups(page)
                    await self._screenshot_step(page, run_dir, "opened", shots)
                    if "login" in page.url.lower() or "passport" in page.url.lower():
                        return {
                            "success": False,
                            "status": "cookie_invalid",
                            "error": "修改可见性时被重定向到登录页，Cookie 已失效",
                            "page_url": page.url,
                            "screenshots": shots,
                        }

                    await self._click_scoped_action(
                        page,
                        labels=["编辑", "修改", "管理"],
                        title=title,
                        external_post_id=external_post_id,
                        publish_url=publish_url,
                        pre_open_labels=["更多", "操作", "...", "···"],
                        required=False,
                    )
                    await asyncio.sleep(2)
                    applied = await self._apply_visibility(page, visibility)
                    if not applied and visibility != "public":
                        continue
                    saved = await self._click_scoped_action(
                        page,
                        labels=["保存", "更新", "提交", "确认修改", "发布"],
                        title=None,
                        external_post_id=None,
                        publish_url=None,
                        pre_open_labels=[],
                        required=False,
                        allow_global=True,
                    )
                    if saved:
                        await asyncio.sleep(2)
                    await self._screenshot_step(
                        page, run_dir, "visibility_updated", shots
                    )
                    return {
                        "success": True,
                        "status": "visibility_updated",
                        "message": f"平台内容可见性已尝试调整为 {visibility}",
                        "page_url": page.url,
                        "screenshots": shots,
                    }
                except Exception as exc:
                    logger.warning(
                        "%s visibility attempt failed url=%s: %s",
                        self.platform,
                        url,
                        exc,
                    )
                    continue
            return {
                "success": False,
                "status": "remote_action_failed",
                "error": f"未在平台管理页找到匹配内容，无法调整可见性为 {visibility}",
                "screenshots": shots,
            }
        finally:
            await self._close_browser(browser)

    async def _confirm_dialog(self, page, labels: list[str]) -> bool:
        try:
            clicked = await self._evaluate_with_timeout(
                page,
                """(labels) => {
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  const norm = (s) => String(s || '').trim().replace(/\\s+/g, '');
                  for (const el of document.querySelectorAll('button,[role="button"],span,div')) {
                    if (!visible(el)) continue;
                    const text = norm(el.innerText || el.textContent || '');
                    if (labels.some(label => text === norm(label) || text.includes(norm(label)))) {
                      (el.closest('button,[role="button"]') || el).click();
                      return true;
                    }
                  }
                  return false;
                }""",
                labels,
                timeout=8,
            )
            return bool(clicked)
        except Exception:
            return False

    async def _click_scoped_action(
        self,
        page,
        labels: list[str],
        title: str | None,
        external_post_id: str | None,
        publish_url: str | None,
        pre_open_labels: list[str] | None = None,
        required: bool = True,
        allow_global: bool = False,
    ) -> bool:
        """Click an action button either inside a matched content row or globally.

        Destructive actions are scoped by title/id/link whenever possible to
        avoid touching the wrong post in a management list.
        """
        target = {
            "labels": labels,
            "title": title or "",
            "id": external_post_id or "",
            "url": publish_url or "",
            "allowGlobal": allow_global,
        }
        opener_target = dict(target)
        opener_target["labels"] = pre_open_labels or []
        for attempt in range(3):
            clicked = await self._evaluate_with_timeout(
                page,
                """(target) => {
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  const norm = (s) => String(s || '').trim().replace(/\\s+/g, '').toLowerCase();
                  const labels = (target.labels || []).map(norm);
                  const title = norm(target.title || '');
                  const id = norm(target.id || '');
                  const url = String(target.url || '');
                  const currentIsTarget = id && location.href.includes(id);
                  const matches = (el) => {
                    const text = norm(el.innerText || el.textContent || '');
                    const href = String(el.href || el.getAttribute?.('href') || '');
                    if (title && text.includes(title.slice(0, Math.min(24, title.length)))) return true;
                    if (id && (text.includes(id) || href.includes(id))) return true;
                    if (url && href && url.includes(href)) return true;
                    return false;
                  };
                  let scopes = [];
                  if (currentIsTarget || target.allowGlobal) scopes.push(document.body);
                  for (const el of document.querySelectorAll('a,tr,li,[class*="item"],[class*="card"],[class*="row"],div')) {
                    if (!visible(el)) continue;
                    if (!matches(el)) continue;
                    scopes.push(el.closest('tr,li,[class*="item"],[class*="card"],[class*="row"]') || el);
                  }
                  scopes = [...new Set(scopes)];
                  if (!scopes.length && !target.allowGlobal) return false;
                  if (!scopes.length) scopes = [document.body];
                  const isAction = (el) => {
                    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.title || '');
                    return labels.some(label => text === label || text.includes(label));
                  };
                  for (const scope of scopes) {
                    const candidates = [...scope.querySelectorAll('button,[role="button"],a,span,div')].filter(visible).filter(isAction);
                    candidates.sort((a, b) => {
                      const ra = a.getBoundingClientRect();
                      const rb = b.getBoundingClientRect();
                      return (rb.x + rb.y) - (ra.x + ra.y);
                    });
                    if (candidates.length) {
                      (candidates[0].closest('button,[role="button"],a') || candidates[0]).click();
                      return true;
                    }
                  }
                  return false;
                }""",
                target,
                timeout=8,
            )
            if clicked:
                return True
            if attempt == 0 and opener_target["labels"]:
                opened = await self._evaluate_with_timeout(
                    page,
                    """(target) => {
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      const norm = (s) => String(s || '').trim().replace(/\\s+/g, '').toLowerCase();
                      const labels = (target.labels || []).map(norm);
                      const title = norm(target.title || '');
                      const id = norm(target.id || '');
                      const scopes = [];
                      for (const el of document.querySelectorAll('a,tr,li,[class*="item"],[class*="card"],[class*="row"],div')) {
                        if (!visible(el)) continue;
                        const text = norm(el.innerText || el.textContent || '');
                        const href = String(el.href || el.getAttribute?.('href') || '');
                        if ((title && text.includes(title.slice(0, Math.min(24, title.length)))) || (id && (text.includes(id) || href.includes(id)))) {
                          scopes.push(el.closest('tr,li,[class*="item"],[class*="card"],[class*="row"]') || el);
                        }
                      }
                      for (const scope of scopes) {
                        for (const el of scope.querySelectorAll('button,[role="button"],a,span,div')) {
                          if (!visible(el)) continue;
                          const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.title || '');
                          if (labels.some(label => text === label || text.includes(label))) {
                            (el.closest('button,[role="button"],a') || el).click();
                            return true;
                          }
                        }
                      }
                      return false;
                    }""",
                    opener_target,
                    timeout=8,
                )
                if opened:
                    await asyncio.sleep(1)
        if required:
            logger.info(
                "%s scoped action not found labels=%s title=%s id=%s",
                self.platform,
                labels,
                title,
                external_post_id,
            )
        return False

    async def _dismiss_popups(self, page) -> None:
        """Best-effort close onboarding/popover overlays that block publish buttons."""
        for text in ("我知道了", "知道了", "确定", "确认", "跳过", "稍后再说", "暂不"):
            try:
                loc = page.get_by_text(text, exact=False).first
                if await loc.count() > 0 and await loc.is_visible(timeout=500):
                    await loc.click(timeout=1200)
                    await asyncio.sleep(0.4)
            except Exception:
                continue
        try:
            await self._evaluate_with_timeout(
                page,
                """() => {
                  const selectors = [
                    '[aria-label="Skip"]', '[aria-label="Close"]',
                    '.semi-modal-close', '.ant-modal-close', '.el-dialog__headerbtn',
                    '[class*="close"]', '[class*="Close"]'
                  ];
                  for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                      const r = el.getBoundingClientRect();
                      if (r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0 && r.x < innerWidth && r.y < innerHeight) {
                        el.click();
                        return true;
                      }
                    }
                  }
                  return false;
                }""",
                timeout=5,
            )
            await asyncio.sleep(0.3)
        except Exception:
            pass

    async def _wait_for_publish_page_ready(self, page, timeout: int = 90) -> None:
        """Wait until a publish page is interactive before uploading/filling.

        Some creator centers (especially Douyin) can report domcontentloaded while
        the actual upload workspace is still a full-page spinner. Continuing at
        that point produced false "uploaded" screenshots and all later selectors
        matched nothing.  This guard waits for a real upload/input/editor signal
        or at least for the generic loading text/spinner to disappear.
        """
        deadline = time.time() + timeout
        ready_selectors = [
            'input[type="file"]',
            "textarea",
            'input[placeholder*="标题"]',
            '[contenteditable="true"]',
            'button:has-text("发布")',
            'button:has-text("立即投稿")',
            "xhs-publish-btn",
        ]
        while time.time() < deadline:
            try:
                for sel in ready_selectors:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        # file inputs are normally hidden, so visibility is not
                        # required for them. Other controls should exist in DOM.
                        await asyncio.sleep(1.0)
                        return
            except Exception:
                pass
            try:
                body_text = await page.locator("body").inner_text(timeout=2500)
            except Exception:
                body_text = ""
            if self._publish_page_body_is_ready(body_text):
                await asyncio.sleep(1.0)
                return
            await asyncio.sleep(1.5)
        raise RuntimeError(
            f"{self.platform_name or self.platform} 发布页面加载超时，请稍后重试"
        )

    def _publish_page_body_is_ready(self, body_text: str | None) -> bool:
        """Do not mistake a creator-center shell for a loaded publish workspace."""
        text = body_text or ""
        if self.platform == "kuaishou":
            return "拖拽视频到此或点击上传" in text
        return bool(
            text and not re.search(r"(加载中|正在加载|Loading|请稍候)", text, re.I)
        )

    async def _fill_control_text(self, locator, text: str) -> bool:
        """Fill native inputs and custom contenteditable editors robustly."""
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            await locator.click(timeout=3000)
        except Exception:
            pass
        try:
            await locator.fill(text, timeout=5000, force=True)
            return True
        except Exception:
            pass
        try:
            await locator.press("Control+A", timeout=1500)
            await locator.press("Backspace", timeout=1500)
            await locator.type(text, delay=8, timeout=15000)
            return True
        except Exception:
            pass
        try:
            await locator.evaluate(
                """(el, value) => {
                  const proto = el.tagName === 'TEXTAREA'
                    ? HTMLTextAreaElement.prototype
                    : (el.tagName === 'INPUT' ? HTMLInputElement.prototype : null);
                  if (proto) {
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(el, value); else el.value = value;
                  } else {
                    el.focus();
                    el.textContent = value;
                    el.innerText = value;
                  }
                  el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                  el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                text,
            )
            return True
        except Exception:
            return False

    async def _upload_files(self, page, media_paths: list[str]) -> None:
        """上传媒体文件。"""
        await self._prepare_upload_mode(page, media_paths)
        if self.platform == "douyin":
            if await self._upload_douyin_files(page, media_paths):
                return
        selectors = _PLATFORM_FILE_INPUT_SELECTORS.get(
            self.platform, ['input[type="file"]']
        )
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.set_input_files(media_paths, timeout=30000)
                    logger.info(
                        "%s 已向上传控件提交文件 selector=%s", self.platform, sel
                    )
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue
        # 回退：找所有 file input
        try:
            loc = page.locator('input[type="file"]').first
            if await loc.count() > 0:
                await loc.set_input_files(media_paths, timeout=30000)
                logger.info(
                    "%s 已向上传控件提交文件 selector=input[type=file] fallback",
                    self.platform,
                )
                await asyncio.sleep(2)
                return
        except Exception as e:
            logger.warning("%s 上传文件失败: %s", self.platform, e)
        raise RuntimeError(
            f"{self.platform} 未找到文件上传入口，素材未上传，已中止发布"
        )

    async def _upload_douyin_files(self, page, media_paths: list[str]) -> bool:
        """Upload Douyin media through the visible upload button when possible.

        Douyin currently renders multiple hidden file inputs. The first matching
        ``input[type=file][accept*=video]`` can belong to a menu/preload node and
        accepts ``set_input_files`` without actually moving the page into the
        editor. Prefer the real file chooser opened by the central upload button;
        if that is not available, use the last matching file input (the one
        closest to the active upload panel in current DOM order).
        """
        click_selectors = [
            'button:has-text("点击上传")',
            'button:has-text("上传视频")',
            'button:has-text("选择视频")',
            '[role="button"]:has-text("点击上传")',
            '[role="button"]:has-text("上传视频")',
            '[class*="upload"]:has-text("点击上传")',
            '[class*="upload"]:has-text("上传视频")',
        ]
        for sel in click_selectors:
            try:
                loc = page.locator(sel).last
                if await loc.count() <= 0:
                    continue
                async with page.expect_file_chooser(timeout=8000) as chooser_info:
                    await loc.click(timeout=8000)
                chooser = await chooser_info.value
                await chooser.set_files(media_paths)
                logger.info(
                    "%s 已通过文件选择器提交素材 selector=%s", self.platform, sel
                )
                await asyncio.sleep(2)
                return True
            except Exception as e:
                logger.debug(
                    "%s 文件选择器上传尝试失败 selector=%s error=%s",
                    self.platform,
                    sel,
                    e,
                )

        selectors = ['input[type="file"][accept*="video"]', 'input[type="file"]']
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                if count <= 0:
                    continue
                # Prefer the active panel input at the end of DOM order.
                await loc.nth(count - 1).set_input_files(media_paths, timeout=30000)
                logger.info(
                    "%s 已向上传控件提交文件 selector=%s nth=%d",
                    self.platform,
                    sel,
                    count - 1,
                )
                await asyncio.sleep(2)
                return True
            except Exception as e:
                logger.debug(
                    "%s 末尾上传控件提交失败 selector=%s error=%s",
                    self.platform,
                    sel,
                    e,
                )
        return False

    async def _prepare_upload_mode(self, page, media_paths: list[str]) -> None:
        """Switch platform upload tabs before selecting files when needed."""
        if not media_paths:
            return
        first = str(media_paths[0]).lower().split("?", 1)[0]
        is_image = first.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
        if self.platform == "xiaohongshu" and is_image:
            try:
                clicked = await page.evaluate(
                    """(needle) => {
                      const nodes = [...document.querySelectorAll('.creator-tab')].filter(el => {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (!text.includes(needle)) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0;
                      });
                      const node = nodes[nodes.length - 1];
                      if (node) { node.click(); return true; }
                      return false;
                    }""",
                    "上传图文",
                )
                if clicked:
                    await asyncio.sleep(1.2)
            except Exception as e:
                logger.debug("%s 切换上传图文失败: %s", self.platform, e)

    async def _wait_for_upload_complete(self, page, timeout: int = 120) -> None:
        """等待上传完成。通用策略：等待上传进度条消失或上传成功提示出现。"""
        try:
            # 等待上传进度条消失（多数平台用 .upload-progress 或 [class*="progress"]）
            progress_selectors = [
                ".upload-progress",
                '[class*="upload-progress"]',
                '[class*="progress-bar"]',
            ]
            for sel in progress_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        # 等待进度条消失（最多 timeout 秒）
                        await loc.wait_for(state="hidden", timeout=timeout * 1000)
                        break
                except Exception:
                    continue
            # DOM/text fallback: 抖音等平台的上传进度不一定使用 progress-bar 类名。
            # 如果页面仍显示“上传中 / xx% / 处理中”，继续等待，避免上传未完成就点发布。
            deadline = time.time() + max(timeout, 180)
            while time.time() < deadline:
                try:
                    body_text = await page.locator("body").inner_text(timeout=3000)
                except Exception:
                    body_text = ""
                uploading = bool(
                    re.search(
                        r"(上传中|上传进度|正在上传|处理中|转码中|审核中|\b\d{1,2}%)",
                        body_text,
                    )
                )
                if not uploading:
                    break
                await asyncio.sleep(2)
            # 额外等待确保上传后 DOM 稳定
            if self.platform == "douyin":
                ready = await self._wait_for_douyin_editor_ready(
                    page, timeout=max(timeout, 180)
                )
                if not ready:
                    await self._log_douyin_upload_state(page)
                    raise RuntimeError(
                        "抖音素材提交后未进入标题/描述/发布设置编辑页，可能素材未被平台接受或上传控件选择错误。"
                    )
            await asyncio.sleep(2)
        except Exception:
            if self.platform == "douyin":
                raise
            # 超时不一定失败，可能是该平台没有进度条 UI
            await asyncio.sleep(3)

    async def _wait_for_douyin_editor_ready(self, page, timeout: int = 180) -> bool:
        """Douyin-specific post-upload guard.

        The initial upload page contains a file input immediately, so generic
        "input exists" checks can return before the selected video has actually
        moved into the editor.  Publishing before this point loses the title,
        description and visibility settings.  Wait until the real editor fields
        and publish settings are present.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ready = await self._evaluate_with_timeout(
                    page,
                    """() => {
                      const hasTitle = [...document.querySelectorAll('input')]
                        .some(i => (i.placeholder || '').includes('标题'));
                      const hasEditor = !!document.querySelector('.zone-container[contenteditable="true"], .editor-comp-publish[contenteditable="true"], [contenteditable="true"]');
                      const body = (document.body.innerText || document.body.textContent || '').replace(/\\s+/g, '');
                      const hasVisibility = body.includes('谁可以看') && body.includes('仅自己可见');
                      return hasTitle || (hasEditor && hasVisibility);
                    }""",
                    timeout=6,
                )
                if ready:
                    logger.info("%s 上传后已进入编辑页", self.platform)
                    return True
            except Exception as e:
                logger.debug("%s 等待抖音编辑页脚本失败: %s", self.platform, e)
            await asyncio.sleep(2)
        return False

    async def _log_douyin_upload_state(self, page) -> None:
        """Log a compact page snapshot when Douyin upload never reaches editor."""
        try:
            state = await self._evaluate_with_timeout(
                page,
                """() => {
                  const body = (document.body.innerText || document.body.textContent || '').replace(/\\s+/g, ' ').slice(0, 500);
                  const inputs = [...document.querySelectorAll('input')].slice(0, 12).map((i, idx) => ({
                    idx,
                    type: i.type || '',
                    accept: i.accept || '',
                    placeholder: i.placeholder || '',
                    value: i.value || ''
                  }));
                  const fileInputs = [...document.querySelectorAll('input[type="file"]')].map((i, idx) => ({
                    idx,
                    accept: i.accept || '',
                    files: i.files ? i.files.length : 0
                  }));
                  return {url: location.href, body, inputs, fileInputs};
                }""",
                timeout=6,
            )
            logger.warning(
                "%s 上传后仍未进入编辑页 snapshot=%s",
                self.platform,
                json.dumps(state, ensure_ascii=False)[:1800],
            )
        except Exception as e:
            logger.warning("%s 上传后状态快照失败: %s", self.platform, e)

    async def _fill_title(self, page, title: str) -> None:
        """填写标题。"""
        if not title:
            return
        if self.platform == "douyin":
            try:
                ok = await self._evaluate_with_timeout(
                    page,
                    """(value) => {
                      const el = [...document.querySelectorAll('input')].find(i => (i.placeholder || '').includes('标题'));
                      if (!el) return false;
                      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                      el.focus();
                      if (setter) setter.call(el, value.slice(0, 30)); else el.value = value.slice(0, 30);
                      el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value.slice(0, 30)}));
                      el.dispatchEvent(new Event('change', {bubbles: true}));
                      return true;
                    }""",
                    title,
                    timeout=8,
                )
                if ok:
                    logger.info("%s 已填写标题", self.platform)
                    await asyncio.sleep(0.3)
                    return
            except Exception as e:
                logger.debug("%s 抖音标题填写脚本失败: %s", self.platform, e)
        if self.platform == "xiaohongshu":
            for sel in (
                'input.d-text[placeholder*="标题"]',
                'input[placeholder*="标题"]',
                "input.d-text",
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        if await self._fill_control_text(loc, title[:20]):
                            return
                except Exception:
                    continue
        selectors = _PLATFORM_TITLE_SELECTORS.get(
            self.platform,
            ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]', "#title"],
        )
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    if await self._fill_control_text(loc, title):
                        return
            except Exception:
                continue
        logger.warning("%s 未找到标题输入框", self.platform)

    async def _fill_body(self, page, body: str) -> None:
        """填写正文/描述。"""
        if self.platform == "douyin":
            try:
                ok = await self._evaluate_with_timeout(
                    page,
                    """(value) => {
                      const el = document.querySelector('.zone-container[contenteditable="true"], .editor-comp-publish[contenteditable="true"], [contenteditable="true"]');
                      if (!el) return false;
                      el.scrollIntoView({block: 'center', inline: 'nearest'});
                      el.focus();
                      // Rich editors on Douyin listen to input before change.
                      el.textContent = value;
                      el.innerText = value;
                      el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                      el.dispatchEvent(new Event('change', {bubbles: true}));
                      return true;
                    }""",
                    body,
                    timeout=8,
                )
                if ok:
                    logger.info("%s 已填写正文/描述", self.platform)
                    await asyncio.sleep(0.5)
                    return
            except Exception as e:
                logger.debug("%s 抖音正文填写脚本失败: %s", self.platform, e)
        if self.platform == "xiaohongshu":
            for sel in (
                '.tiptap.ProseMirror[contenteditable="true"]',
                'div[role="textbox"][contenteditable="true"]',
                '[contenteditable="true"]',
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        if await self._fill_control_text(loc, body[:1000]):
                            return
                except Exception:
                    continue
        selectors = _PLATFORM_BODY_SELECTORS.get(
            self.platform,
            ['[contenteditable="true"]', 'textarea[placeholder*="描述"]'],
        )
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    if await self._fill_control_text(loc, body):
                        return
            except Exception:
                continue
        logger.warning("%s 未找到正文输入框", self.platform)

    async def _fill_tags(self, page, tags: list[str]) -> None:
        """填写标签/话题。通用策略：在标题或正文后追加 #话题#"""
        if not tags:
            return
        # 多数平台支持在正文里 #话题# 触发话题选择
        # 这里只做简单追加，真实生产可能需要更复杂的话题选择器交互
        tag_text = " ".join(f"#{t}#" if not t.startswith("#") else t for t in tags)
        try:
            body_selectors = _PLATFORM_BODY_SELECTORS.get(
                self.platform, ['[contenteditable="true"]']
            )
            for sel in body_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.press("End")
                        await loc.type(f" {tag_text}", delay=50)
                        return
                except Exception:
                    continue
        except Exception as e:
            logger.warning("%s 填写标签失败: %s", self.platform, e)

    async def _apply_publish_params(self, page, params: dict) -> None:
        """Apply best-effort platform options from task.publish_params.

        当前各平台 DOM 变化很快，因此这里只做保守操作：
        - visibility: public/friends/private -> 点击公开/好友/仅自己可见等单选文案
        - location/location_name -> 填写位置/地理位置/详细地址输入框
        - topics/tags 已在 _fill_tags 处理；这里不重复点击复杂话题弹层
        - allow_download/allow_comment/allow_duet 等先持久化，保守不强制翻转未知开关，避免误关平台默认项
        """
        if not params:
            return
        visibility = str(params.get("visibility") or "public")
        if self.platform == "bilibili":
            if visibility != "public":
                logger.warning(
                    "bilibili does not expose a stable private visibility option in this web flow; publishing as public"
                )
            await self._apply_bilibili_publish_params(page, params)
            return
        visibility_applied = await self._apply_visibility(page, visibility)
        if visibility in {"private", "friends"} and not visibility_applied:
            raise RuntimeError(
                f"无法确认已设置可见范围为 {visibility}，已中止发布，避免误公开。"
            )
        location = (
            params.get("location")
            or params.get("location_name")
            or params.get("poi")
            or params.get("address")
        )
        if location:
            await self._fill_location(page, str(location))

    async def _apply_bilibili_publish_params(self, page, params: dict) -> None:
        """Best-effort Bilibili-specific publish settings.

        B站视频发布页通常没有“仅自己可见”。这里仅处理公开发布可用的字段：
        创作声明/分区/转载来源；标题、简介和标签仍由通用输入流程填写。
        """
        statement = str(
            params.get("creation_statement")
            or params.get("statement")
            or params.get("bilibili_statement")
            or "内容无需标注"
        ).strip()
        statement_aliases = {
            "none": "内容无需标注",
            "normal": "内容无需标注",
            "no_ai": "内容无需标注",
            "ai": "含AI生成内容",
            "generated": "含AI生成内容",
            "fiction": "含虚构演绎内容",
            "marketing": "内容含营销信息",
            "opinion": "个人观点，仅供参考",
            "reprint": "内容为转载",
        }
        statement = statement_aliases.get(statement.lower(), statement)
        if statement:
            try:
                await self._evaluate_with_timeout(
                    page,
                    """async (target) => {
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      const textOf = (el) => (el.innerText || el.textContent || el.value || el.placeholder || '').replace(/\\s+/g, ' ').trim();
                      const root = document.querySelector('.creation-statement-container')
                        || [...document.querySelectorAll('.form-item')]
                          .filter(visible)
                          .find(el => textOf(el).includes('创作声明'));
                      if (!root) return false;
                      const input = root.querySelector('input[placeholder*="创作声明"],input');
                      const current = input ? String(input.value || '').trim() : '';
                      if (current.includes(target)) return true;
                      const opener = input || root.querySelector('.bcc-select,[class*="select"]') || root;
                      opener.scrollIntoView({block: 'center', inline: 'nearest'});
                      opener.click();
                      await new Promise(resolve => setTimeout(resolve, 400));
                      const options = [...document.querySelectorAll('.bcc-option,li,[role="option"],button,[role="button"]')]
                        .filter(visible)
                        .map(el => ({el, text: textOf(el)}))
                        .filter(x => x.text);
                      const targetNorm = String(target || '').replace(/\\s+/g, '');
                      const match = options.find(x => x.text.replace(/\\s+/g, '') === targetNorm)
                        || options.find(x => x.text.includes(target))
                        || (target.includes('无需') ? options.find(x => x.text.includes('内容无需标注')) : null);
                      if (!match) return false;
                      (match.el.closest('li,.bcc-option,[role="option"],button,[role="button"]') || match.el).click();
                      return true;
                    }""",
                    statement,
                    timeout=10,
                )
                await asyncio.sleep(0.6)
            except Exception as exc:
                logger.info("bilibili creation statement selection skipped: %s", exc)

        category = (
            params.get("category")
            or params.get("partition")
            or params.get("type")
            or params.get("category_name")
        )
        if category:
            try:
                clicked = await self._evaluate_with_timeout(
                    page,
                    """(name) => {
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      const textOf = (el) => (el.innerText || el.textContent || el.placeholder || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
                      const root = [...document.querySelectorAll('.video-human-type,.form-item,div')]
                        .filter(visible)
                        .find(el => textOf(el).includes('分区'));
                      if (!root) return false;
                      const current = textOf(root);
                      if (current.includes(name)) return true;
                      const opener = root.querySelector('.select-controller,.selector-container,[role="combobox"],[class*="select"]') || root;
                      if (opener) {
                        opener.scrollIntoView({block: 'center', inline: 'nearest'});
                        opener.click();
                      }
                      return !!opener;
                    }""",
                    str(category),
                    timeout=8,
                )
                if clicked:
                    await asyncio.sleep(0.8)
                    await self._evaluate_with_timeout(
                        page,
                        """(name) => {
                          const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = getComputedStyle(el);
                            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                          };
                          const target = String(name || '').trim();
                          const options = [...document.querySelectorAll('li,.selector-item,.bcc-option,div,span,button,[role="option"]')].filter(visible);
                          for (const el of options) {
                            if (!visible(el)) continue;
                            const text = (el.innerText || el.textContent || '').trim();
                            if (text && text.includes(target)) {
                              (el.closest('li,.selector-item,.bcc-option,button,[role="button"],[role="option"]') || el).click();
                              return true;
                            }
                          }
                          return false;
                        }""",
                        str(category),
                        timeout=8,
                    )
            except Exception as exc:
                logger.info("bilibili category selection skipped: %s", exc)

        copyright_text = str(
            params.get("copyright") or params.get("copyright_type") or ""
        ).strip()
        if copyright_text:
            try:
                labels = (
                    ["自制", "原创"]
                    if copyright_text in {"1", "original", "自制", "原创"}
                    else ["转载"]
                )
                await self._evaluate_with_timeout(
                    page,
                    """(labels) => {
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      for (const el of document.querySelectorAll('label,button,span,div')) {
                        if (!visible(el)) continue;
                        const text = (el.innerText || el.textContent || '').trim();
                        if (labels.some(label => text === label || text.includes(label))) {
                          (el.closest('label,button,[role="button"]') || el).click();
                          return true;
                        }
                      }
                      return false;
                    }""",
                    labels,
                    timeout=8,
                )
            except Exception:
                pass

        source = str(params.get("source") or params.get("reprint_source") or "").strip()
        if source:
            selectors = [
                'input[placeholder*="来源"]',
                'textarea[placeholder*="来源"]',
                'input[placeholder*="转载"]',
            ]
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible(timeout=800):
                        await self._fill_control_text(loc, source)
                        break
                except Exception:
                    continue

    async def _apply_visibility(self, page, visibility: str) -> bool:
        label_map = {
            "public": ("公开", "所有人可见"),
            "friends": ("好友可见", "朋友可见", "仅互关好友可见"),
            "private": ("仅自己可见", "私密", "仅我可见"),
        }
        labels = label_map.get(visibility, label_map["public"])

        # 抖音发布页是 radio 组选项：谁可以看 -> 公开 / 好友可见 / 仅自己可见。
        # 用 radio group 的结构和值直接点，避免误点左侧「高清发布」等含“发布/公开”的菜单。
        if self.platform == "douyin":
            try:
                value_map = {"public": "0", "friends": "2", "private": "1"}
                clicked = await self._evaluate_with_timeout(
                    page,
                    """(value) => {
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      const groups = [...document.querySelectorAll('div')].filter(el => {
                        if (!visible(el)) return false;
                        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                        const r = el.getBoundingClientRect();
                        return text.includes('谁可以看') && text.includes('仅自己可见') &&
                          r.x >= 200 && r.width >= 300 && r.height <= 160;
                      });
                      groups.sort((a, b) => {
                        const ra = a.getBoundingClientRect();
                        const rb = b.getBoundingClientRect();
                        return (ra.height - rb.height) || (rb.y - ra.y);
                      });
                      const group = groups[0];
                      if (!group) return false;
                      group.scrollIntoView({block: 'center', inline: 'nearest'});
                      const inputs = [...group.querySelectorAll('input[type="checkbox"],input[type="radio"]')];
                      const target = inputs.find(i => String(i.value) === String(value)) || inputs[value === '1' ? 2 : value === '2' ? 1 : 0];
                      if (!target) return false;
                      target.click();
                      target.dispatchEvent(new Event('change', {bubbles: true}));
                      return true;
                    }""",
                    value_map.get(visibility, "0"),
                    timeout=10,
                )
                if clicked:
                    await asyncio.sleep(0.8)
                    selected = await self._evaluate_with_timeout(
                        page,
                        """(value) => {
                          const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = getComputedStyle(el);
                            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                          };
                          const groups = [...document.querySelectorAll('div')].filter(el => {
                            if (!visible(el)) return false;
                            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                            const r = el.getBoundingClientRect();
                            return text.includes('谁可以看') && text.includes('仅自己可见') &&
                              r.x >= 200 && r.width >= 300 && r.height <= 160;
                          });
                          for (const group of groups) {
                            const target = [...group.querySelectorAll('input[type="checkbox"],input[type="radio"]')]
                              .find(i => String(i.value) === String(value));
                            if (target && target.checked) return true;
                          }
                          return false;
                        }""",
                        value_map.get(visibility, "0"),
                        timeout=8,
                    )
                else:
                    selected = False
                if selected:
                    logger.info(
                        "%s 已设置可见范围 visibility=%s", self.platform, visibility
                    )
                    return True
            except Exception as e:
                logger.debug("%s 抖音可见范围直接设置失败: %s", self.platform, e)

        # 小红书当前发布页使用 .permission-card-select 作为可见范围下拉。
        # 直接用平台选择器比文本猜测更可靠；只有选择后触发器文案变成目标文案才返回成功。
        if self.platform == "xiaohongshu":
            try:
                trigger = page.locator(".permission-card-select").first
                if await trigger.count() > 0:
                    await trigger.scroll_into_view_if_needed(timeout=3000)
                    await trigger.click(timeout=5000)
                    await asyncio.sleep(0.5)
                    for label in labels:
                        option = (
                            page.locator(".custom-option, .d-grid-item")
                            .filter(has_text=label)
                            .first
                        )
                        try:
                            if await option.count() > 0:
                                await option.wait_for(state="visible", timeout=3000)
                                await option.click(timeout=5000)
                                await asyncio.sleep(0.8)
                                selected_text = (
                                    await trigger.inner_text(timeout=3000) or ""
                                ).strip()
                                if label in selected_text or any(
                                    x in selected_text for x in labels
                                ):
                                    logger.info(
                                        "%s 已设置可见范围 visibility=%s -> %s",
                                        self.platform,
                                        visibility,
                                        selected_text,
                                    )
                                    return True
                        except Exception:
                            continue
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("%s 小红书可见范围直接设置失败: %s", self.platform, e)

        async def _selected_visible() -> bool:
            try:
                selected = await page.evaluate(
                    """(labels) => {
                      const norm = (s) => (s || '').trim().replace(/\\s+/g, '');
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 &&
                          s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      const hasLabel = (el) => labels.some(label => norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '').includes(norm(label)));
                      // Prefer explicit checked/selected radio/option controls.
                      for (const el of document.querySelectorAll('[aria-checked="true"],[aria-selected="true"],input:checked')) {
                        const root = el.closest('label,[role="radio"],[role="option"],li,div') || el;
                        if (visible(root) && hasLabel(root)) return true;
                      }
                      // Many creator UIs render the chosen visibility directly
                      // in a select/dropdown trigger rather than aria-checked.
                      for (const el of document.querySelectorAll('button,[role="button"],[role="combobox"],[class*="select"],[class*="dropdown"]')) {
                        if (visible(el) && hasLabel(el)) return true;
                      }
                      return false;
                    }""",
                    list(labels),
                )
                if selected:
                    return True
            except Exception:
                pass
            # Do not treat mere presence of option text as "selected".
            # Radio/dropdown menus often show every visibility option at once;
            # accepting body text caused private/friends checks to pass while
            # the default public option was still active.
            return False

        async def _click_visible_option() -> bool:
            try:
                clicked = await page.evaluate(
                    """(labels) => {
                      const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 &&
                          s.display !== 'none' && s.visibility !== 'hidden';
                      };
                      const normalize = (s) => (s || '').trim().replace(/\\s+/g, '');
                      const all = [...document.querySelectorAll('label,button,[role="button"],[role="option"],li,span,div')].filter(visible);
                      const matches = all.filter(el => {
                        const text = normalize(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                        if (!text) return false;
                        return labels.some(label => {
                          const needle = normalize(label);
                          return text === needle || (text.length <= 18 && text.includes(needle));
                        });
                      });
                      // Prefer overlay/dropdown options and lower on-screen controls,
                      // not sidebar menu items.
                      matches.sort((a, b) => {
                        const ra = a.getBoundingClientRect();
                        const rb = b.getBoundingClientRect();
                        const sa = (a.closest('[class*="popover"],[class*="dropdown"],[class*="select"],[role="listbox"]') ? 1000 : 0) + ra.y + ra.x / 1000;
                        const sb = (b.closest('[class*="popover"],[class*="dropdown"],[class*="select"],[role="listbox"]') ? 1000 : 0) + rb.y + rb.x / 1000;
                        return sb - sa;
                      });
                      for (const el of matches) {
                        const clickable = el.closest('.custom-option,.d-grid-item,label,button,[role="button"],[role="option"],li') || el;
                        clickable.scrollIntoView({block: 'center', inline: 'center'});
                        clickable.click();
                        return true;
                      }
                      return false;
                    }""",
                    list(labels),
                )
                if clicked:
                    await asyncio.sleep(0.6)
                    return True
            except Exception:
                pass
            return False

        # 1) If target option is already visible (radio row or open menu), click it.
        if await _click_visible_option():
            if await _selected_visible():
                return True

        # XHS keeps "who can see" under the lower publish-settings card.  The
        # text/DOM class names change often, so open dropdown-like rows from the
        # bottom settings area one by one and only accept the operation when the
        # requested target option can then be clicked/verified.  This prevents
        # the previous failure mode where private was requested but the page
        # stayed public.
        if self.platform == "xiaohongshu" and visibility in {
            "private",
            "friends",
            "public",
        }:
            try:
                await page.evaluate(
                    "() => window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})"
                )
                await asyncio.sleep(0.5)
                for idx in range(10):
                    opened = await page.evaluate(
                        """(idx) => {
                          const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = getComputedStyle(el);
                            return r.width > 0 && r.height > 0 &&
                              r.x >= 240 && r.x < innerWidth - 240 &&
                              r.y >= 90 && r.y < innerHeight - 80 &&
                              s.display !== 'none' && s.visibility !== 'hidden';
                          };
                          const bad = ['发布', '保存', '预览', '取消', 'Creator', 'Builder'];
                          const isSwitchLike = (el) => {
                            const cls = String(el.className || '').toLowerCase();
                            if (cls.includes('switch')) return true;
                            if (el.querySelector('[role="switch"],input[type="checkbox"],[class*="switch"],[class*="Switch"]')) return true;
                            return false;
                          };
                          const rows = [...document.querySelectorAll('button,[role="button"],[role="combobox"],label,div')]
                            .filter(visible)
                            .map(el => {
                              const r = el.getBoundingClientRect();
                              const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, '');
                              return {el, r, text, cls: String(el.className || '')};
                            })
                            .filter(x => x.r.width >= 220 && x.r.width <= 420 && x.r.height >= 32 && x.r.height <= 72)
                            .filter(x => x.text && !bad.some(b => x.text.includes(b)))
                            .filter(x => !isSwitchLike(x.el))
                            .filter(x => {
                              // Prefer rows that look like dropdown/select controls:
                              // role/combobox/select class, arrow/down icon, or
                              // "可见/公开/谁可以看" text when present.
                              const cls = x.cls.toLowerCase();
                              const role = x.el.getAttribute('role') || '';
                              const hasArrow = x.el.querySelector('[class*="arrow"],[class*="Arrow"],[class*="down"],[class*="Down"],svg');
                              return role === 'button' || role === 'combobox' || cls.includes('select') || cls.includes('dropdown') ||
                                hasArrow || /可见|公开|权限|谁/.test(x.text);
                            });
                          // Bottom-to-top: the visibility dropdown is below the
                          // editor in publish settings, while topic/location rows
                          // are usually above it.
                          rows.sort((a, b) => (b.r.y - a.r.y) || (a.r.x - b.r.x));
                          const item = rows[idx];
                          if (!item) return false;
                          item.el.scrollIntoView({block: 'center', inline: 'center'});
                          item.el.click();
                          return {text: item.text, x: item.r.x, y: item.r.y, w: item.r.width, h: item.r.height};
                        }""",
                        idx,
                    )
                    if not opened:
                        break
                    await asyncio.sleep(0.7)
                    if await _click_visible_option():
                        if await _selected_visible():
                            logger.info(
                                "%s 已设置可见范围 visibility=%s（XHS 设置区匹配）",
                                self.platform,
                                visibility,
                            )
                            return True
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug("%s XHS 可见范围设置区匹配失败: %s", self.platform, e)

        # 2) Open likely visibility controls (select/dropdown/radio group), then click option.
        try:
            opened = await page.evaluate(
                """() => {
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 &&
                      s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  const textOf = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                  const bad = ['高清发布', '发布视频', '发布图文', '发布全景视频', '发布文章', '上传视频'];
                  const anchors = ['谁可以看', '谁可见', '可见范围', '权限设置', '权限', '公开', '所有人可见', '好友可见', '朋友可见', '仅自己可见', '仅我可见', '私密'];
                  const controls = [];
                  for (const el of document.querySelectorAll('button,[role="button"],[role="combobox"],label,[class*="select"],[class*="dropdown"],[class*="radio"],span,div')) {
                    if (!visible(el)) continue;
                    const text = textOf(el).replace(/\\s+/g, '');
                    if (!text || bad.some(x => text.includes(x))) continue;
                    if (!anchors.some(x => text.includes(x))) continue;
                    const clickable = el.closest('.d-select-wrapper,.d-select,.d-select-main,button,[role="button"],[role="combobox"],label,[class*="dropdown"],[class*="radio"]') || el;
                    const r = clickable.getBoundingClientRect();
                    if (!visible(clickable)) continue;
                    const cls = String(clickable.className || '').toLowerCase();
                    const score =
                      (cls.includes('select') || cls.includes('dropdown') || clickable.getAttribute('role') === 'combobox' ? 1000 : 0) +
                      (text.includes('公开') || text.includes('权限') || text.includes('可见') ? 300 : 0) +
                      (r.x < 180 ? -1000 : 0) +
                      r.y + r.x / 1000;
                    controls.push({ el: clickable, score });
                  }
                  controls.sort((a, b) => b.score - a.score);
                  if (controls.length) {
                    controls[0].el.scrollIntoView({block: 'center', inline: 'center'});
                    controls[0].el.click();
                    return true;
                  }
                  return false;
                }"""
            )
            if opened:
                await asyncio.sleep(0.7)
                if await _click_visible_option():
                    if await _selected_visible():
                        return True
        except Exception:
            pass
        logger.warning(
            "%s 未能确认设置可见范围 visibility=%s labels=%s",
            self.platform,
            visibility,
            labels,
        )
        return visibility == "public"

    async def _fill_location(self, page, location: str) -> None:
        selectors = [
            'input[placeholder*="位置"]',
            'input[placeholder*="地理"]',
            'input[placeholder*="地址"]',
            'textarea[placeholder*="位置"]',
            'textarea[placeholder*="地址"]',
            '[role="combobox"][placeholder*="位置"]',
            '[role="combobox"]',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=800):
                    if await self._fill_control_text(loc, location):
                        await asyncio.sleep(0.8)
                        # 尝试选择第一个下拉建议，不强依赖
                        try:
                            await page.keyboard.press("ArrowDown")
                            await page.keyboard.press("Enter")
                        except Exception:
                            pass
                        return
            except Exception:
                continue

    async def _set_cover(self, page, cover_path: str) -> None:
        """设置封面图。"""
        cover_selectors = [
            'input[type="file"][accept*="image"]',
            '.cover-upload input[type="file"]',
            '[class*="cover"] input[type="file"]',
        ]
        for sel in cover_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.set_input_files(cover_path, timeout=30000)
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue
        logger.warning("%s 未找到封面上传入口", self.platform)

    async def _ensure_bilibili_cover_selected(self, page) -> None:
        """Select the first generated Bilibili video-frame cover when no cover is supplied."""
        try:
            selected = await self._evaluate_with_timeout(
                page,
                """async () => {
                  const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  const selected = document.querySelector('.img-item-cover-selected');
                  if (selected && visible(selected)) return 'already-selected';
                  const cards = [...document.querySelectorAll(
                    '.img-item-box.img-item-cover, .local-group .img-item-box, [class*="img-item-cover"]'
                  )].filter(visible);
                  const card = cards[0];
                  if (!card) return '';
                  card.scrollIntoView({block: 'center', inline: 'nearest'});
                  for (const type of ['mouseover', 'mousedown', 'mouseup', 'click']) {
                    card.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                  }
                  card.click();
                  await new Promise(resolve => setTimeout(resolve, 900));
                  return card.className || 'selected';
                }""",
                timeout=10,
            )
            if selected:
                logger.info(
                    "%s auto selected generated cover: %s", self.platform, selected
                )
        except Exception as exc:
            logger.info(
                "%s auto generated cover selection skipped: %s", self.platform, exc
            )

    async def _click_bilibili_submit(self, page) -> bool:
        """Invoke Bilibili's Vue submit method. DOM clicks can miss the component handler in headless mode."""
        try:
            invoked = await self._evaluate_with_timeout(
                page,
                """() => {
                  const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  const span = document.querySelector('.submit-add')
                    || [...document.querySelectorAll('button,div,span')]
                      .find(el => visible(el) && (el.innerText || el.textContent || '').replace(/\\s+/g, '').includes('立即投稿'));
                  let el = span;
                  while (el) {
                    const vm = el.__vue__;
                    if (vm && typeof vm.submitVideo === 'function') {
                      vm.submitVideo();
                      return 'vue-submitVideo';
                    }
                    el = el.parentElement;
                  }
                  if (span) {
                    span.click();
                    return 'dom-click';
                  }
                  return '';
                }""",
                timeout=10,
            )
            if invoked:
                logger.info("%s submitted via %s", self.platform, invoked)
                return True
        except Exception as exc:
            logger.debug("%s Vue submit fallback failed: %s", self.platform, exc)
        return False

    async def _click_publish_button(self, page) -> dict:
        """点击发布按钮。返回 {"clicked": bool, "error": str | None}。"""
        if self.platform == "xiaohongshu":
            try:
                host = page.locator("xhs-publish-btn").first
                if await host.count() > 0:
                    box = await host.bounding_box()
                    if box:
                        # xhs-publish-btn is a custom element. The public "发布"
                        # button is inside its shadow DOM on the right side.
                        await host.click(
                            position={
                                "x": box["width"] * 0.62,
                                "y": box["height"] * 0.5,
                            },
                            timeout=10000,
                        )
                        logger.info("%s 已点击发布按钮: xhs-publish-btn", self.platform)
                        return {"clicked": True, "error": None}
            except Exception as e:
                logger.debug("%s 点击 xhs-publish-btn 失败: %s", self.platform, e)

        # Prefer the real submit button in the main work area. The first
        # button containing "发布" on Douyin is often the left sidebar "高清发布"
        # menu, which only reopens the upload menu and does not publish.
        if self.platform == "bilibili":
            try:
                await self._evaluate_with_timeout(
                    page,
                    """() => {
                      const scrollables = [document.scrollingElement, document.documentElement, document.body,
                        ...document.querySelectorAll('div,main,section')];
                      for (const el of scrollables) {
                        if (!el) continue;
                        const canScroll = el.scrollHeight && el.clientHeight && el.scrollHeight > el.clientHeight + 20;
                        if (canScroll) el.scrollTop = el.scrollHeight;
                      }
                    }""",
                    timeout=6,
                )
                await asyncio.sleep(0.7)
                if await self._click_bilibili_submit(page):
                    return {"clicked": True, "error": None}
            except Exception as e:
                logger.debug("%s 滚动到发布按钮区域失败: %s", self.platform, e)

        try:
            clicked_text = await self._evaluate_with_timeout(
                page,
                """(labels) => {
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && r.x >= 200 && r.y >= 80 &&
                      r.x < innerWidth && r.y < innerHeight &&
                      s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  const disabled = (el) =>
                    el.disabled || el.getAttribute('aria-disabled') === 'true' ||
                    /disabled/.test(String(el.className || '').toLowerCase());
                  const norm = (s) => (s || '').trim().replace(/\\s+/g, '');
                  const bad = ['高清发布', '发布视频', '发布图文', '发布全景视频', '发布文章', '上传视频', '了解上传规则'];
                  const candidates = [...document.querySelectorAll('button,[role="button"],div,span')]
                    .filter(visible)
                    .map(el => {
                      const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                      const clickable = el.closest('button,[role="button"]') || el;
                      const r = clickable.getBoundingClientRect();
                      return {el: clickable, text, x: r.x, y: r.y, w: r.width, h: r.height, cls: String(clickable.className || '')};
                    })
                    .filter(x => labels.some(label => x.text === norm(label) || x.text === norm(label + '作品') || x.text === norm('立即' + label)))
                    .filter(x => !bad.some(b => x.text.includes(norm(b))) && visible(x.el) && !disabled(x.el));
                  candidates.sort((a, b) => {
                    const sa = a.y + (a.x > innerWidth / 2 ? 200 : 0) + (a.cls.includes('primary') ? 100 : 0);
                    const sb = b.y + (b.x > innerWidth / 2 ? 200 : 0) + (b.cls.includes('primary') ? 100 : 0);
                    return sb - sa;
                  });
                  if (candidates.length) {
                    candidates[0].el.click();
                    return candidates[0].text;
                  }
                  return '';
                }""",
                ["发布", "发表", "立即投稿", "发布笔记", "发布作品"],
                timeout=10,
            )
            if clicked_text:
                logger.info(
                    "%s 已点击发布按钮（主内容区匹配）: %s", self.platform, clicked_text
                )
                return {"clicked": True, "error": None}
        except Exception as e:
            logger.debug("%s 主内容区发布按钮匹配失败: %s", self.platform, e)

        selectors = _PLATFORM_PUBLISH_BUTTON_SELECTORS.get(
            self.platform, ['button:has-text("发布")', 'button:has-text("发表")']
        )
        for sel in selectors:
            try:
                loc = page.locator(sel).last
                if await loc.count() > 0:
                    # 等待按钮可点击
                    await loc.wait_for(state="visible", timeout=10000)
                    await loc.click()
                    logger.info("%s 已点击发布按钮: %s", self.platform, sel)
                    return {"clicked": True, "error": None}
            except Exception as e:
                logger.debug("%s 尝试选择器 %s 失败: %s", self.platform, sel, e)
                continue
        # 最后回退：找所有可见按钮中文字含"发布"或"发表"的
        try:
            buttons = page.get_by_role("button")
            count = await buttons.count()
            for i in range(count):
                btn = buttons.nth(i)
                text = (await btn.text_content() or "").strip()
                if text in ("发布", "发表", "立即投稿", "发布视频", "发布笔记"):
                    await btn.click()
                    logger.info(
                        "%s 已点击发布按钮（回退匹配）: %s", self.platform, text
                    )
                    return {"clicked": True, "error": None}
        except Exception:
            pass
        return {"clicked": False, "error": f"未找到 {self.platform} 的发布按钮"}

    # ===== 验证码 / 人机验证检测与处理（总开关 SYNAPSE_VERIFICATION_ENABLED）=====
    async def _detect_verification(self, page) -> tuple | None:
        """检测当前页面是否出现手机验证码或人机验证弹窗。

        返回：
            ("phone", hint)  - 手机验证码弹窗，hint 是手机号后4位或关键词
            ("human",)       - 人机验证（滑块/拼图/captcha canvas）
            None             - 未检测到验证弹窗

        任何异常都返回 None，避免检测失败中断发布主流程。
        检测只做一次 page.evaluate，不 sleep，速度快。
        优先级：若同时出现滑块/canvas/人机关键词则判人机，否则手机验证码。
        """
        self._last_verification_check_failed = False
        if not self._verification_enabled:
            return None
        try:
            data = await self._evaluate_with_timeout(
                page,
                """() => {
                    const body = (document.body && (document.body.innerText || document.body.textContent)) || '';
                    const visible = (el) => {
                      if (!el) return false;
                      const r = el.getBoundingClientRect();
                      const s = getComputedStyle(el);
                      return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                        s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
                    };
                    // 只在可见验证层/表单内匹配文案，避免页脚帮助文案里的
                    // “验证码/安全验证”让正常发布被误判。
                    const verificationRoots = [...document.querySelectorAll(
                      '[role="dialog"],[aria-modal="true"],[class*="captcha"],[class*="Captcha"],' +
                      '[id*="captcha"],[class*="geetest"],[class*="yidun"],[class*="slide-verify"],' +
                      '[class*="nc_wrapper"],[class*="verify-modal"],[class*="verification-modal"]'
                    )].filter(visible);
                    const verificationText = verificationRoots
                      .map(el => el.innerText || el.textContent || '')
                      .join('\\n');
                    // 手机验证码关键词（"安全验证"既可能是手机也可能是人机）
                    const phoneKw = ['验证码','手机验证','安全验证','发送验证码','获取验证码','短信验证'];
                    // 人机验证关键词
                    const humanKw = ['滑块','拖动','拼图','人机验证','请完成验证','拖动滑块','行为验证'];
                    let phoneHit = null, humanHit = null;
                    for (const k of phoneKw) { if (verificationText.indexOf(k) >= 0) { phoneHit = k; break; } }
                    for (const k of humanKw) { if (verificationText.indexOf(k) >= 0) { humanHit = k; break; } }
                    // 只识别明确的验证码组件。普通业务组件中也经常包含
                    // verify 类名，直接匹配 [class*=verify] 会把发布成功页误判
                    // 为人机验证；普通 canvas 也可能只是视频封面或图表。
                    let hasCaptchaEl = false;
                    try {
                      const sel = '[class*="captcha"],[class*="Captcha"],[id*="captcha"],'+
                        '[class*="geetest"],[class*="yidun"],[class*="slide-verify"],[class*="nc_wrapper"]';
                      hasCaptchaEl = [...document.querySelectorAll(sel)].some(visible);
                    } catch (e) {}
                    // 验证码输入框（手机验证码）
                    let hasCaptchaInput = false;
                    try {
                      hasCaptchaInput = [...document.querySelectorAll(
                        'input[placeholder*="验证码"],input[placeholder*="code"],input[name*="code"],input[name*="captcha"]'
                      )].some(visible);
                    } catch (e) {}
                    let hasCaptchaButton = false;
                    try {
                      hasCaptchaButton = [...document.querySelectorAll('button,[role="button"],a')]
                        .filter(visible)
                        .some(el => /发送验证码|获取验证码|短信验证/.test(
                          (el.innerText || el.textContent || '').trim()
                        ));
                    } catch (e) {}
                    // 提取手机号提示（兼容 131*****01 这类脱敏号码）
                    let phoneHint = '';
                    try {
                      const masked = body.match(/(1[3-9]\\d)[*＊xX·•]{2,8}(\\d{2,4})/);
                      const full = body.match(/1[3-9]\\d{7}(\\d{4})/);
                      if (masked) phoneHint = masked[1] + '****' + masked[2];
                      else if (full) phoneHint = '****' + full[1];
                    } catch (e) {}
                    return {
                      phoneHit, humanHit, hasCaptchaEl, hasCaptchaInput,
                      hasCaptchaButton, phoneHint
                    };
                }""",
                timeout=5,
            )
            if not data:
                return None
            phone_hit = data.get("phoneHit")
            human_hit = data.get("humanHit")
            has_captcha_el = bool(data.get("hasCaptchaEl"))
            has_captcha_input = bool(data.get("hasCaptchaInput"))
            has_captcha_button = bool(data.get("hasCaptchaButton"))
            phone_hint = data.get("phoneHint") or ""
            # 优先级：滑块/canvas/人机关键词优先判人机
            if human_hit or has_captcha_el:
                return ("human",)
            if has_captcha_input or (phone_hit and has_captcha_button):
                return ("phone", phone_hint or "账号绑定手机")
            return None
        except Exception as exc:
            self._last_verification_check_failed = True
            logger.debug("%s _detect_verification 异常（忽略）: %s", self.platform, exc)
            return None

    async def _handle_verification_during_publish(self, page, ver: tuple) -> str:
        """把发布过程中的所有人工验证交给同一个真实浏览器。

        Args:
            ver: ("phone", hint) 或 ("human",)

        Returns:
            "resume"   - 用户确认验证完成，继续等待发布成功
            "published"- 页面已自动检测到发布成功

        Raises:
            VerificationTimeout / VerificationDismissed / VerificationError:
                验证流程异常，由调用方记录为发布失败。
        """
        from app.integrations.synapse_engine.verification.manager import (
            verification_manager,
        )

        task_id = self._current_task_id
        account_id = self._current_account_id
        platform = self.platform
        if not task_id:
            # 没有任务上下文（例如手动调用 adapter 调试），无法走验证流程
            logger.warning(
                "%s 检测到验证但缺少 task_id，跳过验证处理", platform
            )
            return "resume"

        ver_type = ver[0] if ver else None

        if ver_type in {"phone", "human"}:
            try:
                screenshot_bytes = await page.screenshot(full_page=False)
            except Exception:
                screenshot_bytes = b""
            logger.info(
                "[verification] %s task=%s 检测到%s，展示当前真实浏览器",
                platform,
                task_id,
                "短信验证" if ver_type == "phone" else "安全验证",
            )

            native_session_id = self._native_publish_session_id or ""
            native_window_shown = False
            if native_session_id:
                from app.integrations.synapse_engine.native_browser import (
                    native_browser_manager,
                )

                # 不复制页面、不重新登录：直接显示自动化正在操作的同一个
                # 宿主 Chrome 窗口，用户在真实官网完成验证即可。
                try:
                    await page.bring_to_front()
                except Exception as exc:
                    logger.debug(
                        "[verification] page.bring_to_front 失败 task=%s: %s",
                        task_id,
                        exc,
                    )
                await native_browser_manager.show(native_session_id)
                native_window_shown = True

            # 写入任务状态并等待兼容的 resume 信号。正常情况下无需站内按钮：
            # 下面会持续观察真实页面，验证控件消失后自动恢复发布。
            wait_for_user = asyncio.create_task(
                verification_manager.request_human_captcha(
                    task_id=task_id,
                    platform=platform,
                    account_id=account_id or "",
                    page_screenshot_bytes=screenshot_bytes,
                    native_session_id=native_session_id,
                )
            )
            verification_clear_checks = 0
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {wait_for_user},
                        timeout=1.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if wait_for_user in done:
                        await wait_for_user
                        return "resume"

                    # 复用平台已有的成功 URL/成功文案判定。验证仍存在时该
                    # 方法会很快返回验证元组，不会误把验证页当成功页。
                    result = await self._wait_for_publish_success(page, timeout=2)
                    if result is True:
                        wait_for_user.cancel()
                        await asyncio.gather(wait_for_user, return_exceptions=True)
                        await verification_manager.complete_browser_verification(
                            task_id, auto_detected=True
                        )
                        return "published"
                    if isinstance(result, tuple):
                        verification_clear_checks = 0
                        continue

                    try:
                        verification_still_present = (
                            await self._detect_verification(page)
                        )
                    except Exception as exc:
                        # 页面执行瞬时失败不能当成“验证已消失”，否则可能在用户
                        # 尚未完成验证时过早恢复自动化。
                        verification_clear_checks = 0
                        logger.debug(
                            "[verification] 复查验证状态失败 task=%s: %s",
                            task_id,
                            exc,
                        )
                        continue
                    if self._last_verification_check_failed:
                        verification_clear_checks = 0
                        continue
                    if verification_still_present is None:
                        verification_clear_checks += 1
                    else:
                        verification_clear_checks = 0
                    if verification_clear_checks >= 3:
                        wait_for_user.cancel()
                        await asyncio.gather(wait_for_user, return_exceptions=True)
                        await verification_manager.complete_browser_verification(
                            task_id, auto_detected=True
                        )
                        logger.info(
                            "[verification] %s task=%s 验证控件已消失，自动继续发布",
                            platform,
                            task_id,
                        )
                        return "resume"
            finally:
                if not wait_for_user.done():
                    wait_for_user.cancel()
                    await asyncio.gather(wait_for_user, return_exceptions=True)
                if native_window_shown:
                    try:
                        await native_browser_manager.hide(native_session_id)
                    except Exception as exc:
                        # 外层发布服务仍会在任务结束时释放整个原生会话；
                        # 隐藏失败不应把已完成的验证改判为发布失败。
                        logger.warning(
                            "[verification] 隐藏原生浏览器失败 task=%s: %s",
                            task_id,
                            exc,
                        )

        return "resume"

    async def _trigger_phone_captcha_send(self, page) -> dict:
        """用真实浏览器点击触发短信发送，并采集页面倒计时状态。"""
        labels = (
            "获取验证码",
            "发送验证码",
            "获取短信验证码",
            "发送短信验证码",
            "重新获取",
            "重新发送",
        )
        clicked_label = ""

        # 优先使用 Playwright 的真实鼠标点击，避免站点拒绝不可信的 JS click 事件。
        for label in labels:
            locators = (
                page.get_by_role("button", name=label, exact=True),
                page.get_by_text(label, exact=True),
            )
            for locator in locators:
                try:
                    count = min(await locator.count(), 5)
                    for index in range(count):
                        candidate = locator.nth(index)
                        if not await candidate.is_visible():
                            continue
                        try:
                            if not await candidate.is_enabled():
                                continue
                        except Exception:
                            pass
                        await candidate.click(timeout=5000)
                        clicked_label = label
                        break
                except Exception as exc:
                    logger.debug(
                        "%s 点击短信按钮 %s 失败: %s", self.platform, label, exc
                    )
                if clicked_label:
                    break
            if clicked_label:
                break

        if not clicked_label:
            logger.warning(
                "[verification] %s 未找到可点击的短信验证码发送按钮",
                self.platform,
            )
            return {"clicked": False, "label": "", "state": "未找到发送按钮"}

        try:
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        state = ""
        try:
            result = await self._evaluate_with_timeout(
                page,
                """() => {
                    const body = (document.body && (document.body.innerText || document.body.textContent)) || '';
                    const countdown = body.match(/(?:重新获取|重新发送)?\\s*\\(?([1-9]\\d{0,2})\\s*(?:秒|s)\\)?/i);
                    if (countdown) return countdown[0].trim();
                    if (body.includes('重新获取')) return '重新获取';
                    if (body.includes('重新发送')) return '重新发送';
                    return '';
                }""",
                timeout=5,
            )
            state = str(result or "")
        except Exception:
            state = ""

        logger.info(
            "[verification] %s 已点击短信按钮=%s 页面状态=%s",
            self.platform,
            clicked_label,
            state or "等待短信",
        )
        return {"clicked": True, "label": clicked_label, "state": state}

    async def _fill_phone_captcha_and_confirm(self, page, code: str) -> dict:
        """在页面上找到验证码输入框填入 code，并点击"确认/确定"按钮。

        使用 Playwright 的真实 fill/click 触发 React/Vue 受控组件，再等待平台明确
        接受（输入框消失）或返回验证码错误。返回 {accepted, error}。
        """
        if not code:
            return {"accepted": False, "error": "验证码为空"}

        input_filled = False
        input_selectors = (
            'input[placeholder*="验证码"]',
            'input[placeholder*="code"]',
            'input[name*="code"]',
            'input[name*="captcha"]',
        )
        for selector in input_selectors:
            try:
                locator = page.locator(selector)
                count = min(await locator.count(), 5)
                for index in range(count):
                    candidate = locator.nth(index)
                    if not await candidate.is_visible():
                        continue
                    await candidate.fill(str(code), timeout=5000)
                    input_filled = True
                    break
            except Exception as exc:
                logger.debug("%s 验证码输入框 %s 填写失败: %s", self.platform, selector, exc)
            if input_filled:
                break
        if not input_filled:
            return {"accepted": False, "error": "未找到验证码输入框"}

        confirm_clicked = False
        for label in ("验证", "确认", "确定", "提交验证码", "确认提交"):
            for locator in (
                page.get_by_role("button", name=label, exact=True),
                page.get_by_text(label, exact=True),
            ):
                try:
                    count = min(await locator.count(), 5)
                    for index in range(count):
                        candidate = locator.nth(index)
                        if not await candidate.is_visible():
                            continue
                        try:
                            if not await candidate.is_enabled():
                                continue
                        except Exception:
                            pass
                        await candidate.click(timeout=5000)
                        confirm_clicked = True
                        break
                except Exception as exc:
                    logger.debug("%s 验证按钮 %s 点击失败: %s", self.platform, label, exc)
                if confirm_clicked:
                    break
            if confirm_clicked:
                break
        if not confirm_clicked:
            return {"accepted": False, "error": "未找到可点击的验证按钮"}

        return await self._wait_phone_captcha_result(page, timeout=20)

    async def _wait_phone_captcha_result(self, page, timeout: int = 20) -> dict:
        """等待短信验证码弹窗消失，或读取平台返回的明确错误。"""
        deadline = time.monotonic() + max(1, timeout)
        while time.monotonic() < deadline:
            try:
                state = await self._evaluate_with_timeout(
                    page,
                    """() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const r = el.getBoundingClientRect();
                            const s = getComputedStyle(el);
                            return r.width > 0 && r.height > 0 &&
                              s.display !== 'none' && s.visibility !== 'hidden';
                        };
                        const body = (document.body && (document.body.innerText || document.body.textContent)) || '';
                        const input = [...document.querySelectorAll(
                          'input[placeholder*="验证码"],input[placeholder*="code"],input[name*="code"],input[name*="captcha"]'
                        )].find(visible);
                        const errors = [
                          '验证码错误','验证码不正确','验证码有误','验证码已失效',
                          '验证码过期','验证码无效','验证失败','请重新获取验证码'
                        ];
                        const error = errors.find(text => body.includes(text)) || '';
                        return {inputVisible: Boolean(input), error};
                    }""",
                    timeout=5,
                )
            except Exception:
                state = None
            if state:
                if state.get("error"):
                    return {"accepted": False, "error": state["error"]}
                if not state.get("inputVisible"):
                    logger.info("[verification] %s 短信验证码已被平台接受", self.platform)
                    return {"accepted": True, "error": ""}
            await asyncio.sleep(0.5)
        return {
            "accepted": False,
            "error": "平台未确认验证码，请检查验证码是否正确后重试",
        }

    async def _wait_for_publish_success(self, page, timeout: int = 60) -> bool:
        """等待发布成功（URL 跳转到管理页/成功页）。

        Args:
            page: Playwright page
            timeout: 最大等待秒数

        Returns:
            True 表示检测到成功跳转；False 表示超时未跳转
        """
        patterns = _PLATFORM_SUCCESS_URL_PATTERNS.get(self.platform, [])
        if not patterns:
            # 没有配置成功 URL 模式，只等待 5 秒看是否有跳转
            try:
                await page.wait_for_url(
                    lambda url: url != self.publish_url, timeout=10000
                )
                return True
            except Exception:
                return False

        compiled = [re.compile(p) for p in patterns]
        deadline = time.time() + timeout
        confirm_clicked = False
        while time.time() < deadline:
            # 成功 URL 必须优先于验证码检测。小红书发布完成后会回到上传页并
            # 带上 published=true；页面常驻组件含 verify 类名，旧顺序会误弹
            # 人工验证，导致已经发布的任务仍停在“需人机验证”。
            try:
                current_url = page.url
                for pat in compiled:
                    if pat.search(current_url):
                        logger.info("%s 发布成功跳转到: %s", self.platform, current_url)
                        return True
            except Exception:
                pass
            # ===== 验证码/人机验证检测（总开关开启时）=====
            # 检测到验证弹窗则中断等待，把元组返回给 publish_content 处理。
            if self._verification_enabled:
                try:
                    ver = await self._detect_verification(page)
                except Exception:
                    ver = None
                if ver is not None:
                    return ver  # ("phone", hint) 或 ("human",)
            try:
                if not confirm_clicked:
                    try:
                        clicked_confirm = await self._evaluate_with_timeout(
                            page,
                            """() => {
                              const labels = ['确认发布', '确定发布', '仍要发布', '确认', '确定'];
                              const visible = (el) => {
                                const r = el.getBoundingClientRect();
                                const s = getComputedStyle(el);
                                return r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0 &&
                                  r.x < innerWidth && r.y < innerHeight &&
                                  s.display !== 'none' && s.visibility !== 'hidden';
                              };
                              for (const el of document.querySelectorAll('button,[role="button"]')) {
                                if (!visible(el)) continue;
                                const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
                                if (labels.includes(text)) {
                                  el.click();
                                  return true;
                                }
                              }
                              return false;
                            }""",
                            timeout=5,
                        )
                        if clicked_confirm:
                            confirm_clicked = True
                            await asyncio.sleep(1)
                    except Exception:
                        pass
                # 检查是否有成功提示弹窗
                try:
                    success_toast = page.locator(
                        '[class*="success"]:has-text("成功"), [class*="toast"]:has-text("成功")'
                    )
                    if await success_toast.count() > 0:
                        logger.info("%s 发布成功（检测到成功提示）", self.platform)
                        return True
                except Exception:
                    pass
                try:
                    body_text = await page.locator("body").inner_text(timeout=2500)
                    if self.platform == "bilibili" and (
                        "\u4e0a\u4f20\u6210\u529f" in body_text
                        or (
                            "\u67e5\u770b\u8fdb\u5ea6" in body_text
                            and "\u518d\u6295\u4e00\u4e2a" in body_text
                        )
                    ):
                        logger.info(
                            "%s publish success detected from Bilibili success text",
                            self.platform,
                        )
                        return True
                    if re.search(
                        r"(发布成功|投稿成功|作品已发布|提交成功|已提交审核|发布任务已提交)",
                        body_text,
                    ):
                        logger.info("%s 发布成功（检测到成功文案）", self.platform)
                        return True
                except Exception:
                    pass
            except Exception:
                pass
            await asyncio.sleep(1)
        return False


def get_adapter(platform: str, config: dict | None = None) -> PlatformAdapter:
    """工厂方法：返回指定平台的内置适配器实例。"""
    # 延迟导入避免基类与各平台子类循环依赖。平台独立成文件后，后续 DOM
    # 变化只需修改对应适配器，不再继续膨胀本通用基类。
    from app.integrations.synapse_engine.platforms.adapters import (
        ADAPTER_REGISTRY,
    )

    cls = ADAPTER_REGISTRY.get(platform, BuiltinPlatformAdapter)
    return cls(platform=platform, config=config)


__all__ = ["BuiltinPlatformAdapter", "get_adapter"]
