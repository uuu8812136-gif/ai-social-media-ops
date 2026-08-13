"""Synapse 可视网页登录 session_id 一致性测试。

验证：
1. start_login 返回的 session_id 与 adapter.start_visual_login() 生成的一致
2. poll_login_status 用该 session_id 能找到会话（不会返回 expired/session不存在）
3. poll_login_status 返回的状态与 adapter.poll_status() 返回的一致
4. 不存在的 session_id 应返回 expired

不依赖 DB 和真实浏览器，通过 mock adapter 实现。
"""

import pytest

from app.integrations.synapse_engine.platforms.base import (
    LoginResult,
    LoginStatus,
    QRCodeData,
)


class _FakeAdapter:
    """模拟平台适配器，不启动真实浏览器。

    模拟 adapter 内部自己生成 session_id 并维护会话状态的行为，
    复刻真实 BuiltinPlatformAdapter 的 session 管理逻辑。
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._sessions: dict[str, dict] = {}
        self.visual_login_started = False

    async def get_qrcode(self) -> QRCodeData:
        """生成二维码时内部创建 session_id（复刻真实 adapter 行为）。"""
        session_id = "fake_session_001"
        self._sessions[session_id] = {"status": LoginStatus.WAITING}
        return QRCodeData(
            session_id=session_id,
            qr_url="https://example.com/qr/001",
            qr_image="data:image/png;base64,ZmFrZQ==",
            expires_in=300,
        )

    async def start_visual_login(self) -> QRCodeData:
        self.visual_login_started = True
        session_id = "fake_session_001"
        self._sessions[session_id] = {"status": LoginStatus.WAITING}
        return QRCodeData(
            session_id=session_id,
            qr_url="https://example.com/login",
            qr_image="",
            expires_in=300,
        )

    async def poll_status(self, session_id: str) -> LoginResult:
        sess = self._sessions.get(session_id)
        if not sess:
            return LoginResult(status=LoginStatus.EXPIRED, message="session 不存在")
        return LoginResult(status=sess["status"], message="等待扫码")

    async def cleanup_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class _FakeRemoteAdapter(_FakeAdapter):
    def __init__(self, config=None):
        super().__init__(config)
        self.remote_cdp_url = None

    def set_remote_cdp_url(self, cdp_url: str | None) -> None:
        self.remote_cdp_url = cdp_url


@pytest.mark.asyncio
async def test_start_login_returns_adapter_session_id(monkeypatch):
    """start_login 返回的 session_id 必须与可视登录适配器内部生成的一致。

    这是修复的核心：service 不能再自己生成 session_id，必须复用 qr.session_id。
    """
    from app.integrations.synapse_engine import service as service_mod

    fake_adapter = _FakeAdapter()

    def fake_get_adapter(platform, config=None):
        return fake_adapter

    monkeypatch.setattr(service_mod, "get_platform_adapter", fake_get_adapter)

    service = service_mod.EmbeddedSynapseService()
    service._login_sessions.clear()

    result = await service.start_login("xiaohongshu")

    # session_id 必须是 adapter 内部生成的那个，而不是 service 自己 uuid 生成的
    assert result["session_id"] == "fake_session_001"
    assert result["qr_image"] == ""
    assert result["login_mode"] == "visual_browser"
    assert result["platform"] == "xiaohongshu"
    assert fake_adapter.visual_login_started is True


@pytest.mark.asyncio
async def test_poll_status_finds_same_session(monkeypatch):
    """poll_login_status 用 start_login 返回的 session_id 能找到会话。

    修复前：service 用自生成的 session_id，poll 时传给 adapter.poll_status
    查不到内部会话，返回 expired。修复后应能查到并返回 waiting。
    """
    from app.integrations.synapse_engine import service as service_mod

    fake_adapter = _FakeAdapter()

    def fake_get_adapter(platform, config=None):
        return fake_adapter

    monkeypatch.setattr(service_mod, "get_platform_adapter", fake_get_adapter)

    service = service_mod.EmbeddedSynapseService()
    service._login_sessions.clear()

    # 启动登录
    login_result = await service.start_login("xiaohongshu")
    session_id = login_result["session_id"]

    # 用同一个 session_id 轮询，应能找到 adapter 内部会话
    poll_result = await service.poll_login_status(session_id)

    # 不应返回 expired/session不存在
    assert poll_result["status"] != "expired"
    assert "不存在" not in (poll_result.get("message") or "")
    # 应返回 waiting 状态（adapter 内部会话的状态）
    assert poll_result["status"] == "waiting"


@pytest.mark.asyncio
async def test_session_id_stored_in_login_sessions(monkeypatch):
    """start_login 后 _login_sessions 中存的 session_id 与返回值一致。"""
    from app.integrations.synapse_engine import service as service_mod

    fake_adapter = _FakeAdapter()

    def fake_get_adapter(platform, config=None):
        return fake_adapter

    monkeypatch.setattr(service_mod, "get_platform_adapter", fake_get_adapter)

    service = service_mod.EmbeddedSynapseService()
    service._login_sessions.clear()

    result = await service.start_login("xiaohongshu")
    session_id = result["session_id"]

    # service 内部 _login_sessions 应该用同一个 session_id 作为 key
    assert session_id in service._login_sessions
    # 存的 adapter 应该是同一个 fake_adapter
    assert service._login_sessions[session_id]["adapter"] is fake_adapter


@pytest.mark.asyncio
async def test_poll_status_unknown_session_returns_expired(monkeypatch):
    """用不存在的 session_id 轮询应返回 expired。"""
    from app.integrations.synapse_engine import service as service_mod

    service = service_mod.EmbeddedSynapseService()
    service._login_sessions.clear()

    result = await service.poll_login_status("nonexistent_session_id")
    assert result["status"] == "expired"
    assert "不存在" in (result.get("message") or "")


@pytest.mark.asyncio
async def test_login_exposes_and_releases_manual_browser_session(monkeypatch):
    """内置适配器应接管可视浏览器，并把人工认证入口返回给前端。"""
    from app.integrations.synapse_engine import service as service_mod
    from app.integrations.synapse_engine.verification.manager import (
        verification_manager,
    )

    fake_adapter = _FakeRemoteAdapter()
    released = []

    monkeypatch.setattr(
        service_mod,
        "get_platform_adapter",
        lambda platform, config=None: fake_adapter,
    )

    async def fake_acquire(platform, account_id, task_id):
        return {
            "session_id": "vnc_session_001",
            "cdp_url": "http://browser-vnc:9221",
            "vnc_password": "secret",
        }

    async def fake_release(session_id):
        released.append(session_id)

    monkeypatch.setattr(
        verification_manager, "acquire_vnc_session_from_manager", fake_acquire
    )
    monkeypatch.setattr(verification_manager, "release_vnc_session", fake_release)

    service = service_mod.EmbeddedSynapseService()
    service._login_sessions.clear()
    monkeypatch.setattr(service.settings, "SYNAPSE_LOGIN_BROWSER_MODE", "vnc")

    result = await service.start_login("douyin")
    assert fake_adapter.remote_cdp_url == "http://browser-vnc:9221"
    assert result["manual_verification"] == {
        "available": True,
        "session_id": "vnc_session_001",
        "vnc_password": "secret",
        "connection_scheme": "managed_session",
    }

    await service.cancel_login(result["session_id"])
    assert released == ["vnc_session_001"]
