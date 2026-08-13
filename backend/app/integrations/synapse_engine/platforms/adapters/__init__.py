"""各平台适配器注册表。

现阶段子类继承稳定的通用实现；平台 DOM 或验收规则变化时，在对应文件
局部覆盖方法，避免一个平台的修复影响其它平台。
"""

from app.integrations.synapse_engine.platforms.adapters.bilibili import (
    BilibiliAdapter,
)
from app.integrations.synapse_engine.platforms.adapters.channels import (
    ChannelsAdapter,
)
from app.integrations.synapse_engine.platforms.adapters.douyin import DouyinAdapter
from app.integrations.synapse_engine.platforms.adapters.kuaishou import (
    KuaishouAdapter,
)
from app.integrations.synapse_engine.platforms.adapters.xiaohongshu import (
    XiaohongshuAdapter,
)

ADAPTER_REGISTRY = {
    "xiaohongshu": XiaohongshuAdapter,
    "channels": ChannelsAdapter,
    "douyin": DouyinAdapter,
    "kuaishou": KuaishouAdapter,
    "bilibili": BilibiliAdapter,
}

__all__ = ["ADAPTER_REGISTRY"]
