#!/usr/bin/env bash
# Debounced Paper vault watcher — sync world model after Obsidian saves.
#
# Usage:
#   bash scripts/install_paper_watch.sh
#   bash scripts/watch_paper_sync.sh   # foreground (debug)

set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAPER_ROOT="${PAPER_ROOT:-/Users/a1/Paper}"
DEBOUNCE_SEC="${PAPER_SYNC_DEBOUNCE_SEC:-300}"
WATCH_DIRS=(
  "${PAPER_ROOT}/01_Cases"
  "${PAPER_ROOT}/03_Mechanisms"
  "${PAPER_ROOT}/08_Variables"
  "${PAPER_ROOT}/10_Indicators"
  "${PAPER_ROOT}/05_Trade-Ideas"
)

if ! command -v fswatch >/dev/null 2>&1; then
  echo "fswatch not installed. Install with: brew install fswatch" >&2
  exit 1
fi

echo "Watching Paper vault (debounce ${DEBOUNCE_SEC}s)..."
echo "SYSTEM_ROOT=${SYSTEM_ROOT}"
echo "PAPER_ROOT=${PAPER_ROOT}"
echo "Send 'kill -USR1 <pid>' to force immediate sync."

last_run=0
run_sync() {
  now=$(date +%s)
  if (( now - last_run < DEBOUNCE_SEC )); then
    return 0
  fi
  last_run=$now
  echo "[$(date -Iseconds)] Paper change detected — syncing..."
  if PAPER_ROOT="${PAPER_ROOT}" "${SYSTEM_ROOT}/scripts/orchestrate.sh" paper-sync --quiet-on-success; then
    echo "[$(date -Iseconds)] Paper sync completed."
  else
    status=$?
    echo "[$(date -Iseconds)] Paper sync failed (exit ${status}); watcher remains active." >&2
  fi
}

# USR1 signal forces immediate sync (bypasses debounce)
trap 'last_run=0; echo "[$(date -Iseconds)] Debounce reset — will sync on next change."' USR1

existing_dirs=()
for dir in "${WATCH_DIRS[@]}"; do
  if [[ -d "${dir}" ]]; then
    existing_dirs+=("${dir}")
  fi
done

if [[ ${#existing_dirs[@]} -eq 0 ]]; then
  echo "No Paper watch directories found under ${PAPER_ROOT}" >&2
  exit 1
fi

fswatch -o "${existing_dirs[@]}" | while read -r _; do
  run_sync
done
