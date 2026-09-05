from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from src.core.models import CrossValidation, FastSignal, Snapshot


DAILY_FRED_SERIES = ("DAAA", "DBAA", "DCPF3M", "DFF", "T10Y2Y", "VIXCLS")
CHANNELS = ("M", "D", "K", "X")


@dataclass(frozen=True)
class FastSignalConfig:
    baseline_days: int = 364
    watch_threshold: float = 1.0
    warn_threshold: float = 1.5
    alert_threshold: float = 2.0
    min_observations: int = 60
    weights: Mapping[str, float] | None = None

    def channel_weights(self) -> dict[str, float]:
        raw = dict(self.weights or {})
        return {channel: float(raw.get(channel, 0.25)) for channel in CHANNELS}


class FastSignalComputer:
    """Daily surveillance signal built only from local daily FRED evidence."""

    def __init__(
        self,
        raw_fred_dir: str | Path,
        config: FastSignalConfig | None = None,
    ) -> None:
        self.raw_fred_dir = Path(raw_fred_dir)
        self.config = config or FastSignalConfig()

    def compute(self, date: str) -> FastSignal:
        frame = self._load_daily_frame()
        target = pd.to_datetime(date)
        frame = frame.loc[frame.index <= target].sort_index()
        if frame.empty:
            raise ValueError(f"No daily FRED evidence available on or before {date}")

        target_index = frame.index[frame.index <= target].max()
        expressions = self._channel_expressions(frame)
        zscores = {
            channel: self._rolling_zscore(expressions[channel], target_index)
            for channel in CHANNELS
        }
        threshold_hits = tuple(
            channel for channel, value in zscores.items()
            if value is not None and np.isfinite(value) and abs(float(value)) >= self.config.watch_threshold
        )
        composite = self._composite(zscores)
        alert_level = self._alert_level(zscores, composite)
        directions = {channel: _direction(value) for channel, value in zscores.items()}

        return FastSignal(
            date=target_index.strftime("%Y-%m-%d"),
            run_type="DAILY",
            M_zscore=zscores["M"],
            D_zscore=zscores["D"],
            K_zscore=zscores["K"],
            X_zscore=zscores["X"],
            composite=composite,
            alert_level=alert_level,
            threshold_hits=threshold_hits,
            directions=directions,
            components={
                "M_fast_credit_spread": _latest(expressions["M"], target_index),
                "D_fast_curve_vix": _latest(expressions["D"], target_index),
                "K_fast_curve_change": _latest(expressions["K"], target_index),
                "X_fast_policy_cp_spread": _latest(expressions["X"], target_index),
            },
            provenance={
                "source": "Data/harvester/raw/fred",
                "series": list(DAILY_FRED_SERIES),
                "baseline_days": self.config.baseline_days,
                "target_requested": date,
                "target_observation_date": target_index.strftime("%Y-%m-%d"),
                "run_boundary": "surveillance_only_not_canonical_snapshot",
            },
        )

    def _load_daily_frame(self) -> pd.DataFrame:
        columns: dict[str, pd.Series] = {}
        for series_id in DAILY_FRED_SERIES:
            columns[series_id] = self._load_fred_series(series_id)
        frame = pd.concat(columns.values(), axis=1)
        frame.columns = list(columns.keys())
        return frame.sort_index()

    def _load_fred_series(self, series_id: str) -> pd.Series:
        raw_json = self.raw_fred_dir / f"{series_id}_raw.json"
        raw_csv = self.raw_fred_dir / f"{series_id}.csv"
        if raw_json.exists():
            payload = json.loads(raw_json.read_text(encoding="utf-8"))
            observations = payload.get("observations", []) if isinstance(payload, dict) else []
            rows = [
                (obs.get("date"), obs.get("value"))
                for obs in observations
                if isinstance(obs, dict) and obs.get("value") not in {None, "", "."}
            ]
            frame = pd.DataFrame(rows, columns=["date", series_id])
        elif raw_csv.exists():
            frame = pd.read_csv(raw_csv)
            if "date" not in frame.columns and "observation_date" in frame.columns:
                frame = frame.rename(columns={"observation_date": "date"})
            value_cols = [col for col in frame.columns if col != "date"]
            if series_id not in frame.columns and value_cols:
                frame = frame.rename(columns={value_cols[0]: series_id})
            frame = frame[["date", series_id]]
        else:
            raise FileNotFoundError(f"Missing FRED raw evidence for {series_id}: {raw_json}")

        dates = pd.to_datetime(frame["date"], errors="coerce")
        values = pd.to_numeric(frame[series_id], errors="coerce")
        series = pd.Series(values.to_numpy(), index=dates, name=series_id).dropna()
        return series[~series.index.isna()].sort_index()

    def _channel_expressions(self, frame: pd.DataFrame) -> dict[str, pd.Series]:
        credit_spread = pd.to_numeric(frame["DBAA"], errors="coerce") - pd.to_numeric(frame["DAAA"], errors="coerce")
        curve_stress = -_expanding_zscore(frame["T10Y2Y"])
        vix_stress = _expanding_zscore(frame["VIXCLS"])
        policy_cp_spread = pd.to_numeric(frame["DFF"], errors="coerce") - pd.to_numeric(frame["DCPF3M"], errors="coerce")
        return {
            "M": credit_spread.rename("M_fast"),
            "D": ((curve_stress + vix_stress) / 2.0).rename("D_fast"),
            "K": pd.to_numeric(frame["T10Y2Y"], errors="coerce").diff().abs().rename("K_fast"),
            "X": policy_cp_spread.rename("X_fast"),
        }

    def _rolling_zscore(self, series: pd.Series, target_index: pd.Timestamp) -> float | None:
        clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if target_index not in clean.index:
            prior = clean.loc[clean.index <= target_index]
            if prior.empty:
                return None
            target_index = prior.index.max()
        target_value = float(clean.loc[target_index])
        baseline_start = target_index - pd.Timedelta(days=self.config.baseline_days)
        baseline = clean.loc[(clean.index < target_index) & (clean.index >= baseline_start)]
        if len(baseline) < self.config.min_observations:
            baseline = clean.loc[clean.index < target_index].tail(self.config.min_observations)
        if len(baseline) < 2:
            return None
        std = float(baseline.std(ddof=0))
        if not np.isfinite(std) or std == 0.0:
            return 0.0
        return float((target_value - float(baseline.mean())) / std)

    def _composite(self, zscores: Mapping[str, float | None]) -> float | None:
        weights = self.config.channel_weights()
        values = {
            channel: float(value)
            for channel, value in zscores.items()
            if value is not None and np.isfinite(float(value))
        }
        if not values:
            return None
        weight_sum = sum(abs(weights[channel]) for channel in values)
        if weight_sum == 0.0:
            return None
        return float(sum(values[channel] * weights[channel] for channel in values) / weight_sum)

    def _alert_level(self, zscores: Mapping[str, float | None], composite: float | None) -> str:
        magnitudes = [
            abs(float(value))
            for value in zscores.values()
            if value is not None and np.isfinite(float(value))
        ]
        if composite is not None and np.isfinite(composite):
            magnitudes.append(abs(float(composite)))
        peak = max(magnitudes, default=0.0)
        hits = sum(1 for value in magnitudes if value >= self.config.watch_threshold)
        if peak >= self.config.alert_threshold and hits >= 2:
            return "ALERT"
        if peak >= self.config.warn_threshold:
            return "WARN"
        if peak >= self.config.watch_threshold:
            return "WATCH"
        return "CLEAR"


