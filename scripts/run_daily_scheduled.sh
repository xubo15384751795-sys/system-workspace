#!/usr/bin/env bash
# Scheduled entrypoint for launchd — runs full orchestrated daily pipeline.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export SYSTEM_ROOT

exec bash "${SYSTEM_ROOT}/scripts/orchestrate.sh" daily
