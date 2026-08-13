from types import SimpleNamespace

import pytest

from app.integrations.synapse_engine.platforms.builtin import BuiltinPlatformAdapter
from app.integrations.synapse_engine.verification.manager import VerificationManager


@pytest.mark.asyncio
async def test_phone_verification_uses_masked_mobile_hint(monkeypatch):
    adapter = BuiltinPlatformAdapter("douyin")

    async def fake_evaluate(*_args, **_kwargs):
        return {
            "phoneHit": "验证码",
            "humanHit": None,
            "hasCaptchaEl": False,
            "hasCaptchaInput": True,
            "phoneHint": "131****01",
        }

    monkeypatch.setattr(adapter, "_evaluate_with_timeout", fake_evaluate)

    assert await adapter._detect_verification(object()) == ("phone", "131****01")


class _SendButton:
    def __init__(self, page):
        self.page = page

    async def count(self):
        return 1

    def nth(self, _index):
        return self

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self, timeout=0):
        assert timeout == 5000
        self.page.clicked = True


class _MissingButton(_SendButton):
    async def count(self):
        return 0


class _PhoneCaptchaPage:
    def __init__(self):
        self.clicked = False

    def get_by_role(self, _role, name="", exact=False):
        if name == "获取验证码" and exact:
            return _SendButton(self)
        return _MissingButton(self)

    def get_by_text(self, _text, exact=False):
        return _MissingButton(self)

    async def wait_for_timeout(self, value):
        assert value == 1000


@pytest.mark.asyncio
async def test_phone_captcha_clicks_send_before_waiting(monkeypatch):
    adapter = BuiltinPlatformAdapter("douyin")
    page = _PhoneCaptchaPage()

    async def fake_evaluate(*_args, **_kwargs):
        return "重新获取 59 秒"

    monkeypatch.setattr(adapter, "_evaluate_with_timeout", fake_evaluate)
    result = await adapter._trigger_phone_captcha_send(page)

    assert page.clicked is True
    assert result == {
        "clicked": True,
        "label": "获取验证码",
        "state": "重新获取 59 秒",
    }


@pytest.mark.asyncio
async def test_phone_captcha_result_accepts_when_input_disappears(monkeypatch):
    adapter = BuiltinPlatformAdapter("douyin")

    async def fake_evaluate(*_args, **_kwargs):
        return {"inputVisible": False, "error": ""}

    monkeypatch.setattr(adapter, "_evaluate_with_timeout", fake_evaluate)

    assert await adapter._wait_phone_captcha_result(object(), timeout=1) == {
        "accepted": True,
        "error": "",
    }


@pytest.mark.asyncio
async def test_phone_captcha_result_returns_platform_error(monkeypatch):
    adapter = BuiltinPlatformAdapter("douyin")

    async def fake_evaluate(*_args, **_kwargs):
        return {"inputVisible": True, "error": "验证码错误"}

    monkeypatch.setattr(adapter, "_evaluate_with_timeout", fake_evaluate)

    assert await adapter._wait_phone_captcha_result(object(), timeout=1) == {
        "accepted": False,
        "error": "验证码错误",
    }


@pytest.mark.asyncio
async def test_verification_screenshot_path_stays_inside_storage(monkeypatch, tmp_path):
    manager = VerificationManager()
    monkeypatch.setattr(manager.settings, "SYNAPSE_STORAGE_DIR", str(tmp_path))

    image = tmp_path / "screenshots" / "douyin" / "verification" / "ok.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    async def valid_task(_task_id):
        return SimpleNamespace(
            verification_meta={
                "screenshot_path": "screenshots/douyin/verification/ok.png"
            }
        )

    monkeypatch.setattr(manager, "_get_task", valid_task)
    assert await manager.get_screenshot_path("task-id") == image.resolve()

    async def unsafe_task(_task_id):
        return SimpleNamespace(verification_meta={"screenshot_path": "../secret.png"})

    monkeypatch.setattr(manager, "_get_task", unsafe_task)
    assert await manager.get_screenshot_path("task-id") is None
