# 方案 A：noVNC 共享 Worker 浏览器人机验证 — 交接文档

交接日期：2026-07-21

本文档记录 2026-07-21 会话中对"人机验证远程操作"功能（方案 A）的全部改动、当前部署状态、操作流程和遗留事项。原 `项目交接文档.md`（2026-07-14 复审基线）保持不变，本文件为其增补。

---

## 1. 背景

原系统发布抖音时遇到人机验证会直接失败。用户需求：
> 识别到验证后，网站弹出验证提示，让客户自己填写验证码到网站提交之后网站再回填验证码，还要考虑多账号发布时多账号跳出验证的情况，还有如果跳出了人机验证的话那就要把网页在前台打开让客户自己操作了。

采用**方案 A：共享 worker 浏览器** — 用户在 noVNC 远程浏览器里看到的就是 worker 当前正在操作的抖音发布页（带 cookie，不用重新登录），手动完成人机验证后 worker 无缝继续发布。

---

## 2. 架构设计

```
┌─────────────┐     ┌────────────────────────────────────────────┐
│  用户浏览器  │     │              celery worker 容器              │
│  (Chrome)   │     │                                            │
│             │     │  ┌──────────────────────────────────────┐  │
│  noVNC 页面 │◄───►│  │  Xvfb :99 (1280x720x24 虚拟显示)     │  │
│  (iframe)   │ WS  │  │  ├─ Chromium (headless=False)         │  │
│             │     │  │  │   └─ 抖音发布页 (带 cookie)        │  │
└──────┬──────┘     │  │  ├─ openbox (窗口管理器)              │  │
       │            │  │  ├─ x11vnc :5901 (VNC 服务)           │  │
       │            │  │  └─ websockify :6080 (noVNC 网关)     │  │
       │            │  └──────────────────────────────────────┘  │
       │            │                                            │
       │            │  celery worker (concurrency=1)             │
       │            │  ├─ 发布任务 → Playwright 操作 Chromium     │
       │            │  ├─ 检测人机验证 → 写库 + 订阅 Redis        │
       │            │  └─ 收到 human_captcha_done → 继续发布      │
       │            └────────────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│   nginx     │
│ /vnc/{sid}/ ├──► celery:6080 (noVNC 静态 + WebSocket)
│ /websockify ├──► celery:6080 (WebSocket 升级)
└─────────────┘
```

### 关键设计点

- **session_id = task_id**：manager 写库时直接用 task_id 当 vnc_session_id，无需额外映射
- **concurrency=1**：同一时间只跑一个发布任务，避免多个 Playwright 抢同一个 X display
- **Redis pub/sub**：频道 `synapse:verify:task:{task_id}`，事件 `human_captcha_done` / `dismissed`
- **600s 超时**：worker 检测到人机验证后阻塞等待 600 秒，超时则任务失败

---

## 3. 本次会话改动清单

### 3.1 后端代码改动

#### `backend/app/integrations/synapse_engine/platforms/builtin.py`
- **改动**：`publish_content` 方法（约 line 1860）的 `headless=True` → `headless=None`
- **原因**：硬编码 `headless=True` 导致 Chromium 以 headless 模式启动，不在 Xvfb :99 上渲染窗口，noVNC 看不到画面
- **效果**：`headless=None` 让 `_launch_browser` 读取 `settings.SYNAPSE_PLAYWRIGHT_HEADLESS`，worker 容器配置 `false` → Chromium 在 Xvfb 渲染 → noVNC 可见；backend 容器默认 `true` 不受影响

#### `backend/app/integrations/synapse_engine/verification/manager.py`
- **改动**：`request_human_captcha` 方法（约 line 389-474）已实现方案 A 逻辑
- **行为**：写库 meta 含 `scheme=worker_shared, vnc_session_id=task_id, vnc_password=trae-vnc-2026, novnc_url=http://celery:6080, display=:99`，阻塞等待 `human_captcha_done`/`dismissed` 事件（600s 超时）
- **状态**：本会话未改动，已稳定运行

### 3.2 前端代码改动

