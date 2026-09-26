#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SYSTEM_ROOT="$(cd "${ROOT}/../.." && pwd)"
unset PYTHONPATH

AS_OF_DATE="${1:-$(date -u +%F)}"
PYTHON="$("${ROOT}/../../scripts/resolve_system_python.sh")"

"$PYTHON" -m harvester.cli daily-release --as-of-date "$AS_OF_DATE"
"$PYTHON" -m harvester.cli monitor --max-age-days 2
