#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "[start-local] 已从 .env.example 创建 .env；当前仅适合本地开发。"
fi

read_env_value() {
    sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'
}

APP_BIND_HOST=${APP_BIND_HOST:-$(read_env_value APP_BIND_HOST)}
APP_BIND_HOST=${APP_BIND_HOST:-127.0.0.1}
APP_ACCESS_HOST=${APP_ACCESS_HOST:-$(read_env_value APP_ACCESS_HOST)}
NATIVE_BROWSER_BRIDGE_PORT=${NATIVE_BROWSER_BRIDGE_PORT:-$(read_env_value NATIVE_BROWSER_BRIDGE_PORT)}
NATIVE_BROWSER_BRIDGE_PORT=${NATIVE_BROWSER_BRIDGE_PORT:-9324}
SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR=${SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR:-$(read_env_value SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR)}
SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR=${SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR:-/tmp/ai-social-native-media}
SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN=${SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN:-$(read_env_value SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN)}
HOST_BROWSER_BRIDGE_TOKEN=${HOST_BROWSER_BRIDGE_TOKEN:-$(read_env_value HOST_BROWSER_BRIDGE_TOKEN)}
HOST_BROWSER_BRIDGE_TOKEN=${HOST_BROWSER_BRIDGE_TOKEN:-$SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN}
export APP_BIND_HOST APP_ACCESS_HOST NATIVE_BROWSER_BRIDGE_PORT
export SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR
export SYNAPSE_NATIVE_BROWSER_MANAGER_TOKEN HOST_BROWSER_BRIDGE_TOKEN

DOCKER_BIN=$(command -v docker 2>/dev/null || true)
if [ -z "$DOCKER_BIN" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
    DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
    PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    export PATH
fi
if [ -z "$DOCKER_BIN" ]; then
    echo "[start-local] ERROR: 未找到 Docker，请先安装并启动 Docker Desktop。" >&2
    exit 1
fi

if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
    if [ "$(uname -s)" = "Darwin" ] && open -Ra Docker >/dev/null 2>&1; then
        echo "[start-local] 正在启动 Docker Desktop..."
        open -a Docker
        i=0
        while [ "$i" -lt 90 ] && ! "$DOCKER_BIN" info >/dev/null 2>&1; do
            i=$((i + 1))
            sleep 2
        done
    fi
fi
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
    echo "[start-local] ERROR: Docker daemon 不可用。" >&2
    exit 1
fi

# Docker Desktop may stall while starting several dependent services concurrently.
# Serial orchestration is slower by only a few seconds and is much more reliable.
COMPOSE_PARALLEL_LIMIT=${COMPOSE_PARALLEL_LIMIT:-1}
export COMPOSE_PARALLEL_LIMIT

# 重启/升级当前项目时优先复用上次端口；先停止本项目容器释放它们，数据卷不删除。
if [ -f .local-ports.env ]; then
    set -a
    . ./.local-ports.env
    set +a
fi
if [ -n "$("$DOCKER_BIN" compose ps --all --quiet 2>/dev/null)" ]; then
    echo "[start-local] 正在更新当前项目容器（保留数据卷）..."
    "$DOCKER_BIN" compose down --remove-orphans
fi

port_is_free() {
    python3 - "$1" "$2" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        raise SystemExit(1)
PY
}

find_port() {
    candidate=$1
    maximum=$2
    bind_host=${3:-127.0.0.1}
    if [ "$candidate" -gt "$maximum" ]; then
        maximum=$((candidate + 199))
        if [ "$maximum" -gt 65535 ]; then
            maximum=65535
        fi
    fi
    while [ "$candidate" -le "$maximum" ]; do
        if port_is_free "$bind_host" "$candidate"; then
            echo "$candidate"
            return 0
        fi
        candidate=$((candidate + 1))
    done
    echo "[start-local] ERROR: 端口范围 $1-$2 均被占用。" >&2
    return 1
}

POSTGRES_HOST_PORT=$(find_port "${POSTGRES_HOST_PORT:-5434}" 5499)
REDIS_HOST_PORT=$(find_port "${REDIS_HOST_PORT:-6380}" 6449)
FRONTEND_HOST_PORT=$(find_port "${FRONTEND_HOST_PORT:-5174}" 5249)
BACKEND_HOST_PORT=$(find_port "${BACKEND_HOST_PORT:-8001}" 8049)
APP_HTTP_PORT=$(find_port "${APP_HTTP_PORT:-8080}" 8199 "$APP_BIND_HOST")
MINIO_HOST_PORT=$(find_port "${MINIO_HOST_PORT:-9002}" 9049)
MINIO_CONSOLE_HOST_PORT=$(find_port "${MINIO_CONSOLE_HOST_PORT:-9003}" 9099)
if [ "$MINIO_CONSOLE_HOST_PORT" = "$MINIO_HOST_PORT" ]; then
    MINIO_CONSOLE_HOST_PORT=$(find_port "$((MINIO_CONSOLE_HOST_PORT + 1))" 9099)
fi

export POSTGRES_HOST_PORT REDIS_HOST_PORT
export FRONTEND_HOST_PORT BACKEND_HOST_PORT
export APP_HTTP_PORT MINIO_HOST_PORT MINIO_CONSOLE_HOST_PORT

# 账号授权使用宿主机真实 Chrome。固定管理端口由桥接脚本严格检查，
# 若已被其它程序占用则直接报错，避免悄悄切换端口导致容器无法连接。
HOST_BROWSER_BRIDGE_PORT=$NATIVE_BROWSER_BRIDGE_PORT \
    "$ROOT_DIR/host-browser-bridge/start.sh"

mkdir -p "$SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR"
chmod 755 "$SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR"

umask 077
{
    printf 'POSTGRES_HOST_PORT=%s\n' "$POSTGRES_HOST_PORT"
    printf 'REDIS_HOST_PORT=%s\n' "$REDIS_HOST_PORT"
    printf 'FRONTEND_HOST_PORT=%s\n' "$FRONTEND_HOST_PORT"
    printf 'BACKEND_HOST_PORT=%s\n' "$BACKEND_HOST_PORT"
    printf 'APP_HTTP_PORT=%s\n' "$APP_HTTP_PORT"
    printf 'MINIO_HOST_PORT=%s\n' "$MINIO_HOST_PORT"
    printf 'MINIO_CONSOLE_HOST_PORT=%s\n' "$MINIO_CONSOLE_HOST_PORT"
    printf 'NATIVE_BROWSER_BRIDGE_PORT=%s\n' "$NATIVE_BROWSER_BRIDGE_PORT"
} > .local-ports.env

echo "[start-local] 使用端口：Web=$APP_HTTP_PORT API=$BACKEND_HOST_PORT Frontend=$FRONTEND_HOST_PORT NativeBrowser=$NATIVE_BROWSER_BRIDGE_PORT PostgreSQL=$POSTGRES_HOST_PORT Redis=$REDIS_HOST_PORT MinIO=$MINIO_HOST_PORT/$MINIO_CONSOLE_HOST_PORT"
"$DOCKER_BIN" compose config --quiet

diagnostics() {
    "$DOCKER_BIN" compose ps --all || true
    "$DOCKER_BIN" compose logs --tail=120 volume-init postgres redis minio backend celery celery-publish celery-crawl celery-beat frontend nginx || true
    "$ROOT_DIR/host-browser-bridge/status.sh" || true
}

fail_start() {
    echo "[start-local] ERROR: $1" >&2
    diagnostics
    exit 1
}

service_id() {
    "$DOCKER_BIN" compose ps --all --quiet "$1"
}

start_service() {
    service=$1
    id=$(service_id "$service")
    [ -n "$id" ] || fail_start "未找到 $service 容器"
    "$DOCKER_BIN" start "$id" >/dev/null || fail_start "$service 启动失败"
}

wait_for_state() {
    service=$1
    expected=$2
    timeout=$3
    id=$(service_id "$service")
    elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        state=$("$DOCKER_BIN" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || true)
        if [ "$state" = "$expected" ]; then
            return 0
        fi
        case "$state" in
            unhealthy|exited|dead)
                fail_start "$service 状态异常：$state"
                ;;
        esac
        sleep 1
        elapsed=$((elapsed + 1))
    done
    fail_start "等待 $service 进入 $expected 状态超时"
}

