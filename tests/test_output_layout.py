"""Output root layout after the state/legacy split."""
from __future__ import annotations

import os
from pathlib import Path

from system_runtime.paths import CROSS_RUN_STATE_SURFACES, output_surface
from verity.runtime.runtime_io import ROOT, load_yaml

OUTPUT = ROOT / "Output"
POLICY = ROOT / "governance" / "output_routing_policy.yaml"


def test_live_symlink_is_relative_into_generations() -> None:
    live = OUTPUT / "live"
    assert live.is_symlink()
    target = os.readlink(live)
    assert "/Users/" not in target
    assert not target.startswith("/")
    assert target.startswith("generations/")
    assert (OUTPUT / target).is_dir()


def test_output_root_matches_routing_policy() -> None:
    policy = load_yaml(POLICY)
    allowed = set(policy["root_entries"])
    present = {p.name for p in OUTPUT.iterdir() if not p.name.startswith(".")}
    assert present == allowed
    assert len(present) <= 15


def test_compatibility_symlinks_point_at_live_surfaces() -> None:
    expected = {
        "current": "live/current",
        "position": "live/position",
        "judgment": "live/judgment",
        "trade_decision": "live/trade_decision",
        "trade_ledger": "live/trade_ledger",
        "quality": "live/quality",
        "system_learning": "live/system_learning",
        "ledgers": "live/trade_ledger",
    }
    for name, dest in expected.items():
        link = OUTPUT / name
        assert link.is_symlink(), name
        assert os.readlink(link) == dest


def test_state_surfaces_resolve_outside_generation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SYSTEM_GENERATION_DIR", str(tmp_path / "candidate"))
    path = output_surface(tmp_path, "caselab")
    assert path == tmp_path / "Output" / "state" / "caselab"
    assert "alerts" in CROSS_RUN_STATE_SURFACES
    assert "benchmarks" in CROSS_RUN_STATE_SURFACES


def test_legacy_archive_contains_proxy_and_measurement_dirs() -> None:
    legacy = OUTPUT / "archive" / "legacy_2026H1"
    for name in (
        "d_proxy_daily",
        "m_proxy_daily",
        "k_measurement",
        "x_measurement",
        "deformation_runs",
        "rebase",
        "solution",
        "practicality_trial",
    ):
        assert (legacy / name).is_dir(), name
