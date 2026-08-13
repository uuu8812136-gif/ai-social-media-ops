# DESIGN.md — 设计规范

> 本系统是**工具型后台**，不是落地页。设计目标：信息密度高、状态一目了然、流程可追踪、失败可定位。
> 不追求视觉惊艳，追求「打开就知道现在什么状态、下一步该干什么」。

## 一、设计原则

1. **工具优先**：每个页面都是一个操作面，首屏即给出可执行的下一步。
2. **信息密度高**：表格、指标卡、状态标签为主，留白克制，避免大图大字浪费空间。
3. **状态一目了然**：用颜色 + 文案 + 图标三重编码，扫一眼就知道成功/进行中/失败/待处理。
4. **失败必可定位**：失败状态必须展示错误原因，并提供日志/截图/重试入口。
5. **空状态即引导**：空状态不是终点，而是引导用户去创建/添加/开始的起点。
6. **不破坏现有逻辑**：UI/UX 优化只改表现层，不改业务接口与状态机。

## 二、色彩

**只使用 `frontend/src/styles/theme.css` 中已定义的 CSS 变量，不引入新色系。**

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--wm-primary` | `#0f6bc5` | 主色（链接、主按钮、强调） |
| `--wm-primary-light` | `#3b9eff` | 主色亮色（hover、渐变） |
| `--wm-accent` | `#f59e0b` | 强调橙 |
| `--color-success` | `#0d9668` | 成功 |
| `--color-warning` | `#d97706` | 警告/进行中(橙) |
| `--color-danger` | `#dc2626` | 失败/危险 |
| `--color-ink` | `#1a2332` | 主文本 |
| `--color-ink-secondary` | `#4a5568` | 次文本 |
| `--color-ink-tertiary` | `#718096` | 辅助/待处理(灰) |
| `--color-border` | `#e2e8f0` | 边框 |
| `--wm-bg` | `#f5f7fa` | 页面背景 |
| `--wm-surface` | `#ffffff` | 卡片表面 |

指标卡复用 `theme.css` 的 `stat-card--blue/green/amber/purple` 与 `mini-value--*` 变体，不自建新色卡。

## 三、组件

- **统一使用 Element Plus**，保持组件风格一致，不混入其他 UI 库。
- 表格 `el-table` 默认 `size="small"` 提升密度；操作列用 `link` 按钮收敛宽度。
- 状态用 `el-tag` + `type` 表达，禁用自定义色块。
- 弹窗 `el-dialog`、描述列表 `el-descriptions` 用于详情。
- 进度用 `el-progress`，`status` 映射 success/exception/warning。
- 空状态用 `el-empty`，必须带 `description` 与引导按钮。

## 四、状态展示规范

### 通用状态色（与 Element Plus tag type 对齐）

| 状态语义 | 颜色 | el-tag type | 适用场景 |
| --- | --- | --- | --- |
| 成功 | 绿 | `success` | 已发布/有效/已完成/已签单/风控通过 |
| 进行中 | 蓝 | `primary` | 执行中/审核中/已分配 |
| 失败 | 红 | `danger` | 失败/失效/风控未通过/停用 |
| 待处理 | 灰 | `info` | 排队中/待执行/已取消/未知/草稿 |
| 警告/定时 | 橙 | `warning` | 定时待发/已暂停/过期/AI已生成 |

> 注：进行中在本系统用「蓝(primary)」表达，避免与「成功(绿)」混淆；Element Plus 历史上 `type` 缺 `primary`，但当前版本已支持。

### 失败状态必须展示

失败状态（failed/invalid/expired/risk_failed/publish_failed）必须包含：

1. **错误原因**：表格列或详情项直接展示 `error_message` / `reason`，不可仅靠 tooltip。
2. **日志入口**：提供「查看详情」打开任务/批次详情弹窗，内含完整错误与子任务列表。
3. **截图留痕入口**（如有）：Playwright 发布失败时若后端返回截图，在详情中以图片展示。
4. **重试入口**：可重试的失败状态提供「重试」按钮（如发布任务、采集任务）。

### 平台能力状态

- `beta` 平台：可选，文案标注「beta」（如「关键词搜索 beta」）。
- `planned` 平台：`el-option` 必须 `disabled` 并在标签后追加「（待接入）」，不允许选中。
- 采集类型 `creator/detail/comment`：保持禁用并标注「待接入」。