#### `frontend/src/components/BrowserVncDialog.vue` (line 95-99)
- **改动**：noVNC URL 构造 `path=vnc/${id}/websockify` → `path=websockify`
- **原因**：path 里的 `/` 会被浏览器编码成 `%2F`，noVNC 不解码，导致 WebSocket URL 变成 `ws://host/vnc%2F...%2Fwebsockify`，nginx 不匹配任何 location
- **效果**：`path=websockify`（不带 `/`）匹配 nginx 的 `location = /websockify`
- **状态**：✅ 已 rebuild frontend 镜像生效

### 3.3 nginx 配置改动

#### `nginx/snippets/common-server.conf`
新增/修改 3 处：

1. **新增 `location = /websockify`**（line 53-64）
   - 根路径 websockify 反代，配合前端 `path=websockify`（不带 `/`）

2. **修改 `location ~ ^/vnc/{sid}/vnc.html$`**（line 42-51）
   - 新增 `proxy_hide_header Content-Security-Policy` + 宽松 CSP
   - **原因**：noVNC vnc.html 有 inline script 启动代码，被全局 CSP `script-src 'self'` 拦截，noVNC JS 不执行，画面不显示
   - **CSP 内容**：`script-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:`（允许 inline script + WebSocket）

3. **修改 `location ~ ^/vnc/{sid}/{subpath}$`**（静态资源）
   - 新增 `proxy_hide_header Content-Security-Policy`

- **状态**：⚠️ docker cp + nginx reload 临时生效，**重启 nginx 容器会丢失**，需 rebuild nginx 镜像持久化

### 3.4 docker-compose.yml 改动

#### celery 服务（line 146-189）
- **新增** `cap_add: [DAC_OVERRIDE, FOWNER, CHOWN]`
- **原因**：celery 容器以 root 运行，但 `CapEff=0`（没有任何 capability），root 进不去 `/app/data/synapse`（700 appuser:appuser），导致 CookieManager 创建 cookie 目录失败（PermissionError）
- **效果**：重启后 `CapEff=0xb`，root 能访问 cookie 文件
- **状态**：✅ 已写入 docker-compose.yml，重启 celery 生效

### 3.5 celery worker 镜像（已稳定，本会话未改）

#### `backend/Dockerfile.worker`
- 基于 backend 镜像追加：Xvfb + x11vnc + openbox + websockify + noVNC
- Playwright Chromium 以 `headless=False` 跑在 Xvfb :99 上

#### `backend/entrypoint-worker.sh`
- 启动顺序：Xvfb :99 → openbox → x11vnc :5901 → websockify :6080 → celery
- VNC 密码：`SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD`（默认 `trae-vnc-2026`）

---

## 4. 当前部署状态（2026-07-21 14:30）

### 容器状态（全部 healthy）

| 容器 | 状态 | 说明 |
|------|------|------|
| postgres | Up 4 days | 数据库 |
| redis | Up 4 days | 缓存 + pub/sub |
| minio | Up 4 days | 素材存储 |
| backend | Up 3 days | FastAPI |
| nginx | Up 3 days | 反代（CSP 改动是 docker cp 临时生效） |
| celery | Up 3 hours | worker + Xvfb + VNC（cap_add 已生效） |
| frontend | Up 23 minutes | 已 rebuild，含 noVNC URL 修复 |
| browser-vnc | Up 3 days | 旧方案，方案 A 下不使用 |

### 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 127.0.0.1:8080 | nginx | Web 入口 |
| 127.0.0.1:8001 | backend | API 调试 |
| 127.0.0.1:5434 | postgres | 数据库调试 |
| 127.0.0.1:6380 | redis | 缓存调试 |
| 127.0.0.1:9002 | minio | S3 API |
| 127.0.0.1:9003 | minio | 控制台 |
| 127.0.0.1:6081 | celery | noVNC 直连（不走 nginx） |

### 凭证

- 后端登录：`admin / admin123`
- VNC 密码：`trae-vnc-2026`

---

## 5. 操作流程

### 5.1 启动项目

```powershell
cd "D:\浏览器下载\ai社媒\ai社媒"
docker compose up -d
# 等待所有容器 healthy（约 60 秒）
docker compose ps
```

访问 http://127.0.0.1:8080/ ，用 admin/admin123 登录。

### 5.2 触发抖音发布

1. 左侧菜单 → "社媒矩阵"
2. 右上角 "发起到社媒"
3. 对话框中：选内容 → 选 mp4 素材 → 选抖音账号 → 点 "创建发布批次"
4. worker 自动执行：上传视频 → 填写标题/正文 → 点发布

