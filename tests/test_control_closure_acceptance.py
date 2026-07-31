"""Control-closure acceptance: 10 incident-injection scenarios (spec §VI).

Each scenario injects a fault and asserts the three-part contract:
  1. DETECTED   - the failure is surfaced
  2. BLOCKED    - downstream consumers are blocked, not silently run
  3. UNCHANGED  - authoritative state is not modified

These are the final acceptance tests. They compose the Phase A/B/C/D machinery
into end-to-end incident simulations. P0-1 (merge gate) is included here as a
scenario (it was deferred from Phase A; the merge-gate job + verify --merge
landed in Phase C3/C4).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))


def _file_hash(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None


# ── Scenario 1: required test failure -> merge gate rejects ──────────────


class TestScenario1MergeGate:
    """A failing required test must make merge-gate FAIL."""

    def test_failing_test_step_recorded_as_failure(self):
        from verify_merge import _run_step

        # A pytest invocation that always fails.
        r = _run_step("failing_test", [sys.executable, "-m", "pytest",
                                        "--co", "-q", "tests/test_phase_a_incident_regression.py",
                                        "-k", "nonexistent_test_name"])
        # --co (collect-only) with -k nonexistent collects 0 -> pytest exits 5.
        assert not r["passed"], "a failing required test must fail the step"
        assert r["returncode"] != 0


# ── Scenario 2: K builder throws -> BUILD_FAILED, channel degrades ───────


class TestScenario2PressureBuilderFailure:
    def test_k_builder_exception_records_build_failed(self):
        from _proxy_state import ProxyState, classify_build_result, state_of

        r = classify_build_result("K_butterfly", None, build_error="ZeroDivisionError")
        assert state_of(r) == ProxyState.BUILD_FAILED
        assert r.build_error is not None

    def test_pressure_builder_failure_blocks_descendants_via_executor(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_daily_run_executor_s2", ROOT / "scripts" / "_daily_run_executor.py")
        exec_mod = importlib.util.module_from_spec(spec)
        sys.modules["_daily_run_executor_s2"] = exec_mod
        spec.loader.exec_module(exec_mod)

        executed: list[str] = []

        def fake_execute_step(step_id, ctx):
            executed.append(step_id)
            if step_id == "neutral_pressure_measurement":
                return {"step": step_id, "status": "failed", "returncode": 1, "duration_s": 1.0}
            return {"step": step_id, "status": "success", "returncode": 0, "duration_s": 0.1}

        args = SimpleNamespace(force_weekly=True, skip_harvester=False, skip_etf=False)
        ctx = exec_mod.DailyRunContext(
            args=args, start_time=datetime(2026, 7, 17), total_steps=100,
            run_step_fn=lambda *a, **k: {"status": "success"},
            record_fn=lambda *a, **k: None,
            benchmark_panel_path=ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet",
            run_id="s2_bundle",
        )
        with patch.object(exec_mod, "execute_step", side_effect=fake_execute_step):
            results = exec_mod.execute_daily_sequence(ctx)
        status = {r["step"]: r.get("status") for r in results}
        assert status["neutral_pressure_measurement"] == "failed"
        assert status["judgment_layer"] == "blocked_upstream"
        assert "judgment_layer" not in executed


# ── Scenario 3: OFR/CISS stale -> admission blocks paper_portfolio ───────


class TestScenario3OfrCissStale:
    def test_admission_blocks_on_stale_public_components(self, tmp_path, monkeypatch):
        from _admission_gate import admit_for_consumption

        release = tmp_path / "release"
        d = release / "data"
        d.mkdir(parents=True)
        rows = [
            {"date": pd.Timestamp("2026-07-16"), "series_id": "VIXCLS",
             "source_id": "fred", "source_series_id": "VIXCLS", "value": 20.0,
             "unit": "index", "frequency": "daily",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
            # OFR 73 days stale.
            {"date": pd.Timestamp("2026-05-05"), "series_id": "OFR_FSI",
             "source_id": "ofr", "source_series_id": "OFR_FSI", "value": 0.3,
             "unit": "index", "frequency": "daily",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
        ]
        pd.DataFrame(rows).to_parquet(d / "benchmark_panel.parquet")
        (release / "catalog.json").write_text(json.dumps({
            "bundle_id": release.name, "created_at": "2026-07-17T00:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "data/benchmark_panel.parquet"}],
        }), encoding="utf-8")
        monkeypatch.setattr("freshness_validator.check_content_freshness",
                            lambda **kw: {"name": kw["name"], "status": "FRESH"})
        # Assert the general staleness rule, independent of whichever sources
        # configs/freshness_policy.yaml currently declares environmentally
        # blocked (a declared source degrades instead of blocking; see
        # tests/test_admission_gate.py::TestEnvironmentallyBlockedSources).
        monkeypatch.setattr("_admission_gate._environmentally_blocked", dict)

        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                          now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is False
        assert any("OFR_FSI" in b for b in decision.blockers)


# ── Scenario 4: component missing -> P_public not silently renormalized ──


class TestScenario4ComponentMissing:
    def test_p_public_fails_closed_on_missing_component(self):
        from public_residual_stress import public_level_probability

        idx = pd.date_range("2026-04-01", periods=100, freq="B")
        public = pd.DataFrame({
            "ofr_fsi": [np.nan] * 100,
            "nfci": np.linspace(0.2, 0.8, 100),
            "ecb_ciss": [np.nan] * 100,
        }, index=idx)
        p = public_level_probability(public, min_periods=50)
        assert p.notna().sum() == 0, "missing components must not silently renormalize"


# ── Scenario 5: old artifact injection -> bridge rejects ─────────────────


class TestScenario5ArchivedRuntimeInjection:
    def test_archived_bridge_rejects_execution_without_writing(self, tmp_path, monkeypatch):
        import bridge_replay_to_current as bridge

        replay = tmp_path / "replay"
        current = tmp_path / "current"
        replay.mkdir(parents=True)
        current.mkdir(parents=True)
        monkeypatch.setattr(bridge, "REPLAY_DIR", replay)
        monkeypatch.setattr(bridge, "CURRENT", current)
        (replay / "sigma_vector.json").write_text(json.dumps({
            "run_id": "yesterday", "sigma_vector": {"M": 0.1},
        }), encoding="utf-8")
        monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "today")

        before = _file_hash(current / "framework_output.json")
        with pytest.raises(SystemExit) as exc:
            bridge.main()
        assert "ARCHIVED_FALSIFIED" in str(exc.value)
        after = _file_hash(current / "framework_output.json")
        assert before == after, "framework_output must not be written on rejection"


# ── Scenario 6: wrong latest pointer -> consumer rejects ─────────────────


class TestScenario6WrongLatestPointer:
    def test_release_not_finalized_rejected(self, tmp_path):
        from _release_boundary import ReleaseNotFinalizedError, verify_release_finalized

        release = tmp_path / "release"
        release.mkdir()
        (release / "catalog.json").write_text(json.dumps({"release_id": "r1"}))
        # No .finalized marker -> consumer must reject.
        with pytest.raises(ReleaseNotFinalizedError):
            verify_release_finalized(release)


# ── Scenario 7: shadow failure -> no valid NAV, no promotion sample ──────


class TestScenario7ShadowFailure:
    def test_hold_degraded_excluded_from_promotion(self, tmp_path, monkeypatch):

        from scripts import _runtime_io as rio
        from scripts.strategy_lab import shadow_card as sc

        monkeypatch.setattr(sc, "OUTPUT_DIR", tmp_path / "strategy_lab")
        monkeypatch.setattr(rio, "ROOT", tmp_path)
        pos_dir = tmp_path / "Output" / "position"
        pos_dir.mkdir(parents=True)
        degraded_date = pd.Timestamp.now(tz=None).date().isoformat()
        (pos_dir / "paper_portfolio_nav.jsonl").write_text(
            json.dumps({"as_of": degraded_date, "sizing_mode": "HOLD_DEGRADED",
                        "sample_validity": "DEGRADED"}) + "\n", encoding="utf-8")
        card_dir = tmp_path / "strategy_lab" / "shadow_cards"
        card_dir.mkdir(parents=True)
        (card_dir / f"{degraded_date}.json").write_text(json.dumps({
            "as_of_date": degraded_date,
            "outcome_backfill": {"forward_20d_return": 0.01, "evaluation": "correct"},
        }), encoding="utf-8")

        summary = sc.build_90d_outcomes_summary(days=90)
        assert summary["cards_total"] == 0, "degraded sample must not count"
        assert summary["excluded_degraded_samples"] == 1
        assert summary["promotion_indicators"]["min_samples_met"] is False


# ── Scenario 8: partial pipeline failure -> descendants BLOCKED_UPSTREAM ─


class TestScenario8PartialPipelineFailure:
    def test_all_descendants_show_blocked_upstream(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_daily_run_executor_s8", ROOT / "scripts" / "_daily_run_executor.py")
        exec_mod = importlib.util.module_from_spec(spec)
        sys.modules["_daily_run_executor_s8"] = exec_mod
        spec.loader.exec_module(exec_mod)

        def fake_execute_step(step_id, ctx):
            if step_id == "harvester":
                return {"step": step_id, "status": "failed", "returncode": 1, "duration_s": 1.0}
            return {"step": step_id, "status": "success", "returncode": 0, "duration_s": 0.1}

        args = SimpleNamespace(force_weekly=True, skip_harvester=False, skip_etf=False)
        ctx = exec_mod.DailyRunContext(
            args=args, start_time=datetime(2026, 7, 17), total_steps=100,
            run_step_fn=lambda *a, **k: {"status": "success"},
            record_fn=lambda *a, **k: None,
            benchmark_panel_path=ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet",
            run_id="s8_bundle",
        )
        with patch.object(exec_mod, "execute_step", side_effect=fake_execute_step):
            results = exec_mod.execute_daily_sequence(ctx)
        status = {r["step"]: r.get("status") for r in results}
        # harvester is block_core_judgment -> the neutral pressure path must block.
        assert status["harvester"] == "failed"
        assert status["neutral_pressure_measurement"] == "blocked_upstream"


# ── Scenario 9: recovery requires full new run ───────────────────────────


class TestScenario9Recovery:
    def test_stale_manifest_invalid_after_sha_change(self, tmp_path, monkeypatch):
        from verify_merge import is_manifest_valid_for_sha

        # Write a manifest bound to a fake SHA, then check against a different SHA.
        manifest_dir = tmp_path / "verification"
        manifest_dir.mkdir()
        (manifest_dir / "merge_gate_manifest.json").write_text(json.dumps({
            "commit": "old_sha", "verdict": "PASS",
        }), encoding="utf-8")
        monkeypatch.setattr("verify_merge.MANIFEST_PATH", manifest_dir / "merge_gate_manifest.json")
        ok, reason = is_manifest_valid_for_sha("new_sha")
        assert ok is False
        assert "stale" in reason


# ── Scenario 10: end-to-end traceability ─────────────────────────────────


class TestScenario10Traceability:
    def test_provenance_chain_from_producer_to_consumer(self, tmp_path, monkeypatch):
        """An artifact carries provenance (run_id, producer_step); the consumer
        (bridge) verifies run_id match. This is the traceability chain."""
        from _artifact_provenance import build_provenance, verify_provenance

        monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "trace_bundle")
        prov = build_provenance(producer_step="structural_replay",
                                source_release_id="20260717")
        artifact = tmp_path / "sigma_vector.json"
        artifact.write_text(json.dumps({"data": 1, "provenance": prov}), encoding="utf-8")

        # Consumer verifies the run_id matches the bundle.
        ok, reason = verify_provenance(artifact, expected_run_id="trace_bundle")
        assert ok, f"provenance verification failed: {reason}"
        assert prov["producer_step"] == "structural_replay"
        assert prov["source_release_id"] == "20260717"

        # Mismatched run_id is rejected (stale artifact).
        ok2, reason2 = verify_provenance(artifact, expected_run_id="other_bundle")
        assert not ok2
