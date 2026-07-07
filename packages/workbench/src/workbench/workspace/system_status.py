#!/usr/bin/env python3
"""One-screen workspace health digest.

Reads `Data/system_index/latest.json` and `Output/system_learning/latest/summary.json`
and prints a fixed-width table. Designed for terminal consumption and for
pre-commit / pre-merge eyeballing.

If the indexes are stale, run `python3 scripts/build_system_index.py` first.

⚠️ UNTRUSTED ENTRY POINT: This script's key expectations (harvester_release,
deformation_run under `latest`) are stale. The actual system_index uses
top-level keys. Use `freshness_validator.py` or `00_READ_ME_FIRST.md` as
the authoritative health check.
"""
from __future__ import annotations

import json
from pathlib import Path

from ._paths import LEARNING_SUMMARY, SYSTEM_LATEST


def _read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def main() -> int:
    """CLI entry point — print a one-screen workspace health digest."""
    idx = _read_json(SYSTEM_LATEST)
    if idx is None:
        print(f"system_index/latest.json missing at {SYSTEM_LATEST}")
        print("Run: python3 scripts/build_system_index.py")
        return 1
    summary = _read_json(LEARNING_SUMMARY) or {}

    # Support both legacy (under `latest`) and current (top-level) key layout
    latest = idx.get("latest", {})
    if not latest:
        latest = idx  # current layout: keys at top level
    h = latest.get("harvester_release") or latest.get("harvester") or {}
    d = latest.get("deformation_run") or latest.get("structural_replay") or {}
    s = latest.get("deformation_snapshot") or {}
    l = latest.get("learning_report") or latest.get("learning_hub") or {}
    sb = latest.get("sandbox") or {}

    rows: list[tuple[str, str, str]] = []
    # Harvester: show status or existence
    h_status = h.get("status") or ("ok" if h.get("exists") else "<missing>")
    h_detail = h.get("id") or h.get("modified", "-")[:10] if h.get("exists") else "-"
    rows.append((
        "Harvester",
        h_status,
        h_detail,
    ))
    # Deformation: handle both dict and None
    if d and d.get("latest"):
        gaps = ", ".join(d.get("gaps", [])) or "ok"
        d_status = d.get("status", "<missing>")
        d_detail = f"{d.get('id', '-')} (gaps: {gaps})"
    elif d and d.get("exists"):
        d_status = "ok"
        d_detail = d.get("modified", "-")[:10]
    else:
        d_status = "<none>"
        d_detail = "-"
    rows.append((
        "Deformation",
        d_status,
        d_detail,
    ))
    rows.append((
        "Snapshot",
        s.get("status", "<none>"),
        s.get("id") or "-",
    ))
    band = (l.get("band") or "<unknown>")
    open_imp = (summary.get("improvement_queue") or {}).get("proposed", 0)
    crit = (summary.get("overall") or {}).get("critical_subsystems", 0)
    rows.append((
        "LearningHub",
        band,
        f"open={open_imp} critical={crit}",
    ))
    sb_openbb = sb.get("openbb_latest_run") or None
    sb_qlib = sb.get("qlib_latest_run") or None
    rows.append((
        "Sandbox",
        "active" if (sb_openbb or sb_qlib) else "empty",
        f"openbb={sb_openbb['run_id'] if sb_openbb else '-'} qlib={sb_qlib['run_id'] if sb_qlib else '-'}",
    ))

    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    print(f"# system-status   updated_at={idx.get('updated_at', '?')}")
    for layer, status, detail in rows:
        print(f"{layer.ljust(w0)}  {status.ljust(w1)}  {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
