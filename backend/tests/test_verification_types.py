import pytest

from app.integrations.synapse_engine.verification.manager import (
    normalize_verification_type,
)


@pytest.mark.parametrize(
    ("raw_type", "status", "expected"),
    [
        ("phone", "needs_phone_captcha", "phone_captcha"),
        ("phone_captcha", "needs_phone_captcha", "phone_captcha"),
        ("human", "needs_human_captcha", "human_captcha"),
        ("human_captcha", "needs_human_captcha", "human_captcha"),
        (None, "needs_phone_captcha", "phone_captcha"),
        (None, "needs_human_captcha", "human_captcha"),
    ],
)
def test_normalize_verification_type(raw_type, status, expected):
    assert normalize_verification_type(raw_type, status) == expected
