"""Dagster ops for the Output/current refresh chain."""
from __future__ import annotations

import sys
import time
from typing import Any

from dagster import In, Nothing, op

from scripts._admission_gate import admit_for_consumption
from scripts._constants import TIMEOUT_STANDARD
from scripts._runtime_io import ROOT


def _run_script(label: str, script: str, *extra_args: str) -> dict[str, Any]:
    import subprocess

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *extra_args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_STANDARD,
            cwd=str(ROOT),
        )
        return {
            "step": label,
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "duration_s": round(time.time() - start, 1),
            "stdout_tail": (result.stdout or "")[-300:],
            "stderr_tail": (result.stderr or "")[-300:],
        }
    except subprocess.TimeoutExpired:
        return {"step": label, "status": "timeout", "duration_s": TIMEOUT_STANDARD}
    except Exception as exc:  # noqa: BLE001 — surface as step error
        return {"step": label, "status": "error", "error": str(exc), "duration_s": 0}


# Order matters for freshness closure: risk_gate + readme_first must be written
# before freshness_validator runs, otherwise ordering/closure hard-FAIL.
REFRESH_PRODUCER_STEPS: list[tuple[str, str]] = [
    ("quality_validation", "quality_field_validator.py"),
    ("measurement_quality", "commands/weekly/build_measurement_quality_report.py"),
    ("judgment_layer", "judgment_layer.py"),
    ("promotion_gate", "judgment_promotion_gate.py"),
    ("trade_decision", "trade_decision_layer.py"),
    ("trade_risk_gate", "trade_risk_gate.py"),
    ("record_trade_decision", "record_trade_decision.py"),
    ("signal_card", "build_signal_card.py"),
    ("signal_consensus", "signal_consensus.py"),
    ("current_status", "build_current_status.py"),
    ("system_index", "build_system_index.py"),
    ("work_brief", "build_work_brief.py"),
    ("next_actions", "commands/weekly/build_next_actions.py"),
    ("improvement_queue_report", "refresh_improvement_queue_report.py"),
    ("evidence_grade", "commands/weekly/build_evidence_grade_report.py"),
    ("artifact_registry", "commands/weekly/build_artifact_registry.py"),
    ("run_event", "record_daily_run_event.py"),
    ("readme_first", "commands/weekly/build_readme_first.py"),
    ("freshness_validator", "freshness_validator.py"),
]


@op(name="refresh_admission")
def refresh_admission_op(context):
    start = time.time()
    decision = admit_for_consumption("refresh_current")
    result = {
        "step": "pre_consumption_admission",
        "status": "success" if decision.allowed else "blocked",
        "duration_s": round(time.time() - start, 1),
        "blockers": list(decision.blockers),
        "checked_at": decision.checked_at,
    }
    if result["status"] != "success":
        context.log.error("Refresh admission blocked: %s", result["blockers"])
        raise RuntimeError(f"refresh admission blocked: {result['blockers']}")
    return result


@op(
    name="refresh_producers",
    ins={"admission": In(Nothing)},
)
def refresh_producers_op(context, skip_measurement=False):
    steps = []
    if not skip_measurement:
        result = _run_script("neutral_pressure_measurement", "neutral_pressure_measurement.py")
        steps.append(result)
        if result["status"] != "success":
            raise RuntimeError("neutral_pressure_measurement failed")
    for label, script in REFRESH_PRODUCER_STEPS:
        extra = ("--skip-if-unchanged",) if label == "run_event" else ()
        result = _run_script(label, script, *extra)
        steps.append(result)
        context.log.info("%s -> %s", label, result["status"])
        if result["status"] != "success":
            raise RuntimeError(f"refresh stopped after {label}")
    return {"steps": steps}
