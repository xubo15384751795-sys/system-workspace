"""Phase B tests: DAG compiler, failure_behavior interpreter, artifact
provenance, release boundary, atomic publish.

Covers B1 (compile_dag validity), B2 (interpret_failure per-behavior),
B3 (provenance schema + should_publish_with_provenance), B4 (release
finalization verification), B5 (atomic current + shadow publish).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ── B1: DAG compiler ────────────────────────────────────────────────────


class TestCompileDag:
    def test_dag_valid(self):
        from _pipeline_dag import compile_dag

        dag = compile_dag()
        assert dag["valid"], (
            f"DAG invalid: cycles={dag['cycles']} "
            f"missing_producers={dag['missing_producers']} "
            f"duplicate_writers={dag['duplicate_writers']} "
            f"decision_adjacent_cww={dag['decision_adjacent_cww']} "
            f"sequence_contradictions={dag['sequence_contradictions']}"
        )

    def test_no_cycles(self):
        from _pipeline_dag import compile_dag

        assert compile_dag()["cycles"] == []

    def test_no_missing_producers(self):
        from _pipeline_dag import compile_dag

        assert compile_dag()["missing_producers"] == []

    def test_no_duplicate_writers(self):
        from _pipeline_dag import compile_dag

        assert compile_dag()["duplicate_writers"] == []

    def test_no_decision_adjacent_continue_with_warning(self):
        from _pipeline_dag import compile_dag

        assert compile_dag()["decision_adjacent_cww"] == []

    def test_no_sequence_contradictions(self):
        from _pipeline_dag import compile_dag

        assert compile_dag()["sequence_contradictions"] == []

    def test_declared_chain_edges_present(self):
        from _pipeline_dag import compile_dag

        edges = compile_dag()["edges"]
        assert "neutral_pressure_measurement" in edges["judgment_layer"]
        assert "judgment_layer" in edges["trade_decision"]
        assert "neutral_pressure_measurement" in edges["paper_portfolio"]


# ── B2: failure_behavior interpreter ─────────────────────────────────────


class TestInterpretFailure:
    def test_block_current_readout_upstream_blocks(self):
        from _pipeline_dag import interpret_failure

        # Neutral pressure measurement failed -> judgment should block.
        results = [{"step": "neutral_pressure_measurement", "status": "failed"}]
        d = interpret_failure("judgment_layer", results)
        assert d["action"] == "block"
        assert "neutral_pressure_measurement" in d["blocked_by"]

    def test_hold_flat_upstream_degrades_not_blocks(self):
        from _pipeline_dag import interpret_failure

        # trade_decision (hold_flat) failed -> risk_gate should degrade, not block.
        results = [{"step": "trade_decision", "status": "failed"}]
        d = interpret_failure("risk_gate", results)
        assert d["action"] == "run_degraded"
        assert d["degraded"] is True
        assert "trade_decision" in d.get("degraded_by", [])

    def test_continue_with_warning_upstream_does_not_propagate(self):
        from _pipeline_dag import interpret_failure

        # A continue_with_warning step (e.g. hmm_stability_audit) failing must
        # not block or degrade a downstream consumer.
        results = [{"step": "hmm_stability_audit", "status": "failed"}]
        d = interpret_failure("current_status", results)
        assert d["action"] == "run"
        assert d["degraded"] is False

    def test_clean_run_runs(self):
        from _pipeline_dag import interpret_failure

        d = interpret_failure(
            "judgment_layer",
            [{"step": "neutral_pressure_measurement", "status": "success"}],
        )
        assert d["action"] == "run"


# ── B3: artifact provenance ──────────────────────────────────────────────


class TestProvenance:
    def test_build_provenance_has_10_fields(self, monkeypatch):
        from _artifact_provenance import build_provenance

        monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "test_bundle")
        prov = build_provenance(producer_step="structural_replay")
        for field in (
            "run_id", "producer_step", "producer_commit", "source_release_id",
            "generated_at", "as_of_date", "input_fingerprints",
            "validation_verdict", "claim_ceiling", "degraded_reasons",
        ):
            assert field in prov, f"provenance missing {field}"

    def test_verify_provenance_rejects_mismatch(self, tmp_path):
        from _artifact_provenance import verify_provenance

        artifact = tmp_path / "fw.json"
        artifact.write_text(json.dumps({
            "data": 1,
            "provenance": {"run_id": "old_run"},
        }), encoding="utf-8")
        ok, reason = verify_provenance(artifact, expected_run_id="new_run")
        assert ok is False
        assert "mismatch" in reason

    def test_should_publish_with_provenance_blocks_failed_verdict(self):
        from _current_publish import should_publish_with_provenance

        freshness = {"verdict": "PASS"}
        # A validation-failed artifact must block publishing.
        index = [{"path": "x.json", "provenance": {"validation_verdict": "fail"}}]
        ok, reason = should_publish_with_provenance("success", freshness, index)
        assert ok is False
        assert "validation_verdict" in reason

    def test_should_publish_with_provenance_allows_pass(self):
        from _current_publish import should_publish_with_provenance

        freshness = {"verdict": "PASS"}
        index = [{"path": "x.json", "provenance": {"validation_verdict": "pass"}}]
        ok, _ = should_publish_with_provenance("success", freshness, index)
        assert ok is True


# ── B4: release boundary ─────────────────────────────────────────────────


class TestReleaseBoundary:
    def test_unfinalized_release_rejected(self, tmp_path):
        from _release_boundary import ReleaseNotFinalizedError, verify_release_finalized

        release = tmp_path / "release"
        release.mkdir()
        (release / "catalog.json").write_text(json.dumps({"release_id": "r1"}))
        # No .finalized marker.
        with pytest.raises(ReleaseNotFinalizedError):
            verify_release_finalized(release)

    def test_finalized_release_accepted(self, tmp_path):
        from _release_boundary import verify_release_finalized

        release = tmp_path / "release"
        release.mkdir()
        (release / ".finalized").write_text("ok")
        (release / "catalog.json").write_text(json.dumps({"release_id": "r1"}))
        catalog = verify_release_finalized(release)
        assert catalog["release_id"] == "r1"

    def test_non_finalized_status_rejected(self, tmp_path):
        from _release_boundary import ReleaseNotFinalizedError, verify_release_finalized

        release = tmp_path / "release"
        release.mkdir()
        (release / ".finalized").write_text("ok")
        (release / "catalog.json").write_text(json.dumps({"status": "draft"}))
        with pytest.raises(ReleaseNotFinalizedError):
            verify_release_finalized(release)


# ── B5: atomic publish ───────────────────────────────────────────────────


class TestAtomicPublish:
    def test_publish_candidate_atomic_swap(self, tmp_path, monkeypatch):
        from _current_publish import publish_candidate

        # Build a candidate with one artifact.
        candidate = tmp_path / "candidate"
        candidate.mkdir()
        (candidate / "framework_output.json").write_text('{"ok":true}')

        # Stub candidate_artifact_names to return our file.
        monkeypatch.setattr(
            "_current_publish.candidate_artifact_names",
            lambda: ["framework_output.json"],
        )

        result = publish_candidate(candidate, run_id="test_run", root=tmp_path)
        assert result["count"] == 1
        target = tmp_path / "Output" / "current"
        assert (target / "framework_output.json").read_text() == '{"ok":true}'
        assert (target / "latest_run_id.txt").read_text().strip() == "test_run"
        # Staging dir cleaned up.
        assert not list(target.parent.glob(".current_staging.*"))

    def test_publish_shadow_candidate_atomic(self, tmp_path, monkeypatch):
        from _shadow_publish import (
            NAV_JSONL_NAME,
            publish_shadow_candidate,
        )

        candidate = tmp_path / "shadow_candidate"
        candidate.mkdir()
        (candidate / NAV_JSONL_NAME).write_text('{"as_of":"2026-07-17","nav":1.0}\n')
        (candidate / "paper_portfolio.json").write_text('{"position":0.5}')

        # Patch LIVE_POSITION_DIR to tmp so we don't touch real Output.
        import _shadow_publish as sp

        monkeypatch.setattr(sp, "LIVE_POSITION_DIR", tmp_path / "Output" / "position")
        result = publish_shadow_candidate(candidate, root=tmp_path)
        assert result["count"] == 2
        live = tmp_path / "Output" / "position"
        assert (live / NAV_JSONL_NAME).read_text().startswith('{"as_of"')
        assert (live / "paper_portfolio.json").read_text() == '{"position":0.5}'

    def test_append_nav_row_atomic_no_partial_line(self, tmp_path, monkeypatch):
        import _shadow_publish as sp
        from _shadow_publish import append_nav_row_atomic

        monkeypatch.setattr(sp, "LIVE_POSITION_DIR", tmp_path / "live")
        candidate = tmp_path / "cand"
        candidate.mkdir()
        append_nav_row_atomic({"as_of": "d1", "nav": 1.0}, candidate)
        append_nav_row_atomic({"as_of": "d2", "nav": 1.01}, candidate)
        nav = candidate / "paper_portfolio_nav.jsonl"
        lines = [line for line in nav.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        # Each line is valid JSON (no partial).
        for line in lines:
            json.loads(line)
