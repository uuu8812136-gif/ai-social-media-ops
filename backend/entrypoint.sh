#!/bin/sh
set -e

echo "[entrypoint] APP_ENV=${APP_ENV:-development}"

# Playwright browser self-check。镜像构建阶段必须已安装浏览器；运行时不联网下载，
# 以保证镜像只读、启动可重复且供应链可审计。
echo "[entrypoint] Checking Playwright Chromium..."
if ! python -c "from app.core.config import get_settings; from app.integrations.synapse_engine.utils.playwright_provider import assert_chromium_ready; s=get_settings(); print(assert_chromium_ready(s.SYNAPSE_LOCAL_CHROME_PATH, headless=s.SYNAPSE_PLAYWRIGHT_HEADLESS))" >/dev/null 2>&1; then
    echo "[entrypoint] ERROR: Playwright Chromium missing/incomplete; rebuild the backend image" >&2
    exit 1
fi


# 等待 postgres 就绪（最长 60 秒）
echo "[entrypoint] Waiting for postgres..."
POSTGRES_READY=0
for i in $(seq 1 60); do
    if python -c "import socket,os; s=socket.socket(); s.settimeout(2); s.connect((os.environ.get('PG_HOST','postgres'), int(os.environ.get('PG_PORT','5432')))); s.close()" 2>/dev/null; then
        echo "[entrypoint] postgres is reachable"
        POSTGRES_READY=1
        break
    fi
    echo "  ...waiting ($i/60)"
    sleep 1
done

if [ "${POSTGRES_READY}" -ne 1 ]; then
    echo "[entrypoint] ERROR: postgres did not become reachable within 60 seconds" >&2
    exit 1
fi

# 数据库迁移失败必须阻止服务启动，避免以不完整表结构对外提供服务。
echo "[entrypoint] Running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
