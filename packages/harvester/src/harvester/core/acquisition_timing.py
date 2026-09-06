"""Observation-only acquisition timings for harvester.official.

These records do not change fetch, admission, or finalize behavior. They
exist so operators can rank source/series cost against JSONL write and
finalize-validation cost.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def elapsed_s(t0: float, t1: float | None = None) -> float:
    return round((t1 if t1 is not None else time.perf_counter()) - t0, 3)


def source_record(
    *,
    source_id: str,
    started_at: str,
    t0: float,
    attempts: int,
    outcome: str,
    series_id: str = "",
    provider: str = "",
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_id": str(source_id),
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_s": elapsed_s(t0),
        "attempts": int(attempts),
        "outcome": outcome,
    }
    if series_id:
        record["series_id"] = str(series_id)
    if provider:
        record["provider"] = str(provider)
    return record


def local_step_record(
    *,
    step_id: str,
    started_at: str,
    t0: float,
    outcome: str = "success",
    attempts: int = 1,
) -> dict[str, Any]:
    return {
        "step_id": str(step_id),
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_s": elapsed_s(t0),
        "attempts": int(attempts),
        "outcome": outcome,
    }


@contextmanager
def track_local_step(bucket: list[dict[str, Any]], step_id: str) -> Iterator[None]:
    started_at = utc_now()
    t0 = time.perf_counter()
    outcome = "success"
    try:
        yield
    except Exception:
        outcome = "failed"
        raise
    finally:
        bucket.append(
            local_step_record(
                step_id=step_id,
                started_at=started_at,
                t0=t0,
                outcome=outcome,
            )
        )


def ranked_items(acquisition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Merge sources and local_steps, longest first."""
    payload = acquisition if isinstance(acquisition, dict) else {}
    items: list[dict[str, Any]] = []
    for source in payload.get("sources") or []:
        if not isinstance(source, dict):
            continue
        items.append({"kind": "source", "name": source.get("source_id"), **source})
    for step in payload.get("local_steps") or []:
        if not isinstance(step, dict):
            continue
        items.append({"kind": "local_step", "name": step.get("step_id"), **step})
    items.sort(key=lambda item: float(item.get("elapsed_s") or 0), reverse=True)
    return items


def _write_acquisition(path: Path, payload: dict[str, Any], acquisition: dict[str, Any]) -> None:
    from harvester.core.provenance import validate_provenance

    payload["acquisition"] = acquisition
    validate_provenance(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_local_step(path: Path | str, step: dict[str, Any]) -> None:
    """Append one local_step to an existing provenance file. No-op if missing."""
    from harvester.core.provenance import load_provenance

    target = Path(path)
    if not target.is_file():
        return
    payload = load_provenance(target)
    acquisition = dict(payload.get("acquisition") or {})
    steps = list(acquisition.get("local_steps") or [])
    steps.append(step)
    acquisition["local_steps"] = steps
    _write_acquisition(target, payload, acquisition)


def replace_local_steps(path: Path | str, steps: list[dict[str, Any]]) -> None:
    """Replace local_steps on an existing provenance file. No-op if missing."""
    from harvester.core.provenance import load_provenance

    target = Path(path)
    if not target.is_file():
        return
    payload = load_provenance(target)
    acquisition = dict(payload.get("acquisition") or {})
    acquisition["local_steps"] = list(steps)
    acquisition["completed_at"] = utc_now()
    _write_acquisition(target, payload, acquisition)


__all__ = [
    "append_local_step",
    "elapsed_s",
    "local_step_record",
    "ranked_items",
    "replace_local_steps",
    "source_record",
    "track_local_step",
    "utc_now",
]
