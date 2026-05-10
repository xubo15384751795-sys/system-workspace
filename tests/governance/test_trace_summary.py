from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.trace_summary import count_decision_impacts, summarize_trace_paths


def test_count_decision_impacts_includes_zeroes() -> None:
    counts = count_decision_impacts(
        [
            {"decision_impact": "BLOCK"},
            {"decision_impact": "BLOCK"},
            {"decision_impact": "DISPLAY_ONLY"},
        ]
    )

    assert counts["BLOCK"] == 2
    assert counts["DISPLAY_ONLY"] == 1
    assert counts["PROMOTE"] == 0


def test_summarize_trace_paths_counts_authority_and_decisions(tmp_path) -> None:
    decision_path = tmp_path / "decision_trace.jsonl"
    authority_path = tmp_path / "authority_trace.jsonl"
    decision_path.write_text(
        "\n".join(
            [
                json.dumps({"decision_impact": "BLOCK"}),
                json.dumps({"decision_impact": "ACTION_REQUIRED"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    authority_path.write_text(
        "\n".join(
            [
                json.dumps({"event_type": "AUTHORITY_CHECK"}),
                json.dumps({"event_type": "AUTHORITY_VIOLATION"}),
                json.dumps({"event_type": "AUTHORITY_CONFIG_ENABLED"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_trace_paths(decision_trace_path=decision_path, authority_trace_path=authority_path)

    assert summary["decision_impact_counts"]["BLOCK"] == 1
    assert summary["authority"]["authority_violations"] == 1
    assert summary["authority"]["authority_configs_enabled"] == 1

