from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class StructuralLineage:
    """
    Full structural provenance record for a single data series.

    Answers two questions:
      1. Where did this data come from? (provider lineage)
      2. What does it serve in the framework? (structural lineage)

    This is the bridge between the raw data world (providers, series IDs)
    and the analytical world (channels, blocks, roles).
    """

    series_id: str
    provider: str

    # Structural position
    channel: str                # M / D / K / X
    measurement_block: str
    evidence_role: str          # proxy / cross_section / event / filing / feature
    data_role: str              # level / dispersion / density / transition / event / feature

    # Optional context
    jurisdiction_or_scope: str | None = None
    derived_from: tuple[str, ...] = ()  # parent series_ids if this is computed
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "provider": self.provider,
            "channel": self.channel,
            "measurement_block": self.measurement_block,
            "evidence_role": self.evidence_role,
            "data_role": self.data_role,
            "jurisdiction_or_scope": self.jurisdiction_or_scope,
            "derived_from": list(self.derived_from),
            "notes": self.notes,
        }

    def is_derived(self) -> bool:
        return len(self.derived_from) > 0

    def serves_channel(self, channel: str) -> bool:
        return self.channel.upper() == channel.upper()

    def serves_role(self, data_role: str) -> bool:
        return self.data_role == data_role


class LineageRegistry:
    """
    Registry of StructuralLineage records.

    Provides lookup by channel, data_role, measurement_block, and provider.
    Used by the rest of the system to understand what each series does,
    and to audit structural coverage without reading raw data.
    """

    def __init__(self, entries: Sequence[StructuralLineage] | None = None) -> None:
        self._entries: list[StructuralLineage] = list(entries or [])
        self._by_id: dict[str, StructuralLineage] = {e.series_id: e for e in self._entries}

    def register(self, entry: StructuralLineage) -> None:
        self._entries.append(entry)
        self._by_id[entry.series_id] = entry

    def get(self, series_id: str) -> StructuralLineage | None:
        return self._by_id.get(series_id)

    def for_channel(self, channel: str) -> list[StructuralLineage]:
        ch = channel.upper()
        return [e for e in self._entries if e.channel.upper() == ch]

    def for_data_role(self, role: str) -> list[StructuralLineage]:
        return [e for e in self._entries if e.data_role == role]

    def for_measurement_block(self, block: str) -> list[StructuralLineage]:
        return [e for e in self._entries if e.measurement_block == block]

    def for_channel_and_role(self, channel: str, data_role: str) -> list[StructuralLineage]:
        ch = channel.upper()
        return [
            e for e in self._entries
            if e.channel.upper() == ch and e.data_role == data_role
        ]

    def for_provider(self, provider: str) -> list[StructuralLineage]:
        p = provider.lower()
        return [e for e in self._entries if e.provider.lower() == p]

    def derived_series(self) -> list[StructuralLineage]:
        return [e for e in self._entries if e.is_derived()]

    def coverage_matrix(self) -> dict[str, dict[str, list[str]]]:
        """Return channel -> data_role -> [series_ids]. Useful for auditing gaps."""
        matrix: dict[str, dict[str, list[str]]] = {}
        for e in self._entries:
            matrix.setdefault(e.channel, {}).setdefault(e.data_role, []).append(e.series_id)
        return matrix

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_count": len(self._entries),
            "entries": [e.to_dict() for e in self._entries],
            "coverage_matrix": self.coverage_matrix(),
        }

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        channels = sorted({e.channel for e in self._entries})
        return f"LineageRegistry(entries={len(self._entries)}, channels={channels})"
