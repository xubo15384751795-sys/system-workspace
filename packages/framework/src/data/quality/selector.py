from __future__ import annotations

from typing import Sequence

from src.data.quality.tier import DataTier, TieredSeriesSpec


class DataSelector:
    """
    Filters and ranks the series catalog by channel, data_role, and tier.

    The key responsibility: given multiple candidates that serve the same
    channel + role, return them ordered best-first (fastest / highest quality).
    This is how the system chooses what to fetch when alternatives exist.
    """

    def __init__(self, catalog: Sequence[TieredSeriesSpec]) -> None:
        self._catalog = list(catalog)

    def all(self) -> list[TieredSeriesSpec]:
        return list(self._catalog)

    def for_channel(self, channel: str) -> list[TieredSeriesSpec]:
        ch = channel.upper()
        return [s for s in self._catalog if s.channel and s.channel.upper() == ch]

    def for_role(self, role: str) -> list[TieredSeriesSpec]:
        """Filter by data_role: level / dispersion / density / transition / event / feature."""
        return [s for s in self._catalog if s.data_role == role]

    def for_measurement_block(self, block: str) -> list[TieredSeriesSpec]:
        return [s for s in self._catalog if s.measurement_block == block]

    def for_evidence_role(self, role: str) -> list[TieredSeriesSpec]:
        return [s for s in self._catalog if s.evidence_role == role]

    def for_tier(self, tier: DataTier) -> list[TieredSeriesSpec]:
        return [s for s in self._catalog if s.tier == tier]

    def ranked_by_tier(
        self,
        channel: str | None = None,
        data_role: str | None = None,
    ) -> list[TieredSeriesSpec]:
        """
        Return candidates ordered by tier priority (REALTIME first, MOCK last).

        Optionally filter to a specific channel and/or data_role first.
        """
        candidates = list(self._catalog)
        if channel is not None:
            ch = channel.upper()
            candidates = [s for s in candidates if s.channel and s.channel.upper() == ch]
        if data_role is not None:
            candidates = [s for s in candidates if s.data_role == data_role]
        return sorted(candidates, key=lambda s: s.tier.priority)

    def best_available(
        self,
        channel: str,
        data_role: str,
        exclude_tiers: set[DataTier] | None = None,
    ) -> TieredSeriesSpec | None:
        """
        Return the single best candidate for a channel + data_role combination.

        'Best' = lowest tier priority (fastest / most current).
        Pass exclude_tiers={DataTier.MOCK} to skip fallback data.
        """
        ranked = self.ranked_by_tier(channel=channel, data_role=data_role)
        if exclude_tiers:
            ranked = [s for s in ranked if s.tier not in exclude_tiers]
        return ranked[0] if ranked else None

    def coverage_report(self) -> dict[str, dict[str, list[str]]]:
        """
        Return a nested dict: channel -> data_role -> [series_ids].

        Useful for auditing which channel/role combinations have coverage
        and which are gaps.
        """
        report: dict[str, dict[str, list[str]]] = {}
        for spec in self._catalog:
            ch = spec.channel or "_unknown"
            role = spec.data_role or "_unknown"
            report.setdefault(ch, {}).setdefault(role, []).append(spec.series_id)
        return report

    def gap_report(self) -> dict[str, list[str]]:
        """
        Report which channel + data_role combinations have NO coverage.

        Checks all four channels against the standard data roles.
        """
        channels = ["M", "D", "K", "X"]
        roles = ["level", "dispersion", "density", "transition"]
        coverage = self.coverage_report()
        gaps: dict[str, list[str]] = {}
        for ch in channels:
            ch_coverage = coverage.get(ch, {})
            missing = [role for role in roles if role not in ch_coverage]
            if missing:
                gaps[ch] = missing
        return gaps

    def register(self, spec: TieredSeriesSpec) -> None:
        """Add a new spec to the catalog (used for runtime registration of derived series)."""
        self._catalog.append(spec)

    def deregister(self, series_id: str) -> None:
        self._catalog = [s for s in self._catalog if s.series_id != series_id]