# Compose v5 on some Docker Desktop releases can stall while starting a dependency
# graph in parallel. Build/create with Compose, then start in dependency order.
"$DOCKER_BIN" compose build || fail_start "镜像构建失败"
"$DOCKER_BIN" compose create || fail_start "容器创建失败"

volume_init_id=$(service_id volume-init)
[ -n "$volume_init_id" ] || fail_start "未找到 volume-init 容器"
"$DOCKER_BIN" start "$volume_init_id" >/dev/null || fail_start "数据卷权限初始化失败"
volume_init_wait=0
while [ "$volume_init_wait" -lt 30 ]; do
    volume_init_state=$("$DOCKER_BIN" inspect --format '{{.State.Status}}' "$volume_init_id")
    [ "$volume_init_state" = "exited" ] && break
    sleep 1
    volume_init_wait=$((volume_init_wait + 1))
done
[ "$volume_init_state" = "exited" ] || fail_start "等待数据卷权限初始化超时"
volume_init_exit=$("$DOCKER_BIN" inspect --format '{{.State.ExitCode}}' "$volume_init_id")
[ "$volume_init_exit" = "0" ] || fail_start "数据卷权限初始化返回 $volume_init_exit"

start_service postgres
start_service redis
start_service minio
wait_for_state postgres healthy 120
wait_for_state redis healthy 120
wait_for_state minio running 30

start_service backend
wait_for_state backend healthy 240
start_service frontend
wait_for_state frontend healthy 120
start_service celery
wait_for_state celery healthy 180
start_service celery-publish
wait_for_state celery-publish healthy 180
start_service celery-crawl
wait_for_state celery-crawl healthy 180
start_service celery-beat
wait_for_state celery-beat running 60
start_service nginx
wait_for_state nginx healthy 120

if [ -n "$APP_ACCESS_HOST" ]; then
    echo "[start-local] 启动完成：http://$APP_ACCESS_HOST:$APP_HTTP_PORT（监听 $APP_BIND_HOST）"
else
    echo "[start-local] 启动完成：http://127.0.0.1:$APP_HTTP_PORT（监听 $APP_BIND_HOST）"
fi
echo "[start-local] MinIO 控制台：http://127.0.0.1:$MINIO_CONSOLE_HOST_PORT"
