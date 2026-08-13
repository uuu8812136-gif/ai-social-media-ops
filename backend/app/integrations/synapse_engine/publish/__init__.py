"""发布子模块。

提供 Publisher 类作为 worker 与 EmbeddedSynapseService 之间的桥梁：
- 从任务规格（task spec）准备发布输入（标题、正文、媒体文件路径）
- 调用 EmbeddedSynapseService.publish_content 执行发布
- 把结果写回 publish_tasks 表
"""

from app.integrations.synapse_engine.publish.publisher import Publisher

__all__ = ["Publisher"]
