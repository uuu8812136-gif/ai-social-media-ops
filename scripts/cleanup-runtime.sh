#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_DIR}"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

SCREENSHOT_DAYS="${SCREENSHOT_RETAIN_DAYS:-7}"
NATIVE_MEDIA_DAYS="${NATIVE_MEDIA_RETAIN_DAYS:-2}"
case "${SCREENSHOT_DAYS}:${NATIVE_MEDIA_DAYS}" in
  *[!0-9:]*|:*) echo "保留天数必须是非负整数" >&2; exit 2 ;;
esac

docker compose exec -T backend sh -ec "
  if [ -d /app/data/synapse/screenshots ]; then
    find /app/data/synapse/screenshots -type f -mtime +${SCREENSHOT_DAYS} -delete
    find /app/data/synapse/screenshots -depth -type d -empty -delete
  fi
"

NATIVE_MEDIA_DIR="${SYNAPSE_NATIVE_BROWSER_SHARED_MEDIA_DIR:-/tmp/ai-social-native-media}"
if [ -d "${NATIVE_MEDIA_DIR}" ]; then
  find "${NATIVE_MEDIA_DIR}" -type f -mtime "+${NATIVE_MEDIA_DAYS}" -delete
fi
find host-browser-bridge/.runtime/logs -type f -mtime "+${SCREENSHOT_DAYS}" -delete \
  2>/dev/null || true
echo "运行数据清理完成：截图 ${SCREENSHOT_DAYS} 天，临时媒体 ${NATIVE_MEDIA_DAYS} 天"
