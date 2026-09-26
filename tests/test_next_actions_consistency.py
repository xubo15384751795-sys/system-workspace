"""Status hand-off contracts for the current readout generators."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from workbench.surfaces import build_next_actions

from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import load_pipeline

ROOT = Path(__file__).resolve().parents[1]


def _status() -> dict:
    return {
        "generated_at": "2026-08-24T00:00:00+00:00",
        "date": "2026-08-24",
        "judgment": {
            "decision": "ACTIVE_WATCH",
            "confidence": "medium",
            "claim_ceiling": "mechanism_hypothesis",
        },
        "promotion_gate": {
            "status": "WATCH",
            "blocked_gates": [],
            "watch_gates": ["claim_ceiling"],
            "blocking_reasons": [],
            "watch_reasons": ["fixture watch"],
            "forbidden_language": [],
            "allowed_language": ["watch"],
        },
        "signals": {"caselab": {}, "hmm": {}, "k_gate": {}, "x_gate": {}},
    }


def test_next_actions_reads_canonical_status_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "current"
    output_dir.mkdir()
    (output_dir / "status.json").write_text(
        json.dumps(_status()), encoding="utf-8"
    )
    monkeypatch.setattr(build_next_actions, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(
        build_next_actions,
        "gather_status",
        lambda: pytest.fail("next_actions must consume status.json when present"),
    )

    status = build_next_actions._load_current_status()
    markdown = build_next_actions.build_next_actions_md(status, [])

    assert status["judgment"]["decision"] == "ACTIVE_WATCH"
    assert "- **Decision:** ACTIVE_WATCH" in markdown
    assert "- **Decision:** None" not in markdown


def test_current_status_is_a_compiled_upstream_of_next_actions() -> None:
    plan = load_pipeline(WorkspacePaths(root=ROOT))

    assert "current_status" in plan.edges["next_actions"]
    sequence = [step["id"] for step in plan.sequence()]
    assert sequence.index("current_status") < sequence.index("next_actions")
