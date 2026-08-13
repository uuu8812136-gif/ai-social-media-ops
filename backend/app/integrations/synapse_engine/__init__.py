"""Synapse 内嵌发布引擎。

把 SynapseAutomation 的核心能力（扫码登录、Cookie 管理、平台发布器、视频处理）
作为本项目内部 Python 模块加载，所有调用均为进程内 import，不走 HTTP。

模块加载策略：
1. 优先从原项目源码目录 SYNAPSE_SRC_DIR 通过 sys.path 注入加载真实实现
2. 注入失败或未配置时，回退到本目录下的内置简化实现（保证服务可用）

对外只暴露 EmbeddedSynapseService，其它子模块由 service 内部组装。
"""

from app.integrations.synapse_engine.service import EmbeddedSynapseService
from app.integrations.synapse_engine.platforms.base import (
    LoginStatus,
    QRCodeData,
    UserInfo,
    LoginResult,
    PlatformAdapter,
)
from app.integrations.synapse_engine.platforms.codes import (
    PLATFORM_CODES,
    CODE_TO_PLATFORM,
    PLATFORM_NAMES,
)

__all__ = [
    "EmbeddedSynapseService",
    "PlatformAdapter",
    "LoginStatus",
    "QRCodeData",
    "UserInfo",
    "LoginResult",
    "PLATFORM_CODES",
    "CODE_TO_PLATFORM",
    "PLATFORM_NAMES",
]