## 五、空状态规范

**空状态必须引导下一步操作**，用 `el-empty` + 主按钮，禁止只写「暂无数据」。

| 页面/区域 | 空状态文案 | 引导动作 |
| --- | --- | --- |
| 仪表盘（无任何数据） | 还没有数据，开始你的第一次运营 | 去创建内容 / 添加账号 / 开始采集 |
| 仪表盘-待审核 | 暂无待审核内容 | 去内容工厂生成 |
| 仪表盘-发布任务 | 暂无发布任务 | 去社媒发布 |
| 仪表盘-采集任务 | 暂无采集任务 | 去数据采集 |
| 内容工厂-内容列表 | 还没有内容，点击新建开始创作 | 切到脚本生成 |
| 账号管理-社媒账号 | 还没有社媒账号，选择平台扫码登录添加 | 选择平台扫码登录 |
| 社媒发布-批次 | 还没有发布任务，选择内容和账号开始发布 | 发起到社媒 |
| 社媒发布-任务 | 还没有发布任务，选择内容和账号开始发布 | 发起到社媒 |
| 数据采集-任务 | 还没有采集任务，选择平台和关键词开始采集 | 新建采集任务 |

## 六、页面布局

固定结构：**左侧导航（240px） + 顶部 header（60px） + 主内容区**。

- 左侧导航：深色背景，分「核心功能 / 运营管理 / 社媒矩阵 / 系统管理」四组，系统管理仅管理员可见，见 `components/Layout.vue`。
- 顶部 header：当前页标题 + 用户信息 + 退出。
- 主内容区：浅灰背景 `--wm-bg`，内边距 24px；每个页面顶部 `page-header`（标题 + 副标题 + 右侧操作）。
- 页面内通用结构：`page-header` → 可选 `page-guide`（流程提示）→ `el-tabs` 或 `panel-card` → 表格/卡片列表。

## 七、表格与指标卡

- **指标卡**：数字用 `stat-value`（38px/800）或 `mini-value`（26px/800）突出，标签用小字辅色；颜色编码状态。
- **表格**：状态列固定宽度（~100px）用 `el-tag`；操作列 `fixed="right"`；长文本 `show-overflow-tooltip`；时间列固定 170~180px。
- **进度**：批次进度同时展示「成功/失败/总数」，不止一个百分比。

## 八、element-plus chunk 体积说明（任务 3 结论）

**现状**：`frontend/src/main.js` 全量引入 element-plus：
```js
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
app.use(ElementPlus, { locale: zhCn })
```
构建后 element-plus 单独 chunk 约 949KB（vite.config.js 已用 `manualChunks` 拆包）。

**结论：保持现状，不做按需引入改造。** 原因如下：

1. **全局副作用依赖**：`app.use(ElementPlus, { locale: zhCn })` 同时注册了全局组件、`v-loading` 指令与中文 locale。改为按需需：
   - 安装 `unplugin-vue-components` + `unplugin-auto-import` 两个新 dev 依赖（任务约束「不要安装新依赖除非必要」）；
   - 用 `<el-config-provider :locale="zhCn">` 包裹 `App.vue` 根节点，否则日期选择器等组件回退英文；
   - `ElMessage`/`ElMessageBox` 等命令式 API 的样式需额外按需引入，遗漏会导致 toast 无样式（已知坑）。
2. **回归风险高**：本系统有 10+ 视图、刚修复的扫码登录（120s 超时）、Celery 任务轮询等强依赖 Element Plus 行为的逻辑，按需引入的任何一个遗漏都会造成线上回归，违背「不要破坏现有功能逻辑」。
3. **任务显式允许**：任务说明已给出 escape hatch——「如果按需引入风险太大（需改所有组件），在 DESIGN.md 里说明原因并保持现状」。

**后续优化建议（非本次范围）**：
- 若确需瘦身，推荐 `unplugin-vue-components` + `unplugin-auto-import`，并在 `App.vue` 用 `ElConfigProvider` 注入 locale，单独为 `ElMessage`/`ElMessageBox`/`ElLoading` 配置样式自动导入，做完必须全量回归扫码登录、发布批次、采集任务三个核心流。
- 图标当前全量注册（`Object.entries(ElementPlusIconsVue)`），未来可改为按视图按需 import 以减小 `@element-plus` 部分。
