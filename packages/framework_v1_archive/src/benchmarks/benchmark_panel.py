"""Public benchmark panel registry.

Single source of truth for the FRED-fetchable series the research system uses
as benchmarks, controls, proxies, and asset-price inputs. Group membership is
stable so other modules can ask the registry for "all volatility series",
"all credit OAS series", etc., without hardcoding lists.

Series that are not directly on FRED, such as MOVE, CVIX, VIX9D, CISS, SRISK,
and CoVaR, must be acquired by Structural Risk Harvester and published as
admitted evidence before Deformation consumes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BenchmarkSeries:
    fred_id: str
    category: str
    label: str
    description: str
    invert_for_stress: bool = False
    higher_is_safer: bool = False


VOLATILITY: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("VIXCLS", "volatility", "VIX", "S&P 500 1M implied vol"),
    BenchmarkSeries("VXVCLS", "volatility", "VIX3M", "S&P 500 3M implied vol"),
    BenchmarkSeries("VXNCLS", "volatility", "VXN", "Nasdaq 100 implied vol"),
    BenchmarkSeries("VXDCLS", "volatility", "VXD", "DJIA implied vol"),
    BenchmarkSeries("VXOCLS", "volatility", "VXO", "S&P 100 implied vol"),
    BenchmarkSeries("OVXCLS", "volatility", "OVX", "Crude oil implied vol"),
    BenchmarkSeries("EVZCLS", "volatility", "EVZ", "Euro currency implied vol"),
    BenchmarkSeries("GVZCLS", "volatility", "GVZ", "Gold implied vol"),
)

LIQUIDITY: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("TEDRATE", "liquidity", "TED Spread", "3M LIBOR - 3M T-bill (retired Jan 2022)"),
    BenchmarkSeries("DFF", "liquidity", "Effective Fed Funds", "Effective fed funds rate"),
    BenchmarkSeries("EFFR", "liquidity", "Effective FFR", "Effective federal funds rate (post-2016)"),
    BenchmarkSeries("SOFR", "liquidity", "SOFR", "Secured Overnight Financing Rate"),
    BenchmarkSeries("OBFR", "liquidity", "OBFR", "Overnight Bank Funding Rate"),
    BenchmarkSeries("DGS3MO", "liquidity", "3M Treasury", "3M constant maturity Treasury"),
    BenchmarkSeries("DTB3", "liquidity", "3M T-bill", "3M Treasury bill secondary market"),
    BenchmarkSeries("USD3MTD156N", "liquidity", "3M USD LIBOR", "3M USD LIBOR (retired)"),
    BenchmarkSeries("IORB", "liquidity", "Interest on Reserve Balances", "IORB rate"),
)

CREDIT: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("BAMLH0A0HYM2", "credit", "HY OAS", "ICE BofA US High Yield Index OAS"),
    BenchmarkSeries("BAMLC0A4CBBB", "credit", "IG BBB OAS", "ICE BofA BBB Corporate OAS"),
    BenchmarkSeries("BAMLC0A0CM", "credit", "IG OAS", "ICE BofA US Corporate Master OAS"),
    BenchmarkSeries("BAMLEMCBPIOAS", "credit", "EM Corporate OAS", "ICE BofA EM Corporate Plus OAS"),
    BenchmarkSeries("BAA10Y", "credit", "Moody's BAA-10Y", "Moody's BAA Corporate over 10Y Treasury"),
    BenchmarkSeries("AAA10Y", "credit", "Moody's AAA-10Y", "Moody's AAA Corporate over 10Y Treasury"),
)

TERM_STRUCTURE: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("T10Y2Y", "term_structure", "10Y-2Y", "10Y minus 2Y Treasury (curve)"),
    BenchmarkSeries("T10Y3M", "term_structure", "10Y-3M", "10Y minus 3M Treasury (curve)"),
    BenchmarkSeries("DGS2", "term_structure", "2Y Treasury", "2Y constant maturity"),
    BenchmarkSeries("DGS5", "term_structure", "5Y Treasury", "5Y constant maturity"),
    BenchmarkSeries("DGS10", "term_structure", "10Y Treasury", "10Y constant maturity"),
    BenchmarkSeries("DGS30", "term_structure", "30Y Treasury", "30Y constant maturity"),
    BenchmarkSeries("DFII5", "term_structure", "5Y TIPS", "5Y TIPS yield"),
    BenchmarkSeries("DFII10", "term_structure", "10Y TIPS", "10Y TIPS yield"),
    BenchmarkSeries("T5YIE", "term_structure", "5Y breakeven", "5Y breakeven inflation"),
    BenchmarkSeries("T10YIE", "term_structure", "10Y breakeven", "10Y breakeven inflation"),
    BenchmarkSeries("T5YIFR", "term_structure", "5Y5Y fwd breakeven", "5Y forward 5Y breakeven inflation"),
)

COMPOSITE_STRESS: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("NFCI", "composite_stress", "NFCI", "Chicago Fed National Financial Conditions Index"),
    BenchmarkSeries("ANFCI", "composite_stress", "ANFCI", "Adjusted NFCI controlling for macro"),
    BenchmarkSeries("NFCIRISK", "composite_stress", "NFCI Risk", "Chicago Fed NFCI risk subindex"),
    BenchmarkSeries("NFCICREDIT", "composite_stress", "NFCI Credit", "Chicago Fed NFCI credit subindex"),
    BenchmarkSeries("NFCILEVERAGE", "composite_stress", "NFCI Leverage", "Chicago Fed NFCI leverage subindex"),
    BenchmarkSeries("STLFSI4", "composite_stress", "STLFSI4", "St Louis Fed Financial Stress Index v4"),
    BenchmarkSeries("KCFSI", "composite_stress", "KCFSI", "Kansas City Financial Stress Index"),
    BenchmarkSeries("OFRFSI", "composite_stress", "OFR FSI", "Office of Financial Research FSI"),
)

ASSET_PRICE: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("SP500", "asset_price", "S&P 500", "S&P 500 index, daily close"),
    BenchmarkSeries("WILL5000PRFC", "asset_price", "Wilshire 5000", "Full-cap Wilshire 5000 (price index)"),
    BenchmarkSeries("BAMLCC0A0CMTRIV", "asset_price", "IG Total Return", "ICE BofA US Corporate Total Return Index"),
    BenchmarkSeries("BAMLHYH0A0HYM2TRIV", "asset_price", "HY Total Return", "ICE BofA HY Total Return Index"),
    BenchmarkSeries("DEXUSEU", "asset_price", "USD/EUR", "USD per Euro spot"),
    BenchmarkSeries("DEXJPUS", "asset_price", "JPY/USD", "JPY per USD spot"),
    BenchmarkSeries("DCOILWTICO", "asset_price", "WTI Crude", "WTI crude oil spot"),
    BenchmarkSeries("GOLDAMGBD228NLBM", "asset_price", "Gold AM Fix", "London gold AM fix"),
)


PROXY_EXTENSION: tuple[BenchmarkSeries, ...] = (
    BenchmarkSeries("DCOILWTICO", "proxy", "WTI Crude", "Commodity stress sensor"),
    BenchmarkSeries("DEXUSEU", "proxy", "USD/EUR", "FX dislocation sensor"),
)


BENCHMARK_PANEL: tuple[BenchmarkSeries, ...] = (
    VOLATILITY + LIQUIDITY + CREDIT + TERM_STRUCTURE + COMPOSITE_STRESS + ASSET_PRICE
)


def panel_by_category(category: str) -> tuple[BenchmarkSeries, ...]:
    return tuple(s for s in BENCHMARK_PANEL if s.category == category)


def all_fred_ids(panel: Iterable[BenchmarkSeries] = BENCHMARK_PANEL) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for spec in panel:
        seen.setdefault(spec.fred_id, None)
    return tuple(seen.keys())


def derived_spread(frame: pd.DataFrame, left: str, right: str, name: str | None = None) -> pd.Series:
    if left not in frame.columns or right not in frame.columns:
        raise KeyError(f"Cannot compute spread {left}-{right}: missing column")
    out = pd.to_numeric(frame[left], errors="coerce") - pd.to_numeric(frame[right], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan)
    out.name = name or f"{left}_{right}_spread"
    return out


DERIVED_SPREADS_RECIPE: tuple[tuple[str, str, str], ...] = (
    ("SOFR_TBILL_3M", "SOFR", "DTB3"),
    ("SOFR_FFR", "SOFR", "EFFR"),
    ("LIBOR_OIS_3M", "USD3MTD156N", "EFFR"),
    ("HY_IG_GAP", "BAMLH0A0HYM2", "BAMLC0A0CM"),
    ("BBB_IG_GAP", "BAMLC0A4CBBB", "BAMLC0A0CM"),
    ("VIX_TERM_RATIO", "VIXCLS", "VXVCLS"),
    ("REAL_5Y", "DFII5", "T5YIE"),
)


def build_derived_spreads(frame: pd.DataFrame, recipes: Iterable[tuple[str, str, str]] = DERIVED_SPREADS_RECIPE) -> pd.DataFrame:
    out_columns: dict[str, pd.Series] = {}
    for name, left, right in recipes:
        if left in frame.columns and right in frame.columns:
            if name == "VIX_TERM_RATIO":
                num = pd.to_numeric(frame[left], errors="coerce")
                den = pd.to_numeric(frame[right], errors="coerce").replace(0.0, np.nan)
                series = (num / den).replace([np.inf, -np.inf], np.nan)
                series.name = name
                out_columns[name] = series
            else:
                out_columns[name] = derived_spread(frame, left, right, name=name)
    if not out_columns:
        return pd.DataFrame(index=frame.index)
    return pd.DataFrame(out_columns, index=frame.index)


__all__ = [
    "BenchmarkSeries",
    "VOLATILITY",
    "LIQUIDITY",
    "CREDIT",
    "TERM_STRUCTURE",
    "COMPOSITE_STRESS",
    "ASSET_PRICE",
    "PROXY_EXTENSION",
    "BENCHMARK_PANEL",
    "DERIVED_SPREADS_RECIPE",
    "all_fred_ids",
    "build_derived_spreads",
    "derived_spread",
    "panel_by_category",
]
