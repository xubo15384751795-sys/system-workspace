#!/usr/bin/env bash
# Paper vault post-commit hook — sync world model into System after each commit.
# Install: bash scripts/install_paper_sync_hook.sh

set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-/Users/a1/System}"
PAPER_ROOT="${PAPER_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
export PAPER_ROOT

if [[ ! -f "${SYSTEM_ROOT}/scripts/sync_paper_world_model.py" ]]; then
  echo "paper-post-commit: SYSTEM_ROOT not found at ${SYSTEM_ROOT}" >&2
  exit 0
fi

PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"
"${PYTHON}" "${SYSTEM_ROOT}/scripts/sync_paper_world_model.py" --quiet-on-success
