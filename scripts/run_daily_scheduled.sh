#!/usr/bin/env bash
# Scheduled entrypoint for launchd — runs full orchestrated daily pipeline.
set -euo pipefail

# launchd soft maxfiles is often 256; harvester + yfinance need headroom.
ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT

exec bash "${SYSTEM_ROOT}/scripts/orchestrate.sh" daily
