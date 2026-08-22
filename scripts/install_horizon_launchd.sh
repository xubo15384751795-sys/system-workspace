#!/usr/bin/env bash
# Install macOS launchd job for Horizon daily aggregation (runs before System daily_run).
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
HORIZON_ROOT="${HORIZON_ROOT:-$(dirname "${SYSTEM_ROOT}")/Horizon}"
HORIZON_HOUR="${HORIZON_HOUR:-6}"
PLIST_SRC="${SYSTEM_ROOT}/scripts/launchd/com.horizon.daily.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.horizon.daily.plist"
SYSTEM_PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"

mkdir -p "${HOME}/Library/LaunchAgents" "${SYSTEM_ROOT}/Output/runs"
chmod +x "${SYSTEM_ROOT}/scripts/orchestrate.sh" "${SYSTEM_ROOT}/scripts/run_with_runtime_secrets.py"

sed \
  -e "s|__SYSTEM_ROOT__|${SYSTEM_ROOT}|g" \
  -e "s|__HORIZON_ROOT__|${HORIZON_ROOT}|g" \
  -e "s|__SYSTEM_PYTHON__|${SYSTEM_PYTHON}|g" \
  "${PLIST_SRC}" > "${PLIST_DST}.tmp"

"${SYSTEM_PYTHON}" - <<PY
import plistlib
from pathlib import Path
src = Path("${PLIST_DST}.tmp")
data = plistlib.loads(src.read_bytes())
data["StartCalendarInterval"] = {"Hour": int("${HORIZON_HOUR}"), "Minute": 30}
Path("${PLIST_DST}").write_bytes(plistlib.dumps(data))
PY
rm -f "${PLIST_DST}.tmp"

launchctl bootout "gui/$(id -u)/com.horizon.daily" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.horizon.daily"

echo "Installed ${PLIST_DST} (daily ${HORIZON_HOUR}:30)"
