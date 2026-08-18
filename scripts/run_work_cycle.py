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
                    No external data refresh.  Candidate-only by default.
    standard_run:   Run core judgment chain, then all quick artifacts.
                    Candidate-only by default.
    full_refresh:   Owned by the scheduled daily/Dagster path; direct
                    work-cycle execution requires explicit legacy opt-in.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_bundle import RunBundle

from scripts._constants import TIMEOUT_LONG  # noqa: E402
from scripts._pipeline_runner import run_registry_step

# RunBundle integration — use auditable path management
from scripts._runtime_io import ROOT, current_dir, ensure_dir, load_yaml, surface_dir
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import load_pipeline
from system_runtime.publish_transaction import PublishTransaction

logger = logging.getLogger(__name__)

RUNS = ROOT / "Output" / "runs"
RUN_MODE_PATH = ROOT / "governance" / "run_mode_registry.yaml"

QUICK_RENDER_PROFILE = "work_cycle_quick_render"
STANDARD_CORE_PROFILE = "work_cycle_standard_core"
ALWAYS_PROFILE = "work_cycle_always"


def _current_dir() -> Path:
    """Resolve the current surface at call time, after candidate activation."""
    return current_dir()


def _learning_dir() -> Path:
    """Resolve the Learning Hub surface at call time, after candidate activation."""
    return surface_dir("system_learning") / "latest"


def _legacy_work_cycle_enabled() -> bool:
    """Allow the pre-generation direct-write path only by explicit opt-in."""
    return os.environ.get("SYSTEM_USE_LEGACY_WORK_CYCLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _seed_candidate_baseline(transaction: PublishTransaction) -> None:
    """Copy accepted compatibility surfaces into a candidate read baseline.

    Work-cycle renderers need prior judgment/quality/context to explain what
    changed.  Seeding the candidate preserves that read context while keeping
    every new write inside the run bundle; the candidate is never published by
    this entry point.
    """
    copy_surfaces = {
        "current",
        "position",
        "judgment",
        "trade_decision",
        "trade_ledger",
        "quality",
        "system_learning",
    }
    for name, target in transaction.candidate_dirs.items():
        if name not in copy_surfaces:
            continue
        source = ROOT / "Output" / name
        if not source.is_dir():
            continue
        shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)


def _profile_step_ids(profile: str) -> list[str]:
    """Resolve a work-cycle projection from the canonical compiled plan."""
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    return [step.step_id for step in plan.projection(profile)]


def _run_plan_step(step_id: str) -> dict[str, Any]:
    """Run one compiled step and retain the work-cycle status vocabulary."""
    result = run_registry_step(step_id)
    status_map = {
        "success": "OK",
        "failed": "FAIL",
        "missing": "MISSING",
        "timeout": "TIMEOUT",
        "error": "ERROR",
    }
    return {
        "script": step_id,
        **result,
        "status": status_map.get(result.get("status", ""), result.get("status", "ERROR")),
    }




def _load_mode_registry() -> dict[str, Any]:
    return load_yaml(RUN_MODE_PATH)


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
    learning = _learning_dir()
    ensure_dir(learning)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    event_log = learning / f"work_cycle_events_{today}.jsonl"

    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        **data,
    }
    with open(event_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")




def _collect_artifacts_written() -> list[str]:
    """Scan the active current candidate for recently modified artifacts."""
    current = _current_dir()
    if not current.exists():
        return []
    now = time.time()
    artifacts = []
    for item in sorted(current.iterdir()):
        if item.is_file() and (now - item.stat().st_mtime) < 60:
            artifacts.append(str(item.relative_to(ROOT)))
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
        "judgment/latest.json",
        "trade_decision/latest.json",
        "trade_decisions/latest.json",
    ]:
        surface, name = rel.split("/", 1)
        p = surface_dir(surface) / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                bundle.capture_decision_trace({f"Output/{rel}": data})
            except (json.JSONDecodeError, OSError, KeyError):
                logger.debug("Unable to capture decision trace from %s", p, exc_info=True)

    fw_path = _current_dir() / "framework_output.json"
    if fw_path.exists():
        try:
            fw = json.loads(fw_path.read_text(encoding="utf-8"))
            sv = fw.get("advanced", {}).get("sigma_vector", {})
            bundle.capture_signal_trace({
                "framework_status": fw.get("status"),
                "overall": fw.get("basic", {}).get("overall"),
                "sigma_vector": sv,
            })
        except (json.JSONDecodeError, OSError, KeyError):
            logger.debug("Unable to capture framework signal trace from %s", fw_path, exc_info=True)


