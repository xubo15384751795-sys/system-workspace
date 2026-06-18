#!/usr/bin/env bash
# Install macOS launchd job for daily System pipeline.
#
# Usage:
#   bash scripts/install_daily_run_launchd.sh
#   DAILY_RUN_HOUR=8 bash scripts/install_daily_run_launchd.sh

set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAPER_ROOT="${PAPER_ROOT:-/Users/a1/Paper}"
HORIZON_ROOT="${HORIZON_ROOT:-/Users/a1/Horizon}"
DAILY_RUN_HOUR="${DAILY_RUN_HOUR:-7}"
PLIST_SRC="${SYSTEM_ROOT}/scripts/launchd/com.system.daily-run.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.system.daily-run.plist"
RUN_SCRIPT="${SYSTEM_ROOT}/scripts/run_daily_scheduled.sh"

mkdir -p "${SYSTEM_ROOT}/Output/runs" "${HOME}/Library/LaunchAgents"
chmod +x "${RUN_SCRIPT}" "${SYSTEM_ROOT}/scripts/orchestrate.sh" 2>/dev/null || true

sed \
  -e "s|__SYSTEM_ROOT__|${SYSTEM_ROOT}|g" \
  -e "s|__PAPER_ROOT__|${PAPER_ROOT}|g" \
  -e "s|__HORIZON_ROOT__|${HORIZON_ROOT}|g" \
  "${PLIST_SRC}" > "${PLIST_DST}.tmp"

python3 - <<PY
import plistlib
from pathlib import Path
src = Path("${PLIST_DST}.tmp")
data = plistlib.loads(src.read_bytes())
data["StartCalendarInterval"] = {"Hour": int("${DAILY_RUN_HOUR}"), "Minute": 0}
Path("${PLIST_DST}").write_bytes(plistlib.dumps(data))
PY
rm -f "${PLIST_DST}.tmp"

launchctl bootout "gui/$(id -u)/com.system.daily-run" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.daily-run"

echo "Installed ${PLIST_DST}"
echo "Schedule: daily at ${DAILY_RUN_HOUR}:00 local time"
echo "Logs: ${SYSTEM_ROOT}/Output/runs/launchd-daily-run.log"
