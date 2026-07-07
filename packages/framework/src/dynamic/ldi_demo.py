"""LDI-focused diagnostic demo combining mismatch and criticality views (not production scoring)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.dynamic.criticality import build_criticality_state
from src.dynamic.mismatch import map_morphology_to_mismatch
from src.dynamic.registry import get_temporal_frame
from src.dynamic.transition import TransitionSignal

DEMO_DISCLAIMER = "diagnostic-only; not connected to final scoring"


def build_ldi_2022_dyn3_dyn4_diagnostics() -> dict[str, Any]:
    """Assemble a documented diagnostic payload for the LDI 2022 temporal case."""
    case_id = "ldi_2022"
    mismatch = map_morphology_to_mismatch("anchor_mismatch_plus_path_contraction", case_id=case_id)

    # No production TransitionSignal is wired for this replay path yet; values are explicitly synthetic.
    transition_signal = TransitionSignal(pressure_slope=0.35, mode_coupling_index=0.12)
    transition_block = {
        "source": "synthetic_demo",
        "note": "Demonstration TransitionSignal only; not a replay-derived production signal.",
        "transition_signal": transition_signal.to_serializable_dict(),
    }

    # Demonstration scalar inputs aligned with the singular detector threshold vocabulary (not a live replay extract).
    criticality = build_criticality_state(
        case_id=case_id,
        sigma_t=1.9,
        sigma_threshold=2.0,
        singular_flag=False,
        diagnostics=None,
        threshold_hit_time=None,
        transition_signal=transition_signal,
        state_trajectory=None,
        near_ratio=0.85,
        watch_ratio=0.45,
    )

    temporal = get_temporal_frame(case_id).to_serializable_dict()

    return {
        "case_id": case_id,
        "disclaimer": DEMO_DISCLAIMER,
        "temporal_frame": temporal,
        "mismatch_map": mismatch.to_serializable_dict(),
        "transition": transition_block,
        "criticality_state": criticality.to_serializable_dict(),
        "notes": {
            "morphology_label": "anchor_mismatch_plus_path_contraction",
            "criticality_inputs": "synthetic_demo_scalar_inputs",
        },
    }


def default_demo_output_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    out_dir = root / "outputs" / "dynamic_demo"
    return out_dir / "ldi_2022_dyn3_dyn4_diagnostics.json"


def write_ldi_2022_dyn3_dyn4_diagnostics(path: Path | None = None) -> Path:
    """Write the LDI diagnostics demo JSON to disk and return the path used."""
    target = path or default_demo_output_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_ldi_2022_dyn3_dyn4_diagnostics()
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
