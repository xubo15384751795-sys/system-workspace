"""Run work cycle — the system's formal work entry point.

Orchestrates a complete work cycle: build work brief, signal card, data gaps,
run supervisor check, write run manifest.  This is how the system "does work".

Usage:
    python3 scripts/run_work_cycle.py                    # quick mode
    python3 scripts/run_work_cycle.py --mode quick       # quick mode
    python3 scripts/run_work_cycle.py --mode standard    # standard mode
    python3 scripts/run_work_cycle.py --mode full        # full refresh
    python3 scripts/run_work_cycle.py --json             # JSON output

Modes:
    quick_reaction: Read current artifacts, generate brief + signal card +
                    data gaps + supervisor check + run manifest.
                    No external data refresh.  No pipeline execution.
    standard_run:   Run core judgment chain, then all quick artifacts.
    full_refresh:   Full pipeline including Harvester, then all artifacts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
RUNS = ROOT / "Output" / "runs"
LEARNING = ROOT / "Output" / "system_learning" / "latest"
RUN_MODE_PATH = ROOT / "governance" / "run_mode_registry.yaml"

# RunBundle integration — use auditable path management
from _workspace_imports import add_scripts
add_scripts()
from run_bundle import RunBundle

# Scripts for standard/full modes
STANDARD_STEPS = [
    "scripts/bridge_replay_to_current.py",
    "scripts/quality_field_validator.py",
    "scripts/judgment_layer.py",
    "scripts/judgment_promotion_gate.py",
    "scripts/trade_decision_layer.py",
    "scripts/trade_risk_gate.py",
    "scripts/record_trade_decision.py",
    "scripts/market_feedback.py",
    "scripts/claim_evaluator.py",
    "scripts/claim_ladder_tracker.py",
    "scripts/learning_hub_comprehensive_summary.py",
    "scripts/build_system_index.py",
    "scripts/build_readme_first.py",
    "scripts/build_next_actions.py",
]

# Quick cycle scripts — read-only, no data refresh
QUICK_SCRIPTS = [
    "scripts/build_signal_card.py",
    "scripts/signal_consensus.py",
    "scripts/build_work_brief.py",
    "scripts/build_data_gaps.py",
]

GOVERNANCE_STATUS_SCRIPT = "scripts/governance_status.py"




def _load_mode_registry() -> dict[str, Any]:
    return yaml.safe_load(RUN_MODE_PATH.read_text(encoding="utf-8"))


def _run_script(script: str, timeout: int = 120) -> dict[str, Any]:
    """Run a script and return result."""
    script_path = ROOT / script
    if not script_path.exists():
        return {"script": script, "status": "MISSING", "returncode": -1}

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
        )
        return {
            "script": script,
            "status": "OK" if result.returncode == 0 else "FAIL",
            "returncode": result.returncode,
            "stderr_tail": result.stderr[-300:] if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"script": script, "status": "TIMEOUT", "returncode": -1}
    except Exception as e:
        return {"script": script, "status": "ERROR", "returncode": -1, "error": str(e)}


def _write_learning_hub_event(event_type: str, data: dict[str, Any]) -> None:
    """Append event to Learning Hub runtime log."""
    LEARNING.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    event_log = LEARNING / f"work_cycle_events_{today}.jsonl"

    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        **data,
    }
    with open(event_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")




def _collect_artifacts_written() -> list[str]:
    """Scan Output/current for recently modified artifacts (last 60s)."""
    if not CURRENT.exists():
        return []
    now = time.time()
    artifacts = []
    for item in sorted(CURRENT.iterdir()):
        if item.is_file() and (now - item.stat().st_mtime) < 60:
            artifacts.append(f"Output/current/{item.name}")
    return artifacts


def _record_step(bundle: RunBundle, result: dict[str, Any]) -> None:
    """Record a step result into the run bundle."""
    status_map = {"OK": "success", "FAIL": "failed", "MISSING": "missing",
                  "TIMEOUT": "timeout", "ERROR": "error"}
    bundle.record_step(
        name=result.get("step", result.get("script", "unknown")),
        status=status_map.get(result.get("status", ""), result.get("status", "unknown")),
        returncode=result.get("returncode", 0),
    )


def _capture_bundle_traces(bundle: RunBundle) -> None:
    """Capture decision + signal traces into the bundle."""
    for rel in [
        "Output/judgment/latest.json",
        "Output/trade_decision/latest.json",
        "Output/trade_decisions/latest.json",
    ]:
        p = ROOT / rel
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                bundle.capture_decision_trace({rel: data})
            except Exception:
                pass

    fw_path = CURRENT / "framework_output.json"
    if fw_path.exists():
        try:
            fw = json.loads(fw_path.read_text(encoding="utf-8"))
            sv = fw.get("advanced", {}).get("sigma_vector", {})
            bundle.capture_signal_trace({
                "framework_status": fw.get("status"),
                "overall": fw.get("basic", {}).get("overall"),
                "sigma_vector": sv,
            })
        except Exception:
            pass


def _run_governance_status(bundle: RunBundle, step_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate the visible governance status and record it as a normal step."""
    result = _run_script(GOVERNANCE_STATUS_SCRIPT)
    step = {"step": "governance_status", **result}
    step_results.append(step)
    _record_step(bundle, result)
    _write_learning_hub_event("governance_status_completed", {
        "status": result["status"],
    })
    return step


