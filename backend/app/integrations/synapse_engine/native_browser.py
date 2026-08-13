"""Mac 宿主机原生浏览器管理器客户端。

账号授权和发布自动化都可请求宿主机管理器启动真实 Chrome，再通过 CDP
接管该浏览器。发布窗口平时可隐藏，遇到人工验证时再直接显示。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


class NativeBrowserError(RuntimeError):
    """宿主机原生浏览器管理器不可用或返回了无效响应。"""


class NativeBrowserManager:
    def _settings(self):
        return get_settings()

    def _base_url(self) -> str:
        url = self._settings().SYNAPSE_NATIVE_BROWSER_MANAGER_URL.strip().rstrip("/")
        if not url:
            raise NativeBrowserError("未配置原生浏览器管理器地址")
        return url

    def _headers(self) -> dict[str, str]:
        token = self._settings().SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN.strip()
        if not token:
            return {}
        # 同时兼容独立管理器的专用请求头和标准 Bearer 鉴权。
        return {
            "X-Native-Bridge-Token": token,
            "Authorization": f"Bearer {token}",
        }

    @staticmethod
    def _unwrap(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise NativeBrowserError(
                f"原生浏览器管理器返回了非 JSON 响应（HTTP {response.status_code}）"
            ) from exc
        if response.is_error:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise NativeBrowserError(
                str(detail or f"原生浏览器管理器请求失败（HTTP {response.status_code}）")
            )
        if not isinstance(payload, dict):
            raise NativeBrowserError("原生浏览器管理器返回格式错误")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    async def acquire(
        self,
        *,
        platform: str,
        account_id: str,
        task_id: str,
        ttl_seconds: int = 360,
        visible: bool = True,
        purpose: str = "login",
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(35.0, connect=5.0),
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{self._base_url()}/sessions",
                    headers=self._headers(),
                    json={
                        "platform": platform,
                        "account_id": account_id,
                        "task_id": task_id,
                        "ttl": ttl_seconds,
                        "visible": bool(visible),
                        "purpose": purpose,
                    },
                )
        except (httpx.HTTPError, OSError) as exc:
            raise NativeBrowserError(f"无法连接 Mac 原生浏览器服务：{exc}") from exc

        session = self._unwrap(response)
        if not session.get("session_id") or not session.get("cdp_url"):
            raise NativeBrowserError("原生浏览器服务未返回 session_id 或 cdp_url")
        return session

    async def show(self, session_id: str) -> dict[str, Any]:
        """显示并置前指定的宿主 Chrome 会话。"""
        if not session_id:
            raise NativeBrowserError("原生浏览器 session_id 为空")
        try:
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                response = await client.post(
                    f"{self._base_url()}/sessions/{session_id}/show",
                    headers=self._headers(),
                )
        except (httpx.HTTPError, OSError) as exc:
            raise NativeBrowserError(f"无法显示 Mac 原生浏览器：{exc}") from exc
        return self._unwrap(response)

    async def hide(self, session_id: str) -> dict[str, Any]:
        """把指定的宿主 Chrome 会话移回后台并隐藏。"""
        if not session_id:
            raise NativeBrowserError("原生浏览器 session_id 为空")
        try:
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                response = await client.post(
                    f"{self._base_url()}/sessions/{session_id}/hide",
                    headers=self._headers(),
                )
        except (httpx.HTTPError, OSError) as exc:
            raise NativeBrowserError(f"无法隐藏 Mac 原生浏览器：{exc}") from exc
        return self._unwrap(response)

    async def heartbeat(self, session_id: str) -> None:
        if not session_id:
            return
        try:
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                response = await client.post(
                    f"{self._base_url()}/sessions/{session_id}/heartbeat",
                    headers=self._headers(),
                )
            self._unwrap(response)
        except NativeBrowserError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise NativeBrowserError(f"原生浏览器心跳失败：{exc}") from exc

    async def release(self, session_id: str) -> None:
        if not session_id:
            return
        try:
            async with httpx.AsyncClient(timeout=12.0, trust_env=False) as client:
                response = await client.delete(
                    f"{self._base_url()}/sessions/{session_id}",
                    headers=self._headers(),
                )
            if response.status_code != 404:
                self._unwrap(response)
        except (httpx.HTTPError, OSError) as exc:
            raise NativeBrowserError(f"关闭原生浏览器失败：{exc}") from exc


native_browser_manager = NativeBrowserManager()
