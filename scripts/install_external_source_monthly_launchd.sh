#!/usr/bin/env bash
# Install the monthly official external-source endpoint probe.
# This is intentionally explicit: creating/loading the LaunchAgent changes
# the user's schedule, so this script is not called by daily_run.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PLIST_SRC="${SYSTEM_ROOT}/scripts/launchd/com.system.external-source-monthly.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.system.external-source-monthly.plist"
SYSTEM_PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"

mkdir -p "${HOME}/Library/LaunchAgents" "${SYSTEM_ROOT}/Output/runs"
sed \
  -e "s|__SYSTEM_ROOT__|${SYSTEM_ROOT}|g" \
  -e "s|__SYSTEM_PYTHON__|${SYSTEM_PYTHON}|g" \
  "${PLIST_SRC}" > "${PLIST_DST}.tmp"
plutil -lint "${PLIST_DST}.tmp" >/dev/null
mv "${PLIST_DST}.tmp" "${PLIST_DST}"

launchctl bootout "gui/$(id -u)/com.system.external-source-monthly" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.external-source-monthly"

echo "Installed ${PLIST_DST} (monthly on day 1 at 09:15)"