### 5.3 人机验证处理（方案 A）

1. worker 检测到人机验证 → 写库 `needs_human_captcha` → 前端铃铛红点
2. 点铃铛 → 弹出 noVNC 远程浏览器窗口（显示 worker 当前操作的抖音页）
3. 在 noVNC 窗口里手动完成人机验证（拖滑块/点验证码等）
4. 完成后点对话框底部 "继续发布" 按钮（或等 worker 自动检测到验证通过）
5. worker 收到 `human_captcha_done` 事件 → 继续发布 → status=published

### 5.4 noVNC 直连访问（调试用）

不走 nginx，直接访问 celery 容器的 noVNC：
```
http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale&path=websockify&password=trae-vnc-2026
```

### 5.5 查看日志

```powershell
# celery worker 日志（发布流程 + 人机验证）
docker compose logs celery -f --tail 50

# backend 日志（API 请求）
docker compose logs backend -f --tail 50

# nginx 日志（noVNC/WebSocket 请求）
docker compose logs nginx -f --tail 50

# 容器内 VNC 组件日志
docker compose exec celery sh -c "tail -50 /tmp/websockify.log /tmp/x11vnc.log /tmp/xvfb.log"
```

### 5.6 停止项目

```powershell
cd "D:\浏览器下载\ai社媒\ai社媒"
docker compose down
```

---

## 6. 端到端测试验证记录

2026-07-21 已完成完整端到端测试，全部通过：

| 测试项 | 结果 |
|--------|------|
| worker 发布流程（上传→填写→点发布） | ✅ Chromium 无 `--headless`，Xvfb 截图 299KB 有画面 |
| worker 检测人机验证 | ✅ 写库 `needs_human_captcha, scheme=worker_shared` |
| noVNC 后端链路（nginx→websockify→x11vnc→Xvfb） | ✅ curl /websockify 返回 101，websockify/x11vnc 日志有连接 |
| noVNC 通过 nginx 连接（真 Chromium） | ✅ status: Connected (unencrypted) to 3fd892d3e335:99 |
| noVNC 画面渲染 | ✅ 截图 404KB，显示远程桌面 |
| Redis pub/sub 事件传递 | ✅ human_captcha_done subs=1 |
| worker 收到事件继续发布 | ✅ 5-10s 内 status=published |
| 前端 UI 触发发布（patchright 模拟） | ✅ ElMessage "发布批次已创建" → published |

**测试结论**：方案 A 人机验证链路完全可用。从 worker 检测人机验证到发布完成约 10-20 秒。

---

## 7. 已知问题与遗留事项

### 7.1 ⚠️ nginx 镜像未 rebuild（重要）

CSP 修改是 `docker cp + nginx -s reload` 临时生效，**重启 nginx 容器会丢失**。

**持久化方法**：
```powershell
cd "D:\浏览器下载\ai社媒\ai社媒"
docker compose build nginx
docker compose up -d nginx
```

### 7.2 ⚠️ celery 镜像未 rebuild

`builtin.py` 的 `headless=None` 修改是 `docker cp` 临时生效，重启 celery 容器会丢失（但 docker-compose.yml 的 cap_add 已持久化）。

**持久化方法**：
```powershell
docker compose build celery
docker compose up -d celery
```

### 7.3 browser-vnc 容器冗余

方案 A 下不使用 browser-vnc（旧方案）。可在 docker-compose.yml 中注释掉 browser-vnc 服务和 nginx 的 depends_on。

### 7.4 TRAE 内置浏览器不支持 WebSocket

TRAE IDE 的 browser_use（Electron webview）不支持 WebSocket，noVNC 在 TRAE 内置浏览器里显示"加载中"。**用户需用真实浏览器（Chrome/Edge）访问前端**。

### 7.5 多账号并发人机验证

当前 `concurrency=1`，同一时间只跑一个发布任务。多账号发布时排队执行，不会同时跳出多个验证。如需并发，需改造为每个 worker 独立 X display + 独立 VNC 端口。

### 7.6 noVNC 操作延迟

noVNC 通过 WebSocket 传输画面，操作有轻微延迟（约 100-300ms）。人机验证操作（拖滑块等）可能需要适应。

---

## 8. 关键配置项

### `.env` 必须包含

