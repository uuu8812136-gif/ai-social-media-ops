# PRODUCT.md — AI 社媒矩阵运营后台

## 产品定位

**AI 社媒矩阵运营后台**——工具型系统，面向多平台社媒账号的批量内容生产、发布与数据回流运营。
不面向终端消费者，不做花哨落地页；核心价值是「信息密度高、状态一目了然、流程可追踪、失败可定位」。

典型使用者：运营人员在后台完成「选题 → AI 生成 → 风控 → 审核 → 发布 → 采集回流 → 线索转化」的闭环。

## 核心功能模块

| 模块 | 路由 | 职责 |
| --- | --- | --- |
| 仪表盘 | `/dashboard` | 运营总览：账号/内容/线索核心指标、趋势、待审核、风控预警、发布与采集任务概览 |
| 内容工厂 | `/content` | AI 脚本/文案生成、本地化改写、热点选题、风控预检、人工审核、进入社媒矩阵配置并发布、数据回流 |
| 社媒矩阵 | `/social-publish` | 扫码账号授权、Cookie 状态、作品与指标、发布批次、定时发布和失败重试 |
| 数据采集 | `/crawler` | MediaCrawler 关键词搜索采集、采集条目查看、原始文件下载、导入内容工厂 |
| 知识库 | `/knowledge` | 知识条目与引用，供 AI 生成检索增强 |
| 线索管理 | `/leads` | 采集回流线索的分配、跟进、签单转化 |
| 内容日历 | `/calendar` | 内容排期与发布日历 |
| 经销商管理 | `/dealers` | 经销商账号与线索分发 |
| 素材库 | `/assets` | 媒体素材管理 |
| 模型配置 | `/settings/llm` | 管理员配置 OpenAI 兼容模型 API、加密密钥并测试连接 |
| 账号管理 | `/settings/users` | 管理员新增后台登录账号、分配角色、启停和重置密码 |

## 平台能力

平台能力的唯一真相来源：`backend/app/integrations/platform_capabilities.py`。
能力状态分三级：`verified`（已验证可用）/ `beta`（可用，未实测回归）/ `planned`（待接入，前端应禁用并标注「待接入」）。

### 发布能力（synapse_engine，Playwright 自动化）

| 平台 | 状态 | 说明 |
| --- | --- | --- |
| 小红书 xiaohongshu | beta | 五平台共用 BuiltinPlatformAdapter，selector 来自原 Synapse，未做平台级回归 |
| 视频号 channels | beta | 同上 |
| 抖音 douyin | beta | 同上 |
| 快手 kuaishou | beta | 同上 |
| B站 bilibili | beta | 同上 |
| 微博 weibo | planned | 未接入，前端禁用 |

发布模式：直接发布 / 定时发布（scheduled）。

### 采集能力（mediacrawler_engine，关键词搜索 MVP）

| 平台 | 采集码 | 状态 | 采集文案 |
| --- | --- | --- | --- |
| 小红书 | xhs | beta | 关键词搜索 beta |
| 抖音 | dy | beta | 关键词搜索 beta |
| B站 | bili | beta | 关键词搜索 beta |
| 快手 | ks | planned | 待接入 |
| 微博 | wb | planned | 待接入 |

采集类型：`search`（已实现）/ `creator` `detail` `comment`（待接入，前端禁用并标注）。

### 扫码登录

五个发布平台（小红书/视频号/抖音/快手/B站）均由 Synapse 支持二维码登录，获取 Cookie 后用于 Playwright 自动化发布。
启动扫码需打开浏览器加载平台登录页，首次约 30~60s，前端 `startLogin` 单独放宽超时至 120s。

## 用户角色

| 角色 | 标签 | 权限范围 |
| --- | --- | --- |
| admin | 管理员 | 全部模块与操作 |
| operator | 运营官 | 内容/发布/采集/账号/线索等运营操作 |
| dealer | 经销商 | 经销商视角的线索跟进 |

角色与权限由 `backend/app/core/deps.py` 的 `require_roles` 统一校验，前端通过 `directives/permission.js` 做按钮级控制。

模型配置仅管理员可见和修改。API Key 仅以 Fernet 密文保存，前端只显示配置状态和末四位；运行时优先读取数据库配置，没有自定义配置时回退到 `.env`。

系统账号管理仅管理员可见。用户名创建后不可修改；停用账号会立即阻止登录、刷新 Token 和访问受保护接口；当前管理员不能停用或降低自己的角色。

## 核心业务流

```
内容工厂生成 → 风控预检 → 人工审核 → 配置账号/素材/平台参数 → 社媒自动发布（Playwright/Celery worker）→ 数据回流
                                                                  ↑
                                                          扫码登录获取 Cookie
数据采集（关键词搜索）→ 采集条目 → 导入内容工厂 → 进入上述流程 → 线索转化
```
