# 生产部署指南

## 1. 上线前提

- Linux 服务器，建议 8 核 CPU、16 GB 内存、100 GB SSD；浏览器任务多时按 Celery 并发扩容。
- Docker Engine 24+、Docker Compose v2。
- 已解析域名和有效 HTTPS 证书，或由云负载均衡/CDN 终止 TLS。
- 客户提供正式 LLM Key、企业通知配置（如启用）以及待验收的社媒账号。

社媒网页自动化受平台验证码、风控、账号权限和 DOM 改版影响。代码部署完成后，必须使用正式账号逐平台验收，不能把测试环境通过等同于平台侧上线通过。

## 2. 创建生产配置

```bash
cp .env.example .env
chmod 600 .env
```

至少修改以下变量：

```dotenv
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=<openssl rand -hex 32>
PHONE_ENCRYPTION_KEY=<openssl rand -hex 32>
COOKIE_ENCRYPTION_KEY=<独立的 openssl rand -hex 32；轮换前先迁移 Cookie>

POSTGRES_USER=ai_app
POSTGRES_PASSWORD=<至少12位强随机密码>
POSTGRES_DB=ai_social_media
DATABASE_URL=postgresql+asyncpg://ai_app:<URL编码后的同一密码>@postgres:5432/ai_social_media

REDIS_PASSWORD=<至少16位强随机密码>
REDIS_URL=redis://:<URL编码后的同一密码>@redis:6379/0

MINIO_ACCESS_KEY=<非默认访问键>
MINIO_SECRET_KEY=<至少16位强随机密钥>
CORS_ORIGINS=https://social.example.com
ALLOWED_HOSTS=social.example.com,health.internal
HEALTHCHECK_HOST=health.internal

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<正式Key>
AI_MOCK_MODE=false

BOOTSTRAP_ADMIN_ENABLED=true
BOOTSTRAP_ADMIN_USERNAME=admin
SEED_ADMIN_PASSWORD=<至少12位且包含字母和数字>
```

若使用 Qwen，将 `LLM_PROVIDER` 改为 `qwen` 并配置 `QWEN_API_KEY`。生产允许的默认集成组合是：

- `SOCIAL_PROVIDER=synapse_embedded`
- `ANALYTICS_PROVIDER=database`
- `CRAWLER_PROVIDER=mediacrawler_embedded`
- `NOTIFY_PROVIDER=disabled|wecom|email`
- `EMBEDDING_PROVIDER=disabled|openai`
- `MAP_PROVIDER=disabled|amap|tencent`

应用会在生产启动时校验上述配置。任何默认密钥、mock Provider、HTTP 公网模型地址、弱管理员口令、无密码 Redis 或非 HTTPS CORS 都会阻止 Backend 启动。

## 3. 网络与 HTTPS

基础 Compose 为本地联调把调试端口绑定到 `127.0.0.1`。生产必须叠加 `docker-compose.prod.yml`，它会完全移除 PostgreSQL、Redis、MinIO、Backend 与 Frontend 的宿主端口，只保留 Web 入口。推荐让宿主机 Caddy/Nginx 或云负载均衡把 HTTPS 反代到 `127.0.0.1:${APP_HTTP_PORT}`。

CORS 只由 Backend 根据 `CORS_ORIGINS` 返回，仓库内 Nginx 只负责安全响应头，不在生产 Compose 中覆盖或重写 `Access-Control-*` 响应头。生产环境必须使用具体 HTTPS 来源，只有 `APP_ENV=development` 可临时使用 `CORS_ORIGINS=*`。

若直接使用仓库内 Nginx 终止 TLS：

1. 将证书只读挂载到 `nginx/certs`。
2. 在 `docker-compose.yml` 启用 `443:443` 与证书挂载。
3. 在 `nginx/nginx.conf` 启用 HTTPS server、替换域名并开启 HTTP → HTTPS 跳转。
4. HTTPS 验证通过后再启用 HSTS。

防火墙只允许 80/443 和受限来源的 SSH；不要把 5432、6379、9000/9001、8000 暴露公网。

## 4. 构建、迁移与启动

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --wait --wait-timeout 600
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:${APP_HTTP_PORT:-8080}/health/ready
```

Backend entrypoint 会先确认 Chromium 完整、等待 PostgreSQL、执行 `alembic upgrade head`，任何一步失败都会阻止 API 对外服务。Celery 仅在 Backend 健康后启动。

首次登录后立即：

1. 修改管理员密码。
2. 创建具备最小权限的运营用户。
3. 若不再需要自动补建管理员，设置 `BOOTSTRAP_ADMIN_ENABLED=false` 后重启。
4. 在模型配置页测试真实 LLM。
5. 逐个平台重新扫码登录，不迁移开发 Cookie。

## 5. 验收

```bash
./scripts/test-integration.sh
./scripts/verify-local.sh
docker compose logs --tail=200 backend celery nginx
```

上线验收至少包括：

- 登录、刷新 Token、角色权限和禁用账号。
- Refresh Token 单次轮换、旧 Token 重放拒绝，以及退出/改密/重置密码后旧 Access/Refresh Token 的即时失效。
- 内容生成、风控失败、AI 改写、人工审核以及未审核发布拦截。
- MinIO 上传、预览、下载和私有素材权限。
- Celery 发布成功、队列不可用、失败重试、取消和定时任务。
- 采集路径限制、条目导入幂等性。
- 企业微信验签回调（启用时）。
- 小红书、抖音、快手、B站、视频号用正式账号逐项验证媒体、声音、封面、标题、话题、可见范围和作品链接。

## 6. 备份、恢复与升级

```bash
bash scripts/backup.sh
```

脚本读取 `.env`，备份 PostgreSQL 与 MinIO 到 `backups/`，默认保留 7 天。必须把备份同步到异机/对象存储并定期做恢复演练；本机文件不算灾备。

数据库恢复示例：

```bash
gunzip < backups/ai_social_media_YYYYMMDD_HHMMSS.sql.gz | \
  docker compose exec -T postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

升级顺序：备份 → 拉取已审核版本 → 使用生产 Compose 组合执行 `build --pull` → `up -d --wait` → 测试与业务冒烟。Alembic 迁移默认向前执行；涉及破坏性迁移时需在发布前另行准备回滚迁移和数据库快照。

## 7. 监控与故障定位

至少监控：Web 可用性、`/health/ready`、容器重启次数、Celery 队列积压、磁盘/数据卷、PostgreSQL、Redis、证书到期和备份任务。

```bash
docker compose logs -f backend --tail=200
docker compose logs -f celery --tail=200
docker compose exec backend alembic current
docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping'
```

常见判断：

- Backend 不健康：先看生产配置校验、迁移、PostgreSQL/Redis/MinIO 连接。
- 任务一直排队：检查 Celery 健康、Redis 和 worker 内存。
- 发布失败：查看任务日志/截图与 Cookie 状态；平台改版时更新适配器 Selector。
- 上传 502：检查 MinIO，而不是接受 mock URL 降级；生产代码不会静默伪造上传成功。

## 8. 交付包

```bash
bash scripts/package-delivery.sh
```

生成的压缩包会排除 `.env`、Git 历史、依赖目录、数据库备份、浏览器 Profile/Cookie、采集产物和诊断截图，并生成同名 `.sha256` 校验文件。交付前仍应人工检查压缩包文件清单，并用 `sha256sum -c <文件>.sha256`（macOS 用 `shasum -a 256 -c`）验证传输完整性。
