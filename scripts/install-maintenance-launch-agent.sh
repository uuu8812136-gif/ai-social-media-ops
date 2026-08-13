#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.ai-social.maintenance"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_FILE="${HOME}/Library/Logs/ai-social-maintenance.log"
DOMAIN="gui/$(id -u)"
LOCAL_RUNTIME="${HOME}/Library/Application Support/ai-social-maintenance"
LOCAL_SCRIPT="${LOCAL_RUNTIME}/maintenance.sh"
LOCAL_ENV="${LOCAL_RUNTIME}/runtime.env"
mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"
TMP_PLIST="$(mktemp)"
trap 'rm -f "${TMP_PLIST}"' EXIT

read_env_value() {
  key=$1
  sed -n "s/^${key}=//p" "${PROJECT_DIR}/.env" 2>/dev/null |
    tail -n 1 | tr -d '\r'
}

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(read_env_value COMPOSE_PROJECT_NAME)}"
PROJECT_NAME="${PROJECT_NAME:-ai-social-media}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-$(read_env_value BACKUP_RETAIN_DAYS)}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
SCREENSHOT_DAYS="${SCREENSHOT_RETAIN_DAYS:-$(read_env_value SCREENSHOT_RETAIN_DAYS)}"
SCREENSHOT_DAYS="${SCREENSHOT_DAYS:-7}"
case "${PROJECT_NAME}" in
  ""|*[!A-Za-z0-9_.-]*) echo "无效的 Compose 项目名" >&2; exit 2 ;;
esac
case "${RETAIN_DAYS}:${SCREENSHOT_DAYS}" in
  *[!0-9:]*|:*) echo "保留天数必须是非负整数" >&2; exit 2 ;;
esac

mkdir -p "${LOCAL_RUNTIME}"
chmod 700 "${LOCAL_RUNTIME}"
cp "${PROJECT_DIR}/scripts/maintenance-launch-agent-runtime.sh" "${LOCAL_SCRIPT}"
chmod 700 "${LOCAL_SCRIPT}"
umask 077
{
  printf 'COMPOSE_PROJECT_NAME=%s\n' "${PROJECT_NAME}"
  printf 'BACKUP_RETAIN_DAYS=%s\n' "${RETAIN_DAYS}"
  printf 'SCREENSHOT_RETAIN_DAYS=%s\n' "${SCREENSHOT_DAYS}"
} > "${LOCAL_ENV}"
chmod 600 "${LOCAL_ENV}"

cat > "${TMP_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${LOCAL_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key><string>${LOCAL_RUNTIME}</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>${LOG_FILE}</string>
  <key>StandardErrorPath</key><string>${LOG_FILE}</string>
</dict>
</plist>
EOF
plutil -lint "${TMP_PLIST}" >/dev/null
chmod 600 "${TMP_PLIST}"
mv "${TMP_PLIST}" "${PLIST}"
launchctl bootout "${DOMAIN}/${LABEL}" >/dev/null 2>&1 || true
launchctl bootstrap "${DOMAIN}" "${PLIST}"
echo "已安装每日 03:00 自动备份与清理：${PLIST}"
echo "自动备份目录：${LOCAL_RUNTIME}/backups"
