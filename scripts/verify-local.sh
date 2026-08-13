#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -f .local-ports.env ]; then
    set -a
    . ./.local-ports.env
    set +a
fi

APP_HTTP_PORT=${APP_HTTP_PORT:-8080}

curl -fsS "http://127.0.0.1:$APP_HTTP_PORT/health/ready" >/dev/null
curl -fsS "http://127.0.0.1:$APP_HTTP_PORT/" | grep -q '<div id="app"></div>'
# 始终通过用户实际访问的 nginx 入口校验 API，避免 .local-ports.env
# 与已运行容器端口不一致时产生假失败，同时覆盖反向代理配置。
status=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$APP_HTTP_PORT/api/v1/auth/me")
if [ "$status" != "401" ]; then
    echo "[verify-local] ERROR: 未授权接口预期 401，实际 $status" >&2
    exit 1
fi

echo "[verify-local] 健康检查、前端入口和未授权保护均通过。"
