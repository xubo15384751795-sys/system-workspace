from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SeriesEvidenceRecord:
    """
    Per-series provenance record: what was requested, what actually arrived,
    and whether it was real or fallback.
    """

    series_id: str          # e.g. "FRED:T10Y2Y"
    provider: str           # e.g. "fred"
    channel: str | None     # M / D / K / X
    measurement_block: str | None
    evidence_role: str | None
    preset_name: str | None

    row_count: int
    has_real_data: bool     # False = fallback / mock / error
    fallback_reason: str | None   # "error" | "mock" | "empty" | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "provider": self.provider,
            "channel": self.channel,
            "measurement_block": self.measurement_block,
            "evidence_role": self.evidence_role,
            "preset_name": self.preset_name,
            "row_count": self.row_count,
            "has_real_data": self.has_real_data,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class ChannelEvidenceRecord:
    """
    Per-channel summary: which series contributed, how many were real.
    Answers "is the M-channel belief backed by real data?"
    """

    channel: str                    # M / D / K / X
    series_ids: tuple[str, ...]
    presets_used: tuple[str, ...]
    measurement_blocks: tuple[str, ...]
    real_series_count: int
    total_series_count: int
    any_fallback: bool
    all_mock: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "series_ids": list(self.series_ids),
            "presets_used": list(self.presets_used),
            "measurement_blocks": list(self.measurement_blocks),
            "real_series_count": self.real_series_count,
            "total_series_count": self.total_series_count,
            "any_fallback": self.any_fallback,
            "all_mock": self.all_mock,
        }


# Research quality labels — ordered from best to worst.
QUALITY_CLEAN = "clean"      # all series have real data
QUALITY_DEGRADED = "degraded"  # some series fell back, but not all
QUALITY_MOCK = "mock"        # all series are mock / no real data


@dataclass(frozen=True)
class DataEvidenceManifest:
    """
    Full evidence provenance for a single pipeline run.

    Replaces the loose 'fetch metadata' dict with a typed, per-channel,
    per-series record of what data was real, what fell back, and why.

    This is the answer to: "can I trust this channel's belief state?"
    """

    run_date: str
    series_records: tuple[SeriesEvidenceRecord, ...]
    channel_records: tuple[ChannelEvidenceRecord, ...]
    any_fallback: bool
    research_quality: str  # QUALITY_CLEAN | QUALITY_DEGRADED | QUALITY_MOCK
    total_series: int
    real_series: int

    def channel(self, name: str) -> ChannelEvidenceRecord | None:
        for rec in self.channel_records:
            if rec.channel.upper() == name.upper():
                return rec
        return None

    def fallback_series(self) -> list[SeriesEvidenceRecord]:
        return [r for r in self.series_records if not r.has_real_data]

    def real_series_list(self) -> list[SeriesEvidenceRecord]:
        return [r for r in self.series_records if r.has_real_data]

    def channels_with_fallback(self) -> list[str]:
        return [r.channel for r in self.channel_records if r.any_fallback]

    def channels_all_mock(self) -> list[str]:
        return [r.channel for r in self.channel_records if r.all_mock]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "research_quality": self.research_quality,
            "any_fallback": self.any_fallback,
            "total_series": self.total_series,
            "real_series": self.real_series,
            "channels_with_fallback": self.channels_with_fallback(),
            "channels_all_mock": self.channels_all_mock(),
            "channel_records": [r.to_dict() for r in self.channel_records],
            "series_records": [r.to_dict() for r in self.series_records],
        }

    @classmethod
    def build(
        cls,
        run_date: str,
        series_records: list[SeriesEvidenceRecord],
        channel_order: tuple[str, ...] = ("M", "D", "K", "X"),
    ) -> DataEvidenceManifest:
        channel_map: dict[str, list[SeriesEvidenceRecord]] = {}
        for rec in series_records:
            if rec.channel:
                channel_map.setdefault(rec.channel.upper(), []).append(rec)

        channel_records: list[ChannelEvidenceRecord] = []
        for ch in channel_order:
            recs = channel_map.get(ch, [])
            if not recs:
                continue
            real = sum(1 for r in recs if r.has_real_data)
            channel_records.append(
                ChannelEvidenceRecord(
                    channel=ch,
                    series_ids=tuple(r.series_id for r in recs),
                    presets_used=tuple(dict.fromkeys(r.preset_name for r in recs if r.preset_name)),
                    measurement_blocks=tuple(dict.fromkeys(r.measurement_block for r in recs if r.measurement_block)),
                    real_series_count=real,
                    total_series_count=len(recs),
                    any_fallback=any(not r.has_real_data for r in recs),
                    all_mock=all(not r.has_real_data for r in recs),
                )
            )

        total = len(series_records)
        real = sum(1 for r in series_records if r.has_real_data)
        any_fallback = any(not r.has_real_data for r in series_records)

        if total == 0 or real == 0:
            quality = QUALITY_MOCK
        elif any_fallback:
            quality = QUALITY_DEGRADED
        else:
            quality = QUALITY_CLEAN

        return cls(
            run_date=run_date,
            series_records=tuple(series_records),
            channel_records=tuple(channel_records),
            any_fallback=any_fallback,
            research_quality=quality,
            total_series=total,
            real_series=real,
        )
