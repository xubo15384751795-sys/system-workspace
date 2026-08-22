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
SYSTEM_PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"

mkdir -p "${SYSTEM_ROOT}/Output/runs" "${HOME}/Library/LaunchAgents"
chmod +x "${RUN_SCRIPT}" "${SYSTEM_ROOT}/scripts/orchestrate.sh" \
  "${SYSTEM_ROOT}/scripts/run_with_runtime_secrets.py" 2>/dev/null || true

sed \
  -e "s|__SYSTEM_ROOT__|${SYSTEM_ROOT}|g" \
  -e "s|__PAPER_ROOT__|${PAPER_ROOT}|g" \
  -e "s|__HORIZON_ROOT__|${HORIZON_ROOT}|g" \
  -e "s|__SYSTEM_PYTHON__|${SYSTEM_PYTHON}|g" \
  "${PLIST_SRC}" > "${PLIST_DST}.tmp"

"${SYSTEM_PYTHON}" - <<PY
import os
import plistlib
from pathlib import Path
from urllib.parse import urlsplit
src = Path("${PLIST_DST}.tmp")
data = plistlib.loads(src.read_bytes())
data["StartCalendarInterval"] = {"Hour": int("${DAILY_RUN_HOUR}"), "Minute": 0}
general_proxy_url = (
    os.environ.get("HARVESTER_HTTP_PROXY_URL")
    or ""
).strip()
cftc_proxy_url = (
    os.environ.get("HARVESTER_CFTC_PROXY_URL")
).strip()
for proxy_name, proxy_url in (
    ("HARVESTER_HTTP_PROXY_URL", general_proxy_url),
    ("HARVESTER_CFTC_PROXY_URL", cftc_proxy_url),
):
    if not proxy_url:
        continue
    parsed = urlsplit(proxy_url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or parsed.path not in {"", "/"}
    ):
        raise SystemExit(f"{proxy_name} must be a credential-free HTTP(S) proxy URL")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise SystemExit(f"{proxy_name} has an invalid port") from exc
environment = data.setdefault("EnvironmentVariables", {})
for proxy_name, proxy_url in (
    ("HARVESTER_HTTP_PROXY_URL", general_proxy_url),
    ("HARVESTER_CFTC_PROXY_URL", cftc_proxy_url),
):
    if proxy_url:
        environment[proxy_name] = proxy_url
    else:
        environment.pop(proxy_name, None)
Path("${PLIST_DST}").write_bytes(plistlib.dumps(data))
PY
rm -f "${PLIST_DST}.tmp"

launchctl bootout "gui/$(id -u)/com.system.daily-run" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.daily-run"

echo "Installed ${PLIST_DST}"
echo "Schedule: daily at ${DAILY_RUN_HOUR}:00 local time"
echo "Logs: ${SYSTEM_ROOT}/Output/runs/launchd-daily-run.log"
if [[ -n "${HARVESTER_HTTP_PROXY_URL:-}" ]]; then
  echo "Global provider egress: explicit HTTP(S) proxy configured"
else
  echo "Global provider egress: direct only (set HARVESTER_HTTP_PROXY_URL explicitly if needed)"
fi
