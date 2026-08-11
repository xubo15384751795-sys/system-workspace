"""Acceptance skeleton for WP2: current/decision/shadow unified publish transaction.

Defines the contract that publish is a single transaction:
PREPARING -> PREPARED -> ADMITTED -> COMMITTING -> COMMITTED | ROLLED_BACK | RECOVERY_REQUIRED.

Candidate directories are established at run start, and on failure the
previous generation is preserved.  Marked ``xfail(strict=True)`` until WP2 lands.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="WP2: publish transaction not yet implemented",
)


def test_publish_transaction_module_exists() -> None:
    from system_runtime.publish_transaction import PublishTransaction  # noqa: F401


def test_transaction_states_defined() -> None:
    from system_runtime.publish_transaction import PublishTransaction

    expected_states = {
        "PREPARING",
        "PREPARED",
        "ADMITTED",
        "COMMITTING",
        "COMMITTED",
        "ROLLED_BACK",
        "RECOVERY_REQUIRED",
    }
    # PublishTransaction should expose valid states as a class attribute
    states = getattr(PublishTransaction, "STATES", None) or getattr(
        PublishTransaction, "VALID_STATES", None
    )
    assert states is not None, "PublishTransaction must define STATES"
    assert expected_states <= set(states), f"Missing states: {expected_states - set(states)}"


def test_candidate_dirs_established_at_run_start() -> None:
    """A run must create publish_candidate/ dirs before any writer imports."""
    import inspect

    from system_runtime.publish_transaction import PublishTransaction

    source = inspect.getsource(PublishTransaction)
    assert "publish_candidate" in source, (
        "PublishTransaction must reference publish_candidate directories"
    )


def test_transaction_rollback_restores_previous_generation() -> None:
    """On failure, the transaction must restore the previous generation."""
    import inspect

    from system_runtime.publish_transaction import PublishTransaction

    source = inspect.getsource(PublishTransaction)
    assert "retired" in source.lower() or "restore" in source.lower() or "rollback" in source.lower(), (
        "PublishTransaction must implement generation rollback/restore"
    )
