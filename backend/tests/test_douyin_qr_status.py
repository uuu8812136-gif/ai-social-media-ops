import pytest

from app.integrations.synapse_engine.platforms.base import LoginStatus
from app.integrations.synapse_engine.platforms.builtin import BuiltinPlatformAdapter


class _BodyLocator:
    async def inner_text(self, timeout=0):
        return "登录成功"


class _FakePage:
    def locator(self, selector):
        assert selector == "body"
        return _BodyLocator()


def test_douyin_explicit_scanned_status_wins_over_stale_success_text():
    status, message = BuiltinPlatformAdapter._map_douyin_qr_status(
        "scanned", "登录成功", "登录成功"
    )

    assert status == LoginStatus.SCANNED
    assert "已扫码" in message


@pytest.mark.asyncio
async def test_douyin_verification_payload_wins_over_redirect_url():
    adapter = BuiltinPlatformAdapter("douyin")
    session = {
        "douyin_qr_state": {
            "status": "scanned",
            "description": "登录成功",
            "redirect_url": "https://www.douyin.com/passport/sso/",
            "verification_required": True,
            "last_payload_keys": ["captcha", "url", "verify_ways"],
        }
    }

    status, message = await adapter._poll_douyin_qr_status(_FakePage(), session)

    assert status == LoginStatus.SCANNED
    assert "安全验证" in message
