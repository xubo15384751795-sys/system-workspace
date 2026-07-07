#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AS_OF_DATE="${1:-$(date -u +%F)}"

python3 -m harvester.cli daily-release --as-of-date "$AS_OF_DATE"
python3 -m harvester.cli monitor --max-age-days 2
