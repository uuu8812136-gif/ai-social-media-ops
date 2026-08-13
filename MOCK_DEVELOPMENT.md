# AI 社媒矩阵运营系统 — Mock 开发文档

## 1. 如何开启 Mock Provider

项目默认所有外部 Provider 均为 `mock` 模式，无需任何额外配置即可启动全流程演示。

在 `.env` 文件或环境变量中控制：

```bash
# .env 默认值（无需修改即可使用 mock）
AI_MOCK_MODE=true
LLM_PROVIDER=mock
SOCIAL_PROVIDER=mock
ANALYTICS_PROVIDER=mock
NOTIFY_PROVIDER=mock
EMBEDDING_PROVIDER=mock
MAP_PROVIDER=mock
MOCK_SCENARIO=normal
```

如果 `.env` 中未设置，代码中的默认值也是 `mock`，开箱即用。

---

## 2. 每个 Provider 模拟什么

### LLM_PROVIDER（`backend/app/services/llm_client.py`）

| 场景 | Mock 行为 |
|------|-----------|
| 视频脚本生成 | 根据平台（抖音/小红书/视频号）生成 hook + body + cta + tags + 本地化内容 |
| 图文文案生成 | 根据平台生成标题 + 正文 + 标签 |
| 本地化改写 | 为指定城市生成本地化版本（标题 + 正文 + 标签） |
| 风险判断 | Mock 模式下直接返回空列表（无风险） |
| 热门选题 | 返回 5 个预设热门话题 |

Mock 响应基于 prompt 内容的 MD5 哈希生成稳定随机种子，确保相同输入产生一致输出。

### SOCIAL_PROVIDER（`backend/app/services/social_provider.py`）

| 平台 | Mock 行为 |
|------|-----------|
| 抖音 (douyin) | 返回 `published` 状态 + 模拟 URL |
| 小红书 (xiaohongshu) | 返回 `reviewing` 状态 + 模拟 URL |
| 视频号 (wechat_video) | 返回 `published` 状态 + 模拟 URL |
| 公众号 (wechat_mp) | 返回 `reviewing` 状态 + 模拟 URL |

支持场景控制：`publish_fail` / `token_expired` / `content_violation` / `timeout`。

### ANALYTICS_PROVIDER（`backend/app/services/analytics_provider.py`）

| 接口 | Mock 行为 |
|------|-----------|
| 内容级统计 | 基于内容 ID + 平台 + 日期的稳定随机数据（views/likes/comments/favorites/shares/leads） |
| 账号级统计 | 基于账号 ID + 平台 + 日期的稳定随机数据 |
| 仪表盘统计 | 按平台汇总的稳定随机数据 |

支持 `empty` 场景返回空数据。

### NOTIFY_PROVIDER（`backend/app/services/notify_provider.py`）

| 通知类型 | Mock 行为 |
|----------|-----------|
| 待审核通知 | 返回 `success=True` + 模拟 message_id |
| 发布成功通知 | 返回 `success=True` + 模拟 message_id |
| 线索提醒 | 通过企微渠道发送，返回模拟 message_id |
| 风险词提醒 | 返回 `success=True` + 模拟 message_id |

支持场景控制：`notify_fail` / `timeout`。

### EMBEDDING_PROVIDER（`backend/app/services/embedding_provider.py`）

| 接口 | Mock 行为 |
|------|-----------|
| 单文本嵌入 | 基于 MD5 哈希生成 128 维确定性伪向量 |
| 批量嵌入 | 逐个调用单文本嵌入 |
| 相似度计算 | 余弦相似度 |

支持 `empty` 场景返回零向量。

### MAP_PROVIDER（`backend/app/services/map_provider.py`）

| 接口 | Mock 行为 |
|------|-----------|
| 城市坐标 | 返回预定义的 5 个城市坐标（广州/深圳/北京/佛山/东莞） |
| 门店标记 | 生成 GeoJSON Feature |
| 距离计算 | Haversine 公式近似计算 |

支持 `error` 场景返回 None。

---

## 3. 如何切换真实 Provider

### 切换 LLM（DeepSeek / 通义千问）

```bash
# .env
AI_MOCK_MODE=false
LLM_PROVIDER=deepseek    # 或 qwen
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# 如使用通义千问
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/api/v1
```

