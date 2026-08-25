#!/usr/bin/env bash
# Install Paper post-commit hook to trigger world-model sync into System.
#
# Usage:
#   bash scripts/install_paper_sync_hook.sh
#   PAPER_ROOT=/path/to/Paper SYSTEM_ROOT=/path/to/Verity bash scripts/install_paper_sync_hook.sh

set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAPER_ROOT="${PAPER_ROOT:-/Users/a1/Paper}"
HOOK_SRC="${SYSTEM_ROOT}/scripts/hooks/paper-post-commit.sh"
HOOK_DST="${PAPER_ROOT}/.git/hooks/post-commit"

if [[ ! -d "${PAPER_ROOT}/.git" ]]; then
  echo "Paper git repo not found at ${PAPER_ROOT}" >&2
  exit 1
fi

mkdir -p "$(dirname "${HOOK_DST}")"
cat > "${HOOK_DST}" <<EOF
#!/usr/bin/env bash
export SYSTEM_ROOT="${SYSTEM_ROOT}"
export PAPER_ROOT="${PAPER_ROOT}"
exec bash "${HOOK_SRC}"
EOF
chmod +x "${HOOK_DST}" "${HOOK_SRC}"

echo "Installed post-commit hook -> ${HOOK_DST}"
echo "SYSTEM_ROOT=${SYSTEM_ROOT}"
echo "PAPER_ROOT=${PAPER_ROOT}"
