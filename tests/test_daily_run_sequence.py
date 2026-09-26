"""daily_run_sequence.yaml contract tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verity.runtime._daily_run_sequence import (  # noqa: E402
    load_daily_run_sequence,
    step_ids,
)


def test_daily_run_sequence_exists() -> None:
    path = ROOT / "governance" / "daily_run_sequence.yaml"
    assert path.exists()


def test_daily_run_sequence_has_core_steps() -> None:
    ids = step_ids()
    for required in (
        "harvester",
        "paper_sync",
        "neutral_pressure_measurement",
        "judgment_layer",
        "trade_decision",
        "claim_evaluator",
        "freshness_validator",
        "archive_daily_snapshots",
        "backfill_judgment_calibration",
        "mechanism_calibration",
        "evaluate_pending",
        "learning_hub_ingest",
        "system_index",
    ):
        assert required in ids


def test_daily_run_dry_run_labels_match_count() -> None:
    from verity.runtime._daily_run_sequence import dry_run_labels

    steps = load_daily_run_sequence()
    assert len(dry_run_labels()) == len(steps)


def test_daily_run_py_uses_sequence_count() -> None:
    content = (ROOT / "verity" / "cli" / "daily_run.py").read_text(encoding="utf-8")
    assert "load_daily_run_sequence" in content
    assert "dry_run_labels" in content


def test_daily_run_closes_learning_hub_ledgers_after_bundle_ingest() -> None:
    content = (ROOT / "verity" / "cli" / "daily_run.py").read_text(encoding="utf-8")
    bundle_ingest = content.index("ingest_daily_run_bundle(bundle_dir")
    ledger_ingest = content.index("run_learning_hub_ingest()")
    assert bundle_ingest < ledger_ingest


def test_daily_run_uses_canonical_learning_hub_import() -> None:
    content = (ROOT / "verity" / "cli" / "daily_run.py").read_text(encoding="utf-8")
    assert "from system_learning.operators.ingest_daily_run_to_hub import" in content
    assert "from ingest_daily_run_to_hub import" not in content
