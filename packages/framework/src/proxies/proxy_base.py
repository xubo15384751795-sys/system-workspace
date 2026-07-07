from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProxyInput:
    id: str
    orientation: str = "stress"
    weight: float = 1.0
    frequency: str | None = None
    note: str = ""

    def to_builder_spec(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "orientation": self.orientation,
            "weight": self.weight,
        }
        if self.frequency:
            out["frequency"] = self.frequency
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class ProxyGroup:
    name: str
    inputs: tuple[ProxyInput, ...]
    interpretation: str

    def to_builder_specs(self) -> list[dict[str, Any]]:
        return [item.to_builder_spec() for item in self.inputs]


@dataclass(frozen=True)
class StructuralProxyDefinition:
    channel: str
    label: str
    groups: tuple[ProxyGroup, ...]
    construction_boundary: str

    def to_basket_map(self) -> dict[str, list[dict[str, Any]]]:
        return {group.name: group.to_builder_specs() for group in self.groups}
