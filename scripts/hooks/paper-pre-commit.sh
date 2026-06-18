#!/usr/bin/env bash
# Paper vault pre-commit hook — lint world-model frontmatter before commit.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-/Users/a1/System}"
PAPER_ROOT="${PAPER_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
export PAPER_ROOT

changed=$(git diff --cached --name-only --diff-filter=ACM | grep '\.md$' || true)
if [[ -z "${changed}" ]]; then
  exit 0
fi

args=()
while IFS= read -r file; do
  [[ -n "${file}" ]] && args+=("${PAPER_ROOT}/${file}")
done <<< "${changed}"

python3 "${SYSTEM_ROOT}/scripts/lint_paper_frontmatter.py" "${args[@]}"
