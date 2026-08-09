#!/usr/bin/env bash
# Scheduled entrypoint for the authoritative post-close Harvester run.
#
# This job deliberately runs only the acquisition/release command. The full
# System daily pipeline runs once at its morning slot and consumes the latest
# finalized release. Keeping these concerns separate prevents one provider
# outage from starting a second full pipeline and emitting duplicate cascades.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON="${PYTHON:-python3}"

# launchd commonly starts with a low file-descriptor limit.
ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true

export SYSTEM_ROOT
export PYTHONPATH="${SYSTEM_ROOT}/packages/harvester/src${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PYTHON}" -m harvester \
  --exports-root "${SYSTEM_ROOT}/Data/harvester/exports" \
  daily-release
