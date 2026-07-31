#!/usr/bin/env python3
"""Notify when the default branch's CI is failing.

Branch protection is unavailable on this repository (private on a free plan;
the branch-protection API returns 403), so a red commit can reach `main` and
stay there. That happened with 0e3b9c2: `merge-gate` was red on `main` for a
full day before anyone noticed. Local hooks stop a break from being pushed;
this closes the other half by making a red default branch visible.

Read-only: queries the GitHub Actions API via `gh` and notifies. It never
pushes, reverts, or edits anything.

Usage:
    python3 scripts/check_main_ci_status.py
    python3 scripts/check_main_ci_status.py --branch main --workflow ci.yml
    python3 scripts/check_main_ci_status.py --json

Exit codes:
    0  latest run passed, is still running, or status is unknown
    1  latest run failed (a notification was sent)
    2  `gh` is unavailable or not authenticated
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from scripts._constants import TIMEOUT_SHORT
from scripts._notify import notify_failure

# Conclusions that mean "someone should look at this".
_FAILING = {"failure", "timed_out", "startup_failure"}


def _gh_run_list(branch: str, workflow: str) -> list[dict] | None:
    """Return the latest CI run for *branch*, or None if gh is unusable."""
    try:
        proc = subprocess.run(
            [
                "gh", "run", "list",
                "--branch", branch,
                "--workflow", workflow,
                "--limit", "1",
                "--json", "conclusion,status,headSha,displayTitle,url,createdAt",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SHORT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        parsed = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def check(branch: str, workflow: str) -> dict:
    runs = _gh_run_list(branch, workflow)
    if runs is None:
        return {"state": "unavailable", "branch": branch, "workflow": workflow}
    if not runs:
        return {"state": "no_runs", "branch": branch, "workflow": workflow}

    run = runs[0]
    conclusion = (run.get("conclusion") or "").lower()
    status = (run.get("status") or "").lower()
    state = "failing" if conclusion in _FAILING else (
        "running" if status != "completed" else "ok"
    )
    return {
        "state": state,
        "branch": branch,
        "workflow": workflow,
        "conclusion": conclusion or None,
        "status": status or None,
        "head_sha": (run.get("headSha") or "")[:8] or None,
        "title": run.get("displayTitle"),
        "url": run.get("url"),
        "created_at": run.get("createdAt"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--workflow", default="ci.yml")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON.")
    args = parser.parse_args(argv)

    result = check(args.branch, args.workflow)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"{args.branch} / {args.workflow}: {result['state']}")
        if result.get("head_sha"):
            print(f"  {result['head_sha']}  {result.get('title') or ''}")
        if result.get("url"):
            print(f"  {result['url']}")

    if result["state"] == "unavailable":
        print("gh unavailable or not authenticated", file=sys.stderr)
        return 2
    if result["state"] == "failing":
        notify_failure(
            f"{args.branch} CI is red",
            f"{result.get('head_sha')} {result.get('title') or ''} — {result.get('url')}",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
