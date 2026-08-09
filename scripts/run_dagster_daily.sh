#!/usr/bin/env bash
# launchd-facing Dagster daily entry (thin wrapper around orchestration.cli).
set -euo pipefail
ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true
SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT
export SYSTEM_ORCHESTRATOR="${SYSTEM_ORCHESTRATOR:-dagster}"
export PYTHONPATH="${SYSTEM_ROOT}:${SYSTEM_ROOT}/packages/orchestration:${PYTHONPATH:-}"
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" ]]; then
    PY="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
  else
    PY="python3"
  fi
else
  PY="${PYTHON}"
fi
exec bash "${SYSTEM_ROOT}/scripts/orchestrate.sh" daily "$@"
