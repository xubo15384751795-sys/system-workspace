#!/usr/bin/env python3
"""Emit structured LDI 2022 dynamic outputs (JSON + Markdown) from synthetic demo inputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.dynamic.case_pattern_registry import get_known_failure_modes, get_recommended_signal_cards
from src.dynamic.criticality import build_criticality_state
from src.dynamic.mismatch import MismatchMap, build_mismatch_profile_by_type, map_morphology_to_mismatch
from src.dynamic.provider_integrity import ProviderCheck, ProviderIntegrityPanel
from src.dynamic.registry import get_temporal_frame
from src.dynamic.renderers.markdown_renderer import render_research_note
from src.dynamic.research_note import ResearchNote
from src.dynamic.signal_card import EvidenceItem, SignalCard
from src.dynamic.transition import TransitionSignal

CASE_ID = "ldi_2022"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _build_note() -> ResearchNote:
    temporal = get_temporal_frame(CASE_ID)

    morph = map_morphology_to_mismatch("anchor_mismatch_plus_path_contraction", case_id=CASE_ID)
    tau_profile = build_mismatch_profile_by_type(
        "p_tau",
        evidence=["synthetic_ldi_output_script", "case_pattern=policy_intervention_rewrite"],
    )
    mismatch = MismatchMap(
        case_id=CASE_ID,
        profiles=list(morph.profiles) + [tau_profile],
        summary=(
            "Synthetic LDI bundle: morphology adapter profile plus an explicit policy–latency (P–τ) "
            "diagnostic for the intervention window."
        ),
        source="synthetic_ldi_output_script",
    )

    transition_signal = TransitionSignal(pressure_slope=0.35, mode_coupling_index=0.12)
    criticality = build_criticality_state(
        case_id=CASE_ID,
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

    provider_panel = ProviderIntegrityPanel(
        case_id=CASE_ID,
        overall_status="medium",
        checks=[
            ProviderCheck(
                series="UK_30Y_GILT_YIELD",
                provider="Vendor_EndOfDay",
                status="warn",
                issue="End-of-day batch lagged vs exchange prints during the shock window.",
                frequency="daily",
                staleness_days=2,
                provider_disagreement=0.07,
            ),
            ProviderCheck(
                series="UK_GILT_FUTURES_IMPLIED",
                provider="Exchange",
                status="pass",
                issue=None,
                frequency="intraday",
                staleness_days=0,
                provider_disagreement=None,
            ),
        ],
        affected_signal_cards=[
            "ldi_2022_term_structure_deformation",
            "ldi_2022_observation_integrity_warning",
        ],
        interpretation=(
            "Long-end cash yields are directionally reliable but can print stale versus futures-implied "
            "paths intraday; cross-check level changes before inferring clearing speed."
        ),
    )

    cards = [
        SignalCard(
            signal_id="ldi_2022_term_structure_deformation",
            title="Long-end gilt discontinuity with collateral feedback",
            status="warning",
            severity="high",
            confidence="medium",
            time_window="2022-09-23 to 2022-10-14",
            phase="shock",
            main_trigger=[
                "Pension-risk transfer hedging flow into an illiquid long end",
                "Convexity demand spikes as DV01 gaps widen",
            ],
            affected_dimensions=["A", "L", "τ"],
            path_interpretation=(
                "The feasible liquidation frontier shifted faster than liability-driven portfolios could "
                "re-bucket hedges, so price discontinuity showed up as a path problem—not a slow drift in "
                "anchor beliefs."
            ),
            evidence=[
                EvidenceItem(
                    source="Synthetic/BOE_GILT_MARKET",
                    metric="uk_30y_yield_change_bp",
                    value=-118.0,
                    timestamp="2022-09-28",
                    reliability="medium",
                )
            ],
            user_action=[
                "Separate cash vs futures paths when inferring clearing speed",
                "Stress collateral call ladders against long-end liquidity gaps",
            ],
        ),
        SignalCard(
            signal_id="ldi_2022_policy_intervention_rewrite",
            title="Emergency purchase facility as explicit path rewrite",
            status="watch",
            severity="medium",
            confidence="high",
            time_window="2022-09-28 to 2022-10-14",
            phase="intervention",
            main_trigger=[
                "Market-function objective dominates price-discovery shortfall",
                "Dealer balance sheet capacity binds in the long end",
            ],
            affected_dimensions=["P", "τ", "L"],
            path_interpretation=(
                "Policy intervened on market-function grounds, which changes the admissible price path "
                "without instantly restoring private-sector risk absorption; interpret stabilization as "
                "a rewritten constraint set, not a return to the pre-shock path menu."
            ),
            evidence=[
                EvidenceItem(
                    source="Synthetic/NEWS_DIGEST",
                    metric="intervention_announced",
                    value="true",
                    timestamp="2022-09-28",
                    reliability="low",
                )
            ],
            user_action=[
                "Tag post-intervention windows as regime-shifted for risk models",
                "Track unwind conditions rather than assuming mean reversion to pre-shock volatility",
            ],
        ),
    ]

    disclaimer = "diagnostic-only; not connected to final scoring"
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return ResearchNote(
        note_id="ldi_2022_research_note_synthetic",
        title="UK LDI 2022 — synthetic structured research note",
        generated_at=generated_at,
        executive_summary=(
            "Synthetic end-to-end bundle for the dynamic output spine: two signal cards, a merged mismatch "
            "view (morphology + P–τ), a near-threshold criticality read, and a provider integrity panel "
            "flagging end-of-day staleness against intraday paths."
        ),
        signal_cards=cards,
        temporal_frame=temporal,
        mismatch_map=mismatch,
        criticality=criticality,
        provider_integrity=provider_panel,
        scenario_paths=[
            "Backstop holds while dealers recapitalize → gradual long-end volatility decay",
            "Backstop exits into still-thin liquidity → renewed convexity shocks",
        ],
        limitations=[
            "No live FRED/BoE feed is attached in this synthetic path.",
            "Signal cards use illustrative metrics, not replay-extracted observations.",
            "Known failure modes from case pattern library: "
            + "; ".join(get_known_failure_modes(CASE_ID)),
        ],
        disclaimer=disclaimer,
    )


def main() -> None:
    root = _repo_root()
    out_json = root / "outputs" / "dynamic" / "json"
    out_md = root / "outputs" / "dynamic" / "markdown"
    out_json.mkdir(parents=True, exist_ok=True)
    out_md.mkdir(parents=True, exist_ok=True)

    note = _build_note()

    signal_bundle = {
        "case_id": CASE_ID,
        "pattern_recommended_signal_cards": get_recommended_signal_cards(CASE_ID),
        "temporal_frame": note.temporal_frame.to_serializable_dict(),
        "signal_cards": [c.to_serializable_dict() for c in note.signal_cards],
    }
    (out_json / "ldi_signal_cards.json").write_text(
        json.dumps(signal_bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_json / "ldi_mismatch_map.json").write_text(
        json.dumps(note.mismatch_map.to_serializable_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_json / "ldi_criticality.json").write_text(
        json.dumps(note.criticality.to_serializable_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_json / "ldi_provider_integrity.json").write_text(
        json.dumps(note.provider_integrity.to_serializable_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_md / "ldi_research_note.md").write_text(render_research_note(note), encoding="utf-8")
    print(f"Wrote JSON under {out_json} and Markdown under {out_md}")


if __name__ == "__main__":
    main()
