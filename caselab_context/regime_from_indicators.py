"""Infer regime axes from Paper data_pipeline indicator snapshots."""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from caselab_context.load_context import default_regime, load_current_regime
from caselab_context.paper_paths import paper_root

THRESHOLDS_PATH = paper_root() / "90_Admin/Context Rules/regime_thresholds.yml"
PROCESSED_DIR = paper_root() / "data_pipeline/data/processed"


def _load_thresholds() -> dict[str, Any]:
    if not THRESHOLDS_PATH.exists():
        return {}
    return yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}


def _load_history(path: Path, lookback: int = 21) -> list[tuple[str, float]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    parsed: list[tuple[str, float]] = []
    for row in rows[-lookback:]:
        try:
            parsed.append((row["date"], float(row["value"])))
        except (KeyError, ValueError):
            continue
    return parsed


def _latest_value(path: Path) -> dict[str, Any] | None:
    history = _load_history(path, lookback=1)
    if not history:
        return None
    date, value = history[-1]
    return {"date": date, "value": value}


def _delta(history: list[tuple[str, float]], days: int = 20) -> float | None:
    if len(history) < days + 1:
        return None
    return history[-1][1] - history[-days - 1][1]


def _pick_credit(oas_level: float | None, oas_chg: float | None, rules: dict[str, Any]) -> str:
    credit_rules = rules.get("credit") or {}
    if oas_level is None:
        return "expanding"
    fragile = credit_rules.get("fragile") or {}
    contracting = credit_rules.get("contracting") or {}
    expanding = credit_rules.get("expanding") or {}
    if oas_level >= float(contracting.get("min_oas_level", 4.0)):
        return "contracting"
    if oas_level >= float(fragile.get("min_oas_level", 3.2)) or (
        oas_chg is not None and oas_chg >= float(fragile.get("min_oas_chg_20d", 0.25))
    ):
        return "fragile"
    if oas_level <= float(expanding.get("max_oas_level", 3.2)):
        return "expanding"
    return "fragile"


def _pick_liquidity(sofr_level: float | None, sofr_chg: float | None, rules: dict[str, Any]) -> str:
    liquidity_rules = rules.get("liquidity") or {}
    stressed = liquidity_rules.get("stressed") or {}
    tightening = liquidity_rules.get("tightening") or {}
    abundant = liquidity_rules.get("abundant") or {}
    if sofr_level is not None and sofr_level >= float(stressed.get("min_sofr_level", 5.0)):
        return "stressed"
    if sofr_chg is not None and sofr_chg >= float(tightening.get("min_sofr_chg_20d", 0.12)):
        return "tightening"
    if sofr_level is not None and sofr_level <= float(abundant.get("max_sofr_level", 4.2)):
        if sofr_chg is None or sofr_chg <= float(abundant.get("max_sofr_chg_20d", 0.12)):
            return "abundant"
    return "tightening"


def _pick_rates(ten_y_chg: float | None, rules: dict[str, Any]) -> str:
    rates_rules = rules.get("rates") or {}
    if ten_y_chg is None:
        return "stable"
    if ten_y_chg <= float((rates_rules.get("falling") or {}).get("max_ten_y_chg_20d", -0.08)):
        return "falling"
    if ten_y_chg >= float((rates_rules.get("rising") or {}).get("min_ten_y_chg_20d", 0.08)):
        return "rising"
    return "stable"


def _pick_market_mood(oas_level: float | None, ten_y_chg: float | None, rules: dict[str, Any]) -> str:
    mood_rules = rules.get("market_mood") or {}
    if oas_level is not None and oas_level >= float((mood_rules.get("risk_off") or {}).get("min_oas_level", 3.5)):
        return "risk_off"
    if oas_level is not None and oas_level <= float((mood_rules.get("risk_on") or {}).get("max_oas_level", 3.0)):
        if ten_y_chg is None or ten_y_chg <= float((mood_rules.get("risk_on") or {}).get("max_ten_y_chg_20d", 0.15)):
            return "risk_on"
    return "tightening"


def load_indicator_snapshot() -> dict[str, Any]:
    config = _load_thresholds()
    files = (config.get("indicators") or {})
    snapshot: dict[str, Any] = {}
    for name, meta in files.items():
        filename = meta.get("file")
        if not filename:
            continue
        latest = _latest_value(PROCESSED_DIR / filename)
        if latest:
            snapshot[name] = latest
    return snapshot


def infer_regime_from_indicators(
  *,
  snapshot: dict[str, Any] | None = None,
  merge_paper_regime: bool = True,
) -> dict[str, Any]:
    """Return regime axes plus evidence from processed indicator CSVs."""
    config = _load_thresholds()
    thresholds = config.get("thresholds") or {}
    defaults = config.get("defaults") or {}
    files = config.get("indicators") or {}

    histories: dict[str, list[tuple[str, float]]] = {}
    for name, meta in files.items():
        filename = meta.get("file")
        if filename:
            histories[name] = _load_history(PROCESSED_DIR / filename)

    snap = snapshot or load_indicator_snapshot()
    sofr = (snap.get("SOFR") or {}).get("value")
    ten_y = (snap.get("10Y Treasury Yield") or {}).get("value")
    oas = (snap.get("High Yield OAS") or {}).get("value")

    sofr_chg = _delta(histories.get("SOFR", []), 20)
    ten_y_chg = _delta(histories.get("10Y Treasury Yield", []), 20)
    oas_chg = _delta(histories.get("High Yield OAS", []), 20)

    inferred = {
        "liquidity": _pick_liquidity(sofr, sofr_chg, thresholds),
        "rates": _pick_rates(ten_y_chg, thresholds),
        "credit": _pick_credit(oas, oas_chg, thresholds),
        "market_mood": _pick_market_mood(oas, ten_y_chg, thresholds),
        "regulation": str(defaults.get("regulation", "tightening")),
        "technology_cycle": str(defaults.get("technology_cycle", "scaling")),
    }

    evidence = []
    if sofr is not None:
        evidence.append(f"SOFR={sofr:.2f}")
    if ten_y is not None:
        evidence.append(f"10Y={ten_y:.2f}")
    if oas is not None:
        evidence.append(f"HY_OAS={oas:.2f}")
    if sofr_chg is not None:
        evidence.append(f"SOFR_20d_chg={sofr_chg:+.2f}")
    if ten_y_chg is not None:
        evidence.append(f"10Y_20d_chg={ten_y_chg:+.2f}")
    if oas_chg is not None:
        evidence.append(f"OAS_20d_chg={oas_chg:+.2f}")

    as_of = ""
    for item in snap.values():
        if item.get("date"):
            as_of = max(as_of, str(item["date"])) if as_of else str(item["date"])

    regime = dict(inferred)
    source = "indicators"
    if merge_paper_regime:
        paper_regime = load_current_regime()
        if paper_regime:
            for axis in ("regulation", "technology_cycle", "market_mood"):
                if axis in paper_regime:
                    regime[axis] = paper_regime[axis]
            source = "indicators+paper"

    if not snap:
        regime = default_regime()
        source = "default"
        evidence = ["indicator snapshot unavailable"]

    return {
        "regime": regime,
        "source": source,
        "as_of": as_of or datetime.now(UTC).date().isoformat(),
        "evidence": evidence,
        "indicator_snapshot": snap,
        "features": {
            "sofr_chg_20d": sofr_chg,
            "ten_y_chg_20d": ten_y_chg,
            "oas_chg_20d": oas_chg,
            "term_spread": (ten_y - (snap.get("Fed Funds Rate") or {}).get("value"))
            if ten_y is not None and (snap.get("Fed Funds Rate") or {}).get("value") is not None
            else None,
        },
    }
