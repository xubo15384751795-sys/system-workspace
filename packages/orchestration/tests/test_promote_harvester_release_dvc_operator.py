from __future__ import annotations

import json
from pathlib import Path

from orchestration.operators import promote_harvester_release_dvc as operator


def test_operator_records_pointer_off_daily_path(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "dvc-release.json"
    expected = {"dvc_commit_status": "BLOCKED", "dvc_error": "DVC_DISABLED"}

    monkeypatch.setattr(
        operator,
        "record_release_pointer",
        lambda **_kwargs: expected,
    )

    assert (
        operator.main(
            [
                "2026-09-04-r1",
                "--exports-root",
                str(tmp_path / "exports"),
                "--report",
                str(report),
            ]
        )
        == 2
    )
    assert json.loads(report.read_text(encoding="utf-8")) == expected
