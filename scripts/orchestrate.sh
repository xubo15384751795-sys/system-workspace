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

PY="${PYTHON:-python3}"

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
    exec "${PY}" scripts/daily_run.py "${@:2}"
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
    exec "${PY}" scripts/export_feedback_to_paper.py "${@:2}"
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
