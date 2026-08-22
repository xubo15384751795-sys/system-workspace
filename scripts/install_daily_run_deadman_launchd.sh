#!/usr/bin/env bash
# Install the independent daily-run dead-man switch.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PLIST_SRC="${SYSTEM_ROOT}/scripts/launchd/com.system.daily-run-deadman.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.system.daily-run-deadman.plist"
SYSTEM_PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"

mkdir -p "${HOME}/Library/LaunchAgents" "${SYSTEM_ROOT}/Output/runs"
chmod +x "${SYSTEM_ROOT}/scripts/run_with_runtime_secrets.py"
sed \
  -e "s|__SYSTEM_ROOT__|${SYSTEM_ROOT}|g" \
  -e "s|__SYSTEM_PYTHON__|${SYSTEM_PYTHON}|g" \
  "${PLIST_SRC}" > "${PLIST_DST}.tmp"
plutil -lint "${PLIST_DST}.tmp" >/dev/null
mv "${PLIST_DST}.tmp" "${PLIST_DST}"

launchctl bootout "gui/$(id -u)/com.system.daily-run-deadman" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.daily-run-deadman"

echo "Installed ${PLIST_DST} (daily at 09:00; max heartbeat age 26h)"