def _data_freshness() -> dict[str, Any]:
    """Check if framework_output has changed since last work cycle."""
    fw_path = _current_dir() / "framework_output.json"
    if not fw_path.exists():
        return {"fresh": False, "reason": "missing"}

    fw_mtime = os.path.getmtime(fw_path)

    # Check last work cycle run
    latest_pointer = RUNS / "latest_work_cycle.txt"
    if latest_pointer.exists():
        try:
            last_run_dir = Path(latest_pointer.read_text().strip())
            manifest_path = last_run_dir / "manifest.json" if last_run_dir.is_dir() else None
            if manifest_path and manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                last_finished = manifest.get("finished_at", "")
                if last_finished:
                    last_ts = datetime.fromisoformat(last_finished).timestamp()
                    if fw_mtime <= last_ts:
                        return {"fresh": False, "reason": "no_change_since_last_run"}
        except (ValueError, OSError):
            logger.warning("Unable to establish freshness from latest work-cycle manifest", exc_info=True)
            return {"fresh": False, "reason": "latest_work_cycle_manifest_unparseable"}

    return {"fresh": True, "reason": "data_updated"}


def _update_latest_work_cycle_pointer(bundle: RunBundle) -> None:
    """Update pointer to latest work cycle run."""
    if not _legacy_work_cycle_enabled():
        # Candidate-only work cycles must not make an uncommitted or partial
        # bundle authoritative input for the next freshness decision.
        return
    pointer = RUNS / "latest_work_cycle.txt"
    pointer.write_text(str(bundle.run_dir), encoding="utf-8")


def run_quick_cycle(bundle: RunBundle) -> dict[str, Any]:
    """Quick reaction mode — check freshness, run change analysis,
    supervisor check.  Skip re-rendering if data hasn't changed."""
    _write_learning_hub_event("work_cycle_started", {"mode": "quick_reaction"})

    step_results = []
    freshness = _data_freshness()

    if freshness["fresh"]:
        # Data changed — re-render all quick artifacts
        for step_id in _profile_step_ids(QUICK_RENDER_PROFILE):
            result = _run_plan_step(step_id)
            step_results.append(result)
            _record_step(bundle, result)
            _write_learning_hub_event("artifact_generated", {
                "step": step_id,
                "status": result["status"],
            })
    else:
        # Data unchanged — skip re-rendering, only run analysis
        _write_learning_hub_event("work_cycle_skipped_rerender", {
            "reason": freshness["reason"],
        })

    # Always run the analysis/supervisor part of the compiled work-cycle tail.
    always_results = []
    for step_id in _profile_step_ids(ALWAYS_PROFILE):
        result = _run_plan_step(step_id)
        step_results.append(result)
        always_results.append(result)
        _record_step(bundle, result)
    supervisor_result = next(
        (result for result in always_results if result["step"] == "supervisor_check"),
        {"status": "ERROR"},
    )
    _write_learning_hub_event("supervisor_check_completed", {
        "status": supervisor_result["status"],
    })
    governance_result = next(
        (result for result in always_results if result["step"] == "governance_status"),
        {"status": "ERROR"},
    )
    _write_learning_hub_event("governance_status_completed", {
        "status": governance_result["status"],
    })

    _capture_bundle_traces(bundle)
    _update_latest_work_cycle_pointer(bundle)

    return {
        "mode": "quick_reaction",
        "data_freshness": freshness,
        "steps": step_results,
    }


def run_standard_cycle(bundle: RunBundle) -> dict[str, Any]:
    """Standard run mode — run judgment chain if data changed, then analysis."""
    _write_learning_hub_event("work_cycle_started", {"mode": "standard_run"})

    step_results = []
    freshness = _data_freshness()

    if freshness["fresh"]:
        # Data changed — run full judgment chain
        for step_id in _profile_step_ids(STANDARD_CORE_PROFILE):
            result = _run_plan_step(step_id)
            step_results.append(result)
            _record_step(bundle, result)
            if result["status"] not in ("OK",):
                _write_learning_hub_event("module_activity_recorded", {
                    "module": step_id,
                    "status": result["status"],
                })

        # Quick artifacts after judgment chain
        for step_id in _profile_step_ids(QUICK_RENDER_PROFILE):
            result = _run_plan_step(step_id)
            step_results.append(result)
            _record_step(bundle, result)
            _write_learning_hub_event("artifact_generated", {
                "step": step_id,
                "status": result["status"],
            })
    else:
        # Data unchanged — skip judgment chain, only run analysis
        _write_learning_hub_event("standard_cycle_skipped_judgment", {
            "reason": freshness["reason"],
        })

    # Always run the analysis/supervisor part of the compiled work-cycle tail.
    always_results = []
    for step_id in _profile_step_ids(ALWAYS_PROFILE):
        result = _run_plan_step(step_id)
        step_results.append(result)
        always_results.append(result)
        _record_step(bundle, result)
    supervisor_result = next(
        (result for result in always_results if result["step"] == "supervisor_check"),
        {"status": "ERROR"},
    )
    _write_learning_hub_event("supervisor_check_completed", {
        "status": supervisor_result["status"],
    })
    governance_result = next(
        (result for result in always_results if result["step"] == "governance_status"),
        {"status": "ERROR"},
    )
    _write_learning_hub_event("governance_status_completed", {
        "status": governance_result["status"],
    })

    _capture_bundle_traces(bundle)
    _update_latest_work_cycle_pointer(bundle)

    return {
        "mode": "standard_run",
        "data_freshness": freshness,
        "steps": step_results,
    }


