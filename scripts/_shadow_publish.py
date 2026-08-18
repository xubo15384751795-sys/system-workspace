"""Shadow ledger publisher (Phase B5).

Two-phase atomic publish for shadow / paper-portfolio artifacts:

1. ``begin_shadow_candidate(run_dir)`` routes paper_portfolio writes to the
   run's ``shadow_candidate/`` directory (mirrors begin_candidate for current).
2. paper_portfolio writes NAV / state / markdown into the candidate.
3. ``publish_shadow_candidate`` atomically promotes the candidate to the live
   ``Output/position/`` location via temp + os.replace, ONLY if all input +
   compute gates passed. On failure the candidate is retained for audit but
   the live shadow state / NAV ledger / latest pointer are untouched.

This makes the shadow ledger append-only-with-atomic-promote: a failed run
cannot leave a partial NAV row or a refreshed updated_at on the live state.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT, compatibility_surface_dir, ensure_dir, surface_dir

# Previous accepted position surface.  It intentionally ignores the active
# generation so a candidate can seed its full NAV history without reading its
# own empty directory.
LIVE_POSITION_DIR = compatibility_surface_dir("position")
NAV_JSONL_NAME = "paper_portfolio_nav.jsonl"
STATE_JSON_NAME = "paper_portfolio.json"
LATEST_MD_NAME = "paper_portfolio_latest.md"


def begin_shadow_candidate(run_dir: Path) -> Path:
    """Route paper_portfolio writes to the run's shadow_candidate directory."""
    candidate = surface_dir("position") if os.environ.get("SYSTEM_GENERATION_DIR") else run_dir / "shadow_candidate"
    ensure_dir(candidate)
    os.environ["SHADOW_OUTPUT_DIR"] = str(candidate)
    return candidate


def shadow_candidate_dir() -> Path:
    """The active shadow candidate dir, or the live dir if no candidate set."""
    env = os.environ.get("SHADOW_OUTPUT_DIR")
    if env:
        return Path(env)
    if os.environ.get("SYSTEM_GENERATION_MODE", "").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError("generation mode requires SHADOW_OUTPUT_DIR before any position write")
    return LIVE_POSITION_DIR


def clear_shadow_candidate_env() -> None:
    os.environ.pop("SHADOW_OUTPUT_DIR", None)


def publish_shadow_candidate(candidate_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    """Atomically promote shadow candidate artifacts to the live position dir.

    For the NAV ledger (append-only JSONL), the candidate contains the FULL
    new history (existing + new rows); we os.replace it onto the live file.
    For state/markdown, os.replace the candidate file over the live file.

    Returns a dict of promoted file names. If a candidate file is absent, the
    corresponding live file is left untouched (so a partial candidate does not
    delete live state).
    """
    generation_mode = os.environ.get("SYSTEM_GENERATION_MODE", "").strip().lower() in {"1", "true", "yes"}
    if generation_mode or (root / "Output" / "live").is_symlink():
        raise RuntimeError(
            "legacy shadow publisher is disabled in generation topology; use PublishTransaction.commit_generation"
        )
    target = root / "Output" / "position"
    ensure_dir(target)
    promoted: list[str] = []
    for name in (NAV_JSONL_NAME, STATE_JSON_NAME, LATEST_MD_NAME):
        src = candidate_dir / name
        if not src.exists():
            continue
        dest = target / name
        # os.replace is atomic on POSIX for files on the same filesystem.
        os.replace(src, dest)
        promoted.append(name)
    return {"promoted": promoted, "count": len(promoted)}


def append_nav_row_atomic(row: dict[str, Any], candidate_dir: Path | None = None) -> None:
    """Append a NAV row to the candidate ledger (or live if no candidate).

    Uses a temp-file + os.replace per row so a crash never leaves a partial
    JSON line in the ledger.
    """
    d = candidate_dir or shadow_candidate_dir()
    ensure_dir(d)
    nav_path = d / NAV_JSONL_NAME
    line = json.dumps(row, ensure_ascii=False) + "\n"
    # Read existing candidate content (or seed from live if candidate empty).
    if not nav_path.exists() and LIVE_POSITION_DIR.joinpath(NAV_JSONL_NAME).exists():
        existing = LIVE_POSITION_DIR.joinpath(NAV_JSONL_NAME).read_text(encoding="utf-8")
    elif nav_path.exists():
        existing = nav_path.read_text(encoding="utf-8")
    else:
        existing = ""
    tmp = nav_path.with_suffix(".tmp")
    tmp.write_text(existing + line, encoding="utf-8")
    os.replace(tmp, nav_path)


def write_state_atomic(state: dict[str, Any], candidate_dir: Path | None = None) -> None:
    """Write the shadow state JSON atomically (temp + os.replace)."""
    import json as _json

    d = candidate_dir or shadow_candidate_dir()
    ensure_dir(d)
    state_path = d / STATE_JSON_NAME
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(_json.dumps(state, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, state_path)
