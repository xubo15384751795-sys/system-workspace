#!/usr/bin/env bash
# Unified cross-repo orchestration for System workspace.
#
# Usage:
#   bash scripts/orchestrate.sh daily          # Horizon (optional) + daily_run
#   bash scripts/orchestrate.sh horizon        # Run Horizon aggregator only
#   bash scripts/orchestrate.sh paper-sync     # Paper world model sync
#   bash scripts/orchestrate.sh feedback-export
#   bash scripts/orchestrate.sh install-automation

set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAPER_ROOT="${PAPER_ROOT:-/Users/a1/Paper}"
HORIZON_ROOT="${HORIZON_ROOT:-$(dirname "${SYSTEM_ROOT}")/Horizon}"
export SYSTEM_ROOT PAPER_ROOT HORIZON_ROOT

# Defend against launchd's low soft NOFILE (harvester hits EMFILE otherwise).
ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true

# Auto-detect Python: prefer Framework 3.14, then PYTHON env, then python3
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" ]]; then
    PY="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
  else
    PY="python3"
  fi
else
  PY="${PYTHON}"
fi

run_horizon() {
  if [[ ! -d "${HORIZON_ROOT}" ]]; then
    echo "[orchestrate] Horizon not found at ${HORIZON_ROOT}; skipping"
    return 0
  fi
  if [[ ! -f "${HORIZON_ROOT}/data/config.json" ]]; then
    echo "[orchestrate] Horizon config missing; skipping horizon run"
    return 0
  fi
  echo "[orchestrate] Running Horizon..."
  (
    cd "${HORIZON_ROOT}"
    if [[ -x ".venv/bin/python" ]]; then
      .venv/bin/python -m src.main
    elif command -v uv >/dev/null 2>&1; then
      uv run python -m src.main
    else
      "${PY}" -m src.main
    fi
  )
}

cmd="${1:-daily}"
case "${cmd}" in
  daily)
    run_horizon
    cd "${SYSTEM_ROOT}"
    # Default path: Dagster daily_job (launchd → orchestrate → orchestration.cli).
    # Escape hatch: SYSTEM_USE_LEGACY_DAILY_RUN=1 falls back to scripts/daily_run.py
    # which loads the archived legacy executor.
    export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
    export PYTHONPATH="${SYSTEM_ROOT}:${SYSTEM_ROOT}/packages/orchestration:${PYTHONPATH:-}"
    if [[ "${SYSTEM_USE_LEGACY_DAILY_RUN:-}" == "1" ]]; then
      echo "[orchestrate] SYSTEM_USE_LEGACY_DAILY_RUN=1 — bypassing Dagster CLI"
      exec "${PY}" scripts/daily_run.py "${@:2}"
    fi
    exec "${PY}" -m orchestration.cli daily -- "${@:2}"
    ;;
  horizon)
    run_horizon
    ;;
  paper-sync)
    cd "${SYSTEM_ROOT}"
    exec "${PY}" scripts/sync_paper_world_model.py "${@:2}"
    ;;
  paper-sync-now)
    cd "${SYSTEM_ROOT}"
    exec "${PY}" scripts/sync_paper_world_model.py --force "${@:2}"
    ;;
  feedback-export)
    cd "${SYSTEM_ROOT}"
    exec "${PY}" scripts/commands/weekly/export_feedback_to_paper.py "${@:2}"
    ;;
  install-automation)
    bash "${SYSTEM_ROOT}/scripts/install_daily_run_launchd.sh"
    bash "${SYSTEM_ROOT}/scripts/install_horizon_launchd.sh" || true
    bash "${SYSTEM_ROOT}/scripts/install_paper_sync_hook.sh" || true
    bash "${SYSTEM_ROOT}/scripts/install_paper_lint_hook.sh" || true
    bash "${SYSTEM_ROOT}/scripts/install_paper_watch.sh" || true
    echo "[orchestrate] Automation installers finished"
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    echo "Usage: orchestrate.sh {daily|horizon|paper-sync|feedback-export|install-automation}" >&2
    exit 1
    ;;
esac
