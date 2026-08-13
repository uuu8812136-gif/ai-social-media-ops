#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ ! -x .venv/bin/pytest ]; then
    echo "[test-integration] ERROR: 请先创建 .venv 并安装 backend/requirements-dev.txt。" >&2
    exit 1
fi
if [ ! -f .local-ports.env ]; then
    echo "[test-integration] ERROR: 未找到 .local-ports.env，请先运行 ./scripts/start-local.sh。" >&2
    exit 1
fi

set -a
. ./.local-ports.env
set +a

export PYTHONPATH="$ROOT_DIR/backend"
export APP_ENV=test
export DATABASE_URL=$(
    POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT" .venv/bin/python - <<'PY'
import os
from sqlalchemy.engine import make_url
from app.core.config import Settings

url = make_url(Settings().DATABASE_URL).set(
    host="127.0.0.1",
    port=int(os.environ["POSTGRES_HOST_PORT"]),
)
print(url.render_as_string(hide_password=False))
PY
)
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT}/0"
export MINIO_ENDPOINT="127.0.0.1:${MINIO_HOST_PORT}"

echo "[test-integration] 使用本地容器数据库端口 ${POSTGRES_HOST_PORT} 运行完整测试。"
.venv/bin/pytest -q backend/tests