```bash
# VNC 密码（noVNC 连接时用）
SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD=trae-vnc-2026

# Playwright headless 模式（worker 必须 false）
SYNAPSE_PLAYWRIGHT_HEADLESS=false

# X display（worker 容器内 Xvfb）
DISPLAY=:99

# 本地 Chromium 路径（留空用 Playwright 自带的）
SYNAPSE_LOCAL_CHROME_PATH=
```

### docker-compose.yml 关键配置

```yaml
celery:
  environment:
    DISPLAY: ":99"
    SYNAPSE_PLAYWRIGHT_HEADLESS: "false"
    SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD: ${SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD:-trae-vnc-2026}
  cap_add:          # 必须，否则 root 进不去 appuser 700 目录
    - DAC_OVERRIDE
    - FOWNER
    - CHOWN
  ports:
    - "127.0.0.1:${WORKER_VNC_HOST_PORT:-6081}:6080"  # noVNC 直连
```

---

## 9. 故障排查

### noVNC 打开但看不到画面

1. 检查 CSP：浏览器 F12 控制台是否有 `Content Security Policy directive` 错误
   - 有 → nginx CSP 未生效，需 rebuild nginx 镜像或重新 docker cp
2. 检查 WebSocket：F12 Network 是否有 ws:// 请求
   - 无 → 前端 URL 的 path 参数可能带 `/`，检查 BrowserVncDialog.vue
3. 检查 worker Chromium：`docker compose exec celery ps aux | grep chrome`
   - 有 `--headless` 标志 → builtin.py 的 headless 修改未生效，需 rebuild celery
4. 检查 Xvfb 画面：`docker compose exec celery bash -c "DISPLAY=:99 ffmpeg -f x11grab -video_size 1280x720 -i :99 -vframes 1 -y /tmp/check.png"`
   - 黑屏 → worker 浏览器已崩溃，需重启 celery

### 发布任务一直 running 不进入人机验证

- 看 celery 日志确认 worker 卡在哪一步：`docker compose logs celery -f --tail 50`
- 常见原因：视频上传慢、网络问题、抖音页面改版

### 人机验证超时

- worker 阻塞等待 600s，超时后任务变 `publish_unknown`
- 可在 manager.py 调整超时时间（搜索 `timeout=600`）

### celery 容器 PermissionError

- 现象：`PermissionError: [Errno 13] Permission denied: 'data/synapse/cookies'`
- 原因：celery 容器 cap_add 未生效
- 修复：确认 docker-compose.yml 的 celery 服务有 `cap_add: [DAC_OVERRIDE, FOWNER, CHOWN]`，重启 celery

---

## 10. 关键文件清单

| 文件 | 说明 |
|------|------|
| `backend/Dockerfile.worker` | celery worker 镜像（Xvfb + VNC + noVNC） |
| `backend/entrypoint-worker.sh` | worker 入口脚本（启动 Xvfb/VNC/websockify/celery） |
| `backend/app/integrations/synapse_engine/platforms/builtin.py` | 发布逻辑（headless=None 修改点） |
| `backend/app/integrations/synapse_engine/verification/manager.py` | 人机验证管理器（方案 A 实现） |
| `frontend/src/components/VerificationBell.vue` | 铃铛组件（轮询 pending 验证） |
| `frontend/src/components/BrowserVncDialog.vue` | noVNC 弹窗（path=websockify 修改点） |
| `frontend/src/components/Layout.vue` | 顶栏挂铃铛 |
| `nginx/snippets/common-server.conf` | nginx 配置（/vnc/ + /websockify + CSP） |
| `docker-compose.yml` | 编排（celery cap_add + 端口映射） |

---

## 11. 交付包说明

本交付包由 `scripts/package-delivery.sh` 生成，排除：
- `.env`（含密钥）
- `node_modules` / `.venv` / `__pycache__`
- 数据卷 / 备份 / Git 历史
- `dist` 目录（避免嵌套）

**接手方需要做的**：
1. 解压后 `cp .env.example .env` 并填写正式配置
2. `docker compose build`（首次必须，rebuild nginx + celery + frontend 持久化改动）
3. `docker compose up -d`
4. 参考 `DEPLOY.md` 配置正式域名/HTTPS/备份
5. 参考 `README.md` 了解使用方法

---

如需技术支持，提供本文件 + `项目交接文档.md` + `DEPLOY.md` 作为背景。
