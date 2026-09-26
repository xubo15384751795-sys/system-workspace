"""Eradicate recurring daily_run false alarms: gates, soft failures, feeds, imports."""
from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


# ── A: freshness midrun vs publish gate ──────────────────────────────────


class TestFreshnessGateBoundary:
    def test_midrun_closure_is_advisory(self, tmp_path, monkeypatch):
        from workbench.measurement import freshness_validator as fv

        now = datetime.now(UTC)
        fresh = now
        stale = now - timedelta(minutes=35)
        candidate = tmp_path / "candidate"
        candidate.mkdir()
        for name, ts in [
            ("signal_card.json", fresh),
            ("signal_consensus.json", fresh),
        ]:
            p = candidate / name
            p.write_text("{}")
            import os

            os.utime(p, (ts.timestamp(), ts.timestamp()))
        idx = tmp_path / "Data" / "system_index" / "latest.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("{}")
        import os

        os.utime(idx, (stale.timestamp(), stale.timestamp()))

        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(candidate))
        with patch.object(fv, "ROOT", tmp_path), patch.object(fv, "OUTPUT_DIR", tmp_path / "Output"):
            issues = fv.check_closure_chain(now, gate="midrun")
        assert issues
        assert all(i["status"] == "ADVISORY_EXPECTED" for i in issues)

    def test_publish_gate_hard_fails_same_gap(self, tmp_path, monkeypatch):
        from workbench.measurement import freshness_validator as fv

        now = datetime.now(UTC)
        fresh = now
        stale = now - timedelta(minutes=35)
        candidate = tmp_path / "candidate"
        candidate.mkdir()
        for name, ts in [
            ("signal_card.json", fresh),
            ("signal_consensus.json", fresh),
        ]:
            p = candidate / name
            p.write_text("{}")
            import os

            os.utime(p, (ts.timestamp(), ts.timestamp()))
        idx = tmp_path / "Data" / "system_index" / "latest.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("{}")
        import os

        os.utime(idx, (stale.timestamp(), stale.timestamp()))

        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(candidate))
        with patch.object(fv, "ROOT", tmp_path), patch.object(fv, "OUTPUT_DIR", tmp_path / "Output"):
            issues = fv.check_closure_chain(now, gate="publish")
        assert issues
        assert any(i["status"] == "CLOSURE_VIOLATION" for i in issues)

    def test_midrun_main_exits_zero_on_fail_verdict(self, monkeypatch):
        from workbench.measurement import freshness_validator as fv

        monkeypatch.setattr(
            fv,
            "build_freshness_report",
            lambda now, mode="standard", gate=None: {
                "verdict": "FAIL",
                "gate": "midrun",
                "stale_artifacts": [],
                "missing_artifacts": [],
                "ordering_issues": [],
                "closure_chain_issues": [{"status": "ADVISORY_EXPECTED"}],
                "content_freshness": [],
                "artifacts": [],
                "generated_at": now.isoformat(),
            },
        )
        monkeypatch.setattr(fv, "write_outputs", lambda report: {"json": Path("x"), "markdown": Path("y")})
        monkeypatch.setattr(sys, "argv", ["freshness_validator.py", "--gate", "midrun"])
        assert fv.main() == 0


# ── D: soft vs hard failure classification + notify merge ────────────────


class TestSoftHardFailureNotify:
    def test_classify_soft_monitoring_vs_hard_paper(self):
        from verity.runtime._pipeline_dag import classify_step_failures

        hard, soft = classify_step_failures(
            [
                {"step": "monitoring_coverage_audit", "status": "failed"},
                {"step": "paper_portfolio", "status": "failed"},
                {"step": "evidence_grade_report", "status": "blocked_upstream"},
            ]
        )
        assert [s["step"] for s in hard] == ["paper_portfolio"]
        assert [s["step"] for s in soft] == ["monitoring_coverage_audit"]

    def test_write_alert_soft_only_is_medium(self, tmp_path):
        from verity.cli.daily_run import write_alert

        write_alert(
            warnings=["soft_fail:monitoring_coverage_audit"],
            steps=[{"step": "monitoring_coverage_audit", "status": "failed", "stdout_tail": "gap"}],
            output_root=tmp_path,
        )
        alert = json.loads((tmp_path / "state" / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
        assert alert["severity"] == "MEDIUM"
        assert alert["failed_steps"] == []
        assert alert["soft_failed_steps"] == ["monitoring_coverage_audit"]

    def test_notify_merges_content_stale_into_one_hard_alert(self, monkeypatch):
        from verity.runtime import _notify

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _notify,
            "notify_failure",
            lambda title, message: calls.append((title, message)) or True,
        )
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("NOTIFY_DISABLE", "0")
        # Re-enter without pytest suppression for this unit: call notify_deviations path
        # via notify_daily_run_result while forcing suppression off.
        monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)

        _notify.notify_daily_run_result(
            status="partial_failure",
            failed_steps=["paper_portfolio"],
            warnings=[],
            content_stale=["ofr_fsi_cache max=2026-07-08 behind=18d"],
        )
        assert len(calls) == 1
        assert calls[0][0] == "System daily_run failed"
        assert "paper_portfolio" in calls[0][1]
        assert "ofr_fsi_cache" in calls[0][1]

    def test_soft_warnings_do_not_push_desktop(self, monkeypatch, capsys):
        from verity.runtime import _notify

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _notify,
            "notify_failure",
            lambda title, message: calls.append((title, message)) or True,
        )
        monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)

        _notify.notify_daily_run_result(
            status="success",
            failed_steps=[],
            warnings=[
                "COVERAGE: overall=ACTIVE_PARTIAL",
                "soft_fail:monitoring_coverage_audit",
            ],
        )
        assert calls == []
        err = capsys.readouterr().err
        assert "NOTIFY[soft]" in err
        assert "monitoring_coverage_audit" in err

    def test_publish_blocked_pushes_hard(self, monkeypatch):
        from verity.runtime import _notify

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _notify,
            "notify_failure",
            lambda title, message: calls.append((title, message)) or True,
        )
        monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)

        _notify.notify_daily_run_result(
            status="partial_failure",
            failed_steps=[],
            warnings=["PUBLISH_BLOCKED: freshness_fail"],
            publish_blocked="freshness_fail",
        )
        assert len(calls) == 1
        assert calls[0][0] == "System daily_run failed"
        assert "publish blocked" in calls[0][1]


