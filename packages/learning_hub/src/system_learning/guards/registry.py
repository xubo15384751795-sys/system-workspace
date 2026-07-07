"""Governance status registry loader.

Single source of truth lives at
``Data/system_learning/registries/governance_status_registry.yaml``. The guards
read this registry to decide what may appear on the live daily surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_REGISTRY_RELPATH = "Data/system_learning/registries/governance_status_registry.yaml"


@dataclass(frozen=True)
class Posture:
    """Confidence-graded expression for an entity (the promotion-path half)."""

    level: str = ""          # L0_blocked .. L5_trade_ready
    action_type: str = ""    # ACTIVE_WATCH / ROBUSTNESS_TEST / DATA_REPAIR / QUIET_WATCH / IGNORE / BLOCKED
    can_say: str = ""
    watch: tuple[str, ...] = ()
    upgrade_path: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class Entity:
    kind: str  # signal | strategy | module | defect
    name: str
    status: str
    block_in_daily: bool = False
    daily_trigger_allowed: bool | None = None
    expect_artifact: str | None = None
    aliases: tuple[str, ...] = ()
    reason: str = ""
    posture: Posture | None = None

    def reference_terms(self) -> list[str]:
        return [self.name, *self.aliases]


@dataclass(frozen=True)
class Registry:
    schema_version: str
    active_claiming_statuses: frozenset[str]
    status_enums: dict[str, frozenset[str]]
    entities: tuple[Entity, ...]
    posture_priority: tuple[str, ...] = ()

    def by_kind(self, kind: str) -> list[Entity]:
        return [e for e in self.entities if e.kind == kind]

    def with_posture(self) -> list[Entity]:
        return [e for e in self.entities if e.posture is not None]

    def known_status(self, kind: str, status: str) -> bool:
        return status in self.status_enums.get(kind, frozenset())


_KIND_SECTIONS = ("signals", "strategies", "modules", "defects")
_SECTION_TO_KIND = {
    "signals": "signal",
    "strategies": "strategy",
    "modules": "module",
    "defects": "defect",
}


def _posture_from_mapping(raw: dict | None) -> Posture | None:
    if not raw:
        return None
    return Posture(
        level=str(raw.get("level", "")),
        action_type=str(raw.get("action_type", "")),
        can_say=str(raw.get("can_say", "")),
        watch=tuple(str(x) for x in (raw.get("watch") or [])),
        upgrade_path=tuple(str(x) for x in (raw.get("upgrade_path") or [])),
        forbidden=tuple(str(x) for x in (raw.get("forbidden") or [])),
    )


def _entity_from_mapping(kind: str, name: str, raw: dict) -> Entity:
    aliases = raw.get("aliases") or []
    return Entity(
        kind=kind,
        name=name,
        status=str(raw.get("status", "")),
        block_in_daily=bool(raw.get("block_in_daily", False)),
        daily_trigger_allowed=raw.get("daily_trigger_allowed"),
        expect_artifact=raw.get("expect_artifact"),
        aliases=tuple(str(a) for a in aliases),
        reason=str(raw.get("reason", raw.get("title", ""))),
        posture=_posture_from_mapping(raw.get("posture")),
    )


def load_registry(path: Path) -> Registry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    enums_raw = data.get("status_enums", {}) or {}
    status_enums = {k: frozenset(v or []) for k, v in enums_raw.items()}

    entities: list[Entity] = []
    for section in _KIND_SECTIONS:
        kind = _SECTION_TO_KIND[section]
        for name, raw in (data.get(section) or {}).items():
            entities.append(_entity_from_mapping(kind, name, raw or {}))

    return Registry(
        schema_version=str(data.get("schema_version", "")),
        active_claiming_statuses=frozenset(data.get("active_claiming_statuses", []) or []),
        status_enums=status_enums,
        entities=tuple(entities),
        posture_priority=tuple(data.get("posture_priority", []) or []),
    )
