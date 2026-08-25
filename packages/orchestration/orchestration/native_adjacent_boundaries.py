"""Shadow adapters for decision-adjacent ledger and paper-position writers."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

from scripts._runtime_io import ROOT

ADJACENT_BOUNDARY_TAG = "shadow_pilot"
ADJACENT_SHADOW_ROOT = ROOT / "Output" / "health" / "native_adjacent_shadow"
SUPPORTED_ADJACENT_BOUNDARY_STEPS = frozenset(
    {"record_trade_decision", "paper_portfolio"}
)
ALLOWED_FAILURE_BEHAVIORS = {
    "record_trade_decision": "continue_with_warning",
    "paper_portfolio": "decision_adjacent_block",
}


def select_native_adjacent_boundary_steps(
    document: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    """Select explicitly tagged non-core adjacent writers."""
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
        if execution.get("native_adjacent_boundary") != ADJACENT_BOUNDARY_TAG:
            continue

        step_name = str(step_id)
        failure_behavior = str(
            spec.get("failure_behavior")
            or (spec.get("authority") or {}).get("failure_behavior", "")
        )
        if step_name not in SUPPORTED_ADJACENT_BOUNDARY_STEPS:
            errors.append(f"{step_name}: no native adjacent boundary adapter")
        if str(spec.get("status") or "") != "active":
            errors.append(
                f"{step_name}: adjacent shadow boundary requires status=active"
            )
        if bool(
            spec.get("allowed_to_affect_core_judgment")
            or (spec.get("authority") or {}).get("affects_core_judgment")
        ):
            errors.append(
                f"{step_name}: adjacent shadow boundary forbids core authority"
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
                f"{step_name}: adjacent boundary cannot share another native boundary"
            )
        selected.append({"step_id": step_name, "failure_behavior": failure_behavior})

    if errors:
        raise ValueError(
            "invalid registry native_adjacent_boundary tags: " + "; ".join(errors)
        )
    return tuple(sorted(selected, key=lambda item: item["step_id"]))


def load_native_adjacent_boundary_steps(root: Path = ROOT) -> frozenset[str]:
    path = root / "governance" / "daily_pipeline_registry.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ValueError("pipeline registry must be a mapping")
    return frozenset(
        item["step_id"] for item in select_native_adjacent_boundary_steps(document)
    )


NATIVE_ADJACENT_BOUNDARY_STEPS = load_native_adjacent_boundary_steps()


def adjacent_shadow_root(root: Path = ROOT) -> Path:
    return root / "Output" / "health" / "native_adjacent_shadow"


def _load_registry(root: Path) -> dict[str, Any]:
    path = root / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


@contextlib.contextmanager
def _generation_environment(root: Path, generation_root: Path) -> Iterator[None]:
    keys = (
        "SYSTEM_WORKSPACE_ROOT",
        "SYSTEM_ROOT",
        "SYSTEM_GENERATION_MODE",
        "SYSTEM_GENERATION_DIR",
        "CURRENT_OUTPUT_DIR",
        "DAILY_OUTPUT_ROOT",
        "SHADOW_OUTPUT_DIR",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(root),
            "SYSTEM_ROOT": str(root),
            "SYSTEM_GENERATION_MODE": "1",
            "SYSTEM_GENERATION_DIR": str(generation_root),
            "CURRENT_OUTPUT_DIR": str(generation_root / "current"),
            "DAILY_OUTPUT_ROOT": str(generation_root),
            "SHADOW_OUTPUT_DIR": str(generation_root / "position"),
        }
    )
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, symlinks=False)


def _copy_tree_if_missing(source: Path, target: Path) -> None:
    """Seed a generation input once without reverting an earlier asset write."""
    if source.is_dir() and not target.exists():
        shutil.copytree(source, target, dirs_exist_ok=True, symlinks=False)


def _rebase_shadow_snapshot_paths(
    *,
    root: Path,
    snapshot_path: Path,
) -> list[dict[str, str]]:
    """Rebase existing workspace-absolute artifact paths in the shadow copy.

    A generation may be copied between workspace roots.  Only a missing
    absolute path whose ``/Output/...`` suffix exists under the requested root
    is rebased; unresolved paths remain untouched and fail at consumption.
    """
    if not snapshot_path.is_file():
        return []
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    rebases: list[dict[str, str]] = []
    for key, raw_value in list(artifacts.items()):
        if not isinstance(raw_value, str):
            continue
        original = Path(raw_value)
        if not original.is_absolute() or original.exists():
            continue
        marker = f"{os.sep}Output{os.sep}"
        if marker not in raw_value:
            continue
        suffix = raw_value.split(marker, 1)[1]
        candidate = root / "Output" / suffix
        if not candidate.exists():
            continue
        artifacts[key] = str(candidate)
        rebases.append(
            {
                "field": str(key),
                "original": raw_value,
                "resolved": str(candidate),
            }
        )
    if rebases:
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return rebases


def _seed_generation(
    *,
    root: Path,
    generation_root: Path,
    input_root: Path | None,
    decision_shadow_root: Path | None = None,
) -> list[dict[str, str]]:
    """Seed only read-only inputs and the previous accepted position state."""
    current_root = (input_root or root / "Output") / "current"
    snapshot_path = generation_root / "current" / "neutral_pressure_snapshot.json"
    _copy_file(
        current_root / "neutral_pressure_snapshot.json",
        snapshot_path,
    )
    _copy_file(current_root / "framework_output.json", generation_root / "current" / "framework_output.json")
    decision_shadow_root = decision_shadow_root or (
        root / "Output" / "health" / "native_decision_shadow"
    )
    _copy_file(
        decision_shadow_root / "trade_decision" / "latest.json",
        generation_root / "trade_decision" / "latest.json",
    )
    _copy_file(
        decision_shadow_root / "trade_decision" / "risk_gate.json",
        generation_root / "trade_decision" / "risk_gate.json",
    )
    _copy_tree(root / "Output" / "position", generation_root / "position")
    _copy_tree_if_missing(
        root / "Output" / "trade_ledger", generation_root / "trade_ledger"
    )
    _copy_tree_if_missing(
        root / "Output" / "system_learning", generation_root / "system_learning"
    )
    return _rebase_shadow_snapshot_paths(root=root, snapshot_path=snapshot_path)


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


def _record_boundary(generation_root: Path) -> tuple[dict[str, Any], list[str]]:
    from scripts import record_trade_decision as record
    from scripts.commands.weekly import claim_evaluator

    decision = record.load_json(record.TRADE_DECISION_PATH)
    risk_gate = record.load_json(record.RISK_GATE_PATH)
    if not decision or not risk_gate:
        raise FileNotFoundError("shadow trade decision or risk gate is missing")
    entry = record.build_ledger_entry(decision, risk_gate)
    ledger_path, write_mode = record.upsert_to_ledger(entry)
    latest_path = record.write_latest(entry)
    output_paths = [str(ledger_path), str(latest_path)]
    if not all(Path(path).is_file() for path in output_paths):
        raise RuntimeError("record_trade_decision did not produce its shadow outputs")

    # The legacy CLI invokes claim_evaluator after the ledger write.  Preserve
    # that observable side effect inside the same generation; evaluator
    # failures remain a warning, matching the legacy wrapper's best-effort
    # subprocess behavior and the registry's continue_with_warning policy.
    claim_evaluation_status = "not_run"
    claim_evaluation_error: str | None = None
    try:
        claim_evaluation = claim_evaluator.run_claim_evaluator()
        claim_evaluation_status = (
            "success" if claim_evaluation is not None else "no_entries"
        )
    except Exception as exc:  # noqa: BLE001 - legacy wrapper is warning-only
        claim_evaluation_status = "warning"
        claim_evaluation_error = f"{type(exc).__name__}: {exc}"

    return {
        "date": entry.get("date"),
        "decision_fingerprint": entry.get("decision_fingerprint"),
        "risk_gate_status": entry.get("risk_gate_status"),
        "write_mode": write_mode,
        "claim_evaluation_status": claim_evaluation_status,
        "claim_evaluation_error": claim_evaluation_error,
        "ledger_path": str(ledger_path),
        "generation_root": str(generation_root),
    }, output_paths


def _paper_boundary(generation_root: Path) -> tuple[dict[str, Any], list[str]]:
    from scripts.strategy_lab import paper_portfolio as paper

    result = paper.run_paper_portfolio(backfill_days=0, dry_run=False, notify=False)
    state = result.get("state") if isinstance(result, Mapping) else None
    if not isinstance(state, Mapping):
        raise RuntimeError("paper_portfolio did not return a state")
    paths = result.get("paths") if isinstance(result, Mapping) else {}
    output_paths = [
        str(paths.get("state") or paper.STATE_PATH),
        str(paths.get("nav_jsonl") or paper.NAV_JSONL_PATH),
        str(paths.get("markdown") or paper.LATEST_MD_PATH),
    ]
    if not all(Path(path).is_file() for path in output_paths):
        raise RuntimeError("paper_portfolio did not produce all shadow outputs")
    return {
        "as_of_date": state.get("as_of_date"),
        "nav": state.get("nav"),
        "position": state.get("position"),
        "stance": state.get("stance"),
        "effective_size": state.get("effective_size"),
        "history_len": state.get("history_len"),
        "generation_root": str(generation_root),
    }, output_paths


def execute_native_adjacent_boundary(
    step_id: str,
    *,
    root: Path = ROOT,
    shadow_root: Path | None = None,
    input_root: Path | None = None,
    decision_shadow_root: Path | None = None,
) -> dict[str, Any]:
    """Run one adjacent writer in a health-only generation."""
    root = root.resolve()
    shadow_root = (shadow_root or adjacent_shadow_root(root)).resolve()
    selected = {
        item["step_id"]: item["failure_behavior"]
        for item in select_native_adjacent_boundary_steps(_load_registry(root))
    }
    if step_id not in selected:
        raise ValueError(f"no native adjacent boundary registered for {step_id!r}")

    generation_root = shadow_root / "generation"
    generation_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    base = _result_base(step_id, selected[step_id], shadow_root=shadow_root)
    try:
        input_path_rebases = _seed_generation(
            root=root,
            generation_root=generation_root,
            input_root=input_root,
            decision_shadow_root=decision_shadow_root,
        )
        with _generation_environment(root, generation_root):
            if step_id == "record_trade_decision":
                payload, output_paths = _record_boundary(generation_root)
            elif step_id == "paper_portfolio":
                payload, output_paths = _paper_boundary(generation_root)
            else:  # pragma: no cover - selection is fail-closed above
                raise ValueError(
                    f"no implementation for native adjacent boundary {step_id!r}"
                )

        return {
            **base,
            "status": "success",
            "mode": "native_adjacent_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "artifact_status": "PASS",
            "check_passed": True,
            "output_paths": output_paths,
            "payload": payload,
            "input_path_rebases": input_path_rebases,
            "writes_shadow_output": True,
        }
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - preserve typed failure
        return {
            **base,
            "status": "error",
            "mode": "native_adjacent_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "artifact_status": "FAIL",
            "check_passed": False,
            "error": str(exc),
            "input_path_rebases": locals().get("input_path_rebases", []),
            "writes_shadow_output": False,
        }


__all__ = [
    "ADJACENT_BOUNDARY_TAG",
    "ADJACENT_SHADOW_ROOT",
    "ALLOWED_FAILURE_BEHAVIORS",
    "NATIVE_ADJACENT_BOUNDARY_STEPS",
    "SUPPORTED_ADJACENT_BOUNDARY_STEPS",
    "adjacent_shadow_root",
    "execute_native_adjacent_boundary",
    "load_native_adjacent_boundary_steps",
    "select_native_adjacent_boundary_steps",
]