def run_full_cycle(bundle: RunBundle) -> dict[str, Any]:
    """Full refresh mode — run daily pipeline, then all artifacts."""
    _write_learning_hub_event("work_cycle_started", {"mode": "full_refresh"})

    # Run daily pipeline
    pipeline_result = _run_script("scripts/daily_run.py", timeout=TIMEOUT_LONG)

    step_results = [{"step": "daily_pipeline", **pipeline_result}]
    _record_step(bundle, {"step": "daily_pipeline", **pipeline_result})

    # Quick artifacts after pipeline
    for step_id in _profile_step_ids(QUICK_RENDER_PROFILE):
        result = _run_plan_step(step_id)
        step_results.append(result)
        _record_step(bundle, result)
        _write_learning_hub_event("artifact_generated", {
            "step": step_id,
            "status": result["status"],
        })

    # Supervisor and governance tail comes from the same compiled projection.
    always_results = []
    for step_id in _profile_step_ids(ALWAYS_PROFILE):
        result = _run_plan_step(step_id)
        step_results.append(result)
        always_results.append(result)
        _record_step(bundle, result)
    supervisor_result = next(
        (result for result in always_results if result["step"] == "supervisor_check"),
        {"status": "ERROR"},
    )
    _write_learning_hub_event("supervisor_check_completed", {
        "status": supervisor_result["status"],
    })
    governance_result = next(
        (result for result in always_results if result["step"] == "governance_status"),
        {"status": "ERROR"},
    )
    _write_learning_hub_event("governance_status_completed", {
        "status": governance_result["status"],
    })

    _capture_bundle_traces(bundle)

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
    brief_path = _current_dir() / "work_brief.json"
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

        except (json.JSONDecodeError, OSError, KeyError):
            logger.warning("Unable to render work brief details", exc_info=True)

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

    legacy_work_cycle = _legacy_work_cycle_enabled()
    if args.mode == "full" and not legacy_work_cycle:
        message = (
            "full_refresh is owned by the scheduled Dagster path; set "
            "SYSTEM_USE_LEGACY_WORK_CYCLE=1 only for an explicitly audited legacy run"
        )
        print(message, file=sys.stderr)
        raise SystemExit(78)

    mode_map = {
        "quick": run_quick_cycle,
        "standard": run_standard_cycle,
        "full": run_full_cycle,
    }

    # Create run bundle
    # A work-cycle bundle is diagnostic/candidate output by default.  It must
    # never advance Output/current before the scheduled admission/publisher.
    bundle = RunBundle.start(mode=f"work_cycle_{args.mode}", update_pointer=False)
    transaction: PublishTransaction | None = None
    previous_generation_mode = os.environ.get("SYSTEM_GENERATION_MODE")

    if not legacy_work_cycle:
        transaction = PublishTransaction(bundle.run_id, bundle.run_dir)
        transaction.prepare()
        _seed_candidate_baseline(transaction)
        os.environ["SYSTEM_GENERATION_MODE"] = "1"
        transaction.activate()

    try:
        start = time.time()
        result = mode_map[args.mode](bundle)
        elapsed = time.time() - start

        result["elapsed_seconds"] = round(elapsed, 1)
        result["run_id"] = bundle.run_id
        result["candidate_only"] = not legacy_work_cycle

        # Record artifacts into the run bundle, never into a live surface.
        artifacts_written = _collect_artifacts_written()
        result["artifacts_written"] = artifacts_written
        for artifact_rel in artifacts_written:
            bundle.record_artifact(ROOT / artifact_rel)

        # Finish the work-cycle bundle before the governance tail, preserving
        # the existing bundle contract while keeping all writer surfaces in
        # the active candidate.
        overall = "OK" if all(s.get("status") == "OK" for s in result["steps"]) else "PARTIAL"
        bundle.finish(status=overall)

        governance_result = _run_plan_step("governance_status")
        if governance_result.get("status") == "OK":
            governance_dir = surface_dir("system_learning") / "latest"
            for name in ("governance_status.json", "governance_status.md"):
                artifact = governance_dir / name
                if artifact.exists():
                    bundle.record_artifact(artifact)

        _write_learning_hub_event("work_cycle_completed", {
            "run_id": bundle.run_id,
            "mode": result["mode"],
            "elapsed_seconds": result["elapsed_seconds"],
            "overall_status": overall,
            "candidate_only": not legacy_work_cycle,
        })

        if transaction is not None:
            transaction.write_lineage()
            result["candidate_path"] = str(transaction.generation_dir.relative_to(ROOT))

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(summarize_result(result))
        if overall != "OK":
            raise SystemExit(1)
    finally:
        if transaction is not None:
            transaction.deactivate()
            if previous_generation_mode is None:
                os.environ.pop("SYSTEM_GENERATION_MODE", None)
            else:
                os.environ["SYSTEM_GENERATION_MODE"] = previous_generation_mode


if __name__ == "__main__":
    main()
