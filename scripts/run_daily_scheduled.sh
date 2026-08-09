#!/usr/bin/env bash
# Scheduled entrypoint for launchd — Dagster daily_job via orchestrate.sh.
set -euo pipefail

# launchd soft maxfiles is often 256; harvester + yfinance need headroom.
ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT
export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
export PYTHONPATH="${SYSTEM_ROOT}:${SYSTEM_ROOT}/packages/orchestration:${PYTHONPATH:-}"

exec bash "${SYSTEM_ROOT}/scripts/run_dagster_daily.sh"
