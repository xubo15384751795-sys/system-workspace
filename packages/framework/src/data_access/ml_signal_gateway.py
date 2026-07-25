"""Thin read-only gateway for ML signal files.

Deformation reads supplementary ML context through this module.
Hard constraints:
  - Enabled only when config.ml_signals.enabled == true.
  - Falls back to None gracefully; caller must tolerate absent context.
  - Never raises on missing/stale files — logs a warning and returns None.
  - ML context must NEVER feed back into M/D/K/X channels or proxy weights.
  - Gateway checks source_release freshness: if current Harvester release
    differs from signal's source_release, signal is marked stale and
    ml_context.regime_valid / factor_valid are False.
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SYSTEM_ROOT = WorkspacePaths.discover().root
_DEFAULT_ML_SIGNALS_ROOT = _SYSTEM_ROOT / "Output" / "ml_signals"


# ---------------------------------------------------------------------------
# Public data structure — supplementary context only
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MLSignalContext:
    """Supplementary read-only context from the Workbench ML layer.

    This object is attached to RunContext.config['ml_context'] and is
    available to pipeline stages as optional context — never as a primary
    input to M/D/K/X calculations.
    """
    source_release: str
    regime_valid: bool
    regime_current: str | None        # "compression" | "volatile" | "crisis"
    regime_probability: float | None  # probability of current state
    regime_state_probs: dict[str, float] = field(default_factory=dict)
    regime_tft_valid: bool = False
    regime_tft_current: str | None = None
    regime_tft_state_probs: dict[str, float] = field(default_factory=dict)
    factor_valid: bool = False
    factors: list[dict[str, Any]] = field(default_factory=list)
    loaded_from: str = ""
    stale_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_release": self.source_release,
            "regime_valid": self.regime_valid,
            "regime_current": self.regime_current,
            "regime_probability": self.regime_probability,
            "regime_state_probs": self.regime_state_probs,
            "regime_tft_valid": self.regime_tft_valid,
            "regime_tft_current": self.regime_tft_current,
            "regime_tft_state_probs": self.regime_tft_state_probs,
            "factor_valid": self.factor_valid,
            "factors": self.factors,
            "loaded_from": self.loaded_from,
            "stale_reason": self.stale_reason,
        }


# ---------------------------------------------------------------------------
# Freshness check
# ---------------------------------------------------------------------------

def _check_freshness(payload: dict[str, Any], current_release: str | None) -> tuple[bool, str]:
    """Return (is_valid, stale_reason).

    A signal is stale if:
    - freshness_gate.signal_valid is False, or
    - current_release is known and differs from source_release.
    """
    gate = payload.get("freshness_gate", {})
    if not gate.get("signal_valid", True):
        return False, "freshness_gate.signal_valid is False"
    signal_release = str(payload.get("source_release", ""))
    if current_release and signal_release != current_release:
        return False, (
            f"source_release mismatch: signal={signal_release!r} "
            f"current={current_release!r}"
        )
    return True, ""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _resolve_current_release(config: dict[str, Any]) -> str | None:
    hcfg = config.get("harvester") or {}
    release = hcfg.get("release")
    if release and str(release).lower() != "latest":
        return str(release)
    return None


def _read_signal(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("ml_signal_gateway: failed to read %s: %s", path, exc)
        return None


def load_ml_signals(config: dict[str, Any]) -> MLSignalContext | None:
    """Load ML signals from Output/ml_signals/latest/ into an MLSignalContext.

    Returns None when:
    - ml_signals.enabled is False (or absent)
    - signal directory does not exist
    - signal files are missing or malformed

    The caller must handle None gracefully.
    """
    ml_cfg = config.get("ml_signals") or {}
    if not ml_cfg.get("enabled", False):
        return None

    signals_root_str = ml_cfg.get("signals_root") or str(_DEFAULT_ML_SIGNALS_ROOT)
    signals_root = Path(signals_root_str).expanduser()
    latest_dir = signals_root / "latest"

    if not latest_dir.exists():
        log.debug("ml_signal_gateway: latest dir absent at %s", latest_dir)
        return None

    current_release = _resolve_current_release(config)

    # --- Regime ---
    regime_payload = _read_signal(latest_dir / "regime_hmm.json")
    if regime_payload is None:
        regime_payload = _read_signal(latest_dir / "regime.json")
    regime_valid = False
    regime_current = None
    regime_prob = None
    regime_state_probs: dict[str, float] = {}
    stale_reason = ""
    source_release = ""

    if regime_payload:
        source_release = str(regime_payload.get("source_release", ""))
        regime_valid, stale_reason = _check_freshness(regime_payload, current_release)
        if regime_valid:
            reg = regime_payload.get("regime", {})
            regime_current = reg.get("current")
            regime_prob = reg.get("probability")
            regime_state_probs = reg.get("state_probs", {})
        else:
            log.warning("ml_signal_gateway: regime signal stale — %s", stale_reason)

    # --- Parallel TFT / forecaster regime (optional) ---
    tft_payload = _read_signal(latest_dir / "regime_tft.json")
    regime_tft_valid = False
    regime_tft_current = None
    regime_tft_state_probs: dict[str, float] = {}
    if tft_payload:
        if not source_release:
            source_release = str(tft_payload.get("source_release", ""))
        tft_ok, tft_reason = _check_freshness(tft_payload, current_release)
        if tft_ok:
            regime_tft_valid = True
            treg = tft_payload.get("regime", {})
            regime_tft_current = treg.get("current")
            regime_tft_state_probs = treg.get("state_probs", {})
        else:
            log.warning("ml_signal_gateway: regime_tft signal stale — %s", tft_reason)

    # --- Factors ---
    factor_payload = _read_signal(latest_dir / "factor.json")
    factor_valid = False
    factors: list[dict[str, Any]] = []

    if factor_payload:
        if not source_release:
            source_release = str(factor_payload.get("source_release", ""))
        fv, freason = _check_freshness(factor_payload, current_release)
        if fv:
            factor_valid = True
            factors = factor_payload.get("factors", [])
        else:
            log.warning("ml_signal_gateway: factor signal stale — %s", freason)
            if not stale_reason:
                stale_reason = freason

    ctx = MLSignalContext(
        source_release=source_release,
        regime_valid=regime_valid,
        regime_current=regime_current,
        regime_probability=regime_prob,
        regime_state_probs=regime_state_probs,
        regime_tft_valid=regime_tft_valid,
        regime_tft_current=regime_tft_current,
        regime_tft_state_probs=regime_tft_state_probs,
        factor_valid=factor_valid,
        factors=factors,
        loaded_from=str(latest_dir),
        stale_reason=stale_reason,
    )
    log.debug(
        "ml_signal_gateway: loaded context release=%r regime_valid=%s factor_valid=%s",
        source_release, regime_valid, factor_valid,
    )
    return ctx
