import re
import warnings
from functools import lru_cache
from urllib.parse import unquote, urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 标记为"未修改"的默认密钥，生产环境必须替换
_INSECURE_DEFAULTS = {
    "change-me-in-production",
    "dev-secret-key-change-in-production",
    "phone-encryption-key-32bytes!!",
    "minioadmin",
}

# 种子用户默认弱口令（生产环境必须覆盖）
_WEAK_SEED_PASSWORDS = {"admin123", "operator123", "dealer123"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_ENV: str = "development"  # development|production
    APP_SECRET_KEY: str = "change-me-in-production"
    APP_DEBUG: bool = False
    APP_NAME: str = "AI社媒内容协作平台"

    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@postgres:5432/ai_social_media"
    )
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_PASSWORD: str = ""
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "ai_social_media"

    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "assets"
    MINIO_SECURE: bool = False

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_MODEL: str = "qwen-plus"
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_ALLOW_PRIVATE_BASE_URL: bool = False
    # Clash/Surge 等增强模式会把公网域名解析到 198.18.0.0/15 fake-IP。
    # 仅在明确启用时允许“域名解析结果”为该保留网段；字面 IP 仍会被拒绝。
    LLM_ALLOW_FAKE_IP_DNS: bool = False
    AI_MOCK_MODE: bool = False

    # 统一 Provider 配置
    # database 表示只使用“模型配置”页面保存的加密配置；环境变量作为兜底时
    # 可选 deepseek/qwen。
    LLM_PROVIDER: str = "database"  # database|deepseek|qwen
    SOCIAL_PROVIDER: str = "synapse_embedded"
    ANALYTICS_PROVIDER: str = "database"
    NOTIFY_PROVIDER: str = "disabled"  # disabled|wecom|email
    EMBEDDING_PROVIDER: str = "disabled"  # disabled|openai
    MAP_PROVIDER: str = "disabled"  # disabled|amap|tencent
    CRAWLER_PROVIDER: str = "mediacrawler_embedded"  # mock|mediacrawler_embedded

    # Mock 场景控制
    MOCK_SCENARIO: str = "normal"  # normal|timeout|error|empty|content_violation|publish_fail|notify_fail|token_expired

    WECOM_CORP_ID: str = ""
    WECOM_AGENT_ID: str = ""
    WECOM_SECRET: str = ""
    WECOM_TOKEN: str = ""
    WECOM_ENCODING_AES_KEY: str = ""

    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_SSL: bool = True

    # 各 Provider 真实分支所需凭证
    OPENAI_API_KEY: str = ""  # EMBEDDING_PROVIDER=openai 时必填
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    AMAP_KEY: str = ""  # MAP_PROVIDER=amap 时必填
    TENCENT_MAP_KEY: str = ""  # MAP_PROVIDER=tencent 时必填
    # 社媒平台发布：access_token 从 DB Account 表读取（OAuth 授权后存入），此处仅配 API base
    DOUYIN_OPEN_BASE_URL: str = "https://open.douyin.com"
    XIAOHONGSHU_OPEN_BASE_URL: str = "https://edith.xiaohongshu.com"
    WECHAT_MP_BASE_URL: str = "https://api.weixin.qq.com"
    WECHAT_VIDEO_BASE_URL: str = "https://api.weixin.qq.com"

    # 小红书 JS SDK 凭证（agora.xiaohongshu.com 申请）
    XIAOHONGSHU_APP_KEY: str = ""
    XIAOHONGSHU_APP_SECRET: str = ""

    ES_URL: str = "http://elasticsearch:9200"

    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    PHONE_ENCRYPTION_KEY: str = "phone-encryption-key-32bytes!!"
    COOKIE_ENCRYPTION_KEY: str = "cookie-encryption-key-change-me"

    # 初始种子用户口令（生产必须通过环境变量覆盖，否则启动校验拦截）
    SEED_ADMIN_PASSWORD: str = "admin123"
    BOOTSTRAP_ADMIN_ENABLED: bool = True
    BOOTSTRAP_ADMIN_USERNAME: str = "admin"
    BOOTSTRAP_ADMIN_NAME: str = "系统管理员"

    CORS_ORIGINS: str = (
        "http://127.0.0.1:30001,http://127.0.0.1:5176"
    )  # 逗号分隔；仅 APP_ENV=development 可临时使用 *
    ALLOWED_HOSTS: str = "*"  # 逗号分隔；生产环境必须填写对外域名
    HEALTHCHECK_HOST: str = "health.internal"

    # 上传文件大小限制（字节），默认 50MB
    UPLOAD_MAX_SIZE: int = 50 * 1024 * 1024
    # 上传允许的 MIME 类型（逗号分隔），空表示不限制
    UPLOAD_ALLOWED_MIME: str = (
        "image/jpeg,image/png,image/webp,image/gif,video/mp4,application/pdf"
    )

    # ===== Synapse 内嵌发布引擎 =====
    SYNAPSE_EMBEDDED_ENABLED: bool = True
    # 【已废弃】原项目源码目录。本项目已内嵌所有源码，不再通过 sys.path 注入加载外部模块。
    # 保留此配置仅为兼容性，实际运行时不依赖此路径是否存在。
    SYNAPSE_SRC_DIR: str = ""
    # 内嵌引擎数据目录
    SYNAPSE_STORAGE_DIR: str = "data/synapse"
    SYNAPSE_BROWSER_PROFILE_DIR: str = "data/browser_profiles"
    SYNAPSE_COOKIE_DIR: str = "data/synapse/cookies"
    SYNAPSE_PLAYWRIGHT_HEADLESS: bool = True
    SYNAPSE_PLAYWRIGHT_RUNTIME: str = "patchright"  # patchright|playwright
    # 本地 Chrome 可执行文件路径（空表示使用 Playwright 自带 chromium）
    SYNAPSE_LOCAL_CHROME_PATH: str = ""
    # Playwright 浏览器安装目录
    SYNAPSE_PLAYWRIGHT_BROWSERS_DIR: str = ""
    # 浏览器代理：显式指定则走该代理（如 http://127.0.0.1:7890，用于访问海外平台）
    SYNAPSE_BROWSER_PROXY: str = ""
    # 无显式代理时是否强制直连（绕过系统代理，避免系统代理未启动导致 ERR_PROXY_CONNECTION_FAILED）
    SYNAPSE_BROWSER_NO_PROXY: bool = True
    # 仅可信离线任务需要时显式开启；API 发布默认只接受 URL，防止读取宿主机任意文件。
    SYNAPSE_ALLOW_LOCAL_MEDIA: bool = False

    # ===== 账号登录 / 发布浏览器 =====
    # native_host：在 Mac 宿主机使用真实 Chrome；vnc/worker 仅保留兼容旧部署。
    SYNAPSE_LOGIN_BROWSER_MODE: str = "native_host"
    # native_host：整段发布自动化运行在宿主 Chrome 中，平时隐藏，遇到人工
    # 验证时直接显示同一个真实页面；worker：旧版 Xvfb/noVNC 方案。
    SYNAPSE_PUBLISH_BROWSER_MODE: str = "native_host"
    # native_host 发布时，宿主 Chrome 与 celery 必须看到完全相同的绝对
    # 媒体路径，才能上传总量 >=50MiB 的视频/图片。
    SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR: str = "/tmp/ai-social-native-media"
    SYNAPSE_NATIVE_BROWSER_MANAGER_URL: str = "http://host.docker.internal:9324"
    SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN: str = ""

    # ===== 发布验证码 / 人机验证 =====
    # 总开关：关闭时发布流程与改造前完全一致（不在等待循环里检测验证码弹窗）
    SYNAPSE_VERIFICATION_ENABLED: bool = True
    # browser-vnc 容器的 session-manager API 地址（docker 网络内服务名）
    # 留空时默认指向 browser-vnc:9223
    SYNAPSE_VNC_SESSION_MANAGER_URL: str = "http://browser-vnc:9223"
    # 检测到手机验证码后，worker 暂停等待用户输入的最长时间（秒），超时则任务失败释放 worker
    SYNAPSE_PHONE_CAPTCHA_WAIT_TIMEOUT: int = 300
    # 检测到人机验证后，noVNC 会话允许用户操作的最长时间（秒）
    SYNAPSE_HUMAN_CAPTCHA_WAIT_TIMEOUT: int = 600
    # Redis 频道前缀：发布任务等待用户输入时订阅 {prefix}:task:{task_id}
    SYNAPSE_VERIFICATION_REDIS_PREFIX: str = "synapse:verify"
    # 方案 A：celery worker 容器内 x11vnc 密码（用户通过 noVNC 远程操作 worker 浏览器）
    SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD: str = "trae-vnc-2026"
    # 方案 A：worker 容器 noVNC web 入口地址（供 nginx 反代用，留空时默认 celery:6080）
    SYNAPSE_VERIFICATION_WORKER_NOVNC_URL: str = "http://celery:6080"

    # ===== MediaCrawler 内嵌采集引擎 =====
    MEDIACRAWLER_EMBEDDED_ENABLED: bool = True
    # 【已废弃】原项目源码目录。本项目已内嵌所有源码，不再通过 sys.path 注入加载外部模块。
    # 保留此配置仅为兼容性，实际运行时不依赖此路径是否存在。
    MEDIACRAWLER_SRC_DIR: str = ""
    MEDIACRAWLER_DATA_DIR: str = "data/mediacrawler"
    MEDIACRAWLER_DEFAULT_SAVE_FORMAT: str = "jsonl"  # csv|json|jsonl|sqlite|excel|db
    MEDIACRAWLER_HEADLESS: bool = True
    MEDIACRAWLER_ENABLE_CDP_MODE: bool = False
    MEDIACRAWLER_CDP_DEBUG_PORT: int = 9222
    MEDIACRAWLER_MAX_NOTES_COUNT: int = 20
    MEDIACRAWLER_MAX_COMMENTS_COUNT: int = 10
    MEDIACRAWLER_ENABLE_GET_COMMENTS: bool = True
    MEDIACRAWLER_ENABLE_GET_SUB_COMMENTS: bool = False
    MEDIACRAWLER_ENABLE_GET_MEDIA: bool = False
    MEDIACRAWLER_MAX_CONCURRENCY: int = 1
    MEDIACRAWLER_CRAWLER_MAX_SLEEP_SEC: int = 2
    CRAWLER_PARSE_MAX_SIZE: int = 100 * 1024 * 1024
    CRAWLER_PARSE_MAX_ITEMS: int = 10_000

    @field_validator("APP_ENV")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("APP_ENV 只能是 development、test 或 production")
        return normalized

    @field_validator("SYNAPSE_LOGIN_BROWSER_MODE")
    @classmethod
    def validate_login_browser_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"native_host", "vnc"}:
            raise ValueError(
                "SYNAPSE_LOGIN_BROWSER_MODE 只能是 native_host 或 vnc"
            )
        return normalized

    @field_validator("SYNAPSE_PUBLISH_BROWSER_MODE")
    @classmethod
    def validate_publish_browser_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"native_host", "worker"}:
            raise ValueError(
                "SYNAPSE_PUBLISH_BROWSER_MODE 只能是 native_host 或 worker"
            )
        return normalized

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def docs_enabled(self) -> bool:
        """生产环境禁用 /docs /redoc /openapi.json 暴露"""
        return not self.is_production

    @property
    def upload_allowed_mime_list(self) -> list[str]:
        return [m.strip() for m in self.UPLOAD_ALLOWED_MIME.split(",") if m.strip()]


