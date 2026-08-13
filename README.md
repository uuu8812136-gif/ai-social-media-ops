# AI 社媒矩阵运营系统

面向运营团队的内容生产、风控审核、素材管理、社媒账号管理、浏览器自动发布、数据采集与线索协作平台。

后端使用 FastAPI、PostgreSQL、Redis、Celery 和 MinIO，前端使用 Vue 3、Element Plus 与 Vite。发布与采集依赖 Playwright/Patchright 浏览器任务。

> 平台网页会持续改版。代码链路可用不等于目标账号已通过真实平台验收；能力状态以 `backend/app/integrations/platform_capabilities.py` 和前端平台能力提示为准。上线前仍需用客户自己的账号逐平台做低风险发布验收。

## Mac 服务器一键启动

要求 Docker Desktop/Engine 24+ 与 Compose v2。macOS/Linux 执行：

```bash
cp .env.example .env       # 已有 .env 时不要覆盖
./scripts/start-local.sh
```

在存放项目文件的 Mac 服务器上执行上述命令。脚本会构建并启动 PostgreSQL、Redis、MinIO、Backend、Celery、Frontend、Nginx；遇到端口占用会自动顺延选择空闲端口，并把最终端口写入 `.local-ports.env`。

```bash
./scripts/verify-local.sh  # 健康、首页、未授权保护
./scripts/stop-local.sh
```

默认 Web 入口监听全部局域网网卡。其他 Mac 与服务器处于同一局域网时，
直接访问启动脚本输出的地址。地址由 `.env` 的 `APP_ACCESS_HOST` 和
`.local-ports.env` 的 `APP_HTTP_PORT` 决定；当前部署为：

- Web：`http://192.168.2.69:8080`

服务器本机调试入口如下；若发生端口避让，以启动脚本输出为准：

- Web 本机：`http://127.0.0.1:8080`
- Backend：`http://127.0.0.1:8001`
- Frontend 容器直连：`http://127.0.0.1:5174`
- MinIO Console：`http://127.0.0.1:9003`

`.env` 中 `APP_BIND_HOST=0.0.0.0` 负责监听局域网，`APP_ACCESS_HOST` 是客户端
访问地址。如果服务器 IP 改变，需要同步修改 `APP_ACCESS_HOST`、
`ALLOWED_HOSTS` 和 `CORS_ORIGINS` 后重新启动。只有 Web 入口对局域网开放；
数据库、Redis、MinIO、Backend 等调试端口仍限制为服务器本机访问。

开发环境只初始化一个管理员：`admin / admin123`。生产环境不会显示该提示，并会拒绝弱口令配置。

## 业务闭环

发布链路：内容生成 → 风控通过 → 人工审核 → 选择有效社媒账号与素材 → 持久化发布批次 → Celery 派发 → 浏览器发布 → 日志、截图、作品 ID/URL 回填 → 失败重试。

采集链路：选择小红书/抖音/B站与关键词 → Celery 采集 → 受限目录内保存和解析 → 写入采集条目 → 幂等导入内容工厂。

当前发布适配包含小红书、抖音、快手、B站、视频号；当前采集只开放小红书、抖音、B站关键词搜索。未接入能力由前后端共同禁用，不返回伪造业务数据。

## 安全边界

- 生产配置启动即校验：应用密钥、数据库/Redis/MinIO 凭证、真实 LLM Key、HTTPS CORS、管理员口令与 Provider 类型不合规时直接退出。
- 浏览器 Cookie 使用独立密钥加密并以 `0600` 权限原子落盘，旧明文文件首次读取时自动迁移。
- JWT 区分 access/refresh；刷新令牌单次轮换并阻断重放，退出、改密、管理员重置密码或停用账号会立即撤销旧 Access/Refresh Token；浏览器令牌只保存在当前标签会话中。
- 密码采用 bcrypt-sha256，并兼容登录后升级旧 bcrypt 哈希。
- 经销商线索和私有素材执行服务端对象级鉴权。
- 企业微信生产回调只接受加密且验签消息，XML 使用安全解析器。
- 发布只接受已通过风控和人工审核的内容；数据库提交成功后才派发 Celery。
- 远程媒体下载阻断本机、内网和云元数据地址；本地文件路径默认禁用。
- 采集文件只能位于配置的数据目录内，并限制文件大小和解析条数。
- Nginx 提供限流、上传限制、安全响应头和同源私有素材访问。

完整生产配置见 [DEPLOY.md](DEPLOY.md)；实际交付边界见 [项目交接文档.md](项目交接文档.md)。

## 开发与验证

后端：

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
APP_ENV=test .venv/bin/pytest -q backend/tests
.venv/bin/ruff check backend
.venv/bin/pip-audit --local
.venv/bin/bandit -q -r backend/app -x backend/tests -ll
```

前端：

```bash
cd frontend
npm ci
npm audit --audit-level=high
npm test
npm run build
npx playwright test
```

完整容器集成测试：

```bash
./scripts/test-integration.sh
./scripts/verify-local.sh
```

集成测试脚本使用已启动的 PostgreSQL/Redis/MinIO 和宿主机 `.venv`，不会把测试依赖装进生产镜像。

生产部署应叠加不暴露数据与调试端口的覆盖文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

## 运维常用命令

```bash
docker compose ps
docker compose logs -f backend celery celery-publish celery-crawl celery-beat --tail=200
docker compose exec backend alembic current
bash scripts/backup.sh
bash scripts/package-delivery.sh
```

发布/采集队列、真实浏览器人工验证、`publish_unknown` 人工核对、备份恢复和常见
故障处理见 [运维手册](docs/OPERATIONS_RUNBOOK.md)。各平台真实账号上线边界见
[平台验收矩阵](docs/PLATFORM_ACCEPTANCE_MATRIX.md)。

不要把 `.env`、数据库备份、浏览器 Profile、Cookie、模型 Key、`node_modules` 或临时截图放入源码交付包。打包脚本已默认排除这些内容。
