#!/usr/bin/env bash
# launchd-facing Dagster daily entry (thin wrapper around orchestration.cli).
set -euo pipefail
if ! ulimit -n 65536 2>/dev/null && ! ulimit -n 10240 2>/dev/null; then
  echo "[run_dagster_daily] warning: could not raise the file-descriptor limit; continuing with the inherited limit" >&2
fi
SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT
export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
export PYTHONPATH="${SYSTEM_ROOT}:${SYSTEM_ROOT}/packages/orchestration:${PYTHONPATH:-}"
# Always resolve through the canonical validator.  An explicit PYTHON is an
# allowed CI/operator override only when it is actually Python 3.13; accepting
# it verbatim would let a stale launchd plist silently run the unsupported
# local interpreter outside the supported contract.
PY="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"
export PYTHON="${PY}"
exec bash "${SYSTEM_ROOT}/scripts/orchestrate.sh" daily "$@"
