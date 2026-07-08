from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.observability import render_run_observability_summary
from workbench.governance.report_gate import validate_report_verdict


def test_observability_summary_renders_actionable_verdict(tmp_path) -> None:
    semantic = tmp_path / "semantic_registry.json"
    semantic.write_text(
        json.dumps(
            {
                "K": {
                    "implemented_status": "PARTIAL",
                    "proxy_status": "PROXY_REDUCED",
                    "semantic_distance": 3,
                    "operational_proxy": "K basket",
                    "reduction_errors": ["reduced"],
                    "valid_for": ["warning"],
                    "not_valid_for": ["full curvature"],
                }
            }
        ),
        encoding="utf-8",
    )
    decision_trace = tmp_path / "decision_trace.jsonl"
    decision_trace.write_text(json.dumps({"decision_impact": "BLOCK"}) + "\n", encoding="utf-8")
    authority_trace = tmp_path / "authority_trace.jsonl"
    authority_trace.write_text(json.dumps({"event_type": "AUTHORITY_VIOLATION"}) + "\n", encoding="utf-8")
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()
    (routing_dir / "deny.yaml").write_text(
        """
promotion_gate_decision:
  may_promote_current_snapshot: false
  reason: "semantic risk"
  blocking_findings:
    - "PROXY_REDUCED"
  required_actions:
    - "Review semantic metadata"
""",
        encoding="utf-8",
    )

    summary = render_run_observability_summary(
        run_id="run_1",
        semantic_registry_path=semantic,
        decision_trace_path=decision_trace,
        authority_trace_path=authority_trace,
        routing_dir=routing_dir,
    )
    report = tmp_path / "summary.md"
    report.write_text(summary, encoding="utf-8")

    assert "Promotion result: BLOCKED" in summary
    assert "| BLOCK | 1 |" in summary
    assert validate_report_verdict(report)["verdict"] == "BLOCK"
