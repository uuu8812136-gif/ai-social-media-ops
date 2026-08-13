# AI 社媒系统运维手册

## 1. 访问与服务状态

服务只需要在存放项目的 Mac 服务器上运行，局域网中的其他电脑不需要复制项目。

```bash
cd "/Volumes/liuyan/Documents/ai社媒"
./scripts/start-local.sh
./scripts/verify-local.sh
docker compose ps
```

Web 地址由 `.env` 的 `APP_ACCESS_HOST` 和 `.local-ports.env` 的
`APP_HTTP_PORT` 决定。查看当前地址：

```bash
access_host=$(sed -n 's/^APP_ACCESS_HOST=//p' .env | tail -n 1)
http_port=$(sed -n 's/^APP_HTTP_PORT=//p' .local-ports.env | tail -n 1)
echo "http://${access_host}:${http_port}"
```

当前部署使用 `http://192.168.2.69:8080`。如果服务器更换 Wi-Fi、网线或
路由器后 IP 改变，应先修改 `.env` 中的 `APP_ACCESS_HOST`、`ALLOWED_HOSTS`
和 `CORS_ORIGINS`，再运行 `./scripts/start-local.sh`。不要继续使用已经失效的
旧 IP。

停止服务（保留数据库和素材）：

```bash
./scripts/stop-local.sh
```

## 2. 浏览器登录与人工验证

- 新增授权时，系统直接在 Mac 桌面打开真实 Chrome 登录页。
- 扫码、密码、短信和安全验证全部在该真实网页完成，系统不解析验证码。
- 登录成功后窗口自动隐藏并保存会话。
- 发布过程中平台要求验证时，同一个真实浏览器窗口会再次显示；验证完成后任务继续。
- 不再使用 noVNC、网页内远程桌面或验证码弹层。

浏览器桥状态：

```bash
./host-browser-bridge/status.sh
```

若桥接异常：

```bash
./host-browser-bridge/stop.sh
./host-browser-bridge/start.sh
./host-browser-bridge/status.sh
```

桥接端口固定为 `9324`。它只接受鉴权请求和本机/Docker Desktop 网段访问，
不要把该端口开放给局域网。

## 3. 发布任务的安全处理

发布任务分为四类结果：

- `published`：已取得确定的成功结果。
- `publish_error`：确定失败，可检查原因后重试。
- `publish_unknown`：平台页面已发生变化或连接中断，系统无法确定是否已经投递。
- `waiting_verification`：等待用户在真实平台网页完成人工验证。

`publish_unknown` 不会自动重发，避免同一内容重复发布。管理员必须先到
“数据看板 → 自动化运行健康 → 处理发布任务”核对平台后台，再选择“确认已发布”
或“确认未发布”。只有确认未发布后才允许重新执行。

批次和任务使用幂等键、内容指纹、原子领取令牌和过期任务恢复机制。不要直接在
数据库中修改任务状态。

## 4. 队列与日志

三个队列相互隔离：

| 队列 | 服务 | 用途 |
| --- | --- | --- |
| `default` | `celery` | 通用任务、定时恢复、指标同步 |
| `publish` | `celery-publish` | 社媒发布 |
| `crawl` | `celery-crawl` | 数据采集 |

检查服务与日志：

```bash
docker compose ps
docker compose logs --tail=200 backend nginx
docker compose logs --tail=200 celery celery-publish celery-crawl celery-beat
```

检查队列：

```bash
docker compose exec -T celery \
  celery -A app.tasks.celery_app inspect active_queues --timeout=10
```

定时恢复任务每 5 分钟处理异常中断的发布/采集任务；社媒指标同步每 6 小时入队。

## 5. 备份与恢复

macOS LaunchAgent 每天 03:00 自动执行数据库、MinIO、发布运行数据、浏览器会话
和关键配置备份，并清理过期截图。默认保留 7 天。自动任务的运行文件和快照位于
`~/Library/Application Support/ai-social-maintenance`，不直接执行外置项目盘上的
脚本，因此不会被 macOS 可移动卷后台权限拦截。手动备份仍写入项目的 `backups/`。

检查计划任务：

```bash
launchctl print "gui/$(id -u)/com.ai-social.maintenance"
tail -n 200 "$HOME/Library/Logs/ai-social-maintenance.log"
ls -1t "$HOME/Library/Application Support/ai-social-maintenance/backups" | head
```

手动备份并进行隔离恢复演练：

```bash
bash scripts/backup.sh
latest_manifest=$(ls -1t backups/manifest_*.sha256 | head -n 1)
bash scripts/restore.sh --drill "$latest_manifest"
```

正式恢复会覆盖数据库和数据卷，必须明确执行：

```bash
bash scripts/restore.sh --execute backups/manifest_YYYYMMDD_HHMMSS.sha256 \
  --confirm RESTORE_AI_SOCIAL
```

恢复后运行：

```bash
bash scripts/verify-local.sh
```

## 6. 升级与回归

升级前先备份；升级后依次运行：

```bash
docker compose config --quiet
./scripts/start-local.sh
./scripts/test-integration.sh
cd frontend
npm ci
npm test
npm run build
npx playwright test
```

自动化回归只验证站内流程，不应使用真实账号批量发布。真实平台验收按照
[平台验收矩阵](PLATFORM_ACCEPTANCE_MATRIX.md)逐个平台、逐个账号进行三轮低风险
发布，并记录平台作品 ID/URL、截图和结果。

## 7. 常见故障

### 网页打不开

1. `docker compose ps` 确认 `nginx`、`backend`、`frontend` 为 healthy。
2. 在服务器执行 `curl -fsS http://127.0.0.1:8080/health/ready`。
3. 确认客户端和服务器处于同一局域网。
4. 确认 `.env` 的 `APP_ACCESS_HOST` 是服务器当前 IP，不是旧地址。
5. 端口被占用时查看 `.local-ports.env`，启动脚本可能选择了新的空闲端口。

### 登录页没有弹出

1. 运行 `./host-browser-bridge/status.sh`。
2. 确认 Chrome 没有被 macOS 权限或安全软件阻止。
3. 重启桥接服务，再从账号卡片执行“重新授权”。

### 一直要求验证码

不要重复新建授权或连续重试发布。保留已经弹出的真实平台窗口完成验证，等待系统
复用同一浏览器会话。若平台仍反复验证，应停止该账号自动化，检查账号/IP 风控。

### 投递成功后仍弹验证

先到平台创作者后台核对作品。若作品存在，回到系统把 `publish_unknown` 确认为
“已发布”；不要点击重试，否则可能产生重复内容。
