#!/usr/bin/env python3
"""Validate Output/current artifacts against schema contracts.

Modes:
  --require-artifacts   Fail if required artifacts or schemas are missing
                        (Nightly / Weekly scheduled depth checks).
  --ci-clean-checkout   Clean CI checkout may lack Output/current. Missing
                        artifacts yield verdict NOT_APPLICABLE (not PASS).
                        Present artifacts are still validated strictly.

Usage:
    python -m scripts.commands.ci.validate_current_schemas --require-artifacts
    python -m scripts.commands.ci.validate_current_schemas --ci-clean-checkout
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

REQUIRED_CHECKS = (
    {
        "label": "framework_output.json",
        "data": ROOT / "Output" / "current" / "framework_output.json",
        "schema": ROOT / "governance" / "framework_output.schema.json",
    },
    {
        "label": "status.json",
        "data": ROOT / "Output" / "current" / "status.json",
        "schema": ROOT / "protocols" / "current_card.schema.json",
    },
)


def _validate_one(data_path: Path, schema_path: Path) -> None:
    import jsonschema

    data = json.loads(data_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def run(*, require_artifacts: bool, ci_clean_checkout: bool) -> int:
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        print("ERROR: jsonschema not installed — cannot validate schemas")
        return 1

    missing: list[str] = []
    present: list[dict] = []
    for check in REQUIRED_CHECKS:
        data_path: Path = check["data"]
        schema_path: Path = check["schema"]
        if not data_path.exists() or not schema_path.exists():
            parts = []
            if not data_path.exists():
                parts.append(f"missing data {data_path.as_posix()}")
            if not schema_path.exists():
                parts.append(f"missing schema {schema_path.as_posix()}")
            missing.append(f"{check['label']}: {', '.join(parts)}")
        else:
            present.append(check)

    if missing:
        if require_artifacts:
            print("Schema validation FAIL — required artifacts/schemas missing:")
            for item in missing:
                print(f"  {item}")
            return 1
        if ci_clean_checkout and not present:
            print(
                json.dumps(
                    {
                        "check": "current_schemas",
                        "verdict": "NOT_APPLICABLE",
                        "reason": "clean checkout; required current artifacts absent",
                        "missing": missing,
                    },
                    indent=2,
                )
            )
            return 0
        if ci_clean_checkout:
            # Partial presence: validate what exists; missing required still fail.
            print("Schema validation FAIL — partial current tree is not clean-checkout N/A:")
            for item in missing:
                print(f"  {item}")
            return 1
        print("Schema validation FAIL — artifacts/schemas missing:")
        for item in missing:
            print(f"  {item}")
        return 1

    errors: list[str] = []
    for check in present:
        try:
            _validate_one(check["data"], check["schema"])
            print(f"{check['label']}: PASS")
        except Exception as exc:  # noqa: BLE001 — surface validation errors
            message = getattr(exc, "message", str(exc))
            errors.append(f"{check['label']}: {message}")
            print(f"{check['label']}: FAIL — {message}")

    if errors:
        print(f"Schema validation failed: {len(errors)} error(s)")
        return 1

    print(
        json.dumps(
            {
                "check": "current_schemas",
                "verdict": "PASS",
                "validated": [c["label"] for c in present],
            }
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail when required Output/current artifacts or schemas are missing.",
    )
    mode.add_argument(
        "--ci-clean-checkout",
        action="store_true",
        help="Missing current artifacts → NOT_APPLICABLE (not PASS).",
    )
    args = parser.parse_args()
    return run(
        require_artifacts=args.require_artifacts,
        ci_clean_checkout=args.ci_clean_checkout,
    )


if __name__ == "__main__":
    sys.exit(main())
