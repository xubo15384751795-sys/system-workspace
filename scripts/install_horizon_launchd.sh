#!/usr/bin/env bash
# Install macOS launchd job for Horizon daily aggregation (runs before System daily_run).
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
HORIZON_ROOT="${HORIZON_ROOT:-$(dirname "${SYSTEM_ROOT}")/Horizon}"
HORIZON_HOUR="${HORIZON_HOUR:-6}"
PLIST_DST="${HOME}/Library/LaunchAgents/com.horizon.daily.plist"

mkdir -p "${HOME}/Library/LaunchAgents" "${SYSTEM_ROOT}/Output/runs"
chmod +x "${SYSTEM_ROOT}/scripts/orchestrate.sh"

cat > "${PLIST_DST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.horizon.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SYSTEM_ROOT}/scripts/orchestrate.sh</string>
    <string>horizon</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${HORIZON_HOUR}</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${SYSTEM_ROOT}/Output/runs/launchd-horizon.log</string>
  <key>StandardErrorPath</key>
  <string>${SYSTEM_ROOT}/Output/runs/launchd-horizon.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SYSTEM_ROOT</key>
    <string>${SYSTEM_ROOT}</string>
    <key>HORIZON_ROOT</key>
    <string>${HORIZON_ROOT}</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.horizon.daily" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.horizon.daily"

echo "Installed ${PLIST_DST} (daily ${HORIZON_HOUR}:30)"
