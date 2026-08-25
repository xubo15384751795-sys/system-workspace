#!/usr/bin/env bash
set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_SCRIPT="${LOCAL_DIR}/scripts/sync_to_ai_box.sh"

echo "👀 [WatchSync] Starting real-time sync for ${LOCAL_DIR} -> ai-box:~/Verity"
echo "👀 [WatchSync] Press Ctrl+C to stop."

# Run an initial sync
"${SYNC_SCRIPT}"

# Watch for file changes and sync continuously
fswatch -o \
  --exclude '/\.git/' \
  --exclude '/\.venv/' \
  --exclude '/\.mypy_cache/' \
  --exclude '/\.ruff_cache/' \
  --exclude '/\.pytest_cache/' \
  --exclude '/\.dvc/cache/' \
  --exclude '/__pycache__/' \
  --exclude '/\.DS_Store' \
  "${LOCAL_DIR}" | while read -r event; do
    echo "⚡ [$(date +'%H:%M:%S')] Change detected, syncing..."
    "${SYNC_SCRIPT}" >/dev/null 2>&1 || true
    echo "✅ [$(date +'%H:%M:%S')] Synced!"
done
