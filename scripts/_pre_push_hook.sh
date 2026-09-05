#!/usr/bin/env bash
# Pre-push hook (Phase C5): runs cheap contracts on every branch and the
# canonical merge gate before allowing a push to main.
#
# Install with:  ./scripts/install_pre_push_hook.sh
# Or:            cp scripts/_pre_push_hook.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
#
# The hook is intentionally still bypassable with `git push --no-verify`; the
# server-side required check remains authoritative when available. The source
# digest check prevents an untracked/stale local hook from silently changing
# the local safety rail.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
HOOK_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SOURCE_HOOK="$ROOT/scripts/_pre_push_hook.sh"

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    echo "[pre-push] no SHA-256 utility available" >&2
    return 1
  fi
}

if [ ! -f "$SOURCE_HOOK" ] || [ ! -f "$HOOK_PATH" ]; then
  echo "[pre-push] hook source or installed hook is missing" >&2
  exit 1
fi
SOURCE_DIGEST="$(sha256_file "$SOURCE_HOOK")"
INSTALLED_DIGEST="$(sha256_file "$HOOK_PATH")"
if [ "$SOURCE_DIGEST" != "$INSTALLED_DIGEST" ]; then
  echo "[pre-push] installed hook digest differs from tracked source" >&2
  echo "[pre-push] run scripts/install_pre_push_hook.sh" >&2
  exit 1
fi

run_contract_subset() {
  echo "[pre-push] running contract subset."
  cd "$ROOT"
  if [ -x "${ROOT}/scripts/resolve_system_python.sh" ]; then
    PYTHON="$("${ROOT}/scripts/resolve_system_python.sh")"
  else
    # Keep copied/test hooks portable; the checked-in workspace always has the
    # resolver, while a clean temporary Git repo may intentionally not.
    PYTHON="${PYTHON:-$(command -v python3)}"
  fi
  ./sys pipeline validate
  PYTHONPATH="$ROOT:packages/workbench/src:packages/harvester/src:scripts${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" "$ROOT/scripts/validate_data_contract_replay.py"
  PYTHONPATH="$ROOT:packages/workbench/src:packages/harvester/src:scripts${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m pytest \
      tests/test_plan_apply.py \
      tests/test_python_support_contract.py \
      tests/test_repository_governance.py \
      -q -o log_cli=false
}

# Read the ref updates from stdin: <local ref> <local sha> <remote ref> <remote sha>
while read -r local_ref local_sha remote_ref remote_sha; do
  case "$remote_ref" in
    refs/heads/main)
      run_contract_subset
    echo "[pre-push] Push to main detected - running merge gate."
    echo "[pre-push] (skip with: git push --no-verify  -- NOT recommended for main)"
    cd "$ROOT"
    if ! ./sys verify --merge; then
      echo "[pre-push] MERGE GATE FAILED - push to main rejected."
      echo "[pre-push] Fix the failing step above before pushing."
      exit 1
    fi
    echo "[pre-push] merge gate passed - proceeding with push."
      ;;
    refs/heads/*)
      run_contract_subset
      ;;
  esac
done

exit 0
