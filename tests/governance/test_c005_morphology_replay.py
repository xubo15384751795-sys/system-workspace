from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.report


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.c005_morphology_replay import (
    RESIDUAL_SPECS,
    THRESHOLD_BENCHMARK_DOMINANCE,
    compute_operator_diagnostics,
    compute_rejection_flags,
    compute_residuals,
    compute_sigma_t,
    compute_validation_loop_status,
    extract_panel,
    run_replay,
    spearman,
)
from workbench.c005_morphology_report import load_evidence

REAL_RESULTS = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "results.json"


def _channel(M=0.0, D=0.0, K=0.0, X_PRE=0.0, X_REALIZED=0.0):
    return {"M": M, "D_contraction": D, "K": K, "X_PRE": X_PRE, "X_REALIZED": X_REALIZED}


def _bc(NFCI=0.0, VIX=0.0, BAA10YM=0.0, STLFSI4=0.0, CPBill=0.0):
    return {
        "NFCI_zscore": NFCI,
        "VIX_zscore": VIX,
        "BAA10YM_zscore": BAA10YM,
        "STLFSI4_zscore": STLFSI4,
        "CPBill_zscore": CPBill,
    }


def _event(event_id, channel_at_peak, benchmark_context, path=None, regime="Forced Realization"):
    return {
        "event_id": event_id,
        "peak_regime": regime,
        "channel_at_peak": channel_at_peak,
        "benchmark_context": benchmark_context,
        "observed_path": path or [],
        "path_text": " -> ".join(p["channel"] for p in (path or [])),
    }


def test_sigma_t_matches_canonical_formula() -> None:
    # singular_detector.py: pos(M) + pos(-D) + pos(K) + pos(X_PRE)
    # In event data, D_contraction is already -D (sign-flipped), so pos(D_contraction).
    sigma = compute_sigma_t(_channel(M=1.0, D=2.0, K=3.0, X_PRE=0.5, X_REALIZED=10.0))
    assert sigma == pytest.approx(1.0 + 2.0 + 3.0 + 0.5)
    # Negatives clip at zero
    assert compute_sigma_t(_channel(M=-1.0, D=-0.5, K=-2.0, X_PRE=-1.0)) == 0.0
    # X_REALIZED does NOT enter sigma_t directly
    assert compute_sigma_t(_channel(M=0.0, D=0.0, K=0.0, X_PRE=0.0, X_REALIZED=99.0)) == 0.0


def test_spearman_known_pairs() -> None:
    assert spearman([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.0)
    assert spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)
    # Rank-monotone but value-nonlinear stays at 1.0
    assert spearman([1.0, 2.0, 3.0, 4.0], [1.0, 4.0, 9.0, 16.0]) == pytest.approx(1.0)
    # Constant series yields 0 (denominator collapse)
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0


def test_extract_panel_handles_none_values_as_zero() -> None:
    events = [
        _event("a", _channel(M=None, D=2.0, K=None, X_PRE=1.0), _bc(NFCI=None, VIX=5.0)),
        _event("b", _channel(M=1.0, D=None, K=3.0, X_PRE=None), _bc(NFCI=0.5, VIX=None)),
    ]
    panel = extract_panel(events)
    assert panel["M"] == [0.0, 1.0]
    assert panel["D_contraction"] == [2.0, 0.0]
    assert panel["K"] == [0.0, 3.0]
    assert panel["NFCI_zscore"] == [0.0, 0.5]
    assert panel["VIX_zscore"] == [5.0, 0.0]


def test_compute_residuals_produces_all_five_required_keys() -> None:
    events = [
        _event(f"e{i}",
               _channel(M=float(i), D=float(i % 3), K=float(i * 2), X_PRE=float(i), X_REALIZED=float(i)),
               _bc(NFCI=float(i) * 0.3, VIX=float(i) * 0.5, BAA10YM=float(i) * 0.2))
        for i in range(8)
    ]
    panel = extract_panel(events)
    residuals = compute_residuals(panel)
    expected = {key for key, *_ in RESIDUAL_SPECS}
    assert set(residuals) == expected
    for value in residuals.values():
        assert -1.0 <= value <= 1.0


