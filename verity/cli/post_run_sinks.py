"""Post-run evidence and feedback sinks for the daily application.

These sinks consume artifacts already produced by the execution spine.  They
do not decide authority or publication; they only attach post-run evidence to
the current :class:`RunBundle`.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from system_runtime.canonical_lineage import summarize_step_lineage
from system_runtime.events import EventEnvelope, JsonlEventStore
from system_runtime.minimum_monitoring import notification_dedup_key, release_identity
from system_runtime.provider_status import (
    ProviderStatusPolicyError,
    provider_status_policy,
)
from system_runtime.run_outcome import REASON_MANDATORY_SINK_FAILED, RunOutcome
from verity.runtime._constants import CASELAB_USABLE_THRESHOLD
from verity.runtime.run_bundle import RunBundle
from verity.runtime.runtime_io import ROOT, current_dir, ensure_dir, surface_dir

logger = logging.getLogger(__name__)
RUNTIME_DIR = ROOT / "Output" / "state" / "runtime_events"
ALERT_DIR = ROOT / "Output" / "state" / "alerts"


def collect_feedback_pending(bundle: RunBundle) -> None:
    """Auto-generate feedback_pending items for degenerate or weak signals."""
    # HMM degeneracy
    hmm_path = ROOT / "Output" / "state" / "ml_signals" / "latest" / "regime_hmm.json"
    if hmm_path.exists():
        try:
            hmm = json.loads(hmm_path.read_text(encoding="utf-8"))
            degeneracy = hmm.get("degeneracy", {})
            if not degeneracy.get("usable_for_core_judgment", True):
                flags = degeneracy.get("flags", [])
                warnings = degeneracy.get("warnings", [])
                bundle.add_feedback_pending(
                    f"HMM signal degenerate: {', '.join(flags)}",
                    source="hmm_regime_signal",
                    validation_type="ml_signal_calibration",
                    priority="high",
                )
                for w in warnings:
                    bundle.add_feedback_pending(
                        w,
                        source="hmm_regime_signal",
                        validation_type="ml_signal_calibration",
                        priority="medium",
                    )
        except Exception:
            logger.debug("Failed to build HMM regime feedback item", exc_info=True)

    # Judgment confidence low
    judgment_path = surface_dir("judgment") / "latest.json"
    judgment = None
    if judgment_path.exists():
        try:
            judgment = json.loads(judgment_path.read_text(encoding="utf-8"))
            conf_level = (judgment.get("confidence") or {}).get("level", "")
            if conf_level == "low":
                reasons = (judgment.get("confidence") or {}).get("reasons", [])[:2]
                for r in reasons:
                    bundle.add_feedback_pending(
                        f"Low confidence: {r}",
                        source="judgment_layer",
                        validation_type="judgment_calibration",
                        priority="medium",
                    )
        except Exception:
            logger.debug("Failed to build judgment confidence feedback item", exc_info=True)

    # Claim ladder verification targets (structured)
    if judgment:
        try:
            ladder = judgment.get("claim_ladder", {})
            if ladder:
                tier = ladder.get("tier", 0)
                label = ladder.get("label", "unknown")
                claim = ladder.get("claim_statement", "")
                watch_conditions = ladder.get("watch_conditions", [])
                invalidation_conditions = ladder.get("invalidation_conditions", [])
                promo = ladder.get("promotion_conditions", {})
                demotion_risk = ladder.get("demotion_risk", "")

                # Compute CaseLab score gap from caselab output
                caselab_gap = 0.0
                _today_str = datetime.now(UTC).date().isoformat()
                caselab_path_today = ROOT / "Output" / "state" / "caselab" / f"{_today_str}.json"
                if caselab_path_today.exists():
                    try:
                        _cl = json.loads(caselab_path_today.read_text(encoding="utf-8"))
                        _mq = _cl.get("match_quality", {})
                        _ts = _mq.get("top_score", 0)
                        _ut = _mq.get("thresholds", {}).get("usable", CASELAB_USABLE_THRESHOLD)
                        caselab_gap = round(max(0, _ut - _ts), 3)
                    except Exception:
                        logger.debug("Failed to read caselab match quality for feedback", exc_info=True)

                # M/D persistence requirement from promotion conditions
                md_persist_req = promo.get("to_tier_2", "")

                # Structured claim ladder item with all 6 required fields
                bundle.add_feedback_pending(
                    f"Claim ladder: tier={tier} ({label}) — {claim[:150]}",
                    source="claim_ladder",
                    validation_type="claim_verification",
                    priority="high",
                    metadata={
                        "claim_tier": tier,
                        "claim_label": label,
                        "mechanism_hypothesis": claim,
                        "watch_conditions": watch_conditions,
                        "invalidation_conditions": invalidation_conditions,
                        "caselab_score_gap": caselab_gap,
                        "md_persistence_requirement": md_persist_req,
                        "demotion_risk": demotion_risk,
                        # Acceptance criteria: 4 questions answered
                        "what_to_verify": claim,
                        "what_to_watch_next": watch_conditions,
                        "upgrade_conditions": list(promo.values()),
                        "downgrade_conditions": invalidation_conditions + ([demotion_risk] if demotion_risk else []),
                    },
                )
        except Exception:
            logger.debug("Failed to build claim ladder feedback item", exc_info=True)

    # CaseLab match quality
    caselab_dir = ROOT / "Output" / "state" / "caselab"
    if caselab_dir.exists():
        try:
            today = datetime.now(UTC).date().isoformat()
            caselab_path = caselab_dir / f"{today}.json"
            if caselab_path.exists():
                caselab = json.loads(caselab_path.read_text(encoding="utf-8"))
                mq = caselab.get("match_quality", {})
                top_score = mq.get("top_score", 0)
                thresholds = mq.get("thresholds", {})
                usable_th = thresholds.get("usable", CASELAB_USABLE_THRESHOLD)
                gap = round(usable_th - top_score, 3) if top_score < usable_th else 0
                if gap > 0:
                    bundle.add_feedback_pending(
                        f"CaseLab gap: score={top_score}, usable≥{usable_th}, gap={gap}",
                        source="caselab",
                        validation_type="case_matching",
                        priority="medium",
                    )
                # Mechanism context — what's missing
                mc = caselab.get("mechanism_context", {})
                for mtype in mc.get("mechanism_types", []):
                    bundle.add_feedback_pending(
                        f"Mechanism to verify: {mtype}",
                        source="caselab",
                        validation_type="mechanism_verification",
                        priority="medium",
                    )
        except Exception:
            logger.debug("Failed to build CaseLab match quality feedback item", exc_info=True)

    # HMM calibration status
    hmm_audit_path = ROOT / "Output" / "state" / "hmm_stability" / "hmm_stability_audit.json"
    if hmm_audit_path.exists():
        try:
            audit = json.loads(hmm_audit_path.read_text(encoding="utf-8"))
            cal = audit.get("calibration", {})
            if not cal.get("calibration_passed", True):
                hist = cal.get("degradation_reasons", [])
                for reason in hist:
                    bundle.add_feedback_pending(
                        f"HMM calibration: {reason}",
                        source="hmm_calibration",
                        validation_type="ml_signal_calibration",
                        priority="medium",
                    )
                cap = cal.get("cap_applied", "")
                if cap:
                    bundle.add_feedback_pending(
                        f"HMM cap applied: {cap} — regime claims limited",
                        source="hmm_calibration",
                        validation_type="ml_signal_calibration",
                        priority="low",
                    )
        except Exception:
            logger.debug("Failed to build HMM calibration feedback item", exc_info=True)


def capture_traces(bundle: RunBundle) -> None:
    """Capture decision and signal traces from current artifacts."""
    # Decision trace: judgment + trade
    for surface, name in [
        ("judgment", "latest.json"),
        ("trade_decision", "latest.json"),
    ]:
        p = surface_dir(surface) / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                bundle.capture_decision_trace({f"Output/{surface}/{name}": data})
            except Exception:
                logger.debug("Failed to capture decision trace for %s/%s", surface, name, exc_info=True)

    # Signal trace: framework output (sigma vector summary only)
    fw_path = current_dir() / "framework_output.json"
    if fw_path.exists():
        try:
            fw = json.loads(fw_path.read_text(encoding="utf-8"))
            sv = fw.get("advanced", {}).get("sigma_vector", {})
            bundle.capture_signal_trace({
                "source": "framework_output",
                "framework_status": fw.get("status"),
                "overall": fw.get("basic", {}).get("overall"),
                "quality_status": fw.get("basic", {}).get("quality_status"),
                "sigma_vector": sv,
                "primary_readout": fw.get("advanced", {}).get("primary_readout"),
            })
        except Exception:
            logger.debug("Failed to capture framework output trace", exc_info=True)

    # Signal trace: HMM regime signal with degeneracy info
    hmm_path = ROOT / "Output" / "state" / "ml_signals" / "latest" / "regime_hmm.json"
    if hmm_path.exists():
        try:
            hmm = json.loads(hmm_path.read_text(encoding="utf-8"))
            bundle.capture_signal_trace({
                "source": "hmm_regime_signal",
                "regime": hmm.get("regime", {}),
                "stability": hmm.get("stability", {}),
                "degeneracy": hmm.get("degeneracy", {}),
            })
        except Exception:
            logger.debug("Failed to capture HMM regime trace", exc_info=True)


def write_runtime_event(event: dict, output_root: Path | None = None) -> None:
    """Append one versioned event to the runtime event store."""
    runtime_dir = output_root / "state" / "runtime_events" if output_root else RUNTIME_DIR
    ensure_dir(runtime_dir)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = runtime_dir / f"run_events_{today}.jsonl"
    JsonlEventStore(path).append(
        EventEnvelope.create(
            event_type=str(event.get("type") or "daily_run_completed"),
            payload_schema=str(event.get("schema_version") or "run_event.v1"),
            payload=event,
            producer="daily_run",
            run_id=event.get("run_id") or os.environ.get("ZCODE_BUNDLE_RUN_ID"),
            occurred_at=str(event.get("timestamp") or "") or None,
        )
    )


def mandatory_sink_failure_outcome(outcome: RunOutcome) -> RunOutcome:
    """Preserve primary execution/publication semantics after sink failure."""
    return RunOutcome(
        run_id=outcome.run_id,
        spec_status=outcome.spec_status,
        execution_status=outcome.execution_status,
        failed_steps=list(outcome.failed_steps),
        blocked_steps=list(outcome.blocked_steps),
        degraded_steps=list(outcome.degraded_steps),
        admission_verdict=outcome.admission_verdict,
        publish_status=outcome.publish_status,
        authority_mode=outcome.authority_mode,
        reason_codes=[*outcome.reason_codes, REASON_MANDATORY_SINK_FAILED],
        generation_id=outcome.generation_id,
        release_id=outcome.release_id,
        provider_status=outcome.provider_status,
        provider_cache_within_grace=outcome.provider_cache_within_grace,
    )


def write_alert(
    warnings: list[str],
    steps: list[dict],
    output_root: Path | None = None,
    outcome: dict | None = None,
    provider_status: str | None = None,
) -> None:
    """Write an auditable alert, separating hard and tolerated step failures."""
    from orchestration.pipeline_dag import classify_step_failures
    from orchestration.pipeline_runner import load_registry

    alert_dir = output_root / "state" / "alerts" if output_root else ALERT_DIR
    ensure_dir(alert_dir)
    now = datetime.now(UTC).isoformat()
    hard_failures, soft_failures = classify_step_failures(steps)
    known_step_ids = set(load_registry().get("steps", {}))
    unknown_failures = [
        step for step in soft_failures
        if str(step.get("step") or "") not in known_step_ids
    ]
    if unknown_failures:
        hard_failures.extend(unknown_failures)
        soft_failures = [step for step in soft_failures if step not in unknown_failures]
    run_id = str((outcome or {}).get("run_id") or os.environ.get("ZCODE_BUNDLE_RUN_ID") or "")
    release_id = str(
        (outcome or {}).get("release_id")
        or release_identity(ROOT).get("release_id")
        or ""
    )
    generation_id = (outcome or {}).get("generation_id")
    outcome_failed = bool(outcome and int(outcome.get("exit_code") or 0) != 0)
    outcome_degraded = bool(
        outcome
        and (
            outcome.get("status") == "degraded"
            or outcome.get("operational_state") == "COMPLETED_DEGRADED"
        )
    )
    alert_status = (
        "partial_failure"
        if hard_failures or (outcome_failed and not outcome_degraded)
        else "degraded"
        if outcome_degraded
        else "success"
    )
    failed_step_ids = [str(step.get("step", "")) for step in hard_failures]
    provider_status_value = str(
        provider_status
        or (outcome or {}).get("provider_status")
        or next(
            (
                item.get("provider_outcome", {}).get("status")
                for item in steps
                if isinstance(item.get("provider_outcome"), dict)
                and item.get("provider_outcome", {}).get("status")
            ),
            "",
        )
    ).strip().lower()
    provider_policy: dict[str, str] | None = None
    provider_policy_error: str | None = None
    if provider_status_value:
        try:
            provider_policy = provider_status_policy(provider_status_value, root=ROOT)
        except ProviderStatusPolicyError as exc:
            provider_policy_error = str(exc)

    severity = (
        "HIGH"
        if hard_failures or (outcome_failed and not outcome_degraded)
        else "MEDIUM"
        if soft_failures or warnings or outcome_degraded
        else "LOW"
    )
    if provider_policy:
        matrix_severity = {
            "INFO": "LOW",
            "NOTICE": "MEDIUM",
            "WARNING": "MEDIUM",
            "ERROR": "HIGH",
        }[provider_policy["alert"]]
        if outcome_degraded and not hard_failures:
            # The provider policy remains visible in the alert payload, but a
            # completed/degraded run is a warning channel event, not a new
            # system-crash notification.
            matrix_severity = min(
                (matrix_severity, "MEDIUM"),
                key={"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get,
            )
        severity = max((severity, matrix_severity), key={"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get)

    alert = {
        "timestamp": now,
        "status": alert_status,
        "run_id": run_id,
        "release_id": release_id or None,
        "generation_id": generation_id,
        "severity": severity,
        "warnings": warnings,
        "outcome": outcome,
        "provider_status": provider_status_value or None,
        "provider_alert_policy": provider_policy.get("alert") if provider_policy else None,
        "provider_alert_eligibility": (
            "ALLOWED" if provider_policy else "BLOCKED" if provider_status_value else "NOT_APPLICABLE"
        ),
        "failed_steps": [
            {
                "step": s["step"],
                "error": (s.get("stdout_tail") or "")[-300:],
                "duration_s": s.get("duration_s", 0),
            }
            for s in hard_failures
        ],
        "soft_failed_steps": [str(s.get("step", "")) for s in soft_failures],
        # SYS-21 reader dual-read: canonical IDs are observable context only.
        # The alert's run/release/generation fields remain the notification
        # and authority lineage contract.
        "canonical_lineage": summarize_step_lineage(steps, run_id=run_id),
        "summary": (
            f"{len(hard_failures)} hard failures, {len(soft_failures)} soft failures, "
            f"{len(warnings)} warnings"
            if hard_failures or soft_failures or warnings
            else (
                f"Run completed in degraded mode; admission/publish remains blocked "
                f"(exit_code={outcome.get('exit_code')})"
                if outcome_degraded and outcome
                else f"RunOutcome failed with exit_code={outcome.get('exit_code')}"
                if outcome_failed and outcome
                else "All steps succeeded, no warnings"
            )
        ),
    }
    if provider_policy_error:
        alert["provider_alert_policy_error"] = provider_policy_error
    alert["notification_dedup_key"] = notification_dedup_key(
        run_id=run_id,
        status=alert_status,
        failed_steps=failed_step_ids,
        warnings=warnings,
        outcome=outcome,
        provider_status=provider_status_value or None,
    )

    (alert_dir / "latest_alert.json").write_text(
        json.dumps(alert, indent=2, default=str), encoding="utf-8"
    )

    # Markdown version
    lines = [
        f"# Daily Alert — {now[:10]}",
        "",
        f"**Severity:** {alert['severity']}",
        f"**Summary:** {alert['summary']}",
        "",
    ]
    if hard_failures:
        lines.append("## Failed Steps (HARD)")
        for s in hard_failures:
            lines.append(f"- {s['step']}: {s.get('status', '?')}")
        lines.append("")
    if soft_failures:
        lines.append("## Soft Failures")
        for s in soft_failures:
            lines.append(f"- {s['step']}: {s.get('status', '?')}")
        lines.append("")
    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    (alert_dir / "latest_alert.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
