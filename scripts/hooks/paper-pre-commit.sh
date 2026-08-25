#!/usr/bin/env bash
# Paper vault pre-commit hook — lint world-model frontmatter before commit.
set -euo pipefail

PAPER_ROOT="${PAPER_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
export PAPER_ROOT
if [[ -z "${SYSTEM_ROOT:-}" ]]; then
  candidate="$(cd "${PAPER_ROOT}/.." && pwd)/Verity"
  if [[ -f "${candidate}/scripts/resolve_system_python.sh" ]]; then
    SYSTEM_ROOT="${candidate}"
  fi
fi
SYSTEM_ROOT="${SYSTEM_ROOT:-}"

changed=$(git diff --cached --name-only --diff-filter=ACM | grep '\.md$' || true)
if [[ -z "${changed}" ]]; then
  exit 0
fi

if [[ -z "${SYSTEM_ROOT}" || ! -f "${SYSTEM_ROOT}/scripts/resolve_system_python.sh" ]]; then
  echo "paper-pre-commit: set SYSTEM_ROOT to the Verity workspace" >&2
  exit 1
fi

args=()
while IFS= read -r file; do
  [[ -n "${file}" ]] && args+=("${PAPER_ROOT}/${file}")
done <<< "${changed}"

PYTHON="$("${SYSTEM_ROOT}/scripts/resolve_system_python.sh")"
"${PYTHON}" "${SYSTEM_ROOT}/scripts/lint_paper_frontmatter.py" "${args[@]}"
