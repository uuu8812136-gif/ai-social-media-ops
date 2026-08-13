#!/bin/bash
# celery worker 容器入口：启动 Xvfb :99 + openbox + x11vnc 5901 + websockify 6080（noVNC 网关），
# 然后跑 celery。Playwright 以 headless=False 跑在 :99 上，
# 用户通过 noVNC 看到的是 worker 当前正在操作的页面（方案 A 共享 worker 浏览器）。
set -e

echo "[worker-entrypoint] APP_ENV=${APP_ENV:-development}"

NATIVE_MEDIA_DIR="${SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR:-/tmp/ai-social-native-media}"
mkdir -p "$NATIVE_MEDIA_DIR"
chmod 755 "$NATIVE_MEDIA_DIR"

if [ "${SYNAPSE_PUBLISH_BROWSER_MODE:-native_host}" = "native_host" ]; then
    echo "[worker-entrypoint] native_host enabled; skipping Xvfb/x11vnc/websockify"
else
# Xvfb 必须以 root 启动（要写 /tmp/.X99-lock 与 /tmp/.X11-unix）
echo "[worker-entrypoint] starting Xvfb on :99 (1280x720x24)"
Xvfb :99 -screen 0 1280x720x24 -ac +extension RANDR +extension GLX +iglx -noreset \
    > /tmp/xvfb.log 2>&1 &
XVFB_PID=$!

# 等 Xvfb 就绪（最长 5 秒）
XVFB_READY=0
for i in $(seq 1 10); do
    if [ -S /tmp/.X11-unix/X99 ]; then
        XVFB_READY=1
        break
    fi
    sleep 0.5
done
if [ "$XVFB_READY" -ne 1 ]; then
    echo "[worker-entrypoint] ERROR: Xvfb did not become ready on :99" >&2
    cat /tmp/xvfb.log >&2 || true
    exit 1
fi
echo "[worker-entrypoint] Xvfb is ready (pid=$XVFB_PID)"

# openbox 窗口管理器（让 Chromium 标题栏/对话框正常显示）
echo "[worker-entrypoint] starting openbox on :99"
DISPLAY=:99 openbox > /tmp/openbox.log 2>&1 &
OPENBOX_PID=$!
sleep 0.4

# x11vnc：监听 5901，密码来自 SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD（默认 trae-vnc-2026）
VNC_PWD="${SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD:-trae-vnc-2026}"
mkdir -p /tmp/vnc
x11vnc -storepasswd "$VNC_PWD" /tmp/vnc/passwd >/dev/null 2>&1
echo "[worker-entrypoint] starting x11vnc on :5901 (display :99)"
x11vnc -display :99 -rfbauth /tmp/vnc/passwd -rfbport 5901 \
    -forever -shared -bg -o /tmp/x11vnc.log
sleep 0.4

# websockify：监听 6080，提供 noVNC 静态资源 + WebSocket 反代到 localhost:5901
echo "[worker-entrypoint] starting websockify on :6080 (web=/opt/novnc, target=localhost:5901)"
websockify --web /opt/novnc 6080 localhost:5901 > /tmp/websockify.log 2>&1 &
WS_PID=$!

WS_READY=0
for i in $(seq 1 20); do
    if (exec 3<>/dev/tcp/127.0.0.1/6080) 2>/dev/null; then
        exec 3>&- 3<&-
        WS_READY=1
        break
    fi
    sleep 0.5
done
if [ "$WS_READY" -ne 1 ]; then
    echo "[worker-entrypoint] ERROR: websockify did not become ready on :6080" >&2
    cat /tmp/websockify.log >&2 || true
    exit 1
fi
echo "[worker-entrypoint] websockify is ready (pid=$WS_PID)"
echo "[worker-entrypoint] VNC endpoint: 5901 (raw VNC, password=$VNC_PWD)"
echo "[worker-entrypoint] noVNC endpoint: http://<host>:6080/vnc.html"

# Playwright 自检：headless=False 模式必须能找到普通 Chromium
echo "[worker-entrypoint] Checking Playwright Chromium (headless=False)..."
if ! python -c "from app.core.config import get_settings; from app.integrations.synapse_engine.utils.playwright_provider import assert_chromium_ready; s=get_settings(); print(assert_chromium_ready(s.SYNAPSE_LOCAL_CHROME_PATH, headless=False))" >/dev/null 2>&1; then
    echo "[worker-entrypoint] ERROR: Playwright Chromium missing/incomplete; rebuild the worker image" >&2
    exit 1
fi
fi

# 等待 postgres 就绪（最长 60 秒，与 backend entrypoint 一致）
echo "[worker-entrypoint] Waiting for postgres..."
POSTGRES_READY=0
for i in $(seq 1 60); do
    if python -c "import socket,os; s=socket.socket(); s.settimeout(2); s.connect((os.environ.get('PG_HOST','postgres'), int(os.environ.get('PG_PORT','5432')))); s.close()" 2>/dev/null; then
        echo "[worker-entrypoint] postgres is reachable"
        POSTGRES_READY=1
        break
    fi
    echo "  ...waiting ($i/60)"
    sleep 1
done
if [ "${POSTGRES_READY}" -ne 1 ]; then
    echo "[worker-entrypoint] ERROR: postgres did not become reachable within 60 seconds" >&2
    exit 1
fi

# celery 不跑 alembic（由 backend 容器负责迁移），直接启动
echo "[worker-entrypoint] starting celery: $@"
exec "$@"
