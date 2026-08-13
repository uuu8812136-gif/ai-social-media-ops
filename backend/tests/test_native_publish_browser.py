"""宿主真实 Chrome 发布与人工验证链路的回归测试。"""

from __future__ import annotations

import asyncio

import pytest


class _FakePublishAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.remote_cdp_url = ""
        self.reuse_default_context = None
        self.native_session_id = ""
        self.publish_kwargs = None

    def set_remote_cdp_url(
        self, cdp_url: str | None, *, reuse_default_context: bool = False
    ) -> None:
        self.remote_cdp_url = cdp_url or ""
        self.reuse_default_context = reuse_default_context

    def set_native_publish_session(self, session_id: str | None) -> None:
        self.native_session_id = session_id or ""

    async def publish_content(self, **kwargs):
        self.publish_kwargs = kwargs
        if self.fail:
            raise RuntimeError("simulated publish failure")
        return {"success": True, "status": "published"}


@pytest.mark.asyncio
async def test_publish_uses_hidden_native_browser_and_releases_it(monkeypatch):
    from app.integrations.synapse_engine import service as service_mod
    from app.integrations.synapse_engine.native_browser import (
        native_browser_manager,
    )

    adapter = _FakePublishAdapter()
    acquired = []
    released = []

    monkeypatch.setattr(
        service_mod, "get_platform_adapter", lambda _platform: adapter
    )
    service = service_mod.EmbeddedSynapseService()
    monkeypatch.setattr(
        service.cookie_manager,
        "load",
        lambda _platform, _account: {"cookies": [], "origins": []},
    )
    monkeypatch.setattr(
        service.settings, "SYNAPSE_PUBLISH_BROWSER_MODE", "native_host"
    )

    async def fake_acquire(**kwargs):
        acquired.append(kwargs)
        return {
            "session_id": "native-publish-session",
            "cdp_url": "ws://host.docker.internal:39221/devtools/browser/test",
        }

    async def fake_release(session_id):
        released.append(session_id)

    monkeypatch.setattr(native_browser_manager, "acquire", fake_acquire)
    monkeypatch.setattr(native_browser_manager, "release", fake_release)

    result = await service.publish_content(
        platform="douyin",
        account_id="account-1",
        title="title",
        description="body",
    )

    assert result["success"] is True
    assert acquired[0]["visible"] is False
    assert acquired[0]["ttl_seconds"] == 1800
    assert adapter.remote_cdp_url.startswith("ws://host.docker.internal:")
    assert adapter.reuse_default_context is False
    assert adapter.native_session_id == "native-publish-session"
    assert released == ["native-publish-session"]


@pytest.mark.asyncio
async def test_publish_releases_native_browser_after_failure(monkeypatch):
    from app.integrations.synapse_engine import service as service_mod
    from app.integrations.synapse_engine.native_browser import (
        native_browser_manager,
    )

    adapter = _FakePublishAdapter(fail=True)
    released = []
    monkeypatch.setattr(
        service_mod, "get_platform_adapter", lambda _platform: adapter
    )
    service = service_mod.EmbeddedSynapseService()
    monkeypatch.setattr(
        service.cookie_manager,
        "load",
        lambda _platform, _account: {"cookies": [], "origins": []},
    )
    monkeypatch.setattr(
        service.settings, "SYNAPSE_PUBLISH_BROWSER_MODE", "native_host"
    )

    async def fake_acquire(**_kwargs):
        return {
            "session_id": "native-failed-session",
            "cdp_url": "ws://host.docker.internal:39222/devtools/browser/test",
        }

    async def fake_release(session_id):
        released.append(session_id)

    monkeypatch.setattr(native_browser_manager, "acquire", fake_acquire)
    monkeypatch.setattr(native_browser_manager, "release", fake_release)

    result = await service.publish_content(
        platform="douyin",
        account_id="account-1",
        title="title",
        description="body",
    )

    assert result["success"] is False
    assert result["status"] == "publish_error"
    assert released == ["native-failed-session"]


class _FakePage:
    def __init__(self) -> None:
        self.brought_to_front = False

    async def screenshot(self, **_kwargs):
        return b"png"

    async def bring_to_front(self):
        self.brought_to_front = True


