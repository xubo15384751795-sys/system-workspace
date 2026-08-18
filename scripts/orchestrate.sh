#!/usr/bin/env bash
# Unified cross-repo orchestration for System workspace.
#
# Usage:
#   bash scripts/orchestrate.sh daily          # System daily publisher only
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
if ! ulimit -n 65536 2>/dev/null && ! ulimit -n 10240 2>/dev/null; then
  echo "[orchestrate] warning: could not raise the file-descriptor limit; continuing with the inherited limit" >&2
fi

# Resolve the one supported runtime. An explicit PYTHON is an audited
# compatibility/test override; the default path is always checked to be 3.13.
if [[ -n "${PYTHON:-}" ]]; then
  PY="${PYTHON}"
else
  PY="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"
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
    cd "${SYSTEM_ROOT}"
    # Default path: Dagster daily_job (launchd -> orchestrate -> orchestration.cli).
    # Horizon is an independent producer and must not synchronously block the
    # System core slot. The explicit legacy flag is the only compatibility path.
    export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
    export PYTHONPATH="${SYSTEM_ROOT}:${SYSTEM_ROOT}/packages/orchestration:${PYTHONPATH:-}"
    if [[ -z "${SYSTEM_GENERATION_MODE:-}" ]]; then
      if [[ -L "${SYSTEM_ROOT}/Output/live" ]]; then
        export SYSTEM_GENERATION_MODE=1
      else
        export SYSTEM_GENERATION_MODE=0
      fi
    fi
    "${PY}" "${SYSTEM_ROOT}/scripts/reconcile_generation.py" --fail-on-recovery
    if [[ "${SYSTEM_USE_LEGACY_DAILY_RUN:-}" == "1" ]]; then
      echo "[orchestrate] SYSTEM_USE_LEGACY_DAILY_RUN=1 — bypassing Dagster CLI"
      exec "${PY}" scripts/daily_run.py "${@:2}"
    fi
    if ! "${PY}" -c "import dagster, orchestration.cli" >/dev/null 2>&1; then
      echo "[orchestrate] dagster/orchestration unavailable; default path is fail-closed" >&2
      echo "[orchestrate] install with: uv sync --locked --all-packages" >&2
      echo "[orchestrate] run with: uv run --locked ..." >&2
      echo "[orchestrate] emergency compatibility requires SYSTEM_USE_LEGACY_DAILY_RUN=1" >&2
      exit 78
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
    failed_installers=()
    run_installer() {
      local label="$1"
      shift
      if "$@"; then
        return 0
      else
        local status=$?
        failed_installers+=("${label} (exit ${status})")
        echo "[orchestrate] ${label} installer failed (exit ${status})" >&2
        return 0
      fi
    }

    # Run every installer so one missing optional dependency does not hide the
    # status of the remaining automation components.  The aggregate result is
    # non-zero whenever any requested installer failed.
    run_installer "daily System launchd" bash "${SYSTEM_ROOT}/scripts/install_daily_run_launchd.sh"
    run_installer "Horizon launchd" bash "${SYSTEM_ROOT}/scripts/install_horizon_launchd.sh"
    run_installer "Paper post-commit sync hook" bash "${SYSTEM_ROOT}/scripts/install_paper_sync_hook.sh"
    run_installer "Paper pre-commit lint hook" bash "${SYSTEM_ROOT}/scripts/install_paper_lint_hook.sh"
    run_installer "Paper watcher" bash "${SYSTEM_ROOT}/scripts/install_paper_watch.sh"

    if ((${#failed_installers[@]} > 0)); then
      printf '[orchestrate] Automation installers incomplete: %s\n' "${failed_installers[*]}" >&2
      exit 1
    fi
    echo "[orchestrate] Automation installers finished"
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    echo "Usage: orchestrate.sh {daily|horizon|paper-sync|feedback-export|install-automation}" >&2
    exit 1
    ;;
esac
