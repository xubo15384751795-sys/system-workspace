"""Regression tests for judgment evidence lineage."""
from __future__ import annotations

from workbench.judgment.layer import _adapter_chain, _claim_envelopes


def _sample_chain(*, run_id: str, source_release_id: str) -> dict:
    return _adapter_chain(
        as_of="2026-08-21",
        run_id=run_id,
        source_release_id=source_release_id,
        source_id="hmm:regime_model",
        series_id="HMM:REGIME",
        value={"current": "volatile"},
        claim_text="HMM reports a regime state.",
        predicate="reports_regime_state",
        measurement_definition="hmm_regime_state",
        derivation="MODELED",
        evidence_role="SECONDARY",
    )


def test_adapter_evidence_uses_source_release_not_generation_run() -> None:
    chain = _sample_chain(
        run_id="daily_pipeline_20260822_185631_da9932",
        source_release_id="2026-08-22-r1",
    )

    assert chain["evidence"]["source"]["release_id"] == "2026-08-22-r1"
    assert chain["evidence"]["source"]["release_id"] != "daily_pipeline_20260822_185631_da9932"


def test_adapter_evidence_does_not_fallback_to_run_id() -> None:
    chain = _sample_chain(
        run_id="daily_pipeline_20260822_190726_b6c080",
        source_release_id="",
    )

    assert chain["evidence"]["source"]["release_id"] == ""


def test_auxiliary_chains_inherit_primary_release_id() -> None:
    run_id = "daily_pipeline_20260822_190726_b6c080"
    primary = _sample_chain(run_id=run_id, source_release_id="2026-08-22-r1")
    envelopes, _ = _claim_envelopes(
        {
            "as_of": "2026-08-21",
            "canonical_chain": primary,
            "provenance": {"run_id": run_id},
        },
        {"match_quality": {"label": "strong", "top_score": 0.73}},
        {"regime": {"current": "unknown"}},
        None,
        None,
    )

    assert envelopes[1].canonical_chain["evidence"]["source"]["release_id"] == "2026-08-22-r1"
    assert envelopes[2].canonical_chain["evidence"]["source"]["release_id"] == "2026-08-22-r1"
