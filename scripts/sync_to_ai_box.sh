#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="ai-box"
REMOTE_DIR="~/Verity"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Syncing $LOCAL_DIR -> $REMOTE_HOST:$REMOTE_DIR ..."

rsync -avz --delete \
  --exclude='.git' \
  --exclude='.venv*' \
  --exclude='venv*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  --exclude='.pytest_cache' \
  --exclude='.dvc/cache' \
  --exclude='Data/*' \
  --include='Data/harvester' \
  --include='Data/harvester/exports' \
  --include='Data/harvester/exports/latest' \
  --include='Data/harvester/exports/latest/***' \
  --include='Data/system_learning/***' \
  --include='Data/structural_lab/***' \
  --exclude='Output/*' \
  --include='Output/current' \
  --include='Output/current/***' \
  --exclude='ExternalTools/*' \
  --include='ExternalTools/qlib_benchmark_runner' \
  --exclude='ExternalTools/qlib_benchmark_runner/.venv*' \
  --exclude='.system' \
  --exclude='.zcode' \
  --exclude='.DS_Store' \
  "${LOCAL_DIR}/" "${REMOTE_HOST}:${REMOTE_DIR}/"

# The main sync intentionally excludes Data/*; these public external-indicator
# caches are required by the freshness-contract tests, so sync only this
# bounded directory instead of opening the whole data tree.
ssh "${REMOTE_HOST}" 'mkdir -p "$HOME/Verity/Data/harvester/raw/external_indicators"'
rsync -avz \
  "${LOCAL_DIR}/Data/harvester/raw/external_indicators/" \
  "${REMOTE_HOST}:${REMOTE_DIR}/Data/harvester/raw/external_indicators/"

# Native file-boundary adapters consume this read-only system-index snapshot;
# sync the single declared input rather than the rest of Data/system_index.
ssh "${REMOTE_HOST}" 'mkdir -p "$HOME/Verity/Data/system_index"'
rsync -avz \
  "${LOCAL_DIR}/Data/system_index/latest.json" \
  "${REMOTE_HOST}:${REMOTE_DIR}/Data/system_index/latest.json"

# macOS workspaces can hold ``Justfile`` and ``justfile`` as the same inode;
# Linux remote workspaces are case-sensitive and the repository contract tests
# require both spellings. Keep the compatibility copy deterministic after
# rsync rather than relying on filesystem case behavior.
ssh "${REMOTE_HOST}" 'if [ -f "$HOME/Verity/Justfile" ]; then cp "$HOME/Verity/Justfile" "$HOME/Verity/justfile"; fi'

echo "==> Code sync complete!"
