"""system run — execute a single daily pipeline registry step."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ROOT = HARNESS_ROOT.parent.parent.parent
RUN_SCRIPT = SYSTEM_ROOT / "scripts" / "run_pipeline_step.py"


def _print_help(file=None) -> None:
    print(
        "system run — execute one daily pipeline step\n"
        "\n"
        "Usage:\n"
        "  system run list [--json] [--all]\n"
        "  system run describe STEP_ID [--json]\n"
        "  system run STEP_ID [--mode auto|subprocess|callable] [--dry-run] [--json] [-- ARG...]\n"
        "\n"
        "Examples:\n"
        "  system run list\n"
        "  system run evidence_grade_report\n"
        "  system run judgment_layer --mode callable --json\n"
        "  system run structural_replay --dry-run\n",
        file=file,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in ("--help", "-h"):
        _print_help()
        return 0

    use_json = "--json" in args
    clean = [a for a in args if a != "--json"]

    if not RUN_SCRIPT.exists():
        print(f"system run: missing runner script: {RUN_SCRIPT}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(RUN_SCRIPT)]
    if use_json:
        cmd.append("--json")

    if not clean:
        _print_help(file=sys.stderr)
        return 2

    head = clean[0]
    if head == "list":
        cmd.append("list")
        if "--all" in clean:
            cmd.append("--all")
    elif head == "describe":
        if len(clean) < 2:
            print("system run describe requires STEP_ID", file=sys.stderr)
            return 2
        cmd.extend(["describe", clean[1]])
    else:
        step_id = head
        tail = clean[1:]
        cmd.extend(["run"])
        if "--dry-run" in tail:
            cmd.append("--dry-run")
        cmd.append(step_id)
        if "--mode" in tail:
            idx = tail.index("--mode")
            if idx + 1 < len(tail):
                cmd.extend(["--mode", tail[idx + 1]])
        if "--" in tail:
            extra = tail[tail.index("--") + 1 :]
            if extra:
                cmd.append("--")
                cmd.extend(extra)

    proc = subprocess.run(cmd, cwd=SYSTEM_ROOT, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")

    if use_json and proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
            if payload.get("status") not in (None, "success") and head not in ("list", "describe"):
                return 1
        except json.JSONDecodeError:
            pass
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
