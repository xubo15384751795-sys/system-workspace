from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

import numpy as np
import pandas as pd

from src.core.models import ProxyReading
from src.operators.operator_schema import OperatorSequence, OperatorStep
from src.operators.operator_algebra import proxy_from_state, state_from_proxy
from src.operators.operator_diagnostics import operator_sequence_diagnostics
from src.operators.operator_registry import StructuralOperatorRegistry
from src.operators.operator_schema import EventOperatorMatch, OperatorApplication, OperatorDiagnostics, StructuralOperator


_EVENT_MATCH_CACHE: dict[str, tuple[list[EventOperatorMatch], int]] = {}
_EVENT_MATCH_CACHE_MAX = 256


def events_to_operator_matches(
    event_log: pd.DataFrame,
    registry: StructuralOperatorRegistry,
    run_date: str | None = None,
    lookback_days: int | None = None,
    max_events: int | None = None,
) -> tuple[list[EventOperatorMatch], int]:
    if event_log is None or event_log.empty:
        return [], 0
    frame = _filter_events(event_log, run_date=run_date, lookback_days=lookback_days)
    if max_events is not None and max_events > 0:
        frame = frame.tail(int(max_events))
    cache_key = _event_match_cache_key(frame, registry, run_date, lookback_days, max_events)
    if cache_key in _EVENT_MATCH_CACHE:
        return _EVENT_MATCH_CACHE[cache_key]

    matches: list[EventOperatorMatch] = []
    unmapped = 0
    for idx, row in frame.reset_index(drop=True).iterrows():
        event = _row_to_event(row)
        operator = registry.resolve_event(event)
        if operator is None:
            unmapped += 1
            continue
        matches.append(
            EventOperatorMatch(
                operator=operator,
                intensity=_event_intensity(event),
                metadata=_event_metadata(event, idx),
            )
        )
    result = (matches, unmapped)
    if len(_EVENT_MATCH_CACHE) >= _EVENT_MATCH_CACHE_MAX:
        _EVENT_MATCH_CACHE.pop(next(iter(_EVENT_MATCH_CACHE)))
    _EVENT_MATCH_CACHE[cache_key] = result
    return result


def apply_event_log_to_proxy(
    proxy: ProxyReading,
    event_log: pd.DataFrame,
    registry: StructuralOperatorRegistry,
    run_date: str | None = None,
    config: Mapping[str, Any] | None = None,
    prefix_operators: list[tuple[StructuralOperator, float, dict]] | None = None,
) -> tuple[ProxyReading, OperatorDiagnostics]:
    cfg = dict(config or {})
    matches, unmapped = events_to_operator_matches(
        event_log=event_log,
        registry=registry,
        run_date=run_date,
        lookback_days=_optional_int(cfg.get("lookback_days")),
        max_events=_optional_int(cfg.get("max_events")),
    )
    initial_state = state_from_proxy(proxy)
    prefix_packed = list(prefix_operators) if prefix_operators else []
    sequence = OperatorSequence.from_steps(
        [
            OperatorStep(operator=operator, intensity=intensity, metadata=metadata)
            for operator, intensity, metadata in prefix_packed
        ]
        + [
            OperatorStep(operator=match.operator, intensity=match.intensity, metadata=match.metadata)
            for match in matches
        ]
    )
    final_state, trace = sequence.apply(initial_state)
    applications = [_trace_entry_to_application(entry) for entry in trace]
    operators = [step.operator for step in sequence.steps]
    diagnostics = operator_sequence_diagnostics(
        applications=applications,
        initial_state=initial_state,
        final_state=final_state,
        operators=operators,
        singular_threshold=float(cfg.get("singular_threshold", cfg.get("sigma_threshold", 2.0))),
        singular_weights=cfg.get("singular_weights") if isinstance(cfg.get("singular_weights"), Mapping) else None,
        unmapped_event_count=unmapped,
    )
    if not applications:
        return proxy, diagnostics
    return proxy_from_state(proxy, final_state), diagnostics


def _trace_entry_to_application(entry) -> OperatorApplication:
    return OperatorApplication(
        operator_name=entry.operator_name,
        family=entry.family,
        intensity=float(entry.intensity),
        pre_state=entry.before,
        post_state=entry.after,
        delta=entry.delta,
        event_id=_string_or_none(entry.metadata.get("event_id")),
        event_date=_string_or_none(entry.metadata.get("event_date")),
        metadata=entry.metadata,
    )


def _filter_events(
    event_log: pd.DataFrame,
    run_date: str | None = None,
    lookback_days: int | None = None,
) -> pd.DataFrame:
    frame = event_log.copy()
    date_col = _date_column(frame)
    if date_col is None:
        return frame
    frame["_operator_event_date"] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=["_operator_event_date"])
    if run_date is not None:
        end = pd.to_datetime(run_date)
        frame = frame[frame["_operator_event_date"] <= end]
        if lookback_days is not None and lookback_days > 0:
            start = end - pd.Timedelta(days=int(lookback_days))
            frame = frame[frame["_operator_event_date"] >= start]
    return frame.sort_values("_operator_event_date").drop(columns=["_operator_event_date"]).reset_index(drop=True)


def _date_column(frame: pd.DataFrame) -> str | None:
    for col in ("date", "event_date", "created_at"):
        if col in frame.columns:
            return col
    return None


def _event_match_cache_key(
    frame: pd.DataFrame,
    registry: StructuralOperatorRegistry,
    run_date: str | None,
    lookback_days: int | None,
    max_events: int | None,
) -> str:
    stable = frame.copy()
    stable = stable.reindex(sorted(stable.columns), axis=1) if not stable.empty else stable
    payload = stable.to_json(date_format="iso", orient="split", default_handler=str)
    operators = ",".join(sorted(op.name for op in registry.all()))
    raw = f"{run_date}|{lookback_days}|{max_events}|{operators}|{payload}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _row_to_event(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and not np.isfinite(value):
            continue
        out[str(key)] = value
    return out


def _event_intensity(event: Mapping[str, Any]) -> float:
    for key in ("operator_intensity", "intensity", "severity", "weight"):
        if key not in event:
            continue
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            score = _severity_score(value)
            if score is not None:
                return score
        try:
            out = float(value)
        except Exception:
            continue
        if np.isfinite(out):
            return float(np.clip(out, 0.0, 3.0))
    return 1.0


def _severity_score(value: str) -> float | None:
    key = value.strip().lower()
    if key in {"low", "mild"}:
        return 0.5
    if key in {"medium", "moderate"}:
        return 1.0
    if key in {"high", "severe"}:
        return 1.5
    if key in {"critical", "singular"}:
        return 2.0
    return None


def _event_metadata(event: Mapping[str, Any], idx: int) -> dict[str, Any]:
    date = event.get("date", event.get("event_date", event.get("created_at")))
    event_id = event.get("event_id") or event.get("id") or f"event_{idx}"
    metadata = {
        "event_id": str(event_id),
        "event_date": str(date) if date is not None else None,
    }
    for key in ("actor", "intervention_type", "event", "event_type", "channel", "description"):
        value = event.get(key)
        if value is not None:
            metadata[key] = _jsonable(value)
    return metadata


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        out = int(value)
    except Exception:
        return None
    return out if out > 0 else None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
