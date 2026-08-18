"""Scheduled launchd slot idempotency contract tests."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from system_runtime.schedule_slots import (
    ScheduledSlotStore,
    completed_session_slot_key,
    local_slot_key,
    slot_key_for_date,
)


def test_unique_slot_allows_one_concurrent_claim(tmp_path: Path) -> None:
    store = ScheduledSlotStore(tmp_path / "schedule.sqlite3")
    slot = slot_key_for_date(datetime(2026, 8, 12).date())

    def claim(index: int):
        return store.claim(slot, owner_id=f"owner-{index}", owner_pid=os.getpid())

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, range(2)))

    assert sum(claim.acquired for claim in claims) == 1
    assert sum(claim.duplicate for claim in claims) == 1


def test_completed_slot_is_not_replayed(tmp_path: Path) -> None:
    store = ScheduledSlotStore(tmp_path / "schedule.sqlite3")
    slot = local_slot_key(label="test.schedule", now=datetime(2026, 8, 12, tzinfo=UTC))
    first = store.claim(slot, owner_id="first", owner_pid=os.getpid())

    assert first.acquired
    assert store.complete(slot, owner_id="first", outcome={"publish_status": "COMMITTED"})

    second = store.claim(slot, owner_id="second", owner_pid=os.getpid())
    assert second.duplicate
    assert second.existing_status == "completed"
    assert store.get(slot)["outcome"] == {"publish_status": "COMMITTED"}


def test_failed_completed_slot_can_be_retried(tmp_path: Path) -> None:
    store = ScheduledSlotStore(tmp_path / "schedule.sqlite3")
    slot = local_slot_key(label="test.retry", now=datetime(2026, 8, 12, tzinfo=UTC))
    first = store.claim(slot, owner_id="first", owner_pid=os.getpid())

    assert first.acquired
    assert store.complete(
        slot,
        owner_id="first",
        outcome={
            "execution_status": "FAILED",
            "publish_status": "NOT_PUBLISHED",
            "reason_codes": ["REQUIRED_STEP_FAILED", "PUBLISH_NOT_COMMITTED"],
        },
    )

    retry = store.claim(slot, owner_id="retry", owner_pid=os.getpid())

    assert retry.acquired
    assert retry.reclaimed_owner_id == "first"
    assert store.get(slot)["status"] == "claimed"


def test_malformed_completed_outcome_is_retried(tmp_path: Path) -> None:
    store = ScheduledSlotStore(tmp_path / "schedule.sqlite3")
    slot = local_slot_key(label="test.malformed", now=datetime(2026, 8, 12, tzinfo=UTC))
    first = store.claim(slot, owner_id="first", owner_pid=os.getpid())

    assert first.acquired
    assert store.complete(
        slot,
        owner_id="first",
        outcome={
            "execution_status": "SUCCESS",
            "publish_status": "COMMITTED",
            "reason_codes": "not-a-list",
        },
    )

    retry = store.claim(slot, owner_id="retry", owner_pid=os.getpid())

    assert retry.acquired
    assert retry.reclaimed_owner_id == "first"


def test_dead_claim_can_be_reclaimed_without_second_live_owner(tmp_path: Path) -> None:
    store = ScheduledSlotStore(tmp_path / "schedule.sqlite3")
    slot = slot_key_for_date(datetime(2026, 8, 12).date(), label="test.recovery")
    first = store.claim(slot, owner_id="dead-owner", owner_pid=2**31 - 1)
    assert first.acquired

    recovered = store.claim(slot, owner_id="recovered-owner", owner_pid=os.getpid())
    assert recovered.acquired
    assert recovered.reclaimed_owner_id == "dead-owner"
    assert store.get(slot)["status"] == "claimed"


def test_completed_session_slot_converges_weekend_and_preopen_wakes() -> None:
    friday = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 8, 15, 0, tzinfo=UTC),
    )
    sunday = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 8, 16, 23, tzinfo=UTC),
    )
    monday_before_close = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 8, 17, 19, tzinfo=UTC),
    )

    assert friday == sunday == monday_before_close == "test.session|2026-08-14"


def test_completed_session_slot_advances_only_after_session_close() -> None:
    before_close = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 8, 17, 19, tzinfo=UTC),
    )
    after_close = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 8, 17, 23, tzinfo=UTC),
    )

    assert before_close == "test.session|2026-08-14"
    assert after_close == "test.session|2026-08-17"


def test_completed_session_slot_is_dst_stable() -> None:
    before_dst = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 3, 7, 23, tzinfo=UTC),
    )
    after_dst = completed_session_slot_key(
        label="test.session",
        now=datetime(2026, 3, 8, 23, tzinfo=UTC),
    )

    assert before_dst == after_dst == "test.session|2026-03-06"
