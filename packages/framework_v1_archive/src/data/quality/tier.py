from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class DataTier(enum.Enum):
    """
    Speed/quality tier for a data series.

    Ordered from fastest/most current to slowest/most derived.
    Used by DataSelector to rank candidate series when multiple options
    serve the same channel + measurement_block + data_role.
    """

    REALTIME = "realtime"       # sub-minute (exchange feeds, live APIs)
    DAILY = "daily"             # end-of-day (FRED, most market data)
    WEEKLY = "weekly"           # H.4.1, CFTC commitments of traders
    MONTHLY = "monthly"         # some macro aggregates, balance sheet data
    DERIVED = "derived"         # computed proxy (zscore, rolling aggregate)
    MOCK = "mock"               # fallback / test data

    @property
    def priority(self) -> int:
        """Lower number = higher priority (faster / more current)."""
        return {
            DataTier.REALTIME: 0,
            DataTier.DAILY: 1,
            DataTier.WEEKLY: 2,
            DataTier.MONTHLY: 3,
            DataTier.DERIVED: 4,
            DataTier.MOCK: 5,
        }[self]

    def __lt__(self, other: DataTier) -> bool:
        return self.priority < other.priority


# Valid data role labels
DATA_ROLES = frozenset({"level", "dispersion", "density", "transition", "event", "feature"})


@dataclass(frozen=True)
class TieredSeriesSpec:
    """
    Describes a data series with its tier, channel mapping, and data role.

    This is the metadata record that DataSelector uses to rank and filter
    available series. It does NOT store the actual data — it describes where
    to find it and what it serves.
    """

    series_id: str
    tier: DataTier
    provider: str

    # Structural mapping
    channel: str | None = None              # M / D / K / X
    measurement_block: str | None = None
    data_role: str | None = None            # level / dispersion / density / transition / event / feature
    evidence_role: str | None = None        # proxy / cross_section / filing / position
    jurisdiction_or_scope: str | None = None

    # Speed/quality metadata
    latency_hours: float | None = None      # typical lag from real-world event to data availability
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "tier": self.tier.value,
            "provider": self.provider,
            "channel": self.channel,
            "measurement_block": self.measurement_block,
            "data_role": self.data_role,
            "evidence_role": self.evidence_role,
            "jurisdiction_or_scope": self.jurisdiction_or_scope,
            "latency_hours": self.latency_hours,
            "description": self.description,
        }


def default_tiered_catalog() -> list[TieredSeriesSpec]:
    """
    Default catalog of all known series with their tier and structural mapping.

    Mirrors the structural presets in contracts.py but adds tier/speed metadata.
    """
    return [
        # ── M channel: Mismatch ─────────────────────────────────────────────
        TieredSeriesSpec(
            series_id="FRED:T10Y2Y",
            tier=DataTier.DAILY,
            provider="fred",
            channel="M",
            measurement_block="funding_gap",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_rates",
            description="10Y-2Y yield spread — curve shape mismatch proxy",
        ),
        TieredSeriesSpec(
            series_id="FRED:DFF",
            tier=DataTier.DAILY,
            provider="fred",
            channel="M",
            measurement_block="funding_gap",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_policy",
            description="Effective Fed Funds Rate — policy anchor",
        ),
        TieredSeriesSpec(
            series_id="FRED:TEDRATE",
            tier=DataTier.DAILY,
            provider="fred",
            channel="M",
            measurement_block="funding_gap",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_money_market",
            description="TED spread — interbank funding stress",
        ),
        # ── D channel: Degrees of Freedom ───────────────────────────────────
        TieredSeriesSpec(
            series_id="FRED:BAMLH0A0HYM2",
            tier=DataTier.DAILY,
            provider="fred",
            channel="D",
            measurement_block="depth",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_credit",
            description="HY OAS — credit spread / market depth proxy",
        ),
        TieredSeriesSpec(
            series_id="FRED:VIXCLS",
            tier=DataTier.DAILY,
            provider="fred",
            channel="D",
            measurement_block="hedge_breadth",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_cross_asset",
            description="VIX — risk transfer breadth / hedge cost",
        ),
        TieredSeriesSpec(
            series_id="H41:discount_window",
            tier=DataTier.WEEKLY,
            provider="fed_h41",
            channel="D",
            measurement_block="funding_access",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_central_bank",
            description="Discount window usage — funding access shrinkage",
        ),
        # ── K channel: Curvature ────────────────────────────────────────────
        TieredSeriesSpec(
            series_id="FRED:VIXCLS",
            tier=DataTier.DAILY,
            provider="fred",
            channel="K",
            measurement_block="jump_instability",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_cross_asset",
            description="VIX — jump/transition instability proxy",
        ),
        TieredSeriesSpec(
            series_id="TFD:debt_to_penny:tot_pub_debt_out_amt",
            tier=DataTier.DAILY,
            provider="treasury",
            channel="K",
            measurement_block="refinancing_pressure",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_treasury",
            description="Total public debt outstanding — refinancing pressure",
        ),
        TieredSeriesSpec(
            series_id="TFD:daily_treasury_statement:open_today_bal",
            tier=DataTier.DAILY,
            provider="treasury",
            channel="K",
            measurement_block="liquidation_path_instability",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_treasury",
            description="Treasury cash balance — liquidation path instability",
        ),
        # ── X channel: Shadow Load ──────────────────────────────────────────
        TieredSeriesSpec(
            series_id="H41:primary_credit",
            tier=DataTier.WEEKLY,
            provider="fed_h41",
            channel="X",
            measurement_block="shadow_funding",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_central_bank",
            description="Primary credit (discount window) — shadow funding substitution",
        ),
        TieredSeriesSpec(
            series_id="H41:btfp",
            tier=DataTier.WEEKLY,
            provider="fed_h41",
            channel="X",
            measurement_block="shadow_funding",
            data_role="level",
            evidence_role="proxy",
            jurisdiction_or_scope="us_central_bank",
            description="BTFP usage — term funding substitution pressure",
        ),
        TieredSeriesSpec(
            series_id="SEC:0000072971",
            tier=DataTier.DAILY,
            provider="sec",
            channel="X",
            measurement_block="verifiability",
            data_role="level",
            evidence_role="filing",
            jurisdiction_or_scope="issuer_core",
            description="SEC filing pulse — verifiability / hidden load trace",
        ),
    ]
