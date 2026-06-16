"""Daily routing decision — record which modules handled today's tasks.

Lightweight activation of Agent Routing: reads the daily run steps
and produces a routing decision record for the Learning Hub.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_SRC = ROOT / "Workbench" / "agents"
sys.path.insert(0, str(HARNESS_SRC))

from harness.tools.task_router import route_task


def generate_daily_routing(steps: list[dict]) -> dict:
    """Generate routing decisions for each daily run step."""
    decisions = []
    for step in steps:
        name = step.get("step", "")
        status = step.get("status", "")

        # Map step names to task descriptions
        task_map = {
            "harvester": "Fetch latest market data from providers",
            "etf_refresh": "Refresh ETF panel and K features from OpenBB",
            "structural_replay": "Run structural replay on latest harvester release",
            "bridge": "Bridge replay output to current framework output",
            "regime_detection": "Detect current market regime via HMM",
            "research_posture": "Generate research posture digest",
            "practicality_note": "Generate practicality trial daily note",
            "caselab_signal": "Match current state to historical CaseLab cases",
            "governance_audit": "Run learning hub governance audit",
        }

        task = task_map.get(name, f"Execute {name}")
        routing = route_task(task)

        decisions.append({
            "step": name,
            "status": status,
            "task": task,
            "module": routing.get("primary_module", "unknown"),
            "mode": routing.get("recommended_mode", "unknown"),
            "experts": [e.get("protocol", "") for e in routing.get("activated_experts", [])],
        })

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "total_decisions": len(decisions),
        "decisions": decisions,
        "modules_used": list(set(d["module"] for d in decisions)),
        "modes_used": list(set(d["mode"] for d in decisions)),
    }


if __name__ == "__main__":
    # Read latest daily run log
    runtime_dir = ROOT / "Output" / "runtime_events"
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    log_path = runtime_dir / f"{today}.jsonl"

    if not log_path.exists():
        print(f"No daily run log for {today}")
        sys.exit(0)

    # Get the last run
    lines = log_path.read_text().strip().split("\n")
    last_run = json.loads(lines[-1])
    steps = last_run.get("steps", [])

    result = generate_daily_routing(steps)
    print(json.dumps(result, indent=2))
