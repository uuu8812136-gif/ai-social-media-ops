from app.integrations.synapse_engine.platforms.builtin import BuiltinPlatformAdapter


def test_visual_login_does_not_close_on_security_verification_page():
    adapter = BuiltinPlatformAdapter("douyin")

    assert not adapter._is_visual_login_success_url(
        "https://creator.douyin.com/passport/verify/challenge"
    )
    assert not adapter._is_visual_login_success_url(
        "https://creator.douyin.com/creator-micro/login?enter_from=qr"
    )


def test_visual_login_accepts_explicit_creator_dashboard():
    cases = (
        ("douyin", "https://creator.douyin.com/creator-micro/content/manage"),
        ("xiaohongshu", "https://creator.xiaohongshu.com/new/home"),
        ("kuaishou", "https://cp.kuaishou.com/article/manage/video"),
        ("bilibili", "https://member.bilibili.com/platform/upload/video/frame"),
        ("channels", "https://channels.weixin.qq.com/platform/post/list"),
    )

    for platform, url in cases:
        assert BuiltinPlatformAdapter(platform)._is_visual_login_success_url(url)