### 切换社媒发布

```bash
SOCIAL_PROVIDER=douyin    # 或 xiaohongshu / wechat / wechat_mp
```

> 注意：真实社媒 Provider 尚未实现，`get_social_provider()` 会抛出 `NotImplementedError`。
> **重要**：生产环境不自动发布到社媒平台。"发布"接口语义为"生成发布包 / 模拟发布状态 / 人工发布回填"。
> - `POST /publish/{id}/prepare` — 生成发布包（Mock 模式模拟完整流程）
> - `POST /publish/{id}/report` — 人工发布回填（记录手动发布结果，不调第三方 API）
> 接真实 API 时，`prepare` 仅生成素材包供人工确认，`report` 仍为人工回填。

### 切换数据分析

```bash
ANALYTICS_PROVIDER=real
```

> 注意：真实 Analytics Provider 尚未实现。

### 切换通知渠道

```bash
NOTIFY_PROVIDER=wecom     # 或 email
WECOM_CORP_ID=your_corp_id
WECOM_AGENT_ID=your_agent_id
WECOM_SECRET=your_secret
```

> 注意：企微通知 Provider 尚未实现。

### 切换向量嵌入

```bash
EMBEDDING_PROVIDER=openai
```

> 注意：OpenAI Embedding Provider 尚未实现。

### 切换地图服务

```bash
MAP_PROVIDER=amap    # 或 tencent
```

> 注意：高德/腾讯地图 Provider 尚未实现。

---

## 4. Seed 数据有哪些

应用启动时（`lifespan` → `seed_data()`）自动执行，已有 admin 用户则跳过。

| 数据 | 数量 | 说明 |
|------|------|------|
| 用户 | 3 | admin / operator / dealer |
| 城市 | 3 | 广州、深圳、佛山 |
| 经销商 | 1 | 广州示例门窗 |
| 社媒账号 | 2 | 抖音 IP 人设号 + 品牌官方号 |
| 风险词 | 17 | 绝对化用语 8 个 + 门窗行业专属 5 个 + 平台敏感词 4 个 |

---

## 5. 测试脚本怎么跑

### 冒烟测试

```bash
# 确保后端已启动
python scripts/smoke_test.py --api-base http://localhost:8001
```

测试覆盖 10 个检查点：健康检查、登录、知识库 CRUD、脚本列表、风险检测、模拟发布、数据回流、仪表盘、素材列表。

### 单元测试

```bash
cd backend
pytest tests/ -v
```

---

## 6. 当前哪些是假数据、哪些是真数据库数据

### 真数据库数据（PostgreSQL）

- 用户账号与密码哈希
- 城市信息
- 经销商信息
- 社媒账号（Account）
- 风险词库（RiskWord）
- 知识库文档与分块（KnowledgeDocument + KnowledgeChunk）
- 内容（Content）— 包括 AI 生成的脚本和文案
- 素材（Asset）
- 日历事件（Calendar）
- 线索（Lead）

### 假数据（Mock Provider 生成）

- LLM 生成的内容（mock 模式下为基于 prompt 哈希的模板生成，非真实 AI 输出）
- 社媒发布结果（模拟 external_post_id 和 publish_url）
- 数据分析统计（基于稳定种子的随机数据）
- 通知发送结果（模拟 message_id）
- 向量嵌入（128 维伪向量）
- 地图坐标（预定义静态坐标）

---

## 7. 后续接真实 API 要替换哪些文件

| Provider | 需修改文件 | 说明 |
|----------|-----------|------|
| LLM | `backend/app/services/llm_client.py` | `LLMClient.generate()` 已实现 DeepSeek/Qwen 调用，设置 `AI_MOCK_MODE=false` + API Key 即可 |
| 社媒发布 | `backend/app/services/social_provider.py` | 在 `get_social_provider()` 中添加真实 Provider 类 |
| 数据分析 | `backend/app/services/analytics_provider.py` | 在 `get_analytics_provider()` 中添加真实 Provider 类 |
| 通知 | `backend/app/services/notify_provider.py` | 在 `get_notify_provider()` 中添加企微/邮件 Provider |
| 向量嵌入 | `backend/app/services/embedding_provider.py` | 在 `get_embedding_provider()` 中添加 OpenAI Embedding |
| 地图 | `backend/app/services/map_provider.py` | 在 `get_map_provider()` 中添加高德/腾讯地图 |
| 风险检测 | `backend/app/services/risk_check.py` | `llm_judge()` 已实现，mock 模式下返回空列表 |
| 内容生成 | `backend/app/services/content_gen.py` | 依赖 LLMClient，切换 LLM Provider 即可 |

