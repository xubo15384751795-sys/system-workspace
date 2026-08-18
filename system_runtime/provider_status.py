"""Shared reader for the versioned provider outcome status matrix."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path("configs/provider_release_policy.yaml")
PROVIDER_STATUSES = frozenset(
    {
        "refreshed",
        "reused_same_content",
        "reused_after_provider_failure",
        "partial_provider_success",
        "provider_failed_no_acceptable_fallback",
        "no_release_expected",
        "environmentally_blocked",
    }
)
MATRIX_FIELDS = frozenset(
    {"diagnostic", "decision", "watch_zero", "feedback", "alert", "evaluator_verdict"}
)
MATRIX_VALUES = {
    "diagnostic": frozenset({"ALLOW", "FAILURE_ONLY"}),
    "decision": frozenset({"ALLOW", "CONDITIONAL", "DENY"}),
    "watch_zero": frozenset({"NOT_REQUIRED", "CONDITIONAL", "DIAGNOSTIC_ONLY"}),
    "feedback": frozenset({"ELIGIBLE_AFTER_REVIEW", "REVIEW_REQUIRED", "DENY"}),
    "alert": frozenset({"INFO", "NOTICE", "WARNING", "ERROR"}),
    "evaluator_verdict": frozenset({"PASS", "WARN", "BLOCKED", "FAIL"}),
}


class ProviderStatusPolicyError(ValueError):
    """Raised when the shared provider status matrix is absent or malformed."""


def validate_provider_status_matrix(matrix: Any) -> dict[str, dict[str, str]]:
    """Validate and normalize a provider status matrix.

    The validator accepts fixture policies as well as the workspace policy so
    domain evaluators can test custom release rules without reimplementing the
    matrix contract. Unknown rows are rejected: adding a provider outcome is a
    policy change, not an ignorable metadata extension.
    """
    if not isinstance(matrix, Mapping):
        raise ProviderStatusPolicyError("provider status matrix must be a mapping")
    unknown = sorted(set(matrix) - PROVIDER_STATUSES)
    if unknown:
        raise ProviderStatusPolicyError(f"provider status matrix has unknown statuses: {unknown}")
    missing = sorted(PROVIDER_STATUSES - set(matrix))
    if missing:
        raise ProviderStatusPolicyError(f"provider status matrix missing statuses: {missing}")

    validated: dict[str, dict[str, str]] = {}
    for status in sorted(PROVIDER_STATUSES):
        entry = matrix.get(status)
        if not isinstance(entry, Mapping) or not MATRIX_FIELDS.issubset(entry):
            raise ProviderStatusPolicyError(f"provider status matrix entry incomplete: {status}")
        for field, allowed in MATRIX_VALUES.items():
            value = entry[field]
            if value not in allowed:
                raise ProviderStatusPolicyError(
                    f"provider status matrix value invalid: {status}.{field}"
                )
        validated[status] = {field: str(entry[field]) for field in sorted(MATRIX_FIELDS)}
    return validated


def load_provider_status_matrix(root: Path = ROOT) -> dict[str, dict[str, str]]:
    """Load and validate the status matrix without evaluating a provider event."""
    path = root / POLICY_PATH
    if not path.is_file():
        raise ProviderStatusPolicyError(f"provider status policy missing: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProviderStatusPolicyError(f"provider status policy is invalid YAML: {path}") from exc
    matrix = payload.get("status_matrix") if isinstance(payload, dict) else None
    if not isinstance(matrix, dict):
        raise ProviderStatusPolicyError("provider status policy requires status_matrix")
    return validate_provider_status_matrix(matrix)


def provider_status_policy(status: str, *, root: Path = ROOT) -> dict[str, str]:
    """Return the one policy row for a provider outcome status."""
    normalized = str(status or "").strip().lower()
    if normalized not in PROVIDER_STATUSES:
        raise ProviderStatusPolicyError(f"unknown provider status: {status!r}")
    return dict(load_provider_status_matrix(root)[normalized])


__all__ = [
    "MATRIX_FIELDS",
    "PROVIDER_STATUSES",
    "ProviderStatusPolicyError",
    "load_provider_status_matrix",
    "provider_status_policy",
    "validate_provider_status_matrix",
]
