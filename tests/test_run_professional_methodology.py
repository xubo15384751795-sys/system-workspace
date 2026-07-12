from __future__ import annotations

import pandas as pd

from scripts.run_professional_methodology import promotion_verdict, public_baselines


def _result(auc: float, pr: float, brier: float, low: float) -> dict:
    return {
        "metrics": {"roc_auc": auc, "pr_auc": pr, "brier": brier},
        "stationary_bootstrap_auc": {"low": low},
    }


def test_promotion_requires_all_evidence_rules() -> None:
    evaluation = {
        "old": _result(0.55, 0.20, 0.15, 0.49),
        "new": _result(0.60, 0.25, 0.14, 0.52),
    }
    assert promotion_verdict(evaluation, "old", "new")["status"] == "PROMOTION_ELIGIBLE"
    evaluation["new"]["metrics"]["brier"] = 0.16
    assert promotion_verdict(evaluation, "old", "new")["status"] == "SHADOW_ONLY"


def test_promotion_requires_incremental_information_not_to_degrade() -> None:
    evaluation = {
        "old": _result(0.55, 0.20, 0.15, 0.49),
        "new": _result(0.60, 0.25, 0.14, 0.52),
    }
    incremental = {
        "status": "ok",
        "delta": {"roc_auc": 0.01, "pr_auc": -0.001, "brier_improvement": 0.001},
    }
    verdict = promotion_verdict(evaluation, "old", "new", incremental=incremental)
    assert verdict["status"] == "SHADOW_ONLY"
    assert not verdict["rules"]["incremental_information_not_worse"]


def test_public_baselines_only_use_available_series() -> None:
    frame = pd.DataFrame({"FRED:NFCI": range(200), "unrelated": range(200)})
    result = public_baselines(frame)
    assert list(result.columns) == ["nfci"]
