"""Machine-readable boundary for derived proxy measurement candidates."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from system_runtime.context import RuntimeContext


SCHEMA_VERSION = "system.measurement_spec.v1"
PROXY_CLAIM_CEILING = "diagnostic_proxy_candidate_only"
PROXY_SERIES_IDS = frozenset(
    {
        "SOFR_IORB_SPREAD",
        "CP_TBILL_SPREAD",
        "VIX3M_VIX_SLOPE",
        "SPX_ROLL_SPREAD",
        "MOVE_PROXY",
    }
)
RECOGNIZED_STATES = [
    "AVAILABLE",
    "STALE",
    "DELAYED",
    "MISSING",
    "NOT_APPLICABLE",
    "SOURCE_DOWN",
    "SCHEMA_CHANGED",
    "DISCONTINUED",
    "UNKNOWN",
]


class MeasurementSpecValidationError(ValueError):
    """Raised when a proxy measurement specification violates its contract."""


def contracts_dir() -> Path:
    return RuntimeContext.current_context().workspace / "packages" / "harvester" / "contracts"


def schema_path() -> Path:
    return contracts_dir() / "proxy_measurement_spec.schema.json"


def load_schema() -> dict[str, Any]:
    payload = json.loads(schema_path().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MeasurementSpecValidationError("measurement spec schema must be an object")
    return payload


def _source_ladder(series: Any, registry: Any) -> list[dict[str, Any]]:
    inputs = [str(value) for value in getattr(series, "inputs", ())]
    ladder: list[dict[str, Any]] = []
    for input_id in inputs:
        input_series = registry.get(input_id) if hasattr(registry, "get") else None
        providers = [str(value) for value in getattr(input_series, "provider_priority", ())]
        if not providers:
            ladder.append(
                {
                    "tier": 1,
                    "input_series_ids": [input_id],
                    "source_ids": ["unresolved"],
                    "role": "UNRESOLVED",
                }
            )
            continue
        for tier, provider in enumerate(providers, start=1):
            ladder.append(
                {
                    "tier": tier,
                    "input_series_ids": [input_id],
                    "source_ids": [provider],
                    "role": "PRIMARY" if tier == 1 else "FALLBACK",
                }
            )
    if not ladder:
        ladder.append(
            {
                "tier": 1,
                "input_series_ids": [str(getattr(series, "source_series_id", "derived"))],
                "source_ids": ["derived"],
                "role": "COMPUTED",
            }
        )
    return ladder


def build_proxy_measurement_spec(
    *,
    release_id: str,
    derived_series: Sequence[Any],
    registry: Any,
    candidate_panel: Any,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Describe proxy candidates without granting them promotion authority."""
    captured = captured_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    candidate_rows = int(len(candidate_panel))
    row_counts: dict[str, int] = {}
    if hasattr(candidate_panel, "columns") and "source_series_id" in candidate_panel.columns:
        row_counts = {
            str(key): int(value)
            for key, value in candidate_panel["source_series_id"].value_counts(dropna=True).to_dict().items()
        }

    candidates: list[dict[str, Any]] = []
    for series in derived_series:
        canonical_id = str(getattr(series, "canonical_id", ""))
        source_series_id = str(getattr(series, "source_series_id", "") or canonical_id)
        if canonical_id not in PROXY_SERIES_IDS and source_series_id not in PROXY_SERIES_IDS:
            continue
        candidates.append(
            {
                "canonical_series_id": canonical_id,
                "source_series_id": source_series_id,
                "formula": str(getattr(series, "formula", "")),
                "inputs": [str(value) for value in getattr(series, "inputs", ())],
                "structural_role": str(getattr(series, "structural_role", "") or canonical_id),
                "quality_expectation": str(getattr(series, "quality_expectation", "derived")),
                "source_ladder": _source_ladder(series, registry),
                "row_count": row_counts.get(source_series_id, row_counts.get(canonical_id, 0)),
            }
        )
    candidates.sort(key=lambda item: item["canonical_series_id"])
    release_token = "".join(char.lower() if char.isalnum() else "_" for char in release_id)
    spec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "spec_id": f"mspec_proxy_candidate_panel_{release_token}",
        "dataset_id": "proxy_candidate_panel",
        "release_id": release_id,
        "status": "CANDIDATE",
        "derivation": "PROXY_DERIVED",
        "target_variable": "latent_structural_signal",
        "measurement_definition": (
            "Derived proxy candidate for structural research; not a promoted observation "
            "or decision claim."
        ),
        "candidate_row_count": candidate_rows,
        "candidate_series": candidates,
        "missingness_policy": {
            "recognized_states": RECOGNIZED_STATES,
            "stale_states": ["STALE"],
            "blocked_states": [
                "MISSING",
                "NOT_APPLICABLE",
                "SOURCE_DOWN",
                "SCHEMA_CHANGED",
                "DISCONTINUED",
                "UNKNOWN",
            ],
            "imputation_allowed": False,
            "carry_forward_allowed": False,
        },
        "claim_ceiling": PROXY_CLAIM_CEILING,
        "promotion_allowed": False,
        "promotion_requirements": [
            "approve a target-specific MeasurementSpec",
            "validate the source ladder and proxy-to-target relationship",
            "define conflict, missingness, and uncertainty handling",
            "pass an explicit human-reviewed promotion gate",
        ],
        "provenance": {
            "captured_at": captured,
            "producer": "harvester.derived_proxy",
            "release_id": release_id,
            "notes": "Candidate/proxy boundary; no canonical Observation->Claim chain is emitted.",
        },
    }
    validate_measurement_spec(spec)
    return spec


def validate_measurement_spec(
    spec: Mapping[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    validator = Draft202012Validator(schema or load_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(dict(spec)), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise MeasurementSpecValidationError(f"measurement spec failed validation: {details}")


def load_measurement_spec(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MeasurementSpecValidationError(f"measurement spec must be an object: {target}")
    validate_measurement_spec(payload)
    return payload


__all__ = [
    "MeasurementSpecValidationError",
    "PROXY_CLAIM_CEILING",
    "PROXY_SERIES_IDS",
    "SCHEMA_VERSION",
    "build_proxy_measurement_spec",
    "contracts_dir",
    "load_measurement_spec",
    "load_schema",
    "schema_path",
    "validate_measurement_spec",
]
