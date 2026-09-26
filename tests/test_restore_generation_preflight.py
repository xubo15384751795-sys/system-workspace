"""Step 5E must separate structural fidelity from production authority."""
from __future__ import annotations

from tools.audit.restore_generation_preflight import build_report


def test_restore_preflight_accepts_diagnostic_structural_target_without_production_authority() -> None:
    report = build_report()

    assert report["status"] == "PASS_WITH_PRODUCTION_RESTORE_DEFERRED"
    assert report["structural_restore_eligible"] is True
    assert report["production_restore_eligible"] is False
    assert report["eligible_targets"] == []
    assert report["structural_restore"]["status"] == "PASS"
    assert isinstance(report["structural_restore"]["target"], str)
    assert report["structural_restore"]["target"].startswith("daily_pipeline_")
    assert report["production_restore"]["status"] == "BLOCKED_NO_ELIGIBLE_PRODUCTION_TARGET"
    assert report["baseline_target"]["production_restore_eligible"] is False
    assert report["restore"]["production_output_touched"] is False
    assert report["gate"]["reader_graph"] == "PASS"
    assert report["gate"]["production_authority_restore"] == "DEFERRED_STEP6"

    drill = report["structural_restore"]["fidelity_drill"]
    assert drill["status"] == "PASS"
    assert drill["restored_authority"] == "DIAGNOSTIC_ONLY"
    assert drill["restored_claim_ceiling"] == "structural_diagnostic"
    assert drill["restored_allows_decision_consumers"] is False
    assert drill["production_authority_untouched"] is True
    assert drill["production_output_touched"] is False
    assert all(check["status"] == "PASS" for check in drill["checks"].values())