@pytest.mark.asyncio
async def test_verification_shows_native_window_and_auto_resumes(monkeypatch):
    from app.integrations.synapse_engine.native_browser import (
        native_browser_manager,
    )
    from app.integrations.synapse_engine.platforms.builtin import (
        BuiltinPlatformAdapter,
    )
    from app.integrations.synapse_engine.verification.manager import (
        verification_manager,
    )

    adapter = BuiltinPlatformAdapter("douyin")
    adapter._current_task_id = "task-1"
    adapter._current_account_id = "account-1"
    adapter.set_native_publish_session("native-session-1")
    shown = []
    hidden = []
    completed = []
    request_kwargs = []

    async def fake_show(session_id):
        shown.append(session_id)
        return {"session_id": session_id, "visible": True}

    async def fake_hide(session_id):
        hidden.append(session_id)
        return {"session_id": session_id, "visible": False}

    async def fake_request(**kwargs):
        request_kwargs.append(kwargs)
        await asyncio.Event().wait()

    async def fake_complete(task_id, *, auto_detected=False):
        completed.append((task_id, auto_detected))

    async def fake_wait_for_success(_page, timeout=60):
        return False

    async def fake_detect(_page):
        return None

    monkeypatch.setattr(native_browser_manager, "show", fake_show)
    monkeypatch.setattr(native_browser_manager, "hide", fake_hide)
    monkeypatch.setattr(
        verification_manager, "request_human_captcha", fake_request
    )
    monkeypatch.setattr(
        verification_manager, "complete_browser_verification", fake_complete
    )
    monkeypatch.setattr(
        adapter, "_wait_for_publish_success", fake_wait_for_success
    )
    monkeypatch.setattr(adapter, "_detect_verification", fake_detect)

    page = _FakePage()
    outcome = await adapter._handle_verification_during_publish(page, ("human",))

    assert outcome == "resume"
    assert page.brought_to_front is True
    assert shown == ["native-session-1"]
    assert hidden == ["native-session-1"]
    assert request_kwargs[0]["native_session_id"] == "native-session-1"
    assert completed == [("task-1", True)]


@pytest.mark.asyncio
async def test_verification_keywords_without_visible_component_are_ignored(
    monkeypatch,
):
    from app.integrations.synapse_engine.platforms.builtin import (
        BuiltinPlatformAdapter,
    )

    adapter = BuiltinPlatformAdapter("douyin")

    async def fake_evaluate(*_args, **_kwargs):
        return {
            "phoneHit": "验证码",
            "humanHit": None,
            "hasCaptchaEl": False,
            "hasCaptchaInput": False,
            "hasCaptchaButton": False,
            "phoneHint": "",
        }

    monkeypatch.setattr(adapter, "_evaluate_with_timeout", fake_evaluate)
    assert await adapter._detect_verification(object()) is None


@pytest.mark.asyncio
async def test_visible_captcha_input_is_detected_as_phone(monkeypatch):
    from app.integrations.synapse_engine.platforms.builtin import (
        BuiltinPlatformAdapter,
    )

    adapter = BuiltinPlatformAdapter("douyin")

    async def fake_evaluate(*_args, **_kwargs):
        return {
            "phoneHit": None,
            "humanHit": None,
            "hasCaptchaEl": False,
            "hasCaptchaInput": True,
            "hasCaptchaButton": False,
            "phoneHint": "138****1234",
        }

    monkeypatch.setattr(adapter, "_evaluate_with_timeout", fake_evaluate)
    assert await adapter._detect_verification(object()) == (
        "phone",
        "138****1234",
    )


@pytest.mark.asyncio
async def test_native_mode_never_returns_legacy_vnc_session(monkeypatch):
    from types import SimpleNamespace

    from app.integrations.synapse_engine.verification.manager import (
        verification_manager,
    )

    task = SimpleNamespace(
        verification_meta={
            "scheme": "worker_shared",
            "vnc_session_id": "stale-worker-session",
            "vnc_password": "stale-password",
        }
    )

    async def fake_get_task(_task_id):
        return task

    monkeypatch.setattr(verification_manager, "_get_task", fake_get_task)
    monkeypatch.setattr(
        verification_manager.settings,
        "SYNAPSE_PUBLISH_BROWSER_MODE",
        "native_host",
    )

    result = await verification_manager.get_vnc_session("task-1")
    assert result["session_id"] == ""
    assert result["vnc_password"] == ""
    assert result["presentation"] == "native_window"


@pytest.mark.asyncio
async def test_native_mode_does_not_expose_pending_popup_items(monkeypatch):
    from app.integrations.synapse_engine.verification.manager import (
        verification_manager,
    )

    monkeypatch.setattr(
        verification_manager.settings,
        "SYNAPSE_PUBLISH_BROWSER_MODE",
        "native_host",
    )

    assert await verification_manager.pending_verifications() == []