def _validate_production_settings(settings: Settings) -> None:
    """生产环境启动前强制校验关键凭证，避免使用默认弱密钥"""
    if not settings.is_production:
        return

    problems: list[str] = []

    if (
        settings.APP_SECRET_KEY in _INSECURE_DEFAULTS
        or len(settings.APP_SECRET_KEY) < 32
    ):
        problems.append("APP_SECRET_KEY 必须修改为长度≥32的安全随机字符串")

    if (
        settings.PHONE_ENCRYPTION_KEY in _INSECURE_DEFAULTS
        or len(settings.PHONE_ENCRYPTION_KEY) < 32
    ):
        problems.append("PHONE_ENCRYPTION_KEY 必须修改为长度≥32的安全随机字符串")

    if (
        settings.COOKIE_ENCRYPTION_KEY == "cookie-encryption-key-change-me"
        or len(settings.COOKIE_ENCRYPTION_KEY) < 32
    ):
        problems.append("COOKIE_ENCRYPTION_KEY 必须修改为长度≥32的安全随机字符串")
    elif settings.COOKIE_ENCRYPTION_KEY in {
        settings.APP_SECRET_KEY,
        settings.PHONE_ENCRYPTION_KEY,
    }:
        problems.append("COOKIE_ENCRYPTION_KEY 必须与应用密钥、手机号加密密钥相互独立")

    if settings.APP_DEBUG:
        problems.append("APP_DEBUG 生产环境必须为 false")

    if (
        settings.MINIO_ACCESS_KEY == "minioadmin"
        or settings.MINIO_SECRET_KEY == "minioadmin"
        or len(settings.MINIO_ACCESS_KEY) < 3
        or len(settings.MINIO_SECRET_KEY) < 16
    ):
        problems.append("MINIO_ACCESS_KEY/MINIO_SECRET_KEY 必须修改，Secret 至少 16 位")

    if settings.CORS_ORIGINS.strip() in {"*", ""}:
        problems.append("CORS_ORIGINS 不能为 *，必须指定具体域名白名单")
    else:
        for origin in settings.cors_origin_list:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                problems.append(f"CORS_ORIGINS 生产来源必须是完整 HTTPS 地址：{origin}")

    if not settings.allowed_host_list or "*" in settings.allowed_host_list:
        problems.append("ALLOWED_HOSTS 生产环境必须填写对外域名，不能使用 *")
    else:
        for host in settings.allowed_host_list:
            if (
                "://" in host
                or "/" in host
                or "@" in host
                or not re.fullmatch(r"(?:\*\.)?[A-Za-z0-9.-]+(?::\d+)?", host)
            ):
                problems.append(f"ALLOWED_HOSTS 包含无效主机名：{host}")
    if settings.HEALTHCHECK_HOST not in settings.allowed_host_list:
        problems.append("HEALTHCHECK_HOST 必须包含在 ALLOWED_HOSTS 中")

    if settings.AI_MOCK_MODE:
        problems.append("AI_MOCK_MODE 生产环境必须为 false")

    allowed_providers = {
        "LLM_PROVIDER": (settings.LLM_PROVIDER, {"database", "deepseek", "qwen"}),
        "SOCIAL_PROVIDER": (settings.SOCIAL_PROVIDER, {"synapse_embedded"}),
        "ANALYTICS_PROVIDER": (settings.ANALYTICS_PROVIDER, {"database"}),
        "NOTIFY_PROVIDER": (settings.NOTIFY_PROVIDER, {"disabled", "wecom", "email"}),
        "EMBEDDING_PROVIDER": (settings.EMBEDDING_PROVIDER, {"disabled", "openai"}),
        "MAP_PROVIDER": (settings.MAP_PROVIDER, {"disabled", "amap", "tencent"}),
        "CRAWLER_PROVIDER": (settings.CRAWLER_PROVIDER, {"mediacrawler_embedded"}),
    }
    for name, (value, allowed) in allowed_providers.items():
        if value.strip().lower() not in allowed:
            problems.append(f"{name} 不受生产环境支持：{value}")

    if settings.LLM_PROVIDER == "deepseek" and not settings.DEEPSEEK_API_KEY:
        problems.append("LLM_PROVIDER=deepseek 时必须配置 DEEPSEEK_API_KEY")
    if settings.LLM_PROVIDER == "qwen" and not settings.QWEN_API_KEY:
        problems.append("LLM_PROVIDER=qwen 时必须配置 QWEN_API_KEY")
    if settings.LLM_PROVIDER in {"deepseek", "qwen"}:
        selected_llm_url = (
            settings.DEEPSEEK_BASE_URL
            if settings.LLM_PROVIDER == "deepseek"
            else settings.QWEN_BASE_URL
        )
        if (
            urlsplit(selected_llm_url).scheme != "https"
            and not settings.LLM_ALLOW_PRIVATE_BASE_URL
        ):
            problems.append("生产公网 LLM API 地址必须使用 HTTPS")

    mock_providers = [
        name
        for name, value in (
            ("LLM_PROVIDER", settings.LLM_PROVIDER),
            ("SOCIAL_PROVIDER", settings.SOCIAL_PROVIDER),
            ("ANALYTICS_PROVIDER", settings.ANALYTICS_PROVIDER),
            ("NOTIFY_PROVIDER", settings.NOTIFY_PROVIDER),
            ("EMBEDDING_PROVIDER", settings.EMBEDDING_PROVIDER),
            ("MAP_PROVIDER", settings.MAP_PROVIDER),
            ("CRAWLER_PROVIDER", settings.CRAWLER_PROVIDER),
        )
        if value == "mock"
    ]
    if mock_providers:
        problems.append("生产环境禁止使用 mock Provider：" + ", ".join(mock_providers))

    try:
        database_url = urlsplit(
            settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql", 1)
        )
    except ValueError:
        database_url = None
    if (
        not database_url
        or database_url.scheme != "postgresql"
        or not database_url.hostname
    ):
        problems.append("DATABASE_URL 必须是有效的 PostgreSQL asyncpg 连接地址")
    elif not database_url.password or database_url.password == "postgres":
        problems.append("DATABASE_URL 必须使用非默认数据库强密码")
    elif (
        unquote(database_url.username or "") != settings.POSTGRES_USER
        or unquote(database_url.password) != settings.POSTGRES_PASSWORD
        or database_url.path.lstrip("/") != settings.POSTGRES_DB
    ):
        problems.append("DATABASE_URL 用户名、密码和库名必须与 POSTGRES_* 配置一致")
    if settings.POSTGRES_USER == "postgres":
        problems.append("POSTGRES_USER 生产环境不能使用默认 postgres 用户")
    if settings.POSTGRES_PASSWORD == "postgres" or len(settings.POSTGRES_PASSWORD) < 12:
        problems.append("POSTGRES_PASSWORD 必须修改且长度至少 12 位")

    try:
        redis_url = urlsplit(settings.REDIS_URL)
    except ValueError:
        redis_url = None
    if (
        not redis_url
        or redis_url.scheme not in {"redis", "rediss"}
        or not redis_url.hostname
        or not redis_url.password
        or unquote(redis_url.password) != settings.REDIS_PASSWORD
        or len(settings.REDIS_PASSWORD) < 16
    ):
        problems.append(
            "生产 Redis 必须配置长度≥16的 REDIS_PASSWORD，并在 REDIS_URL 中使用同一密码"
        )

    if settings.JWT_ALGORITHM != "HS256":
        problems.append("JWT_ALGORITHM 当前仅允许 HS256")
    if (
        settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES <= 0
        or settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS <= 0
    ):
        problems.append("JWT 有效期必须为正数")

    if settings.NOTIFY_PROVIDER == "wecom":
        required = (
            settings.WECOM_CORP_ID,
            settings.WECOM_AGENT_ID,
            settings.WECOM_SECRET,
            settings.WECOM_TOKEN,
            settings.WECOM_ENCODING_AES_KEY,
        )
        if not all(required):
            problems.append(
                "NOTIFY_PROVIDER=wecom 时必须完整配置企业微信凭证和回调密钥"
            )
    if settings.NOTIFY_PROVIDER == "email" and not all(
        (settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASS, settings.SMTP_FROM)
    ):
        problems.append("NOTIFY_PROVIDER=email 时必须完整配置 SMTP_HOST/USER/PASS/FROM")
    if settings.EMBEDDING_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        problems.append("EMBEDDING_PROVIDER=openai 时必须配置 OPENAI_API_KEY")
    if (
        settings.EMBEDDING_PROVIDER == "openai"
        and urlsplit(settings.OPENAI_BASE_URL).scheme != "https"
    ):
        problems.append("OPENAI_BASE_URL 生产环境必须使用 HTTPS")
    if settings.MAP_PROVIDER == "amap" and not settings.AMAP_KEY:
        problems.append("MAP_PROVIDER=amap 时必须配置 AMAP_KEY")
    if settings.MAP_PROVIDER == "tencent" and not settings.TENCENT_MAP_KEY:
        problems.append("MAP_PROVIDER=tencent 时必须配置 TENCENT_MAP_KEY")

    if (
        settings.UPLOAD_MAX_SIZE <= 0
        or settings.CRAWLER_PARSE_MAX_SIZE <= 0
        or settings.CRAWLER_PARSE_MAX_ITEMS <= 0
    ):
        problems.append("上传和采集文件大小限制必须为正数")

    if settings.BOOTSTRAP_ADMIN_ENABLED and (
        settings.SEED_ADMIN_PASSWORD in _WEAK_SEED_PASSWORDS
        or len(settings.SEED_ADMIN_PASSWORD) < 12
        or not re.search(r"[A-Za-z]", settings.SEED_ADMIN_PASSWORD)
        or not re.search(r"\d", settings.SEED_ADMIN_PASSWORD)
    ):
        problems.append(
            "启用初始管理员时，SEED_ADMIN_PASSWORD 必须至少 12 位并包含字母和数字"
        )

    if problems:
        raise RuntimeError(
            "生产环境配置校验失败，请修正以下问题后再启动：\n  - "
            + "\n  - ".join(problems)
        )


def _validate_cors_settings(settings: Settings) -> None:
    if settings.APP_ENV != "development" and settings.CORS_ORIGINS.strip() == "*":
        raise RuntimeError("CORS_ORIGINS=* 仅允许在 APP_ENV=development 中使用")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _validate_cors_settings(settings)
    if settings.is_production:
        _validate_production_settings(settings)
    elif (
        settings.APP_ENV == "development"
        and settings.APP_SECRET_KEY == "change-me-in-production"
    ):
        warnings.warn(
            "APP_SECRET_KEY 未修改，请在 .env 中设置安全的密钥！", stacklevel=2
        )
    return settings
