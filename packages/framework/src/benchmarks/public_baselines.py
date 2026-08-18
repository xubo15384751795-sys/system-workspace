from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from src.benchmarks.historical_replay import rolling_zscore


@dataclass(frozen=True)
class PublicBaselineReading:
    timestamp: pd.Timestamp
    score: float
    percentile_score: float
    regime_label: str
    confidence: float
    source_features: tuple[str, ...]
    data_coverage: float


@dataclass(frozen=True)
class PublicBaseline:
    name: str
    source_features: tuple[str, ...]
    scorer: Callable[[pd.DataFrame], pd.Series]

    def evaluate(self, frame: pd.DataFrame) -> pd.DataFrame:
        score = self.scorer(frame).reindex(frame.index).replace([np.inf, -np.inf], np.nan)
        percentile = _expanding_percentile(score)
        coverage = frame.reindex(columns=list(self.source_features)).notna().mean(axis=1)
        out = pd.DataFrame(
            {
                "timestamp": frame.index,
                "score": score.fillna(0.0).astype(float),
                "percentile_score": percentile.fillna(0.0).astype(float),
                "regime_label": percentile.map(_regime_label),
                "confidence": coverage.fillna(0.0).clip(0.0, 1.0),
                "source_features": [self.source_features] * len(frame),
                "data_coverage": coverage.fillna(0.0).clip(0.0, 1.0),
            },
            index=frame.index,
        )
        return out


def build_public_baselines(frame: pd.DataFrame, include_random: bool = True) -> dict[str, pd.DataFrame]:
    baselines = available_public_baselines(frame, include_random=include_random)
    return {baseline.name: baseline.evaluate(frame) for baseline in baselines}


def available_public_baselines(frame: pd.DataFrame, include_random: bool = True) -> tuple[PublicBaseline, ...]:
    specs: list[PublicBaseline] = [
        _single("vix_only", ("VIXCLS", "VIX"), frame),
        _single("move_only", ("MOVE",), frame),
        _single("vvix_only", ("VVIX",), frame),
        PublicBaseline("vix_term_structure", _present(frame, ("VIXCLS", "VXVCLS")), _vix_term_structure_score),
        PublicBaseline("yield_curve_only", _present(frame, ("T10Y2Y", "T10Y3M", "DGS10", "DGS2")), _yield_curve_score),
        PublicBaseline("credit_spread_only", _present(frame, ("BAMLH0A0HYM2", "BAA10Y", "AAA10Y")), _credit_spread_score),
        PublicBaseline("ig_oas_only", _present(frame, ("BAMLC0A0CM", "BAMLC0A4CBBB")), _ig_oas_score),
        PublicBaseline("hy_ig_gap_only", _present(frame, ("BAMLH0A0HYM2", "BAMLC0A0CM")), _hy_ig_gap_score),
        PublicBaseline("sofr_ois_only", _present(frame, ("SOFR", "EFFR", "USD3MTD156N")), _sofr_ois_score),
        _single("nfci", ("NFCI",), frame),
        _single("anfci", ("ANFCI",), frame),
        _single("stlfsi", ("STLFSI4", "STLFSI"), frame),
        _single("ofr_fsi", ("OFRFSI", "OFR_FSI"), frame),
        _single("kcfsi", ("KCFSI",), frame),
        _single("ciss_only", ("CISS",), frame),
        _single("srisk_only", ("SRISK",), frame),
        _single("covar_only", ("COVAR",), frame),
        PublicBaseline("equal_weight_public_stress_basket", _stress_features(frame), _equal_weight_score),
        PublicBaseline("breadth_of_stress", _stress_features(frame), _breadth_score),
    ]
    if include_random:
        specs.append(PublicBaseline("random_fixed_seed", tuple(), _random_score))
    return tuple(spec for spec in specs if spec.name == "random_fixed_seed" or spec.source_features)


def latest_reading(baseline_frame: pd.DataFrame) -> PublicBaselineReading | None:
    if baseline_frame.empty:
        return None
    row = baseline_frame.iloc[-1]
    return PublicBaselineReading(
        timestamp=pd.Timestamp(row["timestamp"]),
        score=float(row["score"]),
        percentile_score=float(row["percentile_score"]),
        regime_label=str(row["regime_label"]),
        confidence=float(row["confidence"]),
        source_features=tuple(row["source_features"]),
        data_coverage=float(row["data_coverage"]),
    )


def _single(name: str, candidates: tuple[str, ...], frame: pd.DataFrame) -> PublicBaseline:
    features = _present(frame, candidates)

    def scorer(data: pd.DataFrame) -> pd.Series:
        return _zmean(data, features)

    return PublicBaseline(name, features, scorer)


