"""Platform constants for the embedded Synapse automation adapter.

Keep the visible platform names as unicode escapes so the file is safe when
edited from Windows shells with non-UTF-8 code pages.
"""

PLATFORM_CODES = {
    "xiaohongshu": 1,
    "channels": 2,
    "douyin": 3,
    "kuaishou": 4,
    "bilibili": 5,
}
CODE_TO_PLATFORM = {v: k for k, v in PLATFORM_CODES.items()}

PLATFORM_NAMES = {
    "xiaohongshu": "\u5c0f\u7ea2\u4e66",
    "channels": "\u89c6\u9891\u53f7",
    "douyin": "\u6296\u97f3",
    "kuaishou": "\u5feb\u624b",
    "bilibili": "B\u7ad9",
}

# Publish pages used after a cookie/storage_state has been captured.
PLATFORM_PUBLISH_URLS = {
    "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
    "channels": "https://channels.weixin.qq.com/platform/post/create",
    "douyin": "https://creator.douyin.com/creator-micro/content/upload",
    "kuaishou": "https://cp.kuaishou.com/article/publish/video",
    "bilibili": "https://member.bilibili.com/platform/upload/video/frame",
}

# Login pages used to render QR codes.
PLATFORM_LOGIN_URLS = {
    "xiaohongshu": "https://creator.xiaohongshu.com/login",
    "channels": "https://channels.weixin.qq.com/login",
    "douyin": "https://creator.douyin.com/creator-micro/login?enter_from=qr",
    "kuaishou": "https://passport.kuaishou.com/pc/account/login/",
    "bilibili": "https://passport.bilibili.com/login",
}

# Strong auth cookie names used for quick login-state checks.
PLATFORM_AUTH_COOKIE_NAMES = {
    "xiaohongshu": {"web_session", "customer-sso-sid", "x-user-id-encoder"},
    "channels": {"wxuin", "uin", "finder_username"},
    "douyin": {
        "sessionid",
        "sessionid_ss",
        "sid_guard",
        "sid_tt",
        "uid_tt",
        "sso_uid_tt",
    },
    "kuaishou": {
        "userId",
        "bUserId",
        "kuaishou.server.web_st",
        "kuaishou.server.web_ph",
    },
    "bilibili": {"DedeUserID", "DedeUserID__ckMd5", "SESSDATA", "bili_jct"},
}


def normalize_platform(name: str) -> str:
    return (name or "").strip().lower()


def resolve_platform_code(name: str) -> int:
    norm = normalize_platform(name)
    if norm not in PLATFORM_CODES:
        raise ValueError(f"Unsupported platform: {name}")
    return PLATFORM_CODES[norm]
