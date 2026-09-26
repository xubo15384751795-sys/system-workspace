#!/usr/bin/env bash
# launchd-facing runtime adapter (thin wrapper around ``verity daily``).
set -euo pipefail
if ! ulimit -n 65536 2>/dev/null && ! ulimit -n 10240 2>/dev/null; then
  echo "[run_dagster_daily] warning: could not raise the file-descriptor limit; continuing with the inherited limit" >&2
fi
SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT
export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
unset PYTHONPATH
# Always resolve through the canonical validator.  An explicit PYTHON is an
# allowed CI/operator override only when it is actually Python 3.13; accepting
# it verbatim would let a stale launchd plist silently run the unsupported
# local interpreter outside the supported contract.
PY="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"
export PYTHON="${PY}"
# Dependency availability is a runtime contract check, not pipeline
# composition.  The scheduled adapter must fail before entering a partial
# execution when the one Dagster runtime is not installed.
if [[ "${SYSTEM_USE_LEGACY_DAILY_RUN:-}" != "1" ]] && ! "${PY}" -c "import dagster" >/dev/null 2>&1; then
  echo "[run_dagster_daily] Dagster is unavailable; scheduled path is fail-closed" >&2
  exit 78
fi
cd "${SYSTEM_ROOT}"
exec "${PY}" -m verity.cli daily "$@"
