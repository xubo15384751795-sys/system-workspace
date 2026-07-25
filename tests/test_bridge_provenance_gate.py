"""Archived Deformation bridge execution-boundary tests.

The bridge is evidence-only after v1 falsification. It must never run inside a
daily bundle or write authoritative current output. An explicit reproduction
override is valid only with an isolated output directory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bridge_replay_to_current as bridge  # noqa: E402


@pytest.fixture
def isolated_layout(tmp_path, monkeypatch):
    """Point bridge at tmp REPLAY_DIR / CURRENT and isolate env."""
    replay_dir = tmp_path / "sandbox" / "structural_replay_v2"
    current_dir = tmp_path / "current"
    replay_dir.mkdir(parents=True)
    current_dir.mkdir(parents=True)

    monkeypatch.setattr(bridge, "REPLAY_DIR", replay_dir)
    monkeypatch.setattr(bridge, "CURRENT", current_dir)
    # build_framework_output reads harvester catalog etc.; we only test the
    # provenance gate at main() entry, which exits before build_framework_output
    # on rejection. For the acceptance path we stub build_framework_output.
    monkeypatch.delenv("ZCODE_BUNDLE_RUN_ID", raising=False)
    monkeypatch.delenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", raising=False)
    monkeypatch.delenv("CURRENT_OUTPUT_DIR", raising=False)
    return replay_dir, current_dir


def _write_sigma(replay_dir: Path, run_id: str | None) -> None:
    sv = {
        "sigma_scalar": None,
        "sigma_vector": {"M": 0.1, "D": 0.2},
        "channel_velocity": {},
        "channel_acceleration": {},
        "velocity_window": 20,
        "interpretation_scope": "test",
    }
    if run_id is not None:
        sv["run_id"] = run_id
    (replay_dir / "sigma_vector.json").write_text(
        json.dumps(sv), encoding="utf-8"
    )


def _stub_framework_output() -> dict:
    """Minimal fw_output structure that main() can walk without KeyError."""
    return {
        "schema_version": "stub",
        "basic": {"overall": "ACTIVE_FULL", "quality_status": "OK"},
        "advanced": {
            "coverage_ratio": 1.0,
            "primary_readout": {"state": "STABLE"},
            "measurement_eligibility": {},
        },
        "as_of": "2026-07-17T00:00:00Z",
    }


class TestArchivedBridgeBoundary:
    def test_default_execution_is_rejected(self, isolated_layout, monkeypatch):
        replay_dir, current_dir = isolated_layout
        _write_sigma(replay_dir, run_id="yesterday_bundle_run_id")

        with pytest.raises(SystemExit) as exc:
            bridge.main()
        assert "ARCHIVED_FALSIFIED" in str(exc.value)

        assert not (current_dir / "framework_output.json").exists()

    def test_daily_bundle_is_rejected_even_with_override(self, isolated_layout, monkeypatch):
        replay_dir, current_dir = isolated_layout
        _write_sigma(replay_dir, run_id="today_bundle_run_id")
        monkeypatch.setenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", "1")
        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(current_dir))
        monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "today_bundle_run_id")

        with pytest.raises(SystemExit) as exc:
            bridge.main()
        assert "forbidden inside a daily run bundle" in str(exc.value)
        assert not (current_dir / "framework_output.json").exists()

    def test_current_writer_requires_isolated_output(self, isolated_layout, monkeypatch):
        replay_dir, current_dir = isolated_layout
        _write_sigma(replay_dir, run_id="manual_run")
        monkeypatch.setenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", "1")

        with pytest.raises(SystemExit) as exc:
            bridge.main()
        assert "isolated CURRENT_OUTPUT_DIR" in str(exc.value)
        assert not (current_dir / "framework_output.json").exists()

    def test_explicit_isolated_reproduction_is_allowed(self, isolated_layout, monkeypatch):
        replay_dir, current_dir = isolated_layout
        _write_sigma(replay_dir, run_id="manual_run")
        monkeypatch.setenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", "1")
        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(current_dir))

        monkeypatch.setattr(
            bridge, "build_framework_output", _stub_framework_output
        )
        monkeypatch.setattr(bridge, "generate_summary", lambda fw: "stub summary")
        monkeypatch.setattr(bridge, "_load_replay_results", lambda: [])
        monkeypatch.setattr(bridge, "write_rebase_outputs", lambda fw: {})

        bridge.main()
        assert (current_dir / "framework_output.json").exists()
