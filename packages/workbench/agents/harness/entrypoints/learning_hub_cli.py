"""learning_hub_cli — fast-path commands for System Learning Hub.

inspect-queue / inspect-health  read Markdown reports with stdlib only.
run / analyze                    dynamically import system_learning packages (pandas/pyarrow).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
REPORTS_DIR = WORKBENCH_ROOT / "Output" / "system_learning" / "latest"

HELP = """system learning-hub — System Learning Hub commands

  inspect-queue [--json]    Show improvement queue
  inspect-health [--json]   Show subsystem health report

Exit codes:  0 success  1 runtime error  2 bad arguments"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print(HELP)
        return 0

    cmd, *rest = args
    use_json = "--json" in rest

    if cmd == "inspect-queue":
        return _inspect_queue(json_output=use_json)

    if cmd == "inspect-health":
        return _inspect_health(json_output=use_json)

    print(f"learning-hub: unknown command '{cmd}'", file=sys.stderr)
    print(HELP, file=sys.stderr)
    return 2


# ── fast-path: stdlib only (Markdown parsing) ──────────────────────────

if __name__ == "__main__":
    sys.exit(main())


def _parse_md_table(lines: list[str]) -> list[dict[str, str]]:
    """Parse a standard markdown table into list of dicts."""
    header_line = None
    sep_line = None
    data_lines: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "---" in stripped:
            sep_line = i
            if i > 0 and lines[i - 1].strip().startswith("|"):
                header_line = i - 1
        elif stripped.startswith("|") and sep_line is not None and i > sep_line:
            data_lines.append(stripped)

    if header_line is None:
        return []

    headers = [h.strip() for h in lines[header_line].strip().strip("|").split("|")]
    rows = []
    for dl in data_lines:
        cells = [c.strip() for c in dl.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _inspect_queue(*, json_output: bool = False) -> int:
    path = REPORTS_DIR / "improvement_queue.md"
    if not path.is_file():
        print("learning-hub: no improvement queue report found", file=sys.stderr)
        return 1

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"learning-hub: failed to read report: {exc}", file=sys.stderr)
        return 1

    lines = text.splitlines()
    rows = _parse_md_table(lines)

    if json_output:
        print(json.dumps({"status": "ok", "queue": rows}, indent=2))
        return 0

    if not rows:
        print("Improvement queue is empty.")
        return 0

    print(f"{'STATE':<12} {'PRI':>4} {'SEVERITY':<9} {'SUBSYSTEM':<24} {'ISSUE':<22} {'COUNT':>6}  ACTION")
    print("-" * 120)
    for r in rows:
        action = r.get("Proposed Action", "")[:60]
        print(f"{r.get('State',''):<12} {r.get('Priority',''):>4} {r.get('Severity',''):<9} {r.get('Subsystem',''):<24} {r.get('Issue',''):<22} {r.get('Count',''):>6}  {action}")
    return 0


def _inspect_health(*, json_output: bool = False) -> int:
    path = REPORTS_DIR / "system_health_report.md"
    if not path.is_file():
        print("learning-hub: no health report found", file=sys.stderr)
        return 1

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"learning-hub: failed to read report: {exc}", file=sys.stderr)
        return 1

    lines = text.splitlines()
    rows = _parse_md_table(lines)

    if json_output:
        print(json.dumps({"status": "ok", "health": rows}, indent=2))
        return 0

    if not rows:
        print("No subsystem health data available.")
        return 0

    print(f"{'SUBSYSTEM':<26} {'SCORE':>6} {'BAND':<10} {'EVENTS':>7} {'VIOLATIONS':>11} {'MANUAL':>7}  TOP ISSUE")
    print("-" * 90)
    for r in rows:
        print(f"{r.get('Subsystem',''):<26} {r.get('Score',''):>6} {r.get('Band',''):<10} {r.get('Events',''):>7} {r.get('Violations',''):>11} {r.get('Manual Review',''):>7}  {r.get('Top Issue','')}")
    return 0
