#!/usr/bin/env bash
# Install the pre-push hook (Phase C5).
#
# This wires the contract subset into every branch push and
# `./sys verify --merge` into pushes for main. A direct push to main therefore
# cannot bypass the local merge gate without explicitly using --no-verify.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
HOOK="$ROOT/.git/hooks/pre-push"
SOURCE="$ROOT/scripts/_pre_push_hook.sh"

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    echo "No SHA-256 utility available" >&2
    exit 1
  fi
}

if [ ! -f "$SOURCE" ]; then
  echo "Tracked pre-push source is missing: $SOURCE" >&2
  exit 1
fi
mkdir -p "$(dirname "$HOOK")"
cp "$SOURCE" "$HOOK"
chmod +x "$HOOK"
if [ "$(sha256_file "$SOURCE")" != "$(sha256_file "$HOOK")" ]; then
  echo "Installed pre-push hook failed source digest verification" >&2
  exit 1
fi
echo "Installed pre-push hook at $HOOK"
echo "It self-checks its source digest, runs contracts on branch pushes, and runs ./sys verify --merge on main."
echo "Remove the file to uninstall."
