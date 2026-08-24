"""Portable local experiment tracking for governed run bundles.

This is intentionally a filesystem contract rather than a second service.
It provides the MLflow-sized primitives the project actually needs:
run identity, params, metric history, tags, input snapshots, and artifact
references. Operational run_events remain a compatibility/event projection;
experiment.json is the canonical per-run experiment record.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "system.experiment_run.v1"


class ExperimentTrackingError(ValueError):
    """Raised when a run/metric/artifact record is invalid."""


class ExperimentTracker:
    """Atomic, dependency-free experiment tracker backed by one JSON file."""

    def __init__(
        self,
        path: str | Path,
        *,
        run_id: str,
        experiment_name: str,
        started_at: datetime | None = None,
        params: Mapping[str, Any] | None = None,
        tags: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tracking_backend": "filesystem",
            "run_id": _required_text(run_id, "run_id"),
            "experiment_name": _required_text(experiment_name, "experiment_name"),
            "status": "running",
            "started_at": _timestamp(started_at or datetime.now(UTC)),
            "finished_at": None,
            "duration_s": None,
            "params": {},
            "metrics": {},
            "metric_history": [],
            "tags": {},
            "inputs": {},
            "artifacts": [],
            "compatibility": {
                "operational_events": "Output/runtime_events/run_events_YYYY-MM-DD.jsonl",
            },
        }
        for key, value in (params or {}).items():
            self.log_param(key, value, write=False)
        for key, value in (tags or {}).items():
            self.set_tag(key, value, write=False)
        self._write()

    @property
    def payload(self) -> dict[str, Any]:
        """Return a defensive copy of the current tracking record."""
        return json.loads(json.dumps(self._payload, ensure_ascii=False))

    def log_param(self, name: str, value: Any, *, write: bool = True) -> None:
        key = _required_text(name, "param name")
        self._payload["params"][key] = _json_value(value)
        if write:
            self._write()

    def log_metric(
        self,
        name: str,
        value: Real,
        *,
        step: int | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        key = _required_text(name, "metric name")
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ExperimentTrackingError(f"metric {key} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ExperimentTrackingError(f"metric {key} must be finite")
        if step is not None and (isinstance(step, bool) or not isinstance(step, int)):
            raise ExperimentTrackingError(f"metric {key} step must be an integer")
        observed_at = _timestamp(timestamp or datetime.now(UTC))
        record = {"value": numeric, "timestamp": observed_at}
        if step is not None:
            record["step"] = step
        self._payload["metrics"][key] = numeric
        self._payload["metric_history"].append({"metric": key, **record})
        self._write()

    def set_tag(self, name: str, value: Any, *, write: bool = True) -> None:
        key = _required_text(name, "tag name")
        self._payload["tags"][key] = _json_value(value)
        if write:
            self._write()

    def set_inputs(self, inputs: Mapping[str, Any]) -> None:
        self._payload["inputs"] = _json_value(dict(inputs))
        self._write()

    def log_artifact(self, artifact: Mapping[str, Any]) -> None:
        if not isinstance(artifact, Mapping):
            raise ExperimentTrackingError("artifact must be a mapping")
        path = _required_text(artifact.get("path"), "artifact path")
        entry = {
            key: _json_value(artifact[key])
            for key in ("path", "size_bytes", "sha256", "status", "provenance")
            if key in artifact
        }
        entry["path"] = path
        artifacts = [
            item for item in self._payload["artifacts"]
            if not isinstance(item, Mapping) or item.get("path") != path
        ]
        artifacts.append(entry)
        self._payload["artifacts"] = sorted(artifacts, key=lambda item: str(item.get("path", "")))
        self._write()

    def finish(
        self,
        *,
        status: str,
        finished_at: datetime | None = None,
        duration_s: Real | None = None,
        metrics: Mapping[str, Real] | None = None,
        tags: Mapping[str, Any] | None = None,
    ) -> Path:
        final_status = _required_text(status, "status")
        self._payload["status"] = final_status
        self._payload["finished_at"] = _timestamp(finished_at or datetime.now(UTC))
        if duration_s is not None:
            if isinstance(duration_s, bool) or not isinstance(duration_s, Real):
                raise ExperimentTrackingError("duration_s must be numeric")
            numeric_duration = float(duration_s)
            if not math.isfinite(numeric_duration) or numeric_duration < 0:
                raise ExperimentTrackingError("duration_s must be finite and non-negative")
            self._payload["duration_s"] = numeric_duration
        for key, value in (metrics or {}).items():
            self.log_metric(key, value)
        for key, value in (tags or {}).items():
            self.set_tag(key, value)
        self._write()
        return self.path

    def _write(self) -> None:
        encoded = json.dumps(self._payload, indent=2, ensure_ascii=False) + "\n"
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExperimentTrackingError(f"{field} is required")
    return text


def _json_value(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ExperimentTrackingError(f"value is not JSON-serializable: {value!r}") from exc
    return value


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ExperimentTrackingError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["ExperimentTracker", "ExperimentTrackingError", "SCHEMA_VERSION"]
