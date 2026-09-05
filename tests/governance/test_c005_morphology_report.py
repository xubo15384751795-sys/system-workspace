from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.report


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from scripts.archive.c005_morphology_report import (  # noqa: E402
    evidence_payload,
    load_evidence,
    render_report,
    write_report,
)
from system_runtime.canonical_ids import validate_claim  # noqa: E402


def test_c005_report_blocks_empty_validation_loop(tmp_path) -> None:
    run_dir = tmp_path / "run_a"
    (run_dir / "diagnostics").mkdir(parents=True)
    (run_dir / "tables").mkdir()
    for name in ("rejection_flags.json", "residual_tests.json", "operator_diagnostics.json"):
        (run_dir / "diagnostics" / name).write_text("{}\n", encoding="utf-8")
    (run_dir / "tables" / "benchmark_comparison.csv").write_text(
        "benchmark_value,name,residual_value\n,not_available,\n",
        encoding="utf-8",
    )

    evidence = load_evidence("run_a", run_dir=run_dir)
    report = render_report(evidence)

    assert evidence.claim_verdict == "INSUFFICIENT_DATA"
    assert "- Verdict: BLOCK" in report
    assert "benchmark_comparison contains not_available" in report
    assert "operator_diagnostics is empty" in report
    payload = evidence_payload(evidence)
    assert payload["claim_id"] == "C005"
    assert payload["claim_carrying_allowed"] is False
    assert payload["canonical_claim"]["status"] == "INSUFFICIENT_DATA"
    assert payload["canonical_claim"]["provenance"]["claim_ceiling"] == "diagnostic_watch_only"
    validate_claim(payload["canonical_claim"])


def test_c005_report_supports_populated_validation_loop(tmp_path) -> None:
    run_dir = tmp_path / "run_b"
    (run_dir / "diagnostics").mkdir(parents=True)
    (run_dir / "tables").mkdir()
    (run_dir / "diagnostics" / "rejection_flags.json").write_text(
        json.dumps({"sigma_no_incremental_discrimination": False}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "diagnostics" / "residual_tests.json").write_text(
        json.dumps(
            {
                "Sigma_resid_vs_aggregate_stress": 0.12,
                "M_resid_vs_NFCI": 0.1,
                "D_resid_vs_NFCI": 0.2,
                "K_resid_vs_vol_jump_tail": 0.3,
                "X_resid_vs_leverage": 0.4,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "diagnostics" / "operator_diagnostics.json").write_text(
        json.dumps({"operator_count": 3, "non_commutativity_score": 0.4}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "tables" / "benchmark_comparison.csv").write_text(
        "name,benchmark_value,residual_value\nNFCI,1.2,0.4\n",
        encoding="utf-8",
    )

    evidence = load_evidence("run_b", run_dir=run_dir)
    report = render_report(evidence)

    assert evidence.claim_verdict == "SUPPORTED"
    assert "- Verdict: PROMOTE" in report
    assert "global benchmark outperformance" in report

    report_path = write_report(evidence, output_dir=tmp_path / "reports")
    machine_path = report_path.with_suffix(".json")
    payload = json.loads(machine_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "claim_evidence.c005_morphology.v1"
    assert payload["claim_carrying_allowed"] is True
    assert payload["canonical_claim"]["status"] == "WATCH"
    assert payload["canonical_claim"]["evidence_ids"] == []
    validate_claim(payload["canonical_claim"])
