#!/usr/bin/env python3
"""Ingest completed daily run bundle into Learning Hub memory.

Copies manifest/steps/feedback into Data/system_learning/runs/, updates
runs/latest.json, and refreshes Output/system_learning/latest/summary.json
with failure modes and calibration gaps.
"""
from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT, ensure_dir, load_json, surface_dir, write_json

HUB_RUNS = ROOT / "Data" / "system_learning" / "runs"
HUB_LATEST_POINTER = HUB_RUNS / "latest.json"
_POST_PUBLISH_AUDIT_DIR = os.environ.get("SYSTEM_POST_PUBLISH_AUDIT_DIR", "").strip()
SUMMARY_PATH = (
    Path(_POST_PUBLISH_AUDIT_DIR) / "learning_hub_summary.json"
    if _POST_PUBLISH_AUDIT_DIR
    else surface_dir("system_learning") / "latest" / "summary.json"
)
JUDGMENT_CALIBRATION = surface_dir("judgment") / "calibration_report.json"
TRADE_CALIBRATION = surface_dir("trade_ledger") / "calibration_report.json"
HMM_AUDIT = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
CLAIM_LADDER = ROOT / "Output" / "claim_ladder" / "progression.json"
ALERT_JSON = ROOT / "Output" / "alerts" / "latest_alert.json"


def _copy_if_exists(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False
    ensure_dir(dest.parent)
    shutil.copy2(src, dest)
    return True


def _failed_step_counts(steps: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for step in steps:
        if step.get("status") != "success":
            counts[str(step.get("step", "unknown"))] += 1
    return counts


def _recurrent_failure_modes(steps: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
  counts = _failed_step_counts(steps)
  return [
      {"step": name, "failure_count": count}
      for name, count in counts.most_common(limit)
  ]


def _calibration_snapshot() -> dict[str, Any]:
    judgment = load_json(JUDGMENT_CALIBRATION) or {}
    trade = load_json(TRADE_CALIBRATION) or {}
    hmm = load_json(HMM_AUDIT) or {}
    claim = load_json(CLAIM_LADDER) or {}

    j_eval = judgment.get("summary", {}).get("evaluated_cards")
    if j_eval is None:
        j_eval = judgment.get("evaluated_cards")
    t_eval = trade.get("summary", {}).get("evaluated_decisions")
    if t_eval is None:
        t_eval = trade.get("evaluated_decisions")

    hmm_hist = hmm.get("calibration", {}).get("history", [])
    if not isinstance(hmm_hist, list):
        hmm_hist = []
    hmm_count = hmm.get("compatible_history_length")
    if hmm_count is None and hmm_hist:
        hmm_count = len(hmm_hist)
    elif hmm_count is None:
        cal_status = hmm.get("calibration_status", {})
        hmm_count = cal_status.get("compatible_history", 0)

    return {
        "judgment_calibration_evaluated": int(j_eval or 0),
        "trade_decision_calibration_evaluated": int(t_eval or 0),
        "hmm_calibration_history_count": int(hmm_count or 0),
        "claim_ladder_tier": claim.get("current_tier"),
        "claim_ladder_last_change": claim.get("last_change_reason"),
    }


def ingest_daily_run_bundle(
    bundle_dir: Path,
    *,
    run_status: str,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist run bundle into Learning Hub and refresh latest summary."""
    manifest = load_json(bundle_dir / "manifest.json") or {}
    run_id = str(manifest.get("run_id") or bundle_dir.name)
    steps = steps or []
    failed = [s for s in steps if s.get("status") != "success"]

    ensure_dir(HUB_RUNS)
    hub_manifest = HUB_RUNS / f"{run_id}.json"
    hub_payload = {
        "run_id": run_id,
        "ingested_at": datetime.now(UTC).isoformat(),
        "status": run_status,
        "manifest": manifest,
        "failed_steps": [s.get("step") for s in failed],
        "bundle_dir": str(bundle_dir.relative_to(ROOT)),
    }
    write_json(hub_manifest, hub_payload)

    bundle_copy_dir = HUB_RUNS / run_id
    ensure_dir(bundle_copy_dir)
    for name in (
        "manifest.json",
        "experiment.json",
        "steps.jsonl",
        "feedback_pending.json",
        "decision_trace.json",
        "signal_trace.json",
    ):
        _copy_if_exists(bundle_dir / name, bundle_copy_dir / name)
    _copy_if_exists(ALERT_JSON, bundle_copy_dir / "latest_alert.json")

    write_json(HUB_LATEST_POINTER, {
        "run_id": run_id,
        "manifest": str(hub_manifest.relative_to(ROOT)),
        "ingested_at": hub_payload["ingested_at"],
        "status": run_status,
    })

    calibration = _calibration_snapshot()
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "latest_run_id": run_id,
        "latest_run_status": run_status,
        "failed_step_count": len(failed),
        "top_recurrent_failure_modes": _recurrent_failure_modes(steps),
        "calibration": calibration,
        "feedback_pending_count": len(load_json(bundle_dir / "feedback_pending.json") or []),
        "hmm_calibration_sample_gap": max(0, 10 - calibration["hmm_calibration_history_count"]),
        "judgment_calibration_sample_gap": max(0, 10 - calibration["judgment_calibration_evaluated"]),
        "trade_calibration_sample_gap": max(0, 10 - calibration["trade_decision_calibration_evaluated"]),
    }
    write_json(SUMMARY_PATH, summary)
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest latest or specified run bundle into Learning Hub.")
    parser.add_argument("--bundle-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.bundle_dir:
        bundle_dir = args.bundle_dir
    else:
        from run_bundle import latest_run_dir

        bundle_dir = latest_run_dir()
        if bundle_dir is None:
            raise SystemExit("No run bundle found")

    manifest = load_json(bundle_dir / "manifest.json") or {}
    steps = []
    steps_path = bundle_dir / "steps.jsonl"
    if steps_path.exists():
        for line in steps_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                steps.append(json.loads(line))

    summary = ingest_daily_run_bundle(
        bundle_dir,
        run_status=str(manifest.get("status", "unknown")),
        steps=steps,
    )
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Ingested {bundle_dir.name} -> {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