def run_quick_cycle(bundle: RunBundle) -> dict[str, Any]:
    """Quick reaction mode — read artifacts, build brief + signal card +
    data gaps, supervisor check.  No external data refresh."""
    _write_learning_hub_event("work_cycle_started", {"mode": "quick_reaction"})

    step_results = []
    for script in QUICK_SCRIPTS:
        result = _run_script(script)
        step_results.append({"step": Path(script).stem, **result})
        _record_step(bundle, result)
        _write_learning_hub_event("artifact_generated", {
            "step": Path(script).stem,
            "status": result["status"],
        })

    # Supervisor check
    supervisor_result = _run_script("scripts/run_supervisor_check.py")
    step_results.append({"step": "supervisor_check", **supervisor_result})
    _record_step(bundle, supervisor_result)
    _write_learning_hub_event("supervisor_check_completed", {
        "status": supervisor_result["status"],
    })

    _capture_bundle_traces(bundle)
    _run_governance_status(bundle, step_results)

    return {
        "mode": "quick_reaction",
        "steps": step_results,
    }


def run_standard_cycle(bundle: RunBundle) -> dict[str, Any]:
    """Standard run mode — run judgment chain, then all quick artifacts."""
    _write_learning_hub_event("work_cycle_started", {"mode": "standard_run"})

    step_results = []
    for script in STANDARD_STEPS:
        result = _run_script(script)
        step_results.append({"step": Path(script).stem, **result})
        _record_step(bundle, result)
        if result["status"] not in ("OK",):
            _write_learning_hub_event("module_activity_recorded", {
                "module": Path(script).stem,
                "status": result["status"],
            })

    # Quick artifacts after judgment chain
    for script in QUICK_SCRIPTS:
        result = _run_script(script)
        step_results.append({"step": Path(script).stem, **result})
        _record_step(bundle, result)
        _write_learning_hub_event("artifact_generated", {
            "step": Path(script).stem,
            "status": result["status"],
        })

    # Supervisor check
    supervisor_result = _run_script("scripts/run_supervisor_check.py")
    step_results.append({"step": "supervisor_check", **supervisor_result})
    _record_step(bundle, supervisor_result)
    _write_learning_hub_event("supervisor_check_completed", {
        "status": supervisor_result["status"],
    })

    _capture_bundle_traces(bundle)
    _run_governance_status(bundle, step_results)

    return {
        "mode": "standard_run",
        "steps": step_results,
    }


def run_full_cycle(bundle: RunBundle) -> dict[str, Any]:
    """Full refresh mode — run daily pipeline, then all artifacts."""
    _write_learning_hub_event("work_cycle_started", {"mode": "full_refresh"})

    # Run daily pipeline
    pipeline_result = _run_script("scripts/daily_run.py", timeout=600)

    step_results = [{"step": "daily_pipeline", **pipeline_result}]
    _record_step(bundle, pipeline_result)

    # Quick artifacts after pipeline
    for script in QUICK_SCRIPTS:
        result = _run_script(script)
        step_results.append({"step": Path(script).stem, **result})
        _record_step(bundle, result)
        _write_learning_hub_event("artifact_generated", {
            "step": Path(script).stem,
            "status": result["status"],
        })

    # Supervisor check
    supervisor_result = _run_script("scripts/run_supervisor_check.py")
    step_results.append({"step": "supervisor_check", **supervisor_result})
    _record_step(bundle, supervisor_result)
    _write_learning_hub_event("supervisor_check_completed", {
        "status": supervisor_result["status"],
    })

    _capture_bundle_traces(bundle)
    _run_governance_status(bundle, step_results)

    return {
        "mode": "full_refresh",
        "steps": step_results,
    }