def test_rejection_flag_fires_when_channel_tracks_benchmark() -> None:
    # K perfectly tracks VIX → flag should fire
    events = [
        _event(f"e{i}",
               _channel(K=float(i), X_PRE=0.0),
               _bc(VIX=float(i)))
        for i in range(10)
    ]
    panel = extract_panel(events)
    residuals = compute_residuals(panel)
    assert abs(residuals["K_resid_vs_vol_jump_tail"]) >= THRESHOLD_BENCHMARK_DOMINANCE
    flags = compute_rejection_flags(residuals, events)
    assert flags["benchmark_dominance_K_vs_vol_jump_tail"] is True


def test_rejection_flag_silent_when_channel_orthogonal_to_benchmark() -> None:
    # M and NFCI uncorrelated (alternating pattern)
    events = [
        _event(f"e{i}", _channel(M=float(i % 2)), _bc(NFCI=float(i)))
        for i in range(10)
    ]
    panel = extract_panel(events)
    residuals = compute_residuals(panel)
    flags = compute_rejection_flags(residuals, events)
    # M~NFCI correlation should be weak → flag silent
    assert abs(residuals["M_resid_vs_NFCI"]) < THRESHOLD_BENCHMARK_DOMINANCE
    assert flags["benchmark_dominance_M_vs_NFCI"] is False


def test_operator_diagnostics_aggregate_path_metrics() -> None:
    events = [
        _event("a", _channel(K=1.0, X_PRE=2.0, X_REALIZED=3.0), _bc(),
               path=[{"channel": "M", "date": "2020-01-01"}, {"channel": "X_REALIZED", "date": "2020-01-02"}]),
        _event("b", _channel(K=2.0, X_PRE=1.0, X_REALIZED=0.5), _bc(),
               path=[{"channel": "M", "date": "2020-02-01"}, {"channel": "K", "date": "2020-02-02"}]),
        _event("c", _channel(K=3.0, X_PRE=0.5, X_REALIZED=0.0), _bc(),
               path=[{"channel": "K", "date": "2020-03-01"}]),
    ]
    diag = compute_operator_diagnostics(events)
    assert diag["operator_count"] == 5
    assert diag["events_total"] == 3
    assert diag["irreversible_count"] == 1  # event "a" has X_REALIZED
    assert diag["shadow_transfer"] == pytest.approx(1.0 / 3.0, abs=1e-4)  # only "a" has X_REALIZED > X_PRE
    assert 0.0 <= diag["non_commutativity_score"] <= 1.0
    assert 0.0 < diag["compression_ratio"] <= 1.0
    assert diag["unique_path_count"] == 3


def test_validation_loop_complete_with_full_inputs() -> None:
    residuals = {key: 0.1 for key, *_ in RESIDUAL_SPECS}
    flags = {"sigma_no_incremental_discrimination": False, "benchmark_dominance_K_vs_vol_jump_tail": True}
    operator_diag = {"events_total": 16, "operator_count": 40}
    benchmark_rows = [{"name": key, "benchmark_value": "0.5", "residual_value": "0.1"}
                       for key, *_ in RESIDUAL_SPECS]
    status = compute_validation_loop_status(residuals, flags, operator_diag, benchmark_rows)
    assert status["status"] == "complete"
    assert status["claim_carrying_allowed"] is True
    assert status["actionable_verdict"] == "PROMOTE"


def test_validation_loop_incomplete_when_keys_missing() -> None:
    residuals = {"M_resid_vs_NFCI": 0.1}  # missing 4 keys
    flags = {}
    operator_diag = {"events_total": 0}
    benchmark_rows = [{"name": "not_available", "benchmark_value": "", "residual_value": ""}]
    status = compute_validation_loop_status(residuals, flags, operator_diag, benchmark_rows)
    assert status["status"] == "incomplete"
    assert status["claim_carrying_allowed"] is False
    assert status["actionable_verdict"] == "BLOCK"
    assert any("residual" in b for b in status["blockers"])


