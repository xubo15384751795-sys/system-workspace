"""Shared provider status matrix contract tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from system_runtime.provider_status import (
    PROVIDER_STATUSES,
    ProviderStatusPolicyError,
    load_provider_status_matrix,
    provider_status_policy,
    validate_provider_status_matrix,
)

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_provider_status_matrix_is_complete_and_shared() -> None:
    matrix = load_provider_status_matrix(ROOT)
    assert set(matrix) == set(PROVIDER_STATUSES)
    assert provider_status_policy("refreshed", root=ROOT)["evaluator_verdict"] == "PASS"
    assert provider_status_policy(
        "reused_after_provider_failure", root=ROOT
    )["decision"] == "DENY"
    environmentally_blocked = provider_status_policy("environmentally_blocked", root=ROOT)
    assert environmentally_blocked["decision"] == "DENY"
    assert environmentally_blocked["watch_zero"] == "DIAGNOSTIC_ONLY"


def test_unknown_provider_status_fails_closed() -> None:
    with pytest.raises(ProviderStatusPolicyError, match="unknown provider status"):
        provider_status_policy("unknown", root=ROOT)


def test_matrix_validator_rejects_unknown_rows() -> None:
    matrix = load_provider_status_matrix(ROOT)
    matrix["unexpected"] = dict(matrix["refreshed"])
    with pytest.raises(ProviderStatusPolicyError, match="unknown statuses"):
        validate_provider_status_matrix(matrix)