class CrossValidator:
    def validate(self, canonical: Snapshot, fast: FastSignal) -> CrossValidation:
        canonical_directions = {channel: str(canonical.proxy.directions.get(channel, "UNKNOWN")) for channel in CHANNELS}
        fast_directions = {channel: str(fast.directions.get(channel, "UNKNOWN")) for channel in CHANNELS}
        agreement = {
            channel: canonical_directions[channel] == fast_directions[channel]
            for channel in CHANNELS
        }
        score = sum(1 for value in agreement.values() if value) / len(CHANNELS)
        canonical_elevated = any(value == "WORSENING" for value in canonical_directions.values())
        fast_fires = fast.alert_level != "CLEAR"
        fast_worsening = any(value == "WORSENING" for value in fast_directions.values())

        if score >= 0.75 and fast_fires:
            verdict = "CONFIRMED"
        elif fast_fires and not canonical_elevated:
            verdict = "LEADING"
        elif canonical_elevated and not fast_worsening:
            verdict = "LAGGING"
        elif fast_fires:
            verdict = "NOISE"
        else:
            verdict = "COHERENT"

        return CrossValidation(
            date=fast.date,
            canonical_date=canonical.run_date,
            fast_date=fast.date,
            verdict=verdict,
            confidence_multiplier=float(score),
            agreement_per_channel=agreement,
            canonical_directions=canonical_directions,
            fast_directions=fast_directions,
            alert_level=fast.alert_level,
        )


def _expanding_zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    mean = numeric.expanding(min_periods=60).mean().shift(1)
    std = numeric.expanding(min_periods=60).std(ddof=0).shift(1)
    return ((numeric - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def _latest(series: pd.Series, target_index: pd.Timestamp) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    clean = clean.loc[clean.index <= target_index]
    if clean.empty:
        return None
    return float(clean.iloc[-1])


def _direction(value: float | None) -> str:
    if value is None or not np.isfinite(float(value)):
        return "UNKNOWN"
    if float(value) >= 0.5:
        return "WORSENING"
    if float(value) <= -0.5:
        return "IMPROVING"
    return "STABLE"
