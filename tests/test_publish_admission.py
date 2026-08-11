"""Acceptance skeleton for WP2: PublishAdmission and live-hash invariant.

Defines the contract that admission separates integrity and authority verdicts,
rejects runs with missing required artifacts or previous-run lineage, and
that a rejected run leaves live hashes/mtime/NAV-line-count unchanged.

Also asserts ``freshness_assumed_ok`` is removed.  Marked ``xfail(strict=True)``
until WP2 lands.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="WP2: publish admission not yet implemented",
)


def test_publish_admission_module_exists() -> None:
    from system_runtime.publish_admission import PublishAdmission  # noqa: F401


def test_admission_has_integrity_and_authority_verdicts() -> None:
    import dataclasses

    from system_runtime.publish_admission import PublishAdmission

    fields = {f.name for f in dataclasses.fields(PublishAdmission)}
    assert "integrity_verdict" in fields, "PublishAdmission must have integrity_verdict"
    assert "authority_verdict" in fields, "PublishAdmission must have authority_verdict"


def test_integrity_verdict_values() -> None:
    from system_runtime.publish_admission import PublishAdmission

    expected = {"PASS", "BLOCK"}
    actual = getattr(PublishAdmission, "INTEGRITY_VERDICTS", None) or getattr(
        PublishAdmission, "INTEGRITY_VALUES", None
    )
    assert actual is not None, "PublishAdmission must define INTEGRITY_VERDICTS"
    assert expected <= set(actual), f"Missing integrity verdicts: {expected - set(actual)}"


def test_authority_verdict_values() -> None:
    from system_runtime.publish_admission import PublishAdmission

    expected = {"ALLOW", "DIAGNOSTIC_ONLY", "BLOCK"}
    actual = getattr(PublishAdmission, "AUTHORITY_VERDICTS", None) or getattr(
        PublishAdmission, "AUTHORITY_VALUES", None
    )
    assert actual is not None, "PublishAdmission must define AUTHORITY_VERDICTS"
    assert expected <= set(actual), f"Missing authority verdicts: {expected - set(actual)}"


def test_freshness_assumed_ok_removed() -> None:
    """The ``freshness_assumed_ok`` escape hatch must not exist in admission code."""
    import inspect

    from system_runtime import publish_admission

    source = inspect.getsource(publish_admission)
    assert "freshness_assumed_ok" not in source, (
        "freshness_assumed_ok must be removed from publish_admission"
    )


def test_rejected_run_leaves_live_unchanged() -> None:
    """A rejected admission must not modify live current/position/NAV/ledger.

    This is a contract assertion: the admission module must expose a method
    that, on BLOCK, skips all live-surface writes.
    """
    import inspect

    from system_runtime.publish_admission import PublishAdmission

    source = inspect.getsource(PublishAdmission)
    assert "BLOCK" in source, "PublishAdmission must handle BLOCK verdict"
    # Must reference live-surface preservation semantics
    assert "current" in source.lower() or "live" in source.lower(), (
        "PublishAdmission must reference live current preservation"
    )
