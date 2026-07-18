#!/usr/bin/env bash
# Install the pre-push hook (Phase C5).
#
# This wires `./sys verify --merge` into git push for main, so a direct push
# to main cannot bypass the merge gate. Feature-branch pushes are unaffected.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
HOOK="$ROOT/.git/hooks/pre-push"
cp "$ROOT/scripts/_pre_push_hook.sh" "$HOOK"
chmod +x "$HOOK"
echo "Installed pre-push hook at $HOOK"
echo "It runs ./sys verify --merge on pushes to main. Remove the file to uninstall."
