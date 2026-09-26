"""Evidence grade contributor drill-down tests."""
from __future__ import annotations

from workbench.surfaces.build_evidence_grade_report import (
    _build_contributor_drill_down,
    _build_contributors,
)


def test_contributor_drill_down_includes_artifact_paths() -> None:
    contributors = _build_contributors(None, None, None, None, None, None, None)
    blockers = []
    drill = _build_contributor_drill_down(contributors, blockers)

    assert len(drill) == len(contributors)
    paper = next(item for item in drill if item["source"] == "paper_world_model")
    assert paper["artifact_paths"]
    assert "grade_if_admitted" in paper
    assert isinstance(paper["upgrade_actions"], list)
