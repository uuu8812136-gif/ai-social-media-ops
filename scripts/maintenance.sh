#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="${PROJECT_DIR}/.maintenance.lock"
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  if [ -d "${LOCK_DIR}" ] &&
     [ "$(( $(date +%s) - $(stat -f %m "${LOCK_DIR}") ))" -gt 21600 ]; then
    rmdir "${LOCK_DIR}" 2>/dev/null || true
    mkdir "${LOCK_DIR}"
  else
    echo "维护任务已在运行，跳过本次。"
    exit 0
  fi
fi
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT INT TERM HUP

bash "${PROJECT_DIR}/scripts/backup.sh"
bash "${PROJECT_DIR}/scripts/cleanup-runtime.sh"
