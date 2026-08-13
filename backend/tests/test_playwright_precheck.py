"""Playwright 浏览器预检测试。

验证 /social/accounts/login/start 在 Playwright Chromium 未安装时：
1. 返回 400（不是 500）
2. detail 为可读中文，不含英文 stack trace
3. 不创建假 session（_login_sessions 不会新增条目）

通过 app.dependency_overrides 绕过 auth 依赖，不需要真实 DB。
"""

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.deps import get_current_user
from app.main import app
from app.models.user import User
from app.integrations.synapse_engine.utils.playwright_provider import (
    assert_chromium_ready,
)


class _FakeUser(User):
    """不落库的假用户，仅用于绕过 auth 依赖。"""

    def __init__(self):
        object.__setattr__(self, "id", uuid.uuid4())
        object.__setattr__(self, "role", "admin")
        object.__setattr__(self, "is_active", True)


@pytest.fixture
async def client():
    async def _fake_get_current_user():
        return _FakeUser()

    app.dependency_overrides[get_current_user] = _fake_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://health.internal"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_login_start_returns_chinese_error_when_browser_missing(
    client, monkeypatch
):
    """Playwright 浏览器缺失时返回 400 + 中文错误，不返回 500 英文 stack。"""
    from app.api.v1 import social_accounts as sa

    def _raise_missing():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Playwright Chromium 浏览器未安装，请在后端环境执行：python -m playwright install chromium",
        )

    monkeypatch.setattr(sa, "_check_playwright_browser", _raise_missing)

    resp = await client.post(
        "/api/v1/social/accounts/login/start",
        json={"platform": "xiaohongshu"},
    )

    # 必须是 400，不是 500
    assert resp.status_code == 400
    detail = resp.json().get("message", "")
    # 必须是中文可读错误
    assert "Playwright Chromium 浏览器未安装" in detail
    # 不能含英文 stack trace 标志
    assert "Executable doesn't exist" not in detail
    assert "Traceback" not in detail


@pytest.mark.asyncio
async def test_login_start_no_fake_session_on_browser_missing(client, monkeypatch):
    """浏览器缺失时不创建假 session。"""
    from app.api.v1 import social_accounts as sa
    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    def _raise_missing():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Playwright Chromium 浏览器未安装，请在后端环境执行：python -m playwright install chromium",
        )

    monkeypatch.setattr(sa, "_check_playwright_browser", _raise_missing)

    service = EmbeddedSynapseService()
    session_count_before = len(service._login_sessions)

    await client.post(
        "/api/v1/social/accounts/login/start",
        json={"platform": "xiaohongshu"},
    )

    session_count_after = len(service._login_sessions)
    # 不应新增任何 session
    assert session_count_after == session_count_before


@pytest.mark.asyncio
async def test_login_start_catches_playwright_executable_error(client, monkeypatch):
    """即使预检通过但 launch 时报 Executable doesn't exist，也应返回中文 400。"""
    from app.api.v1 import social_accounts as sa

    # 预检通过（不 raise）
    monkeypatch.setattr(sa, "_check_playwright_browser", lambda: None)

    # 让 service.start_login 抛出 Playwright 英文错误
    async def _fake_start_login(self, platform, account_id=None):
        raise RuntimeError(
            "BrowserType.launch: Executable doesn't exist at "
            "/ms-playwright/chromium_headless_shell-1148/chrome-linux/headless_shell\n"
            "Looks like Playwright was just installed or updated. Please run:\n"
            "playwright install"
        )

    from app.integrations.synapse_engine.service import EmbeddedSynapseService

    monkeypatch.setattr(EmbeddedSynapseService, "start_login", _fake_start_login)

    resp = await client.post(
        "/api/v1/social/accounts/login/start",
        json={"platform": "xiaohongshu"},
    )

    # 应返回 400 + 中文，不是 500 + 英文
    assert resp.status_code == 400
    detail = resp.json().get("message", "")
    assert "Playwright Chromium 浏览器未安装" in detail
    assert "Executable doesn't exist" not in detail


def test_precheck_uses_regular_chromium_fallback_when_headless_shell_missing(
    tmp_path, monkeypatch
):
    """Only regular chromium exists: use it as executable_path fallback."""
    root = tmp_path / "ms-playwright"
    chrome = root / "chromium-1148" / "chrome-linux" / "chrome"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("fake")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))

    assert Path(assert_chromium_ready(headless=True)) == chrome


def test_precheck_accepts_headless_shell(tmp_path, monkeypatch):
    root = tmp_path / "ms-playwright"
    shell = root / "chromium_headless_shell-1148" / "chrome-linux" / "headless_shell"
    shell.parent.mkdir(parents=True)
    shell.write_text("fake")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))

    assert Path(assert_chromium_ready(headless=True)) == shell
