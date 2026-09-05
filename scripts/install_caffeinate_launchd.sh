#!/usr/bin/env bash
# Keep the Mac from sleeping on AC power so 07:00 launchd runs are not missed.
#
# Usage:
#   bash scripts/install_caffeinate_launchd.sh
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PLIST_SRC="${SYSTEM_ROOT}/scripts/launchd/com.system.caffeinate.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.system.caffeinate.plist"

mkdir -p "${HOME}/Library/LaunchAgents" "${SYSTEM_ROOT}/Output/runs"
sed -e "s|__SYSTEM_ROOT__|${SYSTEM_ROOT}|g" "${PLIST_SRC}" > "${PLIST_DST}.tmp"
plutil -lint "${PLIST_DST}.tmp" >/dev/null
mv "${PLIST_DST}.tmp" "${PLIST_DST}"

launchctl bootout "gui/$(id -u)/com.system.caffeinate" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.caffeinate"

echo "Installed ${PLIST_DST} (caffeinate -s KeepAlive; prevents sleep on AC power)"
