from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from workbench.paths import workbench_root as _workbench_root
from typing import Any


ROOT = _workbench_root()


def _resolve_contracts() -> Path:
    """Prefer legacy ``contracts/`` symlink; fall back to packages tree."""
    candidates = (
        ROOT / "contracts" / "workbench",
        ROOT / "packages" / "workbench" / "contracts" / "workbench",
    )
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


CONTRACTS = _resolve_contracts()

EVIDENCE_COLUMNS = {
    "date",
    "series_id",
    "source_id",
    "source_series_id",
    "value",
    "unit",
    "frequency",
    "vintage_date",
    "quality_flag",
}

SCHEMAS = {
    "provider-release": "data_provider_release.schema.json",
    "model-run": "model_run.schema.json",
    "report-artifacts": "report_artifact.schema.json",
    "ml-signal": "ml_signal.schema.json",
    "ml-signal-manifest": "ml_signal_manifest.schema.json",
}


class ValidationError(Exception):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"JSON root must be an object: {path}")
    return payload


def _schema(name: str) -> dict[str, Any]:
    return _read_json(CONTRACTS / SCHEMAS[name])


def _validate_schema(payload: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in schema.get("required", []) or []:
        if field not in payload:
            errors.append(f"missing required field: {field}")
    properties = schema.get("properties", {}) or {}
    expected_version = (properties.get("schema_version") or {}).get("const")
    if expected_version and payload.get("schema_version") != expected_version:
        errors.append(f"schema_version must be {expected_version!r}, got {payload.get('schema_version')!r}")
    return errors


def _path_is_relative(path: str) -> bool:
    return path != "" and not Path(path).is_absolute() and ".." not in Path(path).parts


def _validate_artifact_paths(root: Path, artifacts: list[dict[str, Any]], path_key: str = "path") -> list[str]:
    errors: list[str] = []
    for idx, artifact in enumerate(artifacts):
        rel = artifact.get(path_key)
        if not isinstance(rel, str) or not _path_is_relative(rel):
            errors.append(f"artifact[{idx}] path must be a safe relative path: {rel!r}")
            continue
        if not (root / rel).exists():
            errors.append(f"artifact[{idx}] path does not exist: {rel}")
    return errors


def validate_provider_release(path: Path) -> None:
    release_root = path if path.is_dir() else path.parent
    release_file = path / "provider_release.json" if path.is_dir() else path
    if not release_file.exists() and path.is_dir() and (path / "catalog.json").exists():
        raise ValidationError(
            "catalog.json found, but Workbench provider-release validation expects provider_release.json"
        )
    payload = _read_json(release_file)
    errors = _validate_schema(payload, _schema("provider-release"))
    if payload.get("status") == "failed":
        errors.append("status is failed")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
    else:
        errors.extend(_validate_artifact_paths(release_root, artifacts))
        roles = {item.get("role") for item in artifacts if isinstance(item, dict)}
        if "evidence_panel" not in roles:
            errors.append("artifacts must include role: evidence_panel")
        if "source_registry" not in roles:
            errors.append("artifacts should include role: source_registry")
        if "provenance" not in roles:
            errors.append("artifacts should include role: provenance")
        for item in artifacts:
            if item.get("role") == "evidence_panel":
                validate_evidence_panel(release_root / str(item["path"]))
    if errors:
        raise ValidationError("\n  - " + "\n  - ".join(errors))


def validate_evidence_panel(path: Path) -> None:
    if not path.exists():
        raise ValidationError(f"evidence panel missing: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = sorted(EVIDENCE_COLUMNS - columns)
            if missing:
                raise ValidationError(f"evidence panel missing columns: {', '.join(missing)}")
            rows = list(reader)
            if not rows:
                raise ValidationError("evidence panel has no rows")
            return
    if suffix == ".parquet":
        try:
            import pandas as pd
        except Exception as exc:
            raise ValidationError(f"pandas is required to validate parquet evidence panels: {exc}") from exc
        frame = pd.read_parquet(path)
        missing = sorted(EVIDENCE_COLUMNS - set(frame.columns))
        if missing:
            raise ValidationError(f"evidence panel missing columns: {', '.join(missing)}")
        if frame.empty:
            raise ValidationError("evidence panel has no rows")
        return
    raise ValidationError(f"unsupported evidence panel format: {suffix}")


def validate_model_run(path: Path) -> None:
    payload = _read_json(path)
    errors = _validate_schema(payload, _schema("model-run"))
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("artifacts must be an object keyed by artifact id")
    else:
        run_root = path.parent
        for key, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                errors.append(f"artifact {key!r} must be an object")
                continue
            rel = artifact.get("path")
            kind = artifact.get("kind")
            if not isinstance(rel, str) or not _path_is_relative(rel):
                errors.append(f"artifact {key!r} path must be a safe relative path: {rel!r}")
            elif not (run_root / rel).exists():
                errors.append(f"artifact {key!r} path does not exist: {rel}")
            if kind not in {"markdown", "html", "json", "png", "csv", "parquet", "text"}:
                errors.append(f"artifact {key!r} has unknown kind: {kind!r}")
    if "framework_payload" in payload and not isinstance(payload["framework_payload"], dict):
        errors.append("framework_payload must be an object when present")
    if errors:
        raise ValidationError("\n  - " + "\n  - ".join(errors))


def validate_ml_signal(path: Path) -> None:
    payload = _read_json(path)
    errors = _validate_schema(payload, _schema("ml-signal"))
    signal_type = payload.get("signal_type")
    if signal_type == "regime":
        regime = payload.get("regime")
        if not isinstance(regime, dict):
            errors.append("regime field required when signal_type == 'regime'")
        else:
            probs = regime.get("state_probs", {})
            total = sum(float(v) for v in probs.values() if isinstance(v, (int, float)))
            if abs(total - 1.0) > 0.02:
                errors.append(f"state_probs must sum to ~1.0, got {total:.4f}")
    elif signal_type == "factor":
        factors = payload.get("factors")
        if not isinstance(factors, list) or not factors:
            errors.append("factors must be a non-empty list when signal_type == 'factor'")
    gate = payload.get("freshness_gate", {})
    if not isinstance(gate.get("stale_if_release_changes"), bool) or not gate["stale_if_release_changes"]:
        errors.append("freshness_gate.stale_if_release_changes must be true")
    if errors:
        raise ValidationError("\n  - " + "\n  - ".join(errors))


def validate_ml_signal_manifest(path: Path) -> None:
    manifest_root = path if path.is_dir() else path.parent
    manifest_file = path / "manifest.json" if path.is_dir() else path
    payload = _read_json(manifest_file)
    errors = _validate_schema(payload, _schema("ml-signal-manifest"))
    signals = payload.get("signals")
    if not isinstance(signals, list):
        errors.append("signals must be a list")
    else:
        for idx, entry in enumerate(signals):
            rel = entry.get("path", "")
            if not isinstance(rel, str) or not _path_is_relative(rel):
                errors.append(f"signals[{idx}].path must be a safe relative path: {rel!r}")
                continue
            signal_path = manifest_root / rel
            if not signal_path.exists():
                errors.append(f"signals[{idx}].path does not exist: {rel}")
            else:
                try:
                    validate_ml_signal(signal_path)
                except ValidationError as exc:
                    errors.append(f"signals[{idx}] ({rel}): {exc}")
    if errors:
        raise ValidationError("\n  - " + "\n  - ".join(errors))


def validate_report_artifacts(path: Path) -> None:
    payload = _read_json(path)
    errors = _validate_schema(payload, _schema("report-artifacts"))
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
    else:
        for idx, artifact in enumerate(artifacts):
            rel = artifact.get("path")
            kind = artifact.get("kind")
            if not isinstance(rel, str) or not _path_is_relative(rel):
                errors.append(f"artifact[{idx}] path must be a safe relative path: {rel!r}")
            if kind not in {"markdown", "html", "json", "png", "csv", "parquet", "text"}:
                errors.append(f"artifact[{idx}] has unknown kind: {kind!r}")
    if errors:
        raise ValidationError("\n  - " + "\n  - ".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Workbench contract payloads.")
    parser.add_argument(
        "kind",
        choices=[
            "provider-release",
            "evidence-panel",
            "model-run",
            "report-artifacts",
            "ml-signal",
            "ml-signal-manifest",
        ],
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.kind == "provider-release":
            validate_provider_release(args.path)
        elif args.kind == "evidence-panel":
            validate_evidence_panel(args.path)
        elif args.kind == "model-run":
            validate_model_run(args.path)
        elif args.kind == "report-artifacts":
            validate_report_artifacts(args.path)
        elif args.kind == "ml-signal":
            validate_ml_signal(args.path)
        elif args.kind == "ml-signal-manifest":
            validate_ml_signal_manifest(args.path)
    except ValidationError as exc:
        print("UNREADABLE")
        print(f"Reason: {exc}")
        return 1

    print("OK: readable Workbench contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
