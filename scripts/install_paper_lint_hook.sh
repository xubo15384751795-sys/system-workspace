#!/usr/bin/env bash
# Install Paper pre-commit frontmatter lint hook.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAPER_ROOT="${PAPER_ROOT:-/Users/a1/Paper}"
HOOK_SRC="${SYSTEM_ROOT}/scripts/hooks/paper-pre-commit.sh"
HOOK_DST="${PAPER_ROOT}/.git/hooks/pre-commit"

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

echo "Installed pre-commit lint hook -> ${HOOK_DST}"
