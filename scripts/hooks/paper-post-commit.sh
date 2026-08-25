#!/usr/bin/env bash
# Paper vault post-commit hook — sync world model into Verity after each commit.
# Install: bash scripts/install_paper_sync_hook.sh

set -euo pipefail

PAPER_ROOT="${PAPER_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
export PAPER_ROOT
if [[ -z "${SYSTEM_ROOT:-}" ]]; then
  candidate="$(cd "${PAPER_ROOT}/.." && pwd)/Verity"
  if [[ -f "${candidate}/scripts/sync_paper_world_model.py" ]]; then
    SYSTEM_ROOT="${candidate}"
  fi
fi

if [[ -z "${SYSTEM_ROOT:-}" || ! -f "${SYSTEM_ROOT}/scripts/sync_paper_world_model.py" ]]; then
  echo "paper-post-commit: set SYSTEM_ROOT to the Verity workspace" >&2
  exit 0
fi

PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"
"${PYTHON}" "${SYSTEM_ROOT}/scripts/sync_paper_world_model.py" --quiet-on-success
