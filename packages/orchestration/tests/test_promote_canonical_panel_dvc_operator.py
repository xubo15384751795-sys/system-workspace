from __future__ import annotations

import json
from pathlib import Path

from orchestration.operators import promote_canonical_panel_dvc as operator


def test_verify_only_can_persist_evidence_report(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "panels.duckdb"
    database.write_bytes(b"candidate")
    report = tmp_path / "dvc-verify.json"
    expected = {"status": "BLOCKED", "promotion_allowed": False}

    monkeypatch.setattr(
        operator,
        "verify_canonical_panel_pointer",
        lambda **_kwargs: expected,
    )

    assert (
        operator.main(
            [
                "--database",
                str(database),
                "--verify-only",
                "--report",
                str(report),
            ]
        )
        == 2
    )
    assert json.loads(report.read_text(encoding="utf-8")) == expected