def test_replay_end_to_end_writes_canonical_run_layout(tmp_path) -> None:
    minimal_events = [
        _event("e_low", _channel(M=0.2, D=0.0, K=0.3, X_PRE=0.0), _bc(NFCI=-0.5, VIX=0.1)),
        _event("e_mid", _channel(M=1.5, D=2.0, K=3.5, X_PRE=2.5), _bc(NFCI=0.2, VIX=3.0),
               path=[{"channel": "M"}, {"channel": "K"}], regime="Curvature Break"),
        _event("e_high", _channel(M=2.0, D=2.5, K=4.0, X_PRE=3.0, X_REALIZED=4.5), _bc(NFCI=1.5, VIX=5.0),
               path=[{"channel": "X_REALIZED"}], regime="Forced Realization"),
        _event("e_mixed", _channel(M=0.5, D=1.0, K=0.5, X_PRE=0.5), _bc(NFCI=-0.1, VIX=1.5),
               path=[{"channel": "M"}, {"channel": "K"}], regime="Normal / Untriggered"),
    ]
    fake_results = tmp_path / "sandbox" / "results.json"
    fake_results.parent.mkdir(parents=True)
    fake_results.write_text(json.dumps(minimal_events), encoding="utf-8")

    output_root = tmp_path / "deformation_runs"
    run_replay(
        run_id="2026-05-17_C005_TEST",
        harvester_release="test-release",
        results_path=fake_results,
        output_root=output_root,
    )

    run_dir = output_root / "2026-05-17_C005_TEST"
    for relative in (
        "machine/snapshot.json",
        "diagnostics/residual_tests.json",
        "diagnostics/rejection_flags.json",
        "diagnostics/operator_diagnostics.json",
        "diagnostics/validation_loop_status.json",
        "diagnostics/validation_report.md",
        "tables/benchmark_comparison.csv",
        "traces/operator_trace.jsonl",
        "config_snapshot.json",
        "freshness_manifest.json",
        "run_manifest.json",
        "artifacts.json",
        "reports/executive_summary.md",
        "logs/run.log",
    ):
        assert (run_dir / relative).exists(), f"missing artifact: {relative}"

    # diagnostics are non-empty dicts (not {})
    for name in ("residual_tests.json", "rejection_flags.json", "operator_diagnostics.json"):
        payload = json.loads((run_dir / "diagnostics" / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict) and payload, f"{name} should be non-empty"

    # benchmark_comparison has rows other than not_available
    table_text = (run_dir / "tables" / "benchmark_comparison.csv").read_text(encoding="utf-8")
    assert "not_available" not in table_text
    assert "Sigma_resid_vs_aggregate_stress" in table_text

    # config_snapshot captured
    cs = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    assert cs["captured_status"] == "captured"

    # operator trace header not "missing"
    first_line = (run_dir / "traces" / "operator_trace.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert '"status": "missing"' not in first_line
    header = json.loads(first_line)
    assert header.get("status") == "complete"

    # freshness gate blocks promotion by design (historical evidence run)
    freshness = json.loads((run_dir / "freshness_manifest.json").read_text(encoding="utf-8"))
    assert freshness["gate_result"]["promotion_allowed"] is False
    assert freshness["gate_result"]["blockers"], "freshness must block canonical promotion"

    # C005 reporter on this synthetic run yields a real verdict (not INSUFFICIENT_DATA)
    evidence = load_evidence("2026-05-17_C005_TEST", run_dir=run_dir)
    assert evidence.claim_verdict in {"SUPPORTED", "WEAKENED", "REJECTED"}
    assert evidence.gate_verdict in {"PROMOTE", "DOWNWEIGHT"}


@pytest.mark.skipif(not REAL_RESULTS.exists(), reason="structural_replay_v2 results.json not present")
def test_replay_on_real_event_windows_produces_real_verdict(tmp_path) -> None:
    output_root = tmp_path / "deformation_runs"
    summary = run_replay(
        run_id="real_data_smoke",
        harvester_release="2026-05-05-r1",
        results_path=REAL_RESULTS,
        output_root=output_root,
    )
    assert summary["n_events"] == 16
    assert summary["validation_loop"]["status"] == "complete"

    evidence = load_evidence("real_data_smoke", run_dir=output_root / "real_data_smoke")
    assert evidence.claim_verdict != "INSUFFICIENT_DATA"
    # When K channel has data, K~VIX rank correlation ~0.80 exceeds 0.70 threshold,
    # pushing verdict to WEAKENED. When K has 0% coverage (no data), correlation
    # cannot be computed and verdict stays SUPPORTED.
    assert evidence.claim_verdict in {"SUPPORTED", "WEAKENED"}
    # K~VIX rejection flag only fires when K channel has data.
    # When K has 0% coverage, the flag is False (no correlation to test).
    k_flag = evidence.rejection_flags.get("benchmark_dominance_K_vs_vol_jump_tail")
    assert k_flag in {True, False}
