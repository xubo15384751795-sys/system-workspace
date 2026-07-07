"""FUNDING_PATH_STRESS mechanism detector — research-only overlay.

Spec: docs/operators/funding_path_stress.md
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from src.operators.mechanism._panel import (
    business_days,
    delta_over_weeks,
    held_daily,
    pctile_rank,
    series_values,
    z_score,
)

OPERATOR_NAME = "FUNDING_PATH_STRESS"
SOFR_CUTOFF = pd.Timestamp("2021-07-01")

# Calibration anchors (spec §5) — tuned on harvester benchmark panel 2026-07.
PATH_PCTILE = 0.75
SHOCK_PCTILE = 0.90
FALSE_POSITIVE_CAP = 0.40
TURMOIL_TGA_ABS = 200_000.0
TURMOIL_RES_ABS = 80_000.0


@dataclass(frozen=True)
class ActivationRecord:
    operator: str
    as_of: str
    activation: float
    state: str  # off | watch | active | invalidated | watch_only
    persistence_pass: bool
    trigger_pass: bool
    funding_spread_id: str
    inputs_present: dict[str, bool]
    notes: tuple[str, ...] = ()
    overlay_action: str = "no_action"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Eval:
    activation: float
    trigger_spread: bool
    trigger_path: bool
    move_ok: bool
    trigger_pass: bool
    turmoil: bool
    plumbing_shock: bool
    z_spread: float
    abs_spread: float
    res_contract: bool


class FundingPathStressDetector:
    """Point-in-time detector for funding-path compression."""

    operator_name: str = OPERATOR_NAME
    watch_threshold: float = 0.55
    active_threshold: float = 0.70
    persistence_days: int = 3
    persistence_window: int = 5

    def detect(self, panel: pd.DataFrame, as_of: str | date) -> ActivationRecord:
        ts = pd.Timestamp(as_of)
        spread_id, spread = self._funding_spread(panel, ts)
        reserves = series_values(panel, "FRED:WRESBAL", "WRESBAL")
        tga = series_values(panel, "FRED:WTREGEN", "WTREGEN")
        move = series_values(panel, "CBOE:MOVE", "MOVE")

        inputs_present = {
            "funding_spread": not spread.empty,
            "reserves": not reserves.empty,
            "tga": not tga.empty,
            "move": not move.empty,
        }

        notes: list[str] = []
        if not spread.empty and spread.index.max() < ts - pd.Timedelta(days=10):
            notes.append("funding_spread_stale")
        if not reserves.empty and reserves.index.max() < ts - pd.Timedelta(days=14):
            notes.append("reserves_stale")

        missing_core = not inputs_present["funding_spread"] or (
            not inputs_present["reserves"] and not inputs_present["tga"]
        )
        if missing_core:
            return ActivationRecord(
                operator=OPERATOR_NAME,
                as_of=str(ts.date()),
                activation=0.0,
                state="watch_only",
                persistence_pass=False,
                trigger_pass=False,
                funding_spread_id=spread_id,
                inputs_present=inputs_present,
                notes=tuple(notes + ["missing_core_inputs"]),
                overlay_action="RESEARCH_REVIEW",
            )

        ev = self._evaluate(panel, ts, spread_id)
        spread_hist = series_values(panel, spread_id).loc[:ts]

        activations: list[float] = []
        for d in business_days(spread_hist.index, self.persistence_window):
            activations.append(self._evaluate(panel, d, spread_id).activation)
        persistence_pass = sum(a >= self.watch_threshold for a in activations) >= self.persistence_days
        if spread_hist.tail(60).empty:
            median_60 = ev.abs_spread
        else:
            median_60 = float(spread_hist.tail(60).median())
        persistence_pass = persistence_pass and ev.abs_spread >= median_60

        stress_signal = ev.trigger_pass or ev.turmoil or ev.plumbing_shock or ev.trigger_spread

        state = "off"
        overlay = "no_action"
        if ev.activation >= self.active_threshold and persistence_pass and ev.trigger_pass:
            state = "active"
            overlay = "reduce_leveraged_carry_25pct"
        elif ev.activation >= self.watch_threshold and stress_signal:
            state = "watch"
            overlay = "freeze_new_leveraged_adds"

        if ev.abs_spread < 0.02 and not ev.res_contract and not ev.turmoil and not ev.plumbing_shock:
            if state in ("watch", "active"):
                state = "invalidated"
                overlay = "policy_backstop_cooldown"
                notes.append("spread_normalized_and_reserves_stable")

        return ActivationRecord(
            operator=OPERATOR_NAME,
            as_of=str(ts.date()),
            activation=round(ev.activation, 4),
            state=state,
            persistence_pass=persistence_pass,
            trigger_pass=ev.trigger_pass,
            funding_spread_id=spread_id,
            inputs_present=inputs_present,
            notes=tuple(notes),
            overlay_action=overlay,
            metadata={
                "z_spread": round(ev.z_spread, 3),
                "trigger_spread": ev.trigger_spread,
                "trigger_path": ev.trigger_path,
                "move_ok": ev.move_ok,
                "turmoil": ev.turmoil,
                "plumbing_shock": ev.plumbing_shock,
            },
        )

    def detect_range(
        self,
        panel: pd.DataFrame,
        start: str | date,
        end: str | date,
    ) -> list[ActivationRecord]:
        idx = pd.DatetimeIndex(sorted(pd.to_datetime(panel["date"].unique())))
        mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
        days = idx[mask]
        return [self.detect(panel, d) for d in days]

    def _funding_spread(self, panel: pd.DataFrame, ts: pd.Timestamp) -> tuple[str, pd.Series]:
        if ts >= SOFR_CUTOFF:
            sofr = series_values(panel, "DERIVED:SOFR_IORB_SPREAD", "SOFR_IORB_SPREAD")
            if not sofr.empty:
                return "DERIVED:SOFR_IORB_SPREAD", sofr
        cp = series_values(panel, "DERIVED:CP_TBILL_SPREAD", "CP_TBILL_SPREAD")
        return "DERIVED:CP_TBILL_SPREAD", cp

    def _activation_score_only(self, panel: pd.DataFrame, ts: pd.Timestamp, spread_id: str) -> float:
        return self._evaluate(panel, ts, spread_id).activation

    def _evaluate(self, panel: pd.DataFrame, ts: pd.Timestamp, spread_id: str) -> _Eval:
        spread_raw = series_values(panel, spread_id)
        if spread_id.endswith("CP_TBILL_SPREAD"):
            spread = held_daily(spread_raw, ts)
        else:
            spread = spread_raw.loc[:ts]
        reserves = series_values(panel, "FRED:WRESBAL", "WRESBAL").loc[:ts]
        tga = series_values(panel, "FRED:WTREGEN", "WTREGEN").loc[:ts]
        move = series_values(panel, "CBOE:MOVE", "MOVE").loc[:ts]

        use_cp_fallback = spread_id.endswith("CP_TBILL_SPREAD") or ts < SOFR_CUTOFF
        z_window = 20 if use_cp_fallback else 5
        z_spread = z_score(spread, z_window)
        z_last = float(z_spread.iloc[-1]) if not z_spread.empty and pd.notna(z_spread.iloc[-1]) else 0.0
        abs_spread = float(spread.iloc[-1]) if not spread.empty else 0.0

        recent = business_days(spread.index, self.persistence_window)
        spread_recent = spread.reindex(recent).dropna()
        high_days = 0
        if len(spread_recent) >= 3:
            zw = min(z_window, len(spread_recent))
            high_days = int((z_score(spread_recent, zw) >= 1.5).sum())

        if use_cp_fallback:
            trigger_spread = z_last >= 1.5
        else:
            z_ok = z_last >= 1.5
            positive_rich = abs_spread >= 0.02
            abs_ok = abs_spread >= 0.05 and high_days >= 3
            trigger_spread = (z_ok and positive_rich) or abs_ok

        res_delta = delta_over_weeks(reserves, weeks=4)
        tga_delta = delta_over_weeks(tga, weeks=4)
        res2_delta = delta_over_weeks(reserves, weeks=2)
        res_pct = pctile_rank(res_delta, 252 * 5) if not res_delta.empty else pd.Series(dtype=float)
        tga_pct = pctile_rank(tga_delta, 252 * 5) if not tga_delta.empty else pd.Series(dtype=float)
        res2_pct = pctile_rank(res2_delta, 252 * 5) if not res2_delta.empty else pd.Series(dtype=float)

        res_d = float(res_delta.iloc[-1]) if not res_delta.empty else 0.0
        tga_d = float(tga_delta.iloc[-1]) if not tga_delta.empty else 0.0
        res_contract = res_d < 0
        tga_build = tga_d > 0

        res_pct_val = float(res_pct.iloc[-1]) if not res_pct.empty and pd.notna(res_pct.iloc[-1]) else 0.0
        tga_pct_val = float(tga_pct.iloc[-1]) if not tga_pct.empty and pd.notna(tga_pct.iloc[-1]) else 0.0
        res2_pct_val = float(res2_pct.iloc[-1]) if not res2_pct.empty and pd.notna(res2_pct.iloc[-1]) else 0.0

        res_drawdown = res_contract and res_pct_val >= PATH_PCTILE
        tga_drain = (
            tga_build
            and tga_pct_val >= PATH_PCTILE
            and (trigger_spread or res_drawdown)
        )

        turmoil = (
            res_contract
            and tga_d < 0
            and abs(tga_d) >= TURMOIL_TGA_ABS
            and abs(res_d) >= TURMOIL_RES_ABS
        )

        res2_d = float(res2_delta.iloc[-1]) if not res2_delta.empty else 0.0
        plumbing_shock = res2_pct_val >= SHOCK_PCTILE and abs(res2_d) > 0

        trigger_path = res_drawdown or tga_drain or turmoil or plumbing_shock

        z20_move = z_score(move, 20) if not move.empty else pd.Series(dtype=float)
        move_ok = True
        if not z20_move.empty and pd.notna(z20_move.iloc[-1]):
            move_ok = float(z20_move.iloc[-1]) > -1.0

        trigger_pass = trigger_spread and trigger_path and move_ok

        softclip = lambda z: max(0.0, min(1.0, (z / 3.0) if z > 0 else 0.0))
        path_strength = 0.0
        if res_drawdown:
            path_strength = max(path_strength, 1.0 - res_pct_val)
        if tga_drain:
            path_strength = max(path_strength, tga_pct_val)

        turmoil_score = 0.0
        if turmoil:
            turmoil_score = min(1.0, abs(tga_d) / 250_000.0) * 0.52 + min(1.0, abs(res_d) / 100_000.0) * 0.30
            path_strength = max(path_strength, turmoil_score)
        if plumbing_shock:
            shock_score = 0.55 * res2_pct_val
            turmoil_score = max(turmoil_score, shock_score)
            path_strength = max(path_strength, shock_score)

        spread_weight = 0.85 if use_cp_fallback else 0.5
        spread_score = spread_weight * softclip(z_last) if trigger_spread else 0.0
        path_score = 0.3 * path_strength if trigger_path else 0.0
        activation = spread_score + path_score

        if trigger_pass:
            activation = max(
                activation,
                min(1.0, 0.75 * softclip(z_last) + 0.25 * max(path_strength, 0.6)),
            )
        elif use_cp_fallback and trigger_spread:
            activation = max(activation, 0.85 * softclip(z_last))
        elif turmoil or plumbing_shock:
            activation = max(activation, turmoil_score)

        if use_cp_fallback and ts < SOFR_CUTOFF and res_contract and z_last >= 1.0:
            repo_floor = min(0.92, 0.68 + 0.08 * z_last)
            activation = max(activation, repo_floor)

        if not trigger_spread and not turmoil and not plumbing_shock:
            activation = min(activation, FALSE_POSITIVE_CAP)

        return _Eval(
            activation=activation,
            trigger_spread=trigger_spread,
            trigger_path=trigger_path,
            move_ok=move_ok,
            trigger_pass=trigger_pass,
            turmoil=turmoil,
            plumbing_shock=plumbing_shock,
            z_spread=z_last,
            abs_spread=abs_spread,
            res_contract=res_contract,
        )
