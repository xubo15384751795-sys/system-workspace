"""P0-2 runtime status contract and classification sanity."""
from __future__ import annotations

from pathlib import Path

import yaml

from scripts._runtime_status_contract import (
    framework_output_status_values,
    judgment_decision_values,
    load_runtime_status_contract,
)
from scripts.verify_merge import STATEFUL_ROOT_TESTS

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_status_contract_includes_roadmap_enums() -> None:
    statuses = framework_output_status_values(include_legacy=False)
    assert "degraded_partial" in statuses
    assert "active_full" in statuses
    decisions = judgment_decision_values(include_legacy=False)
    assert "ACTIVE_WATCH" in decisions
    assert "WATCH_ONLY" in decisions
    assert "RESEARCH_REVIEW" in decisions


def test_framework_schema_and_contract_canonical_align() -> None:
    import json

    schema = json.loads(
        (ROOT / "governance" / "framework_output.schema.json").read_text(encoding="utf-8")
    )
    schema_enum = set(schema["properties"]["status"]["enum"])
    canonical = set(load_runtime_status_contract()["framework_output_status"]["canonical"])
    assert schema_enum == canonical


def test_stateful_classification_covers_ignored_suites() -> None:
    data = yaml.safe_load(
        (ROOT / "tests" / "stateful_test_classification.yaml").read_text(encoding="utf-8")
    )
    classified = {item["path"] for item in data["items"]}
    ignored = set(STATEFUL_ROOT_TESTS)
    # Every still-ignored suite must be classified; hermeticized suites may
    # remain in the classification file with class=hermetic.
    missing = ignored - classified
    assert not missing, f"STATEFUL_ROOT_TESTS missing classification: {missing}"
    hermetic = {item["path"] for item in data["items"] if item["class"] == "hermetic"}
    assert "tests/test_current_artifact_chain.py" in hermetic
    assert "tests/test_current_artifact_chain.py" not in ignored
    assert "tests/test_sys_entrypoints.py" in hermetic
    assert "tests/test_sys_entrypoints.py" not in ignored
    assert "tests/test_output_current.py" in hermetic
    assert "tests/test_output_current.py" not in ignored
    assert "tests/test_current_refresh_bundle.py" in hermetic
    assert "tests/test_current_refresh_bundle.py" not in ignored
    assert "tests/test_modules_paths_exist.py" in hermetic
    assert "tests/test_modules_paths_exist.py" not in ignored
