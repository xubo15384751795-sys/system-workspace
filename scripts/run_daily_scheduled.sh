#!/usr/bin/env bash
# Scheduled entrypoint for launchd — process adapter for ``verity daily``.
set -euo pipefail

# launchd soft maxfiles is often 256; harvester + yfinance need headroom.
if ! ulimit -n 65536 2>/dev/null && ! ulimit -n 10240 2>/dev/null; then
  echo "[run_daily_scheduled] warning: could not raise the file-descriptor limit; continuing with the inherited limit" >&2
fi

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT
# launchd's StartCalendarInterval stays machine-local; the process clock used
# by IDs, shell timestamps, and library loggers is explicitly UTC.
export TZ=UTC
export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
export SYSTEM_SCHEDULE_LABEL="${SYSTEM_SCHEDULE_LABEL:-com.system.daily-run}"
export SYSTEM_SCHEDULE_CALENDAR="${SYSTEM_SCHEDULE_CALENDAR:-XNYS}"
# Scheduler-neutral execution identity. The legacy origin marker below is
# retained only as compatibility metadata; reliability qualification reads the
# explicit trigger/scheduler fields instead.
export SYSTEM_TRIGGER_KIND="${SYSTEM_TRIGGER_KIND:-scheduled}"
export SYSTEM_SCHEDULER_KIND="${SYSTEM_SCHEDULER_KIND:-launchd}"
export SYSTEM_SCHEDULER_ID="${SYSTEM_SCHEDULER_ID:-com.system.daily-run}"
export SYSTEM_SCHEDULE_ID="${SYSTEM_SCHEDULE_ID:-${SYSTEM_SCHEDULE_LABEL}}"
export SYSTEM_TRIGGER_ID="${SYSTEM_TRIGGER_ID:-${SYSTEM_SCHEDULER_ID}-$(date -u +%Y%m%dT%H%M%SZ)}"
export SYSTEM_HOST_ID="${SYSTEM_HOST_ID:-$(hostname 2>/dev/null || printf 'unknown-host')}"
# Compatibility metadata only; it is not the formal meaning of scheduled.
export SYSTEM_RUN_ORIGIN=launchd
unset PYTHONPATH
if [[ -z "${SYSTEM_GENERATION_MODE:-}" ]]; then
  if [[ -L "${SYSTEM_ROOT}/Output/live" ]]; then
    export SYSTEM_GENERATION_MODE=1
  else
    export SYSTEM_GENERATION_MODE=0
  fi
fi

exec bash "${SYSTEM_ROOT}/scripts/run_dagster_daily.sh" "$@"
