"""Shared fixtures for Workbench tests.

WORKBENCH_ROOT is set to tmp_path before any workbench module is imported
so that workspace_root() returns a controlled, isolated directory for every test.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

# Real workspace roots — used only to copy read-only assets (contracts, configs)
# into the isolated tmp workspace so validators can load their schemas.
_WORKBENCH_ROOT = Path(__file__).resolve().parents[1]  # Workbench/
_SYSTEM_ROOT = _WORKBENCH_ROOT.parent                  # System/


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Point every test at its own tmp workspace."""
    monkeypatch.setenv("WORKBENCH_ROOT", str(tmp_path))

    # Copy read-only workspace assets so validators and policy loaders work.
    for asset in ("contracts",):
        src = _WORKBENCH_ROOT / asset
        if src.exists():
            shutil.copytree(src, tmp_path / asset)
    for asset in ("configs",):
        src = _SYSTEM_ROOT / asset
        if src.exists():
            shutil.copytree(src, tmp_path / asset)
    # Reset module-level constants that were baked in at import time.
    # We patch the attributes directly on the already-imported module objects.
    import workbench.current as _cur
    import workbench.freshness as _fresh
    import workbench.contract_validator as _cv
    import workbench.evidence_dashboard as _ed

    output = tmp_path / "Output"
    data = tmp_path / "Data"
    for mod, attrs in [
        (_cur, {
            "ROOT": tmp_path,
            "OUTPUT": output,
            "CURRENT": output / "current",
            "DEFORMATION_LATEST": output / "deformation_runs" / "latest",
            "LEARNING_LATEST": output / "system_learning" / "latest",
        }),
        (_fresh, {
            "ROOT": tmp_path,
            "POLICY_PATH": tmp_path / "configs" / "freshness_policy.yaml",
            "HARVESTER_LATEST": data / "harvester" / "exports" / "latest",
            "DEFORMATION_LATEST": output / "deformation_runs" / "latest",
            "CURRENT": output / "current",
        }),
        (_cv, {
            "ROOT": tmp_path,
            "CONTRACTS": tmp_path / "contracts" / "workbench",
        }),
        (_ed, {
            "ROOT": tmp_path,
            "OUTPUT": output,
            "WORKBENCH": output / "workbench" / "benchmark_evidence",
            "CURRENT": output / "current",
            "HARVESTER_LATEST": data / "harvester" / "exports" / "latest",
        }),
    ]:
        for attr, val in attrs.items():
            monkeypatch.setattr(mod, attr, val)

    yield tmp_path


# ---------------------------------------------------------------------------
# Shared data builders
# ---------------------------------------------------------------------------

def make_policy() -> dict:
    return {
        "frequency_thresholds": {
            "weekly": {"fresh_lag_days": 10, "acceptable_lag_days": 21},
            "daily":  {"fresh_lag_days": 3,  "acceptable_lag_days": 10},
            "unknown": {"fresh_lag_days": 30, "acceptable_lag_days": 90},
        },
        "indicators": {
            "NFCI": {"frequency": "weekly", "required": True},
            "VIXCLS": {"frequency": "daily", "required": True},
            "TEDRATE": {
                "frequency": "daily",
                "required": False,
                "status_override": "retired_or_unavailable",
                "retired_reason": "Series discontinued 2023-06-16.",
                "retired_effective_date": "2023-06-16",
            },
        },
        "gate_defaults": {
            "stale_required_severity": "warn",
            "missing_required_severity": "block",
            "retired_used_severity": "block",
        },
    }


def make_panel_df() -> pd.DataFrame:
    rows = [
        {"series_id": "NFCI",   "date": "2026-04-28", "value": -0.45, "vintage_date": "2026-04-28", "unit": "index", "frequency": "weekly", "source_id": "fred", "source_series_id": "NFCI",   "quality_flag": "ok"},
        {"series_id": "VIXCLS", "date": "2026-05-01", "value": 17.3,  "vintage_date": "2026-05-01", "unit": "index", "frequency": "daily",  "source_id": "cboe", "source_series_id": "VIXCLS", "quality_flag": "ok"},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def sample_policy():
    return make_policy()


@pytest.fixture
def sample_panel():
    return make_panel_df()
