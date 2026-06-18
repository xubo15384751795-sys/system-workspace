#!/usr/bin/env bash
# Install macOS launchd job for debounced Paper → System sync watcher.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAPER_ROOT="${PAPER_ROOT:-/Users/a1/Paper}"
PLIST_DST="${HOME}/Library/LaunchAgents/com.system.paper-watch.plist"

if ! command -v fswatch >/dev/null 2>&1; then
  echo "fswatch not found — install with: brew install fswatch" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${SYSTEM_ROOT}/Output/runs"
chmod +x "${SYSTEM_ROOT}/scripts/watch_paper_sync.sh"

cat > "${PLIST_DST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.system.paper-watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SYSTEM_ROOT}/scripts/watch_paper_sync.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${SYSTEM_ROOT}/Output/runs/launchd-paper-watch.log</string>
  <key>StandardErrorPath</key>
  <string>${SYSTEM_ROOT}/Output/runs/launchd-paper-watch.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SYSTEM_ROOT</key>
    <string>${SYSTEM_ROOT}</string>
    <key>PAPER_ROOT</key>
    <string>${PAPER_ROOT}</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.system.paper-watch" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.paper-watch"

echo "Installed ${PLIST_DST}"
