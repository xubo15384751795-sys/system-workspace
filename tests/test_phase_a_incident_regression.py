"""Phase A P0 incident regression tests.

Each test injects a historical incident and asserts the three-part contract:
  1. DETECTED   - the failure is surfaced (blocked status / exit code / blocker)
  2. BLOCKED    - downstream consumers are blocked, not silently run
  3. UNCHANGED  - authoritative state is not modified (hash / line-count / pointer)

Incidents:
  P0-2: K builder throws -> structural_replay fails -> bridge/judgment/trade/
        paper blocked_upstream; bridge refuses stale sigma_vector (no
        framework_output written).
  P0-3: OFR/CISS stale -> admission gate blocks paper_portfolio; freshness
        hard-fails; P_public fail-closed -> HOLD_DEGRADED, no valid sample.

P0-1 (merge gate) is Phase C and not covered here.
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


# ── shared assertion helpers ─────────────────────────────────────────────


def _file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _nav_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _snapshot(position_dir: Path, current_dir: Path) -> dict:
    return {
        "nav_hash": _file_hash(position_dir / "paper_portfolio_nav.jsonl"),
        "nav_lines": _nav_line_count(position_dir / "paper_portfolio_nav.jsonl"),
        "state_hash": _file_hash(position_dir / "paper_portfolio.json"),
        "framework_output_hash": _file_hash(current_dir / "framework_output.json"),
        "latest_run_id": _read_latest_run_id(current_dir),
    }


def _read_latest_run_id(current_dir: Path) -> str | None:
    p = current_dir / "latest_run_id.txt"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip()


# ── P0-2: K builder failure ─────────────────────────────────────────────


class TestKBuilderFailure:
    """K builder throws -> structural_replay fails -> descendants blocked,
    bridge refuses stale sigma_vector, no authoritative write."""

    def test_failure_detected_descendants_blocked_state_unchanged(self, tmp_path, monkeypatch):
        import importlib.util

        # Load executor module fresh.
        spec = importlib.util.spec_from_file_location(
            "_daily_run_executor", ROOT / "scripts" / "_daily_run_executor.py",
        )
        exec_mod = importlib.util.module_from_spec(spec)
        sys.modules["_daily_run_executor"] = exec_mod
        spec.loader.exec_module(exec_mod)

        # Set up isolated authoritative-state paths.
        position_dir = tmp_path / "Output" / "position"
        current_dir = tmp_path / "Output" / "current"
        position_dir.mkdir(parents=True)
        current_dir.mkdir(parents=True)
        # Pre-existing (yesterday's) authoritative artifacts.
        (position_dir / "paper_portfolio_nav.jsonl").write_text(
            json.dumps({"as_of": "2026-07-15", "nav": 1.0}) + "\n", encoding="utf-8"
        )
        (current_dir / "framework_output.json").write_text(
            json.dumps({"run_id": "yesterday"}), encoding="utf-8"
        )
        before = _snapshot(position_dir, current_dir)

        executed: list[str] = []

        def fake_execute_step(step_id, ctx):
            executed.append(step_id)
            # The active neutral pressure producer fails.
            if step_id == "neutral_pressure_measurement":
                return {"step": step_id, "status": "failed", "returncode": 1, "duration_s": 1.0}
            return {"step": step_id, "status": "success", "returncode": 0, "duration_s": 0.1}

        args = SimpleNamespace(force_weekly=True, skip_harvester=False, skip_etf=False)
        ctx = exec_mod.DailyRunContext(
            args=args,
            start_time=datetime(2026, 7, 17),
            total_steps=100,
            run_step_fn=lambda *a, **k: {"status": "success"},
            record_fn=lambda *a, **k: None,
            benchmark_panel_path=ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet",
            run_id="test_bundle_run_id",
        )

        with patch.object(exec_mod, "execute_step", side_effect=fake_execute_step):
            results = exec_mod.execute_daily_sequence(ctx)

        status = {r["step"]: r.get("status") for r in results}

        # 1. DETECTED: active pressure producer recorded as failed.
        assert status.get("neutral_pressure_measurement") == "failed"

        # 2. BLOCKED: declared descendants are blocked_upstream, not executed.
        for descendant in ("judgment_layer", "trade_decision", "paper_portfolio"):
            assert status.get(descendant) == "blocked_upstream", (
                f"{descendant}: expected blocked_upstream, got {status.get(descendant)!r}"
            )
            assert descendant not in executed, f"{descendant} must not execute"

        # 3. UNCHANGED: authoritative state untouched (the executor never ran
        # the real bridge/paper steps, so no writes happened).
        after = _snapshot(position_dir, current_dir)
        for key in before:
            assert before[key] == after[key], (
                f"authoritative state {key} changed: {before[key]!r} -> {after[key]!r}"
            )

    def test_archived_bridge_rejects_without_framework_write(self, tmp_path, monkeypatch):
        """The archived bridge is rejected before legacy input can be reused,
        and does not write framework_output.json."""
        import bridge_replay_to_current as bridge

        replay_dir = tmp_path / "sandbox" / "structural_replay_v2"
        current_dir = tmp_path / "current"
        replay_dir.mkdir(parents=True)
        current_dir.mkdir(parents=True)
        monkeypatch.setattr(bridge, "REPLAY_DIR", replay_dir)
        monkeypatch.setattr(bridge, "CURRENT", current_dir)

        # Yesterday's sigma_vector with an old run_id.
        (replay_dir / "sigma_vector.json").write_text(json.dumps({
            "run_id": "yesterday_bundle",
            "sigma_vector": {"M": 0.1},
        }), encoding="utf-8")
        monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "today_bundle")

        before_fw = _file_hash(current_dir / "framework_output.json")

        with pytest.raises(SystemExit) as exc:
            bridge.main()
        assert "ARCHIVED_FALSIFIED" in str(exc.value)

        after_fw = _file_hash(current_dir / "framework_output.json")
        assert before_fw == after_fw, "framework_output.json must not be written on rejection"


# ── P0-3: OFR/CISS stale -> admission block + HOLD_DEGRADED ──────────────


class TestOfrCissStaleAdmission:
    """OFR/CISS stale -> admission gate blocks paper_portfolio; P_public
    fail-closed -> HOLD_DEGRADED; no valid promotion sample added."""

    def test_admission_blocks_on_stale_release_components(self, tmp_path, monkeypatch):
        """A release with stale NFCI (>21d behind) produces a blocker that
        blocks paper_portfolio admission."""
        from _admission_gate import admit_for_consumption

        release = tmp_path / "release"
        data_dir = release / "data"
        data_dir.mkdir(parents=True)
        rows = [
            {"date": pd.Timestamp("2026-07-16"), "series_id": "VIXCLS",
             "source_id": "fred", "source_series_id": "VIXCLS", "value": 20.0,
             "unit": "index", "frequency": "daily",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
            {"date": pd.Timestamp("2026-07-16"), "series_id": "BAMLH0A0HYM2",
             "source_id": "fred", "source_series_id": "BAMLH0A0HYM2", "value": 5.0,
             "unit": "pct", "frequency": "daily",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
            # OFR 73 days behind (stale for daily, acceptable_lag=10).
            {"date": pd.Timestamp("2026-05-05"), "series_id": "OFR_FSI",
             "source_id": "ofr", "source_series_id": "OFR_FSI", "value": 0.3,
             "unit": "index", "frequency": "daily",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
            # NFCI 69 days behind (stale for weekly, acceptable_lag=21).
            {"date": pd.Timestamp("2026-05-09"), "series_id": "NFCI",
             "source_id": "fred_chicago_fed", "source_series_id": "NFCI", "value": -0.4,
             "unit": "index", "frequency": "weekly",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
        ]
        pd.DataFrame(rows).to_parquet(data_dir / "benchmark_panel.parquet")
        (release / "catalog.json").write_text(json.dumps({
            "bundle_id": release.name,
            "created_at": "2026-07-17T00:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "data/benchmark_panel.parquet"}],
        }), encoding="utf-8")

        # Stub content checks (we are testing release-level admission here).
        monkeypatch.setattr(
            "freshness_validator.check_content_freshness",
            lambda **kw: {"name": kw["name"], "status": "FRESH"},
        )

        decision = admit_for_consumption(
            "paper_portfolio", release_dir=release, now=pd.Timestamp("2026-07-17"),
        )

        # 1. DETECTED: blockers name the stale public components.
        assert decision.allowed is False
        blocker_text = " ".join(decision.blockers)
        assert "OFR_FSI" in blocker_text or "NFCI" in blocker_text, (
            f"expected OFR_FSI/NFCI in blockers, got {decision.blockers}"
        )

    def test_p_public_fail_closed_on_stale_components(self):
        """P_public returns NaN when public components are stale/missing,
        so paper_portfolio holds existing (HOLD_DEGRADED), not renormalizes."""
        from public_residual_stress import public_level_probability

        idx = pd.date_range("2026-04-01", periods=100, freq="B")
        # Simulate the incident: OFR+CISS NaN (stale caches), only NFCI present.
        public = pd.DataFrame(
            {
                "ofr_fsi": [np.nan] * 100,
                "nfci": np.linspace(0.2, 0.8, 100),
                "ecb_ciss": [np.nan] * 100,
            },
            index=idx,
        )
        p = public_level_probability(public, min_periods=50)
        # Fail-closed: all NaN (only 1 of 3 components -> below required 3).
        assert p.notna().sum() == 0, (
            "stale OFR/CISS must yield NaN P_public (fail-closed), not NFCI-only renormalization"
        )

    def test_require_admission_exits_nonzero_on_stale(self, tmp_path, monkeypatch):
        """paper_portfolio's require_admission guard exits 1 on stale OFR/CISS,
        so the executor records failed and descendants block."""
        from _admission_gate import require_admission

        release = tmp_path / "release"
        data_dir = release / "data"
        data_dir.mkdir(parents=True)
        # Only VIXCLS + BAML (no OFR/NFCI/CISS) -> OFR/NFCI/CISS missing -> block.
        rows = [
            {"date": pd.Timestamp("2026-07-16"), "series_id": "VIXCLS",
             "source_id": "fred", "source_series_id": "VIXCLS", "value": 20.0,
             "unit": "index", "frequency": "daily",
             "vintage_date": pd.Timestamp("2026-07-17"), "quality_flag": "observed"},
        ]
        pd.DataFrame(rows).to_parquet(data_dir / "benchmark_panel.parquet")
        (release / "catalog.json").write_text(json.dumps({
            "bundle_id": release.name,
            "created_at": "2026-07-17T00:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "data/benchmark_panel.parquet"}],
        }), encoding="utf-8")
        monkeypatch.setattr(
            "freshness_validator.check_content_freshness",
            lambda **kw: {"name": kw["name"], "status": "FRESH"},
        )

        with pytest.raises(SystemExit) as exc:
            require_admission("paper_portfolio", release_dir=release,
                              now=pd.Timestamp("2026-07-17"))
        assert exc.value.code == 1