def _present(frame: pd.DataFrame, candidates: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(col for col in candidates if col in frame.columns)


def _stress_features(frame: pd.DataFrame) -> tuple[str, ...]:
    return _present(
        frame,
        (
            "VIXCLS",
            "VIX",
            "MOVE",
            "VVIX",
            "VXVCLS",
            "NFCI",
            "ANFCI",
            "STLFSI4",
            "OFRFSI",
            "KCFSI",
            "CISS",
            "SRISK",
            "COVAR",
            "BAMLH0A0HYM2",
            "BAMLC0A0CM",
            "BAMLC0A4CBBB",
            "BAA10Y",
        ),
    )


def _zmean(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    if not columns:
        return pd.Series(0.0, index=frame.index)
    z = pd.DataFrame({col: rolling_zscore(frame[col], robust=True).clip(lower=0.0) for col in columns}, index=frame.index)
    return z.mean(axis=1)


def _yield_curve_score(frame: pd.DataFrame) -> pd.Series:
    if "T10Y2Y" in frame.columns:
        return rolling_zscore(-frame["T10Y2Y"], robust=True).clip(lower=0.0)
    if "T10Y3M" in frame.columns:
        return rolling_zscore(-frame["T10Y3M"], robust=True).clip(lower=0.0)
    if {"DGS10", "DGS2"}.issubset(frame.columns):
        return rolling_zscore(-(frame["DGS10"] - frame["DGS2"]), robust=True).clip(lower=0.0)
    return pd.Series(0.0, index=frame.index)


def _credit_spread_score(frame: pd.DataFrame) -> pd.Series:
    return _zmean(frame, _present(frame, ("BAMLH0A0HYM2", "BAA10Y", "AAA10Y")))


def _ig_oas_score(frame: pd.DataFrame) -> pd.Series:
    return _zmean(frame, _present(frame, ("BAMLC0A0CM", "BAMLC0A4CBBB")))


def _hy_ig_gap_score(frame: pd.DataFrame) -> pd.Series:
    if not {"BAMLH0A0HYM2", "BAMLC0A0CM"}.issubset(frame.columns):
        return pd.Series(0.0, index=frame.index)
    gap = pd.to_numeric(frame["BAMLH0A0HYM2"], errors="coerce") - pd.to_numeric(frame["BAMLC0A0CM"], errors="coerce")
    return rolling_zscore(gap, robust=True).clip(lower=0.0)


def _sofr_ois_score(frame: pd.DataFrame) -> pd.Series:
    if {"SOFR", "EFFR"}.issubset(frame.columns):
        spread = pd.to_numeric(frame["SOFR"], errors="coerce") - pd.to_numeric(frame["EFFR"], errors="coerce")
        return rolling_zscore(spread.abs(), robust=True).clip(lower=0.0)
    if {"USD3MTD156N", "EFFR"}.issubset(frame.columns):
        spread = pd.to_numeric(frame["USD3MTD156N"], errors="coerce") - pd.to_numeric(frame["EFFR"], errors="coerce")
        return rolling_zscore(spread, robust=True).clip(lower=0.0)
    return pd.Series(0.0, index=frame.index)


def _vix_term_structure_score(frame: pd.DataFrame) -> pd.Series:
    if not {"VIXCLS", "VXVCLS"}.issubset(frame.columns):
        return pd.Series(0.0, index=frame.index)
    short = pd.to_numeric(frame["VIXCLS"], errors="coerce")
    longv = pd.to_numeric(frame["VXVCLS"], errors="coerce").replace(0.0, np.nan)
    inversion = (short / longv) - 1.0
    return rolling_zscore(inversion, robust=True).clip(lower=0.0)


def _equal_weight_score(frame: pd.DataFrame) -> pd.Series:
    return _zmean(frame, _stress_features(frame))


def _breadth_score(frame: pd.DataFrame) -> pd.Series:
    cols = _stress_features(frame)
    if not cols:
        return pd.Series(0.0, index=frame.index)
    z = pd.DataFrame({col: rolling_zscore(frame[col], robust=True) for col in cols}, index=frame.index)
    breadth = (z >= 1.0).sum(axis=1).astype(float) / float(len(cols))
    return breadth


def _random_score(frame: pd.DataFrame) -> pd.Series:
    rng = np.random.default_rng(1729)
    return pd.Series(rng.normal(0.0, 1.0, len(frame)), index=frame.index).clip(lower=0.0)


def _expanding_percentile(series: pd.Series) -> pd.Series:
    values: list[float] = []
    out: list[float] = []
    for value in pd.to_numeric(series, errors="coerce"):
        if not np.isfinite(value):
            out.append(0.0)
            continue
        if not values:
            out.append(0.5)
        else:
            out.append(float(np.mean(np.asarray(values) <= value)))
        values.append(float(value))
    return pd.Series(out, index=series.index)


def _regime_label(percentile: float) -> str:
    if percentile >= 0.95:
        return "CRISIS_CANDIDATE"
    if percentile >= 0.8:
        return "ELEVATED"
    if percentile >= 0.6:
        return "WATCH"
    return "CALM"
