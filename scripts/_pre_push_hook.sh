#!/usr/bin/env bash
# Pre-push hook (Phase C5): runs the merge gate before allowing a push to main.
#
# Install with:  ./scripts/install_pre_push_hook.sh
# Or:            cp scripts/_pre_push_hook.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
#
# The hook runs `./sys verify --merge` only for pushes that include main. For
# feature branches it is a no-op (the merge-gate job in CI is the authoritative
# check for PRs). This prevents a direct push to main from bypassing the gate.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"

# Read the ref updates from stdin: <local ref> <local sha> <remote ref> <remote sha>
while read -r local_ref local_sha remote_ref remote_sha; do
  remote_branch="${remote_ref#refs/heads/}"
  if [ "$remote_branch" = "main" ]; then
    echo "[pre-push] Push to main detected - running merge gate."
    echo "[pre-push] (skip with: git push --no-verify  -- NOT recommended for main)"
    cd "$ROOT"
    if ! ./sys verify --merge; then
      echo "[pre-push] MERGE GATE FAILED - push to main rejected."
      echo "[pre-push] Fix the failing step above before pushing."
      exit 1
    fi
    echo "[pre-push] merge gate passed - proceeding with push."
  fi
done

exit 0
