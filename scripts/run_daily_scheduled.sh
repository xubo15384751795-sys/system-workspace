#!/usr/bin/env bash
# Scheduled entrypoint for launchd — Dagster daily_job via orchestrate.sh.
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
# This marker is evidence that a bundle came through the real scheduled
# default path.  It is intentionally separate from the human-facing tag.
export SYSTEM_RUN_ORIGIN=launchd
export PYTHONPATH="${SYSTEM_ROOT}:${SYSTEM_ROOT}/packages/orchestration:${PYTHONPATH:-}"
if [[ -z "${SYSTEM_GENERATION_MODE:-}" ]]; then
  if [[ -L "${SYSTEM_ROOT}/Output/live" ]]; then
    export SYSTEM_GENERATION_MODE=1
  else
    export SYSTEM_GENERATION_MODE=0
  fi
fi

# A launchd calendar is a single opportunity, but provider/network and
# transaction failures are often transient.  Retry one bounded time in the
# same invocation so operators do not have to wait for the next calendar day.
# The SQLite slot claim remains the idempotency boundary: a successful first
# attempt makes the retry a harmless duplicate, while a failed/non-published
# attempt is reclaimable by the next attempt.
retry_attempts="${SYSTEM_DAILY_RETRY_ATTEMPTS:-1}"
retry_delay_seconds="${SYSTEM_DAILY_RETRY_DELAY_SECONDS:-30}"
if [[ ! "${retry_attempts}" =~ ^[0-9]+$ ]]; then
  echo "[run_daily_scheduled] invalid SYSTEM_DAILY_RETRY_ATTEMPTS=${retry_attempts}; using 1" >&2
  retry_attempts=1
fi
if [[ ! "${retry_delay_seconds}" =~ ^[0-9]+$ ]]; then
  echo "[run_daily_scheduled] invalid SYSTEM_DAILY_RETRY_DELAY_SECONDS=${retry_delay_seconds}; using 30" >&2
  retry_delay_seconds=30
fi

attempt=0
while true; do
  if bash "${SYSTEM_ROOT}/scripts/run_dagster_daily.sh" "$@"; then
    exit 0
  else
    status=$?
  fi

  # Exit 2/78 represent configuration or missing-runtime failures; retrying
  # those immediately only creates noise.  Codes 3-6 are typed run failures
  # for which a bounded same-day retry can repair a transient condition.
  if (( attempt >= retry_attempts )) || [[ ! "${status}" =~ ^[3456]$ ]]; then
    exit "${status}"
  fi
  attempt=$((attempt + 1))
  echo "[run_daily_scheduled] daily run failed with exit ${status}; retry ${attempt}/${retry_attempts} in ${retry_delay_seconds}s" >&2
  sleep "${retry_delay_seconds}"
done