---

## 8. 测试账号和权限

| 用户名 | 密码 | 角色 | 权限 |
|--------|------|------|------|
| `admin` | `admin123` | 管理员 | 全部权限：知识库管理、内容生成与审核、发布管理、账号管理、数据看板、用户管理 |
| `operator` | `operator123` | 运营 | 知识库管理、内容生成、发布管理、数据看板 |
| `dealer` | `dealer123` | 经销商 | 仅查看本经销商线索、上传素材、查看发布状态 |

### 权限规则

- 经销商角色无法访问知识库管理接口
- 内容审核和发布仅 admin / operator 可操作
- 经销商只能查看关联的线索和素材
- 数据看板 admin 可看全量，operator 看本账号，dealer 看本经销商

---

## 9. 业务状态机

### 内容流程

```
draft → ai_generated → risk_checked → approved → scheduled → published → stats_synced
                          │                │
                          └→ risk_failed   └→ rejected → (修改后重新提交)
```

| 状态 | 含义 | 触发条件 |
|------|------|----------|
| `draft` | 草稿 | 手动创建 |
| `ai_generated` | AI 已生成 | LLM 生成完成并入库 |
| `risk_checked` | 风控通过 | AI 风险检测通过 |
| `risk_failed` | 风险检测未通过 | 检测到高风险词 |
| `approved` | 审核通过 | 运营/管理员手动审核通过 |
| `human_reviewed` | 人工审核通过 | 人工审核通过（与 approved 等价，前端可能使用此状态） |
| `rejected` | 审核拒绝 | 运营/管理员拒绝 |
| `scheduled` | 已排期 | 设置发布时间 |
| `published` | 已发布 | 人工发布回填 / Mock 模拟发布成功 |
| `stats_synced` | 数据已回传 | Analytics Provider 同步数据完成 |

### 线索流程

```
new → assigned → contacted → qualified → deal → lost
```

### 发布流程

> **红线**：系统不自动发布到社媒平台。所有"发布"操作均为人工确认后执行或回填。

```
risk_checked → approved/human_reviewed → prepare(生成发布包) → scheduled → published(人工回填) → stats_synced
                                                          └→ publish_failed
                                                          └→ token_expired
                                                          └→ content_violation
```

- `POST /publish/{id}/prepare` — 生成发布包（Mock 模拟完整流程，生产仅打包素材）
- `POST /publish/{id}/report` — 人工发布回填（不调第三方 API，仅记录结果）

---

## 10. Mock 场景控制

通过 `MOCK_SCENARIO` 环境变量控制 Mock Provider 的行为：

```bash
MOCK_SCENARIO=normal              # 默认，正常返回
MOCK_SCENARIO=timeout             # 模拟超时（Social/Notify 会延迟后返回错误）
MOCK_SCENARIO=error               # 模拟错误返回（Map 返回 None）
MOCK_SCENARIO=empty               # 返回空数据（Analytics/Embedding 返回空）
MOCK_SCENARIO=content_violation   # 内容违规（Social 返回 content_violation 状态）
MOCK_SCENARIO=publish_fail        # 发布失败（Social 返回 publish_failed 状态）
MOCK_SCENARIO=notify_fail         # 通知失败（Notify 返回 success=False）
MOCK_SCENARIO=token_expired        # Token 过期（Social 返回 token_expired 状态）
```

### 各 Provider 场景响应

| Provider | normal | timeout | error | empty | content_violation | publish_fail | notify_fail | token_expired |
|----------|--------|---------|-------|-------|-------------------|--------------|-------------|---------------|
| Social | published/reviewing | publish_timeout | — | — | content_violation | publish_failed | — | token_expired |
| Analytics | 稳定随机数据 | — | — | 空数据 | — | — | — | — |
| Notify | success=True | 超时错误 | — | — | — | — | success=False | — |
| Embedding | 128维伪向量 | — | — | 零向量 | — | — | — | — |
| Map | 预定义坐标 | — | None | — | — | — | — | — |

