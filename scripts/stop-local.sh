#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -f .local-ports.env ]; then
    set -a
    . ./.local-ports.env
    set +a
fi

DOCKER_BIN=$(command -v docker 2>/dev/null || true)
if [ -z "$DOCKER_BIN" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
    DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
    PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    export PATH
fi
if [ -z "$DOCKER_BIN" ]; then
    echo "[stop-local] ERROR: 未找到 Docker。" >&2
    exit 1
fi

"$DOCKER_BIN" compose down
"$ROOT_DIR/host-browser-bridge/stop.sh"