def summarize_result(result: dict[str, Any]) -> str:
    """Generate human-readable summary with work brief highlights."""
    lines = [
        f"# Work Cycle Result — {result['mode']}",
        "",
        f"**Run ID:** {result.get('run_id', 'unknown')}",
        f"**Mode:** {result['mode']}",
        f"**Steps completed:** {len(result['steps'])}",
        "",
    ]

    all_ok = True
    for step in result["steps"]:
        icon = "✅" if step["status"] == "OK" else "❌"
        if step["status"] != "OK":
            all_ok = False
        lines.append(f"- {icon} {step['step']}: {step['status']}")

    lines.append("")
    lines.append(f"**Overall:** {'✅ ALL STEPS OK' if all_ok else '⚠️ SOME STEPS FAILED'}")

    # Load work brief for key sections
    brief_path = CURRENT / "work_brief.json"
    if brief_path.exists():
        try:
            brief = json.loads(brief_path.read_text(encoding="utf-8"))

            # Current reaction
            r = brief.get("reaction", {})
            lines += [
                "",
                "## Current Reaction",
                "",
                f"- Judgment: **{r.get('judgment_decision', 'N/A')}**",
                f"- Confidence: **{r.get('confidence', 'N/A')}**",
                f"- Trade: **{r.get('trade_decision', 'N/A')}**",
                f"- Promotion gate: **{r.get('promotion_gate', 'N/A')}**",
            ]

            # Blocker
            blocker = brief.get("most_important_blocker", "")
            if blocker:
                lines += ["", f"**Blocker:** {blocker}"]

            # Can say / Cannot say
            can_say = brief.get("can_say", [])
            if can_say:
                lines += ["", "### Can Say", ""]
                for item in can_say:
                    lines.append(f"- {item}")

            cannot_say = brief.get("cannot_say", [])
            if cannot_say:
                lines += ["", "### Cannot Say", ""]
                for item in cannot_say:
                    lines.append(f"- {item}")

            # Mechanism hypothesis
            mh = brief.get("mechanism_hypothesis", {})
            if mh.get("mechanisms"):
                lines += [
                    "",
                    "### Mechanism Hypothesis",
                    "",
                    f"- Mechanisms: {', '.join(mh.get('mechanisms', []))}",
                    f"- Match quality: {mh.get('match_quality', 'N/A')} (score={mh.get('top_score', 0):.3f})",
                ]

            # Most important limiter
            limiters = brief.get("limiters", [])
            if limiters:
                lines += ["", f"**Most important limiter:** {limiters[0]}"]

            # Next verification
            next_work = brief.get("next_work", [])
            if next_work:
                lines += ["", "### Next Verification", ""]
                for i, action in enumerate(next_work, 1):
                    lines.append(f"{i}. {action}")

            # Needs full refresh
            refresh = brief.get("needs_full_refresh", {})
            if refresh:
                needed = refresh.get("needed", False)
                rec = refresh.get("recommendation", "unknown")
                icon = "🔴" if needed else "🟢"
                lines += ["", f"{icon} **Needs full refresh:** {'YES' if needed else 'No'} ({rec})"]

        except Exception:
            pass

    if result.get("artifacts_written"):
        lines += ["", "## Artifacts Written", ""]
        for artifact in result["artifacts_written"]:
            lines.append(f"- {artifact}")

    lines += [
        "",
        f"**Elapsed:** {result.get('elapsed_seconds', 0)}s",
        f"**Manifest:** Output/runs/{result.get('run_id', '?')}/run_manifest.json",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run work cycle")
    parser.add_argument(
        "--mode", default="quick",
        choices=["quick", "standard", "full"],
        help="Work cycle mode",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    mode_map = {
        "quick": run_quick_cycle,
        "standard": run_standard_cycle,
        "full": run_full_cycle,
    }

    # Create run bundle
    bundle = RunBundle.start(mode=f"work_cycle_{args.mode}")

    start = time.time()
    result = mode_map[args.mode](bundle)
    elapsed = time.time() - start

    result["elapsed_seconds"] = round(elapsed, 1)
    result["run_id"] = bundle.run_id

    # Record artifacts into bundle
    artifacts_written = _collect_artifacts_written()
    result["artifacts_written"] = artifacts_written
    for artifact_rel in artifacts_written:
        bundle.record_artifact(ROOT / artifact_rel)

    # Finish run bundle
    overall = "OK" if all(s.get("status") == "OK" for s in result["steps"]) else "PARTIAL"
    bundle.finish(status=overall)

    # Refresh governance status after the bundle has its final manifest.
    governance_result = _run_script(GOVERNANCE_STATUS_SCRIPT)
    if governance_result.get("status") == "OK":
        for artifact_rel in [
            "Output/system_learning/latest/governance_status.json",
            "Output/system_learning/latest/governance_status.md",
        ]:
            artifact = ROOT / artifact_rel
            if artifact.exists():
                bundle.record_artifact(artifact)

    _write_learning_hub_event("work_cycle_completed", {
        "run_id": bundle.run_id,
        "mode": result["mode"],
        "elapsed_seconds": result["elapsed_seconds"],
        "overall_status": overall,
    })

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(summarize_result(result))


if __name__ == "__main__":
    main()
