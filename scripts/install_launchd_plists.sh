#!/usr/bin/env bash
# Install staged launchd plists (Phase 0.3 + 2.3).
#
# Default is DRY-RUN: prints the diff of what would change. Pass --apply to
# actually install (overwrites ~/Library/LaunchAgents/ and reloads via launchctl).
#
# These are persistent config changes (⚠️): the 21:30 job remains downstream-only,
# the 06:30 job is Harvester-only, and both logs move from /tmp/ to
# Output/logs/launchd/. Review the staged plists in scripts/launchd/ before applying.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
APPLY=0
if [ "${1:-}" = "--apply" ]; then APPLY=1; fi

mkdir -p "$ROOT/Output/logs/launchd"
chmod +x "$ROOT/scripts/run_harvester_scheduled.sh" 2>/dev/null || true

for plist in com.system.daily-run-harvester-postclose com.system.daily-run-harvester; do
    src="$ROOT/scripts/launchd/$plist.plist"
    dst="$AGENTS/$plist.plist"
    echo "=== $plist ==="
    if [ -f "$dst" ]; then
        diff -u "$dst" "$src" || true
    else
        echo "(not currently installed)"
    fi
    if [ "$APPLY" -eq 1 ]; then
        launchctl unload "$dst" 2>/dev/null || true
        cp "$src" "$dst"
        launchctl load "$dst"
        echo "  installed + reloaded: $dst"
    else
        echo "  [dry-run] would copy $src -> $dst and launchctl reload"
    fi
done

if [ "$APPLY" -eq 0 ]; then
    echo ""
    echo "Dry-run complete. To apply: $0 --apply"
fi