class TestNotifyCallSiteAllowlist:
    """Only known production modules may call desktop notify helpers."""

    _ALLOWED = {
        "scripts/_notify.py",
        "scripts/daily_run.py",
        "scripts/freshness_validator.py",
        "scripts/strategy_lab/paper_portfolio.py",
        "scripts/commands/ci/check_main_ci_status.py",
    }

    def test_no_surprise_notify_call_sites(self):
        import re

        root = ROOT
        hits: list[str] = []
        pattern = re.compile(r"\bnotify_(?:failure|alert|deviations|daily_run_result)\b")
        for path in root.joinpath("scripts").rglob("*.py"):
            rel = str(path.relative_to(root))
            if rel in self._ALLOWED:
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                hits.append(rel)
        assert hits == [], f"unexpected notify call sites: {hits}"


# ── B: external feed URL / schema contracts ──────────────────────────────


class TestExternalFeedContracts:
    def test_ofr_publisher_is_csv_not_html(self):
        sys.path.insert(0, str(ROOT / "packages" / "harvester" / "src"))
        from harvester.providers.external_indicators import OFR_FSI

        assert OFR_FSI.publisher_url.endswith("/financial-stress-index/data/fsi.csv")
        assert not OFR_FSI.publisher_url.rstrip("/").endswith("financial-stress-index")

    def test_content_freshness_date_columns_match_caches(self):
        reg = yaml.safe_load(
            (ROOT / "governance" / "daily_pipeline_registry.yaml").read_text(encoding="utf-8")
        )
        content = reg.get("content_freshness") or {}
        # Decision-critical CSV caches must declare a real date column that
        # naive readers can open without KeyError after a harvester refresh.
        for name in ("ofr_fsi_cache", "ciss_cache"):
            assert name in content
            path = ROOT / content[name]["path"]
            assert path.exists(), f"missing cache for {name}: {path}"
            import pandas as pd

            frame = pd.read_csv(path, nrows=2)
            col = content[name]["date_column"]
            assert col in frame.columns, f"{name}: date_column {col!r} not in {list(frame.columns)}"

    def test_known_file_indicators_urls_look_like_data(self):
        sys.path.insert(0, str(ROOT / "packages" / "harvester" / "src"))
        from harvester.providers.external_indicators import CISS, OFR_FSI

        for ind in (OFR_FSI, CISS):
            url = ind.publisher_url.lower()
            assert any(
                token in url for token in (".csv", "format=csv", "csvdata", "/data/")
            ), f"{ind.name} publisher_url does not look like a data export: {ind.publisher_url}"


# ── C: daily_run callable import smoke ───────────────────────────────────


class TestDailyRunCallableImports:
    def test_active_callable_mode_modules_import(self):
        """Import modules actually invoked as mode=callable (not aspirational stubs)."""
        reg = yaml.safe_load(
            (ROOT / "governance" / "daily_pipeline_registry.yaml").read_text(encoding="utf-8")
        )
        failures: list[str] = []
        seen: set[str] = set()
        for step_id, step in (reg.get("steps") or {}).items():
            if step.get("status") not in (None, "active"):
                continue
            execution = step.get("execution") or {}
            if execution.get("mode") != "callable":
                continue
            target = execution.get("future_callable") or ""
            if ":" not in target:
                continue
            mod_name, _, _func = target.partition(":")
            if mod_name in seen:
                continue
            seen.add(mod_name)
            try:
                importlib.import_module(mod_name)
            except Exception as exc:  # noqa: BLE001 — collect all import breaks
                failures.append(f"{step_id}: {mod_name} -> {exc}")
        assert not failures, "callable-mode import failures:\n" + "\n".join(failures)

    def test_paper_portfolio_package_imports_resolve(self):
        """Regression: daily_run package path must see canonical Workbench helpers."""
        from strategy_lab import paper_portfolio as pp
        from workbench.measurement.public_residual_stress import (
            build_public_residual_bundle,
        )

        from scripts.professional_methods import causal_pit, continuous_position

        assert callable(causal_pit) and callable(continuous_position)
        assert callable(build_public_residual_bundle)
        source = Path(pp.__file__).read_text(encoding="utf-8")
        assert "workbench.measurement.professional_methods" in source
        assert "scripts.professional_methods" not in source