---

## 11. 一键重置脚本

当前项目未提供独立的重置脚本。可通过以下方式重置：

```bash
# 方式 1：删除数据库并重启（Docker 环境）
docker compose down -v
docker compose up -d

# 方式 2：手动清空数据库
psql -h localhost -U postgres -c "DROP DATABASE ai_social_media;"
psql -h localhost -U postgres -c "CREATE DATABASE ai_social_media;"
# 重启应用，seed_data() 会自动执行
```

> 注意：seed_data() 仅在 admin 用户不存在时执行，如需重新 seed 需先删除所有用户。

---

## 12. 数据导入导出

### 导出

```bash
# 导出 PostgreSQL 数据
pg_dump -h localhost -U postgres ai_social_media > backup.sql
```

### 导入

```bash
psql -h localhost -U postgres ai_social_media < backup.sql
```

### 知识库单独导入

通过 API 批量创建知识库文档：

```bash
curl -X POST http://localhost:8001/api/v1/knowledge/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "kb_type": "content", "content": "...", "tags": [...]}'
```

### 素材导入

通过 API 上传素材至 MinIO：

```bash
curl -X POST http://localhost:8001/api/v1/assets/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@image.jpg"
```

---

## 13. Mock Provider 日志

所有 Mock Provider 的关键操作均通过 Python logging 输出：

```python
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
```

| Provider | Logger 名称 | 关键日志 |
|----------|-------------|----------|
| Social | `app.services.social_provider` | `SocialProvider.publish platform=%s content_id=%s scenario=%s` |
| Analytics | `app.services.analytics_provider` | `AnalyticsProvider.get_content_stats content_id=%s platform=%s views=%d` |
| Notify | `app.services.notify_provider` | `NotifyProvider.send user_id=%s type=%s channel=%s scenario=%s` |
| Embedding | `app.services.embedding_provider` | 无独立日志 |
| Map | `app.services.map_provider` | `MapProvider mock error scenario`（仅 error 场景） |

---

## 14. 未完成事项和风险点

### 未完成

1. **真实社媒 Provider**：`get_social_provider()` 仅实现 mock，抖音/小红书/视频号/公众号的 OAuth 和发布 API 未对接
2. **真实 Analytics Provider**：`get_analytics_provider()` 仅实现 mock，各平台数据回流 API 未对接
3. **真实 Notify Provider**：`get_notify_provider()` 仅实现 mock，企微/邮件通知未对接
4. **真实 Embedding Provider**：`get_embedding_provider()` 仅实现 mock，OpenAI Embedding 未对接
5. **真实 Map Provider**：`get_map_provider()` 仅实现 mock，高德/腾讯地图 API 未对接
6. **Celery 异步任务**：`backend/app/tasks/` 已搭建框架，但未配置真实 Broker
7. **MinIO 素材存储**：配置已就绪，但上传接口可能需要调试
8. **Elasticsearch 全文检索**：配置已预留，知识库检索当前使用数据库 ILIKE 查询
9. **一键重置脚本**：尚未创建，需手动删除数据库重建
10. **内容本地化**：`localize()` 方法已实现，但 mock 模式下本地化质量有限

### 风险点

1. **Seed 数据幂等性**：`seed_data()` 仅检查 admin 用户是否存在，部分 seed 数据可能不完整
2. **Mock 场景全局生效**：`MOCK_SCENARIO` 为全局变量，影响所有 Provider，无法按 Provider 单独设置
3. **伪向量检索质量**：128 维伪向量的相似度计算无实际语义意义，仅用于流程验证
4. **并发安全**：无独立的数据库重置脚本，生产环境需确保不会误操作
5. **JWT Secret**：默认 `change-me-in-production`，必须在生产环境修改
6. **电话加密密钥**：`PHONE_ENCRYPTION_KEY` 为默认值，生产环境必须更换
7. **CORS 配置**：默认 `*` 允许所有来源，生产环境需限制为具体域名
8. **风险词库不完整**：当前仅 17 个风险词，实际业务需持续补充
9. **Mock LLM 响应解析**：基于 prompt 哈希的稳定随机可能导致边界情况下的 JSON 解析失败
