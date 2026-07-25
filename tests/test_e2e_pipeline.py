"""End-to-end pipeline structural completeness test.

Verifies that the daily pipeline, authority graph, governance freeze,
and key governance scripts are structurally sound. Does NOT require
external data or artifact files — runs on a fresh checkout.

This test is marked critical_gate because it validates the pipeline
skeleton that all other tests depend on.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

pytestmark = pytest.mark.critical_gate


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPipelineSkeleton:
    """Verify the daily pipeline structure is intact."""

    def test_daily_run_dry_run(self):
        """daily_run.py --dry-run should complete without error."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "daily_run.py"), "--dry-run"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        assert result.returncode == 0, f"dry-run failed: {result.stderr}"
        assert "DRY RUN" in result.stdout

    def test_daily_run_sequence_loads(self):
        """daily_run_sequence.yaml should load with expected step count."""
        seq_mod = _load("_daily_run_sequence", SCRIPTS / "_daily_run_sequence.py")
        steps = seq_mod.load_daily_run_sequence()
        assert len(steps) >= 20, f"Expected >=20 steps, got {len(steps)}"
        weekly = seq_mod.weekly_step_ids()
        assert len(weekly) >= 5, f"Expected >=5 weekly steps, got {len(weekly)}"

    def test_authority_graph_builds(self):
        """build_authority_graph.py should produce a valid graph."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "commands" / "weekly" / "build_authority_graph.py")],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
        assert result.returncode == 0, f"authority graph build failed: {result.stderr}"

    def test_governance_freeze_passes(self):
        """check_governance_freeze.py should pass (no unapproved files)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_governance_freeze.py")],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        assert result.returncode == 0, f"governance freeze failed: {result.stderr}"


class TestModuleIntegrity:
    """Verify key modules import and have expected structure."""

    def test_replay_registry_imports(self):
        """_replay_registry should export PROXY_REGISTRY and VARIABLES."""
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import _replay_registry as mod
        assert hasattr(mod, "PROXY_REGISTRY")
        assert hasattr(mod, "VARIABLES")
        assert len(mod.PROXY_REGISTRY) >= 10
        assert "M" in mod.VARIABLES

    def test_replay_transforms_imports(self):
        """_replay_transforms should export transform functions."""
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import _replay_transforms as mod
        assert hasattr(mod, "_rolling_zscore")
        assert hasattr(mod, "_freq_aware_zscore")

    def test_proxy_aggregation_imports(self):
        """_proxy_aggregation should export coupled_aggregate."""
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import _proxy_aggregation as mod
        assert hasattr(mod, "coupled_aggregate")
        assert hasattr(mod, "DEFAULT_ALPHA")

    def test_runtime_io_exports(self):
        """_runtime_io should export canonical I/O functions."""
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import _runtime_io as mod
        assert hasattr(mod, "load_json")
        assert hasattr(mod, "load_yaml")
        assert hasattr(mod, "ROOT")
