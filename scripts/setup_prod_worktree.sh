#!/usr/bin/env bash
# Phase 3.2: production worktree separation (⚠️ persistent config).
#
# Creates a sibling git worktree on main, so the nightly
# launchd jobs run ONLY committed, tested code - not the dirty dev worktree.
# This is the mechanism-level fix for "保存即部署" (save = deploy).
#
# This script is DRY-RUN by default. Pass --apply to actually create the
# worktree and re-point the plists. Review carefully: the nightly jobs will
# switch to running from the prod worktree, so any uncommitted change in the
# dev worktree stops affecting production immediately.
#
# Prerequisites:
#   - Phase 3.1 commits landed (the prod worktree should run committed code).
#   - Data/ and Output/ are shared via symlinks (data not in git).
set -euo pipefail
DEV="${SYSTEM_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PROD="${SYSTEM_PROD_ROOT:-${DEV}-prod}"
APPLY=0
if [ "${1:-}" = "--apply" ]; then APPLY=1; fi

echo "=== Phase 3.2: prod worktree separation ==="
echo "  dev worktree:  $DEV  (dirty, for editing)"
echo "  prod worktree: $PROD (clean main, for nightly jobs)"

if [ -d "$PROD" ]; then
    echo "  [!] $PROD already exists."
else
    if [ "$APPLY" -eq 1 ]; then
        git -C "$DEV" worktree add "$PROD" main
        echo "  created worktree at $PROD on main"
    else
        echo "  [dry-run] would: git -C $DEV worktree add $PROD main"
    fi
fi

# Share Data/ and Output/ (not in git) via symlinks prod -> dev.
for shared in Data Output; do
    if [ "$APPLY" -eq 1 ]; then
        if [ ! -e "$PROD/$shared" ]; then
            ln -s "$DEV/$shared" "$PROD/$shared"
            echo "  symlinked $PROD/$shared -> $DEV/$shared"
        fi
    else
        echo "  [dry-run] would: ln -s $DEV/$shared $PROD/$shared"
    fi
done

# Re-point the launchd plists' WorkingDirectory + script paths to PROD.
if [ "$APPLY" -eq 1 ]; then
    echo ""
    echo "  To re-point launchd jobs to PROD, edit the plists in"
    echo "  ~/Library/LaunchAgents/ to use $PROD as WorkingDirectory, then:"
    echo "    launchctl unload ~/Library/LaunchAgents/com.system.daily-run*.plist"
    echo "    launchctl load ~/Library/LaunchAgents/com.system.daily-run*.plist"
    echo ""
    echo "  Suggested: first switch ONLY the 21:30 job (least critical),"
    echo "  observe one night, then switch the others."
else
    echo ""
    echo "  [dry-run] after applying, re-point launchd plists to $PROD"
    echo "  (see scripts/launchd/ for staged plists; update WorkingDirectory)."
fi

echo ""
if [ "$APPLY" -eq 0 ]; then
    echo "Dry-run complete. To apply: $0 --apply"
    echo "WARNING: this changes what the nightly jobs run. Ensure 3.1 commits landed."
fi
