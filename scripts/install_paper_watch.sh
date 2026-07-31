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

# This check passes because it runs in a login shell, whose PATH includes
# Homebrew. launchd's does not. Without exporting a PATH into the plist the
# watcher exits 1 on every start and KeepAlive restarts it forever — an
# invisible crash loop, found at ~98,000 restarts with the Paper sync having
# never run once. Derive the directory from where fswatch actually is rather
# than hardcoding a Homebrew prefix.
FSWATCH_DIR="$(cd "$(dirname "$(command -v fswatch)")" && pwd)"
LAUNCHD_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
case ":${LAUNCHD_PATH}:" in
  *":${FSWATCH_DIR}:"*) ;;
  *) LAUNCHD_PATH="${FSWATCH_DIR}:${LAUNCHD_PATH}" ;;
esac

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
  <!-- Bound a restart loop if the watcher ever fails to start again: without
       this, KeepAlive plus an immediate exit spins as fast as launchd allows. -->
  <key>ThrottleInterval</key>
  <integer>60</integer>
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
    <key>PATH</key>
    <string>${LAUNCHD_PATH}</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.system.paper-watch" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.system.paper-watch"

echo "Installed ${PLIST_DST}"
