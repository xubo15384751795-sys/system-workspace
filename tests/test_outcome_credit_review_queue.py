from __future__ import annotations

from scripts import run_supervisor_check
from scripts.run_supervisor_check import _outcome_credit_review_items


def test_outcome_credit_only_reorders_human_review() -> None:
    items = _outcome_credit_review_items({
        "status": "ELIGIBLE_FOR_REVIEW_PRIORITY",
        "eligible_to_affect_review_priority": True,
        "credit_can_grant_authority": False,
        "review_queue": [{
            "rank": 1,
            "node_id": "k_gate",
            "samples": 20,
            "mean_loss_reduction": -0.2,
            "review_action": "investigate_drag",
        }],
    })

    assert items == [{
        "source": "outcome_credit",
        "id": "k_gate",
        "severity": "medium",
        "action": "rank=1; investigate_drag; n=20; mean_loss_reduction=-0.2",
    }]
    assert all("authority" not in item and "promote" not in item for item in items)


def test_authority_capable_credit_is_rejected_from_queue() -> None:
    items = _outcome_credit_review_items({
        "status": "ELIGIBLE_FOR_REVIEW_PRIORITY",
        "eligible_to_affect_review_priority": True,
        "credit_can_grant_authority": True,
        "review_queue": [{"node_id": "k_gate"}],
    })

    assert items == []


def test_supervisor_rejects_policy_that_lets_credit_affect_authority(
    tmp_path, monkeypatch
) -> None:
    policy = tmp_path / "incentive_policy.yaml"
    policy.write_text(
        """
authority_boundary:
  credit_never_grants_authority: true
  governance_can_grant_core_authority: false
  canonical_authority_requires_runtime_wiring: true
outcome_credit:
  enabled: true
  affects_review_priority_only: true
  can_affect_authority: true
credit_sources: {}
review_outcomes: []
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_supervisor_check, "INCENTIVE_POLICY_PATH", policy)

    result = run_supervisor_check._check_incentive_overreach()

    assert result["status"] == "OVERREACH"
    assert "outcome_credit cannot affect authority" in result["issues"]
