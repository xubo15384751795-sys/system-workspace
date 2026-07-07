from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.core.interfaces import ProxyBuilderInterface
from src.core.models import ProxyReading
from src.proxies import structural_basket_map


MEASUREMENT_CHANNELS = ("M", "D", "K", "X_PRE", "X_REALIZED")
PUBLIC_CHANNELS = ("M", "D", "K", "X", "X_PRE", "X_REALIZED")

# Rolling window for z-score normalization (weeks).
# Full-history normalization creates look-ahead bias; 260w ≈ 5 years gives
# enough context while keeping the reference window from reaching forward.
ROLLING_ZSCORE_WINDOW = 260

# Winsorization clip before z-scoring (in raw standard deviations).
WINSOR_CLIP_STD = 3.0


DEFAULT_DIRECT_CHANNEL_MAP: dict[str, str] = {
    "M": "M_PROXY",
    "D": "D_PROXY",
    "K": "K_PROXY",
    "X": "X_PROXY",
    "X_PRE": "X_PRE_PROXY",
    "X_REALIZED": "X_REALIZED_PROXY",
}


DEFAULT_BASKET_MAP: dict[str, dict[str, list[dict[str, Any]]]] = structural_basket_map()


@dataclass
class DefaultProxyBuilder(ProxyBuilderInterface):
    channel_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_DIRECT_CHANNEL_MAP))
    basket_map: dict[str, dict[str, list[dict[str, Any]]]] = field(
        default_factory=lambda: copy.deepcopy(DEFAULT_BASKET_MAP)
    )
    worsening_threshold: float = 0.5
    stable_threshold: float = -0.5

    def build(self, raw: pd.DataFrame, run_date: str) -> ProxyReading:
        values = {channel: None for channel in PUBLIC_CHANNELS}
        if raw.empty:
            return self._to_reading(run_date, values)

        try:
            history = raw.loc[: pd.to_datetime(run_date)].copy()
        except Exception:
            history = raw.copy()
        latest = history.tail(1)
        if latest.empty:
            return self._to_reading(run_date, values)

        components: dict[str, float | None] = {}
        coverage: dict[str, float] = {}
        for channel in MEASUREMENT_CHANNELS:
            val, channel_components = self._build_channel(channel, history)
            values[channel] = val
            components.update(channel_components)
            coverage[channel] = self._coverage_score(channel, history)

        legacy_x = self._legacy_x_direct(history)
        values["X"] = self._combine_shadow_channels(values["X_PRE"], values["X_REALIZED"], legacy_x)
        coverage["X"] = max(
            coverage.get("X_PRE", 0.0),
            coverage.get("X_REALIZED", 0.0),
            self._legacy_x_coverage(history),
        )
        components["X"] = values["X"]
        components["X_PRE"] = values["X_PRE"]
        components["X_REALIZED"] = values["X_REALIZED"]

        reading = self._to_reading(run_date, values, components)
        reading = self._attach_coverage(reading, coverage)
        return reading

    def _build_channel(self, channel: str, history: pd.DataFrame) -> tuple[float | None, dict[str, float | None]]:
        direct_col = self.channel_map.get(channel)
        if direct_col in history.columns:
            val = self._latest_float(history[direct_col])
            components: dict[str, float | None] = {}
            for basket_name, specs in self.basket_map.get(channel, {}).items():
                components[basket_name] = self._basket_score(channel, history, specs)
            if channel == "D":
                components["D_STRESS"] = self._positive_or_zero(-(val or 0.0))
            elif channel in {"M", "K", "X_PRE", "X_REALIZED"}:
                components[f"{channel}_STRESS"] = self._positive_or_zero(val)
            components[channel] = val
            return val, components

        basket_scores: dict[str, float | None] = {}
        for basket_name, specs in self.basket_map.get(channel, {}).items():
            basket_scores[basket_name] = self._basket_score(channel, history, specs)

        available_scores = [v for v in basket_scores.values() if v is not None]
        if not available_scores:
            return None, basket_scores

        # All channels aggregate as signed mean.
        # M previously used weighted_l1 (mean of absolute values) which destroyed
        # sign information — anchor mismatch can be negative (compressing), zero
        # (balanced), or positive (dislocating). Mean preserves that.
        value = float(np.mean(available_scores))
        if channel == "D":
            basket_scores["D_STRESS"] = self._positive_or_zero(-value)
        elif channel in {"M", "K", "X_PRE", "X_REALIZED"}:
            basket_scores[f"{channel}_STRESS"] = self._positive_or_zero(value)
        basket_scores[channel] = value
        return value, basket_scores

    def _basket_score(self, channel: str, history: pd.DataFrame, specs: list[dict[str, Any]]) -> float | None:
        scores: list[float] = []
        for spec in specs:
            source_id = str(spec.get("id", "")).strip()
            if source_id not in history.columns:
                continue
            series = pd.to_numeric(history[source_id], errors="coerce")
            z = self._rolling_zscore(series)
            if z is None:
                continue
            orientation = str(spec.get("orientation", "stress")).lower()
            is_freedom_positive = orientation in {"freedom", "capacity", "good"}
            if channel == "D":
                if not is_freedom_positive:
                    z = -z
            elif is_freedom_positive:
                z = -z
            weight = float(spec.get("weight", 1.0))
            scores.append(z * weight)
        if not scores:
            return None
        return float(np.mean(scores))

    def _latest_float(self, series: pd.Series) -> float | None:
        val = pd.to_numeric(series.tail(1), errors="coerce")
        if val.empty or pd.isna(val.iloc[0]):
            return None
        return float(val.iloc[0])

    def _rolling_zscore(self, series: pd.Series, window: int = ROLLING_ZSCORE_WINDOW) -> float | None:
        """Z-score using a rolling historical window to avoid look-ahead bias.

        Uses min(window, len(series)) observations ending at the current point.
        Winsorizes raw values at ±WINSOR_CLIP_STD * std before computing z.
        """
        finite = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if finite.empty:
            return None
        # Restrict to the look-back window ending at the last observation
        window_data = finite.iloc[-min(window, len(finite)):]
        if len(window_data) < 4:
            return None
        # Winsorize: clip raw series at ±3 std of window
        raw_std = float(window_data.std(ddof=0))
        raw_mean = float(window_data.mean())
        if raw_std > 0:
            lo = raw_mean - WINSOR_CLIP_STD * raw_std
            hi = raw_mean + WINSOR_CLIP_STD * raw_std
            window_data = window_data.clip(lo, hi)
        mean = float(window_data.mean())
        std = float(window_data.std(ddof=0))
        latest = float(finite.iloc[-1])
        latest_clipped = np.clip(latest, raw_mean - WINSOR_CLIP_STD * raw_std if raw_std > 0 else latest,
                                         raw_mean + WINSOR_CLIP_STD * raw_std if raw_std > 0 else latest)
        if not np.isfinite(std) or std == 0:
            return float(latest_clipped - mean)
        return float((latest_clipped - mean) / std)

    def _coverage_score(self, channel: str, history: pd.DataFrame) -> float:
        """Fraction of proxy inputs for this channel that have non-null data."""
        specs_all: list[dict[str, Any]] = []
        for basket_specs in self.basket_map.get(channel, {}).values():
            specs_all.extend(basket_specs)
        if not specs_all:
            direct_col = self.channel_map.get(channel)
            if direct_col and direct_col in history.columns:
                series = pd.to_numeric(history[direct_col], errors="coerce")
                return 1.0 if series.notna().any() else 0.0
            return 0.0
        available = sum(
            1 for s in specs_all
            if str(s.get("id", "")).strip() in history.columns
            and pd.to_numeric(history[str(s.get("id", "")).strip()], errors="coerce").notna().any()
        )
        return available / len(specs_all)

    def _attach_coverage(self, reading: ProxyReading, coverage: dict[str, float]) -> ProxyReading:
        """Attach per-channel coverage scores and a snapshot validity label."""
        components = dict(reading.components or {})
        for ch, score in coverage.items():
            components[f"{ch}_coverage"] = score
        # Snapshot validity label based on the legacy four-channel contract:
        #   VALID_FULL    all channels ≥ 0.8
        #   VALID_PARTIAL all channels ≥ 0.3
        #   DIAGNOSTIC_ONLY  any channel < 0.3
        contract_channels = ("M", "D", "K", "X")
        min_cov = min((coverage.get(ch, 0.0) for ch in contract_channels), default=0.0)
        if min_cov >= 0.80:
            components["snapshot_validity"] = "VALID_FULL"
        elif min_cov >= 0.30:
            components["snapshot_validity"] = "VALID_PARTIAL"
        else:
            components["snapshot_validity"] = "DIAGNOSTIC_ONLY"
        from dataclasses import replace as dc_replace
        return dc_replace(reading, components=components)

    def _legacy_x_direct(self, history: pd.DataFrame) -> float | None:
        direct_col = self.channel_map.get("X")
        if direct_col in history.columns:
            return self._latest_float(history[direct_col])
        return None

    def _legacy_x_coverage(self, history: pd.DataFrame) -> float:
        direct_col = self.channel_map.get("X")
        if direct_col and direct_col in history.columns:
            series = pd.to_numeric(history[direct_col], errors="coerce")
            return 1.0 if series.notna().any() else 0.0
        return 0.0

    def _combine_shadow_channels(
        self,
        x_pre: float | None,
        x_realized: float | None,
        legacy_x: float | None = None,
    ) -> float | None:
        values = [v for v in (x_pre, x_realized) if v is not None and np.isfinite(v)]
        if values:
            # Legacy X is a compatibility aggregate, not a structural channel.
            # Use the strongest visible shadow condition so forced realization
            # does not dilute hidden-accumulation traces and vice versa.
            return float(max(values))
        return legacy_x

    def _positive_or_zero(self, value: float | None) -> float:
        if value is None or not np.isfinite(value):
            return 0.0
        return float(max(0.0, value))

    def _to_reading(
        self,
        run_date: str,
        values: dict[str, float | None],
        components: dict[str, float | None] | None = None,
    ) -> ProxyReading:
        directions = {}
        available = {}
        for key, val in values.items():
            available[key] = val is not None
            if val is None:
                directions[key] = "UNKNOWN"
            elif self._is_worsening(key, val):
                directions[key] = "WORSENING"
            elif val < self.stable_threshold:
                directions[key] = "IMPROVING"
            else:
                directions[key] = "STABLE"
        return ProxyReading(
            run_date=run_date,
            M=values["M"],
            D=values["D"],
            K=values["K"],
            X=values["X"],
            directions=directions,
            available=available,
            components=components or values,
            X_PRE=values.get("X_PRE"),
            X_REALIZED=values.get("X_REALIZED"),
        )

    def _is_worsening(self, channel: str, val: float) -> bool:
        if channel == "D":
            return val < -self.worsening_threshold
        return val > self.worsening_threshold
