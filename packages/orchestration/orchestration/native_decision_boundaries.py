"""Shadow-only adapters for the decision and risk boundary migration.

The adapters keep the existing judgment, promotion, trade-decision, and risk
rules as the business authority.  They only inject input paths and redirect
the four writers into ``Output/health/native_decision_shadow``.  No shared
``Output/judgment`` or ``Output/trade_decision`` file is written here.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from scripts._runtime_io import ROOT, load_json, utc_now, write_json

DECISION_BOUNDARY_TAG = "shadow_pilot"
DECISION_SHADOW_ROOT = ROOT / "Output" / "health" / "native_decision_shadow"
SUPPORTED_DECISION_BOUNDARY_STEPS = frozenset(
    {
        "judgment_layer",
        "judgment_promotion_gate",
        "trade_decision",
        "risk_gate",
    }
)
ALLOWED_FAILURE_BEHAVIORS = {
    "judgment_layer": "block_current_readout",
    "judgment_promotion_gate": "block_promotion",
    "trade_decision": "hold_flat",
    "risk_gate": "hold_flat",
}


def select_native_decision_boundary_steps(
    document: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    """Select registry-tagged decision boundaries and fail closed on drift."""
    steps = document.get("steps") or {}
    if not isinstance(steps, Mapping):
        raise ValueError("pipeline registry steps must be a mapping")

    selected: list[dict[str, str]] = []
    errors: list[str] = []
    for step_id, spec in steps.items():
        if not isinstance(spec, Mapping):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, Mapping):
            continue
        if execution.get("native_decision_boundary") != DECISION_BOUNDARY_TAG:
            continue

        step_name = str(step_id)
        failure_behavior = str(
            spec.get("failure_behavior")
            or (spec.get("authority") or {}).get("failure_behavior", "")
        )
        if step_name not in SUPPORTED_DECISION_BOUNDARY_STEPS:
            errors.append(f"{step_name}: no native decision boundary adapter")
        if str(spec.get("status") or "") != "active":
            errors.append(
                f"{step_name}: decision shadow boundary requires status=active"
            )
        if not bool(
            spec.get("allowed_to_affect_core_judgment")
            or (spec.get("authority") or {}).get("affects_core_judgment")
        ):
            errors.append(
                f"{step_name}: decision shadow boundary requires core authority"
            )
        expected_failure_behavior = ALLOWED_FAILURE_BEHAVIORS.get(step_name)
        if failure_behavior != expected_failure_behavior:
            errors.append(
                f"{step_name}: expected failure_behavior={expected_failure_behavior!r}, "
                f"got {failure_behavior!r}"
            )
        if execution.get("native_file_boundary") or execution.get(
            "native_core_boundary"
        ):
            errors.append(
                f"{step_name}: decision boundary cannot share another native boundary"
            )
        selected.append(
            {
                "step_id": step_name,
                "failure_behavior": failure_behavior,
            }
        )

    if errors:
        raise ValueError(
            "invalid registry native_decision_boundary tags: " + "; ".join(errors)
        )
    return tuple(sorted(selected, key=lambda item: item["step_id"]))


def load_native_decision_boundary_steps(root: Path = ROOT) -> frozenset[str]:
    """Load decision-boundary selection from the authoritative registry."""
    path = root / "governance" / "daily_pipeline_registry.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ValueError("pipeline registry must be a mapping")
    return frozenset(
        item["step_id"] for item in select_native_decision_boundary_steps(document)
    )


NATIVE_DECISION_BOUNDARY_STEPS = load_native_decision_boundary_steps()


def decision_shadow_root(root: Path = ROOT) -> Path:
    return root / "Output" / "health" / "native_decision_shadow"


def _load_registry(root: Path) -> dict[str, Any]:
    path = root / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


def _load_required_json(path: Path, label: str) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict) or not payload:
        raise FileNotFoundError(f"{label} not found or invalid: {path}")
    return payload


def _source_surface(root: Path, name: str, input_root: Path | None) -> Path:
    return (input_root or root / "Output") / name


def _find_caselab(
    caselab_dir: Path, date_str: str
) -> tuple[dict[str, Any] | None, Path | None]:
    dated_path = caselab_dir / f"{date_str}.json"
    if dated_path.exists():
        return load_json(dated_path), dated_path
    candidates = sorted(caselab_dir.glob("*.json"))
    if not candidates:
        return None, None
    latest = candidates[-1]
    return load_json(latest), latest


def _date_from_payload(payload: Mapping[str, Any], fallback: str | None = None) -> str:
    value = str(payload.get("as_of") or payload.get("date") or fallback or "")
    return value[:10] if len(value) >= 10 else utc_now().strftime("%Y-%m-%d")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _result_base(
    step_id: str, failure_behavior: str, *, shadow_root: Path
) -> dict[str, Any]:
    return {
        "step": step_id,
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "writes_legacy_output": False,
        "writes_active_generation": False,
        "shadow_output_root": str(shadow_root),
    }


def _judgment_boundary(
    *,
    root: Path,
    shadow_root: Path,
    input_root: Path | None,
    date_str: str | None,
) -> tuple[dict[str, Any], list[str]]:
    from scripts.paper_freshness import check_paper_world_model_freshness
    from workbench.judgment.layer import build_judgment, format_markdown as format_judgment

    current = _source_surface(root, "current", input_root)
    framework_path = current / "neutral_pressure_snapshot.json"
    framework = _load_required_json(framework_path, "neutral pressure snapshot")
    resolved_date = date_str or _date_from_payload(framework)
    caselab, caselab_path = _find_caselab(root / "Output" / "caselab", resolved_date)
    hmm_path = root / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
    validation_path = current / "quality_validation.json"
    hmm = load_json(hmm_path)
    validation = load_json(validation_path)

    card = build_judgment(framework, caselab, hmm, None, None, validation)
    freshness = check_paper_world_model_freshness()
    card["paper_world_model_freshness"] = freshness
    if freshness.get("stale"):
        card.setdefault("confidence", {}).setdefault("reasons", []).append(
            f"Paper world model stale ({freshness.get('reason')}, "
            f"age={freshness.get('age_hours')}h) — size discount at trade decision"
        )
    card["inputs"] = {
        "neutral_pressure_snapshot": str(framework_path),
        "caselab": str(caselab_path) if caselab_path else None,
        "hmm": str(hmm_path),
        "k_gate": None,
        "x_gate": None,
        "validation": str(validation_path),
    }

    output_dir = shadow_root / "judgment"
    date_path = output_dir / f"{resolved_date}.json"
    date_md_path = output_dir / f"{resolved_date}.md"
    latest_path = output_dir / "latest.json"
    latest_md_path = output_dir / "latest.md"
    for path in (date_path, latest_path):
        write_json(path, card)
    for path in (date_md_path, latest_md_path):
        _write_markdown(path, format_judgment(card))
    artifact_ok = bool(card.get("judgment_id") and card.get("canonical_chain"))
    return card, [
        str(date_path),
        str(date_md_path),
        str(latest_path),
        str(latest_md_path),
    ] if artifact_ok else []


def _promotion_boundary(
    *,
    root: Path,
    shadow_root: Path,
    date_str: str | None,
) -> tuple[dict[str, Any], list[str]]:
    from workbench.judgment.promotion_gate import (
        format_markdown as format_promotion_gate,
        run_promotion_gate,
    )

    judgment_path = shadow_root / "judgment" / "latest.json"
    judgment = _load_required_json(judgment_path, "shadow judgment")
    resolved_date = date_str or _date_from_payload(judgment)
    caselab_dir = root / "Output" / "caselab"
    hmm_path = root / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
    report = run_promotion_gate(
        resolved_date,
        judgment_path=judgment_path,
        caselab_dir=caselab_dir,
        hmm_path=hmm_path,
        hmm_audit_path=root / "Output" / "hmm_stability" / "hmm_stability_audit.json",
        k_gate_path=root / "Output" / "k_measurement" / "k_measurement_gate.json",
        x_gate_path=root / "Output" / "x_measurement" / "x_measurement_gate.json",
    )
    report["inputs"] = {
        "judgment": str(judgment_path),
        "caselab_dir": str(caselab_dir),
        "hmm": str(hmm_path),
    }
    output_dir = shadow_root / "judgment"
    json_path = output_dir / "promotion_gate.json"
    md_path = output_dir / "promotion_gate.md"
    write_json(json_path, report)
    _write_markdown(md_path, format_promotion_gate(report))
    artifact_ok = bool(report.get("schema_version") and report.get("overall_status"))
    return report, [str(json_path), str(md_path)] if artifact_ok else []


def _trade_boundary(
    *,
    root: Path,
    shadow_root: Path,
    input_root: Path | None,
    date_str: str | None,
) -> tuple[dict[str, Any], list[str]]:
    from scripts import trade_decision_layer as trade

    judgment_path = shadow_root / "judgment" / "latest.json"
    promotion_path = shadow_root / "judgment" / "promotion_gate.json"
    judgment = _load_required_json(judgment_path, "shadow judgment")
    _load_required_json(promotion_path, "shadow promotion gate")
    resolved_date = date_str or _date_from_payload(judgment)
    current = _source_surface(root, "current", input_root)
    caselab, caselab_path = _find_caselab(root / "Output" / "caselab", resolved_date)
    del caselab  # build_trade_decision resolves the same path for parity.
    decision = trade.build_trade_decision(
        resolved_date,
        judgment_path=judgment_path,
        promotion_gate_path=promotion_path,
        hmm_audit_path=root / "Output" / "hmm_stability" / "hmm_stability_audit.json",
        caselab_path=caselab_path,
        sigma_snapshot_path=current / "neutral_pressure_snapshot.json",
        paper_world_model_dir=root / "Data" / "paper_world_model",
        support_registry_path=root / "governance" / "paper_support_registry.yaml",
    )
    output_dir = shadow_root / "trade_decision"
    json_path = output_dir / "latest.json"
    md_path = output_dir / "latest.md"
    write_json(json_path, decision)
    _write_markdown(md_path, trade._format_markdown(decision))
    artifact_ok = bool(decision.get("schema_version") and decision.get("decision"))
    return decision, [str(json_path), str(md_path)] if artifact_ok else []


def _risk_boundary(*, shadow_root: Path) -> tuple[dict[str, Any], list[str]]:
    from scripts import trade_risk_gate as risk

    decision_path = shadow_root / "trade_decision" / "latest.json"
    decision = _load_required_json(decision_path, "shadow trade decision")
    risk_check = risk.check_decision(decision)
    report = risk.build_risk_gate_report(decision, risk_check)
    output_dir = shadow_root / "trade_decision"
    json_path = output_dir / "risk_gate.json"
    md_path = output_dir / "risk_gate.md"
    write_json(json_path, report)
    _write_markdown(md_path, risk.format_markdown(report))
    artifact_ok = bool(
        report.get("schema_version") and isinstance(report.get("risk_check"), dict)
    )
    return report, [str(json_path), str(md_path)] if artifact_ok else []


def execute_native_decision_boundary(
    step_id: str,
    *,
    root: Path = ROOT,
    shadow_root: Path | None = None,
    input_root: Path | None = None,
    date_str: str | None = None,
) -> dict[str, Any]:
    """Execute one decision boundary without touching shared authority."""
    root = root.resolve()
    shadow_root = (shadow_root or decision_shadow_root(root)).resolve()
    document = _load_registry(root)
    selected = {
        item["step_id"]: item["failure_behavior"]
        for item in select_native_decision_boundary_steps(document)
    }
    if step_id not in selected:
        raise ValueError(f"no native decision boundary registered for {step_id!r}")

    started = time.monotonic()
    failure_behavior = selected[step_id]
    base = _result_base(step_id, failure_behavior, shadow_root=shadow_root)
    try:
        if step_id == "judgment_layer":
            payload, output_paths = _judgment_boundary(
                root=root,
                shadow_root=shadow_root,
                input_root=input_root,
                date_str=date_str,
            )
        elif step_id == "judgment_promotion_gate":
            payload, output_paths = _promotion_boundary(
                root=root,
                shadow_root=shadow_root,
                date_str=date_str,
            )
        elif step_id == "trade_decision":
            payload, output_paths = _trade_boundary(
                root=root,
                shadow_root=shadow_root,
                input_root=input_root,
                date_str=date_str,
            )
        elif step_id == "risk_gate":
            payload, output_paths = _risk_boundary(shadow_root=shadow_root)
        else:  # pragma: no cover - selection is fail-closed above
            raise ValueError(
                f"no implementation for native decision boundary {step_id!r}"
            )

        return {
            **base,
            "status": "success",
            "mode": "native_decision_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "artifact_status": "PASS" if output_paths else "FAIL",
            "check_passed": bool(output_paths),
            "output_paths": output_paths,
            "payload": payload,
            "writes_shadow_output": True,
        }
    except Exception as exc:  # noqa: BLE001 - preserve typed boundary result
        return {
            **base,
            "status": "error",
            "mode": "native_decision_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "artifact_status": "FAIL",
            "check_passed": False,
            "error": str(exc),
            "writes_shadow_output": False,
        }


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "DECISION_BOUNDARY_TAG",
    "DECISION_SHADOW_ROOT",
    "NATIVE_DECISION_BOUNDARY_STEPS",
    "SUPPORTED_DECISION_BOUNDARY_STEPS",
    "decision_shadow_root",
    "execute_native_decision_boundary",
    "load_native_decision_boundary_steps",
    "select_native_decision_boundary_steps",
]
