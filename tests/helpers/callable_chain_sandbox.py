"""Sandbox helpers for P0-3 callable main-chain execution tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from tests.helpers.sandbox_workspace import build_sandbox_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]

# Minimal neutral-pressure snapshot accepted by judgment_layer / build_judgment.
_PRESSURE_SNAPSHOT = {
    "as_of": "2026-07-26T00:00:00+00:00",
    "basic": {
        "quality_status": "FULL_PROXY_REDUCED",
        "measurement_quality": "LOW_CONFIDENCE_PROXY_REDUCED",
        "validity_scope": "PARTIAL_STRUCTURAL_STRESS_DIAGNOSTIC",
        "overall": "DEGRADED_PARTIAL",
    },
    "advanced": {
        "primary_readout": {
            "state": "MIXED_ANCHOR_PATH_STRESS",
            "M_anchor_geometry": {"value": -1.1},
            "D_path_geometry": {"value": -0.8},
        },
        "channel_confidence": {
            "M": {
                "proxy_quality": "PROXY_REDUCED",
                "confidence": "low",
                "readout_role": "primary_readout",
            },
            "D": {
                "proxy_quality": "PROXY_REDUCED",
                "confidence": "low",
                "readout_role": "primary_readout",
            },
            "K": {
                "proxy_quality": "PROXY_REDUCED",
                "confidence": "low",
                "readout_role": "diagnostic_rebuild",
            },
            "X_agg": {
                "proxy_quality": "PROXY_REDUCED",
                "confidence": "low",
                "readout_role": "background_only",
            },
        },
    },
}

_SYSTEM_INDEX = {
    "generated_at": "2026-07-26T00:00:00+00:00",
    "measurement_state": {
        "judgment": {"summary": {"decision": "ACTIVE_WATCH", "confidence": "low"}},
        "promotion_gate": {"summary": {"status": "BLOCKED", "blocked_gates": ["fixture_gate"]}},
        "signals": {
            "hmm": {"summary": {"status": "SKIP"}},
            "k_gate": {"summary": {"status": "SKIP"}},
            "x_gate": {"summary": {"status": "SKIP"}},
        },
    },
    "trade_decision": {"summary": {"decision": "NO_TRADE"}},
    "risk_gate": {"summary": {"status": "BLOCKED"}},
    "freshness": {"verdict": "FAIL", "stale_artifacts": ["fixture_panel"]},
    "paper_world_model": {"cases": {"exists": False}},
    "horizon_events": {"events": {"exists": False}},
    "market_feedback": {"latest": {"exists": False}},
}


def seed_callable_chain_workspace(target: Path) -> Path:
    """Build a workspace with fixtures for judgment → promotion → readout callables."""
    sandbox = build_sandbox_workspace(target)
    current = sandbox / "Output" / "current"
    (current / "neutral_pressure_snapshot.json").write_text(
        json.dumps(_PRESSURE_SNAPSHOT, indent=2) + "\n",
        encoding="utf-8",
    )

    (sandbox / "Output" / "k_measurement").mkdir(parents=True, exist_ok=True)
    (sandbox / "Output" / "x_measurement").mkdir(parents=True, exist_ok=True)
    (sandbox / "Output" / "k_measurement" / "k_measurement_gate.json").write_text(
        json.dumps({"gate_verdict": "PASS", "tests": {"a": {"status": "PASS"}}}),
        encoding="utf-8",
    )
    (sandbox / "Output" / "x_measurement" / "x_measurement_gate.json").write_text(
        json.dumps({"gate_verdict": "PASS", "tests": {"b": {"status": "PASS"}}}),
        encoding="utf-8",
    )

    index_dir = sandbox / "Data" / "system_index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "latest.json").write_text(
        json.dumps(_SYSTEM_INDEX, indent=2) + "\n",
        encoding="utf-8",
    )

    # configs needed by freshness_validator / artifact registry readers
    cfg_src = REPO_ROOT / "configs"
    if cfg_src.is_dir():
        shutil.copytree(
            cfg_src,
            sandbox / "configs",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    return sandbox


def patch_callable_chain_paths(monkeypatch, sandbox: Path) -> None:
    """Point runtime + judgment modules at the sandbox workspace root."""
    import scripts._data_paths as dp
    import scripts._runtime_io as rio
    import scripts.commands.weekly.build_artifact_registry as artifact_reg
    import scripts.commands.weekly.build_evidence_grade_report as evidence_grade
    import scripts.commands.weekly.build_readme_first as readme_first
    import scripts.judgment_layer as jl_script
    import scripts.pending_evaluation as pe
    import workbench.judgment.layer as jl
    import workbench.judgment.promotion_gate as pg

    out = sandbox / "Output"
    current = out / "current"
    judgment = out / "judgment"

    monkeypatch.setattr(rio, "ROOT", sandbox)
    monkeypatch.setattr(dp, "ROOT", sandbox)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", sandbox / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(
        dp,
        "HARVESTER_DATA",
        sandbox / "Data" / "harvester" / "exports" / "latest" / "data",
    )

    monkeypatch.setattr(jl, "ROOT", sandbox)
    monkeypatch.setattr(jl, "PRESSURE_PATH", current / "neutral_pressure_snapshot.json")
    monkeypatch.setattr(jl, "FW_PATH", current / "neutral_pressure_snapshot.json")
    monkeypatch.setattr(jl, "CASELAB_DIR", out / "caselab")
    monkeypatch.setattr(jl, "HMM_PATH", out / "ml_signals" / "latest" / "regime_hmm.json")
    monkeypatch.setattr(jl, "K_GATE_PATH", out / "k_measurement" / "k_measurement_gate.json")
    monkeypatch.setattr(jl, "X_GATE_PATH", out / "x_measurement" / "x_measurement_gate.json")
    monkeypatch.setattr(jl, "VALIDATION_PATH", current / "quality_validation.json")
    monkeypatch.setattr(jl, "OUTPUT_DIR", judgment)

    # scripts.judgment_layer binds FW_PATH at import time — keep it aligned.
    monkeypatch.setattr(jl_script, "FW_PATH", current / "neutral_pressure_snapshot.json")

    monkeypatch.setattr(pg, "ROOT", sandbox)
    monkeypatch.setattr(pg, "JUDGMENT_PATH", judgment / "latest.json")
    monkeypatch.setattr(pg, "CASELAB_DIR", out / "caselab")
    monkeypatch.setattr(pg, "HMM_PATH", out / "ml_signals" / "latest" / "regime_hmm.json")
    monkeypatch.setattr(pg, "HMM_AUDIT_PATH", out / "hmm_stability" / "hmm_stability_audit.json")
    monkeypatch.setattr(pg, "K_GATE_PATH", out / "k_measurement" / "k_measurement_gate.json")
    monkeypatch.setattr(pg, "X_GATE_PATH", out / "x_measurement" / "x_measurement_gate.json")
    monkeypatch.setattr(pg, "OUTPUT_DIR", judgment)

    monkeypatch.setattr(pe, "ROOT", sandbox)
    monkeypatch.setattr(pe, "EVAL_DIR", out / "evaluations")
    monkeypatch.setattr(pe, "PENDING_PATH", out / "evaluations" / "pending.jsonl")

    monkeypatch.setattr(evidence_grade, "ROOT", sandbox)
    monkeypatch.setattr(evidence_grade, "JUDGMENT_PATH", judgment / "latest.json")
    monkeypatch.setattr(evidence_grade, "PROMOTION_GATE_PATH", judgment / "promotion_gate.json")
    monkeypatch.setattr(evidence_grade, "TRADE_DECISION_PATH", out / "trade_decision" / "latest.json")
    monkeypatch.setattr(evidence_grade, "K_GATE_PATH", out / "k_measurement" / "k_measurement_gate.json")
    monkeypatch.setattr(evidence_grade, "X_GATE_PATH", out / "x_measurement" / "x_measurement_gate.json")
    monkeypatch.setattr(evidence_grade, "HMM_AUDIT_PATH", out / "hmm_stability" / "hmm_stability_audit.json")
    monkeypatch.setattr(evidence_grade, "FRESHNESS_PATH", out / "quality" / "freshness_report.json")
    monkeypatch.setattr(
        evidence_grade, "PAPER_MANIFEST_PATH", sandbox / "Data" / "paper_world_model" / "manifest.json"
    )
    monkeypatch.setattr(
        evidence_grade,
        "HARVESTER_CATALOG_PATH",
        sandbox / "Data" / "harvester" / "exports" / "latest" / "catalog.json",
    )
    monkeypatch.setattr(
        evidence_grade, "DATA_REQUEST_PATH", sandbox / "governance" / "data_request_registry.yaml"
    )
    monkeypatch.setattr(evidence_grade, "OUTPUT_PATH", current / "evidence_grade_report.json")

    monkeypatch.setattr(artifact_reg, "ROOT", sandbox)
    monkeypatch.setattr(
        artifact_reg, "ROUTING_POLICY_PATH", sandbox / "governance" / "output_routing_policy.yaml"
    )
    monkeypatch.setattr(
        artifact_reg, "PIPELINE_REGISTRY_PATH", sandbox / "governance" / "daily_pipeline_registry.yaml"
    )
    monkeypatch.setattr(artifact_reg, "OUTPUT_PATH", current / "artifact_registry.json")

    monkeypatch.setattr(readme_first, "ROOT", sandbox)
    monkeypatch.setattr(readme_first, "INDEX_PATH", sandbox / "Data" / "system_index" / "latest.json")
    monkeypatch.setattr(readme_first, "FRAMEWORK_OUTPUT_PATH", current / "framework_output.json")
    monkeypatch.setattr(readme_first, "EVIDENCE_REPORT_PATH", current / "evidence_grade_report.json")
    monkeypatch.setattr(readme_first, "OUTPUT_PATH", current / "00_READ_ME_FIRST.md")

    monkeypatch.setenv("SYSTEM_WORKSPACE_ROOT", str(sandbox))
    monkeypatch.setenv("SYSTEM_ROOT", str(sandbox))
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(current))
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(out))
    monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "p0_3_wave3_fixture_run")
