"""Versioned event envelope and JSONL compatibility store."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

ENVELOPE_SCHEMA = "system.event_envelope.v1"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    payload_schema: str
    payload: dict[str, Any]
    event_id: str
    occurred_at: str
    producer: str
    run_id: str | None = None
    schema_version: str = ENVELOPE_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        payload_schema: str,
        payload: Mapping[str, Any],
        producer: str,
        run_id: str | None = None,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> "EventEnvelope":
        return cls(
            event_type=event_type,
            payload_schema=payload_schema,
            payload=dict(payload),
            producer=producer,
            run_id=run_id,
            event_id=event_id or uuid.uuid4().hex,
            occurred_at=occurred_at or datetime.now(UTC).isoformat(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload_schema": self.payload_schema,
            "occurred_at": self.occurred_at,
            "producer": self.producer,
            "run_id": self.run_id,
            "payload": self.payload,
        }


def is_envelope(record: Mapping[str, Any]) -> bool:
    return record.get("schema_version") == ENVELOPE_SCHEMA and isinstance(record.get("payload"), dict)


def payload_of(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return an event payload, adapting legacy flat JSONL records."""
    if is_envelope(record):
        return dict(record["payload"])
    return dict(record)


def envelope_of(
    record: Mapping[str, Any],
    *,
    event_type: str,
    payload_schema: str,
    producer: str,
    run_id: str | None = None,
) -> EventEnvelope:
    if is_envelope(record):
        return EventEnvelope(
            event_type=str(record["event_type"]),
            payload_schema=str(record["payload_schema"]),
            payload=dict(record["payload"]),
            event_id=str(record["event_id"]),
            occurred_at=str(record["occurred_at"]),
            producer=str(record["producer"]),
            run_id=record.get("run_id"),
        )
    payload = dict(record)
    stable_id = payload.get("event_id") or payload.get("decision_fingerprint")
    occurred_at = payload.get("occurred_at") or payload.get("recorded_at") or payload.get("timestamp")
    return EventEnvelope.create(
        event_type=event_type,
        payload_schema=str(payload.get("schema_version") or payload_schema),
        payload=payload,
        producer=producer,
        run_id=run_id or payload.get("run_id"),
        event_id=str(stable_id) if stable_id else None,
        occurred_at=str(occurred_at) if occurred_at else None,
    )


class JsonlEventStore:
    """Append/read/upsert JSONL events through one versioned boundary."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{self.path}:{lineno}: event must be an object")
                yield value

    def read_payloads(self) -> list[dict[str, Any]]:
        return [payload_of(record) for record in self.iter_records()]

    def append(self, event: EventEnvelope) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.as_dict(), ensure_ascii=False, default=str) + "\n")

    def replace(self, events: Iterable[EventEnvelope]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event.as_dict(), ensure_ascii=False, default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                logger.debug("Temporary event file already absent during cleanup: %s", temporary)
            raise

    def replace_payloads(
        self,
        payloads: Iterable[Mapping[str, Any]],
        *,
        event_type: str,
        payload_schema: str,
        producer: str,
        run_id: str | None = None,
    ) -> None:
        self.replace(
            EventEnvelope.create(
                event_type=event_type,
                payload_schema=str(payload.get("schema_version") or payload_schema),
                payload=payload,
                producer=producer,
                run_id=run_id or payload.get("run_id"),
                event_id=str(payload.get("event_id") or payload.get("decision_fingerprint") or "") or None,
                occurred_at=str(
                    payload.get("occurred_at")
                    or payload.get("recorded_at")
                    or payload.get("timestamp")
                    or ""
                )
                or None,
            )
            for payload in payloads
        )

    def upsert(
        self,
        event: EventEnvelope,
        *,
        identity_fields: tuple[str, ...],
    ) -> str:
        records = list(self.iter_records())
        events = [
            envelope_of(
                record,
                event_type=event.event_type,
                payload_schema=event.payload_schema,
                producer=event.producer,
                run_id=event.run_id,
            )
            for record in records
        ]
        identity = tuple(event.payload.get(key) for key in identity_fields)
        for index, existing in enumerate(events):
            if tuple(existing.payload.get(key) for key in identity_fields) == identity:
                events[index] = event
                self.replace(events)
                return "updated"
        events.append(event)
        self.replace(events)
        return "inserted"
