"""Control-closure runtime (Phase D code).

Phase D is, by definition, calendar-bound (observe 5-10 real daily runs in
shadow-enforcement, then switch to hard enforcement). The code-implementable
parts live here:

1. **Shadow-enforcement toggle** (``CONTROL_ENFORCEMENT_MODE``): the new
   controller can run in ``shadow`` (compute "what should be blocked" but
   don't actually block) or ``hard`` (actually block). Default is ``hard``
   after Phase A/B/C; set ``CONTROL_ENFORCEMENT_MODE=shadow`` to observe
   before enforcing.

2. **Historical sample tagging**: tag each shadow NAV row with
   ``VALID`` / ``DEGRADED`` / ``INVALIDATED`` so promotion stats can filter.
   ``HOLD_DEGRADED`` rows (Phase A) are ``DEGRADED``; a future explicit
   invalidation command marks rows ``INVALIDATED``.

3. **Promotion filter**: promotion/capability-board reads must exclude
   ``DEGRADED`` and ``INVALIDATED`` samples (Phase A's
   build_90d_outcomes_summary already excludes HOLD_DEGRADED; this module
   generalizes the filter for any reader).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT

# ── enforcement mode ─────────────────────────────────────────────────────


def enforcement_mode() -> str:
    """``hard`` (default) or ``shadow`` (observe, don't block).

    In ``shadow`` mode, the controller computes what it WOULD block and
    records it in a shadow-enforcement log, but the executor does not
    actually mark steps blocked_upstream. Use this to observe 5-10 real
    runs before switching to hard enforcement (Phase D acceptance stage 2).
    """
    return os.environ.get("CONTROL_ENFORCEMENT_MODE", "hard").lower()


def is_hard_enforcement() -> bool:
    return enforcement_mode() == "hard"


# ── sample validity tagging ──────────────────────────────────────────────

VALID = "VALID"
DEGRADED = "DEGRADED"
INVALIDATED = "INVALIDATED"


def tag_nav_row(row: dict[str, Any]) -> dict[str, Any]:
    """Tag a NAV row with its sample validity.

    - ``sizing_mode == HOLD_DEGRADED`` -> DEGRADED (Phase A: incomplete P_public)
    - explicitly invalidated -> INVALIDATED
    - otherwise -> VALID
    """
    if row.get("sizing_mode") == "HOLD_DEGRADED":
        row["sample_validity"] = DEGRADED
    elif row.get("sample_validity") == INVALIDATED:
        pass  # keep explicit invalidation
    else:
        row["sample_validity"] = VALID
    return row


def invalidate_nav_rows(
    nav_path: Path | None = None,
    *,
    dates: list[str] | None = None,
    reason: str = "",
) -> int:
    """Mark NAV rows for the given dates (or all DEGRADED rows if none) as
    INVALIDATED. Does NOT rewrite historical NAV values - only adds the tag.

    Returns the count of invalidated rows.
    """
    path = nav_path or (ROOT / "Output" / "position" / "paper_portfolio_nav.jsonl")
    if not path.exists():
        return 0
    rows = []
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"_raw": line})
            continue
        as_of = str(row.get("as_of") or row.get("date") or "")
        if dates is None:
            # Invalidate all DEGRADED rows.
            if row.get("sample_validity") == DEGRADED or row.get("sizing_mode") == "HOLD_DEGRADED":
                row["sample_validity"] = INVALIDATED
                row["invalidation_reason"] = reason
                count += 1
        elif as_of in dates:
            row["sample_validity"] = INVALIDATED
            row["invalidation_reason"] = reason
            count += 1
        rows.append(row)
    # Rewrite the ledger (append-only values preserved; only the tag field changes).
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            if "_raw" in r:
                f.write(r["_raw"] + "\n")
            else:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return count


def valid_sample_filter(row: dict[str, Any]) -> bool:
    """True if a NAV row counts as a valid promotion sample.

    DEGRADED and INVALIDATED rows are excluded from promotion stats (90-day
    acceptance window, min_samples_met, correct_rate).
    """
    validity = row.get("sample_validity", VALID)
    return validity == VALID
