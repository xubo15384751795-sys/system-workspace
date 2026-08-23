#!/usr/bin/env bash
# Install staged launchd plists (Phase 0.3 + 2.3).
#
# Default is DRY-RUN: prints the diff of what would change. Pass --apply to
# actually install (overwrites the two legacy records and boots out their
# currently loaded labels; Disabled=true means launchd will not load them).
#
# These are persistent config changes (⚠️): the 21:30 run gains --skip-harvester,
# and both runs' logs move from /tmp/ to Output/logs/launchd/. Review the staged
# plists in scripts/launchd/ before applying.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
SYSTEM_PYTHON="$("${ROOT}/scripts/resolve_system_python.sh")"
APPLY=0
if [ "${1:-}" = "--apply" ]; then APPLY=1; fi

if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$ROOT/Output/logs/launchd"
fi

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
        tmp="$dst.tmp"
        sed -e "s|__SYSTEM_ROOT__|${ROOT}|g" \
              -e "s|__SYSTEM_PYTHON__|${SYSTEM_PYTHON}|g" "$src" > "$tmp"
        plutil -lint "$tmp" >/dev/null
        launchctl bootout "gui/$(id -u)/$plist" 2>/dev/null || true
        cp "$tmp" "$dst"
        rm -f "$tmp"
        echo "  installed (disabled legacy record): $dst"
    else
        echo "  [dry-run] would bootout $plist and copy $src -> $dst (disabled; not bootstrapped)"
    fi
done

if [ "$APPLY" -eq 0 ]; then
    echo ""
    echo "Dry-run complete. To apply: $0 --apply"
fi
