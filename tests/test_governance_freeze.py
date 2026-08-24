from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.critical_gate


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_governance_freeze_passes_on_current_repo() -> None:
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    report = module.check_governance_freeze(ROOT)
    assert report["valid"] is True, report["violations"]
    assert report["unapproved_new_files"] == []
    # Hash mismatches are now advisory (medium severity) — may be present but don't block


def test_unapproved_file_detected(tmp_path: Path) -> None:
    """Unclassified root files still fail freeze; freeze-allowlist is not the gate."""
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    (tmp_path / "governance").mkdir()
    for name in ("system_constitution.yaml", "governance_freeze_manifest.yaml", "governance_tiers.yaml"):
        (tmp_path / "governance" / name).write_text("schema_version: test\n", encoding="utf-8")
    (tmp_path / "governance" / "governance_freeze_manifest.yaml").write_text(
        (ROOT / "governance/governance_freeze_manifest.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "governance" / "governance_tiers.yaml").write_text(
        "work_support:\n  files: []\n",
        encoding="utf-8",
    )
    (tmp_path / "governance" / "system_constitution.yaml").write_text(
        "governance_freeze:\n  active: true\n",
        encoding="utf-8",
    )
    (tmp_path / "governance" / "random_new_rule.yaml").write_text("x: 1\n", encoding="utf-8")
    report = module.check_governance_freeze(tmp_path)
    assert report["valid"] is False
    assert "random_new_rule.yaml" in report["unapproved_new_files"]
    assert any(v["id"] == "governance_shape_unclassified" for v in report["violations"])


def test_baseline_hash_integrity_detects_modification(tmp_path: Path) -> None:
    """Tampering with a critical baseline file must block."""
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    # Copy real governance dir to tmp
    gov_tmp = tmp_path / "governance"
    shutil.copytree(ROOT / "governance", gov_tmp)
    shutil.copyfile(ROOT / "ROUTING_CONSTITUTION.md", tmp_path / "ROUTING_CONSTITUTION.md")

    # Tamper with a baseline file
    target = gov_tmp / "incentive_policy.yaml"
    target.write_text(target.read_text() + "\n# TAMPERED\n", encoding="utf-8")

    report = module.check_governance_freeze(tmp_path)
    assert report["valid"] is False
    assert any("incentive_policy.yaml" in m["file"] for m in report["hash_mismatches"])
    assert any(v["id"] == "baseline_file_modified" and v["severity"] == "high" for v in report["violations"])


def test_baseline_hash_integrity_detects_missing_file(tmp_path: Path) -> None:
    """Deleting any baseline file must block."""
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    gov_tmp = tmp_path / "governance"
    shutil.copytree(ROOT / "governance", gov_tmp)
    shutil.copyfile(ROOT / "ROUTING_CONSTITUTION.md", tmp_path / "ROUTING_CONSTITUTION.md")

    # Delete a baseline file
    (gov_tmp / "redundancy_budget.yaml").unlink()

    report = module.check_governance_freeze(tmp_path)
    assert report["valid"] is False
    assert any("redundancy_budget.yaml" in m["file"] for m in report["hash_mismatches"])
    assert any(v["id"] == "baseline_file_missing" and v["severity"] == "high" for v in report["violations"])


def test_review_after_enforcement(tmp_path: Path) -> None:
    """Expired review_after date must be flagged."""
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    gov_tmp = tmp_path / "governance"
    shutil.copytree(ROOT / "governance", gov_tmp)

    # Set review_after to past date in BOTH manifest and constitution
    manifest = yaml.safe_load((gov_tmp / "governance_freeze_manifest.yaml").read_text())
    manifest["review_after"] = "2020-01-01"
    (gov_tmp / "governance_freeze_manifest.yaml").write_text(yaml.dump(manifest))

    const = yaml.safe_load((gov_tmp / "system_constitution.yaml").read_text())
    const.setdefault("governance_freeze", {})["review_after"] = "2020-01-01"
    (gov_tmp / "system_constitution.yaml").write_text(yaml.dump(const))

    report = module.check_governance_freeze(tmp_path)
    assert any(v["id"] == "freeze_review_expired" for v in report["violations"])


def test_pending_commit_detected(tmp_path: Path) -> None:
    """commit='pending' in approved_additions must be flagged."""
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    gov_tmp = tmp_path / "governance"
    shutil.copytree(ROOT / "governance", gov_tmp)

    # Inject a pending commit
    manifest = yaml.safe_load((gov_tmp / "governance_freeze_manifest.yaml").read_text())
    manifest["approved_additions"].append({
        "file": "fake_pending.yaml",
        "approved_at": "2026-06-18",
        "commit": "pending",
        "reason": "test",
    })
    (gov_tmp / "governance_freeze_manifest.yaml").write_text(yaml.dump(manifest))
    (gov_tmp / "fake_pending.yaml").write_text("x: 1\n")

    report = module.check_governance_freeze(tmp_path)
    assert any(v["id"] == "pending_commit_attribution" for v in report["violations"])


def test_approved_additions_budget_is_advisory(tmp_path: Path) -> None:
    """Exceeding approved_additions ledger cap is medium and does not fail freeze."""
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    gov_tmp = tmp_path / "governance"
    shutil.copytree(ROOT / "governance", gov_tmp)

    manifest = yaml.safe_load((gov_tmp / "governance_freeze_manifest.yaml").read_text())
    manifest["approved_additions_budget"] = {"max_files": 2}
    (gov_tmp / "governance_freeze_manifest.yaml").write_text(yaml.dump(manifest))

    report = module.check_governance_freeze(tmp_path)
    budget_hits = [v for v in report["violations"] if v["id"] == "approved_additions_budget_exceeded"]
    assert budget_hits
    assert all(v["severity"] == "medium" for v in budget_hits)
    assert not any(
        v["id"] == "approved_additions_budget_exceeded" and v["severity"] == "high"
        for v in report["violations"]
    )


def test_no_pending_commits_in_manifest() -> None:
    """Real manifest must not contain commit='pending'."""
    manifest = yaml.safe_load(
        (ROOT / "governance" / "governance_freeze_manifest.yaml").read_text()
    )
    pending = [
        item for item in manifest.get("approved_additions", [])
        if item.get("commit") == "pending"
    ]
    assert pending == [], f"Found pending commits: {[p['file'] for p in pending]}"


def test_admission_is_shape_inventory_not_freeze_allowlist() -> None:
    """A classified machine registry is admitted without freeze-allowlist membership."""
    manifest = yaml.safe_load(
        (ROOT / "governance" / "governance_freeze_manifest.yaml").read_text()
    )
    allowed = set(manifest.get("baseline_root_files", [])) | {
        item["file"] for item in manifest.get("approved_additions", []) if item.get("file")
    }
    assert "experiment_registry.yaml" not in allowed
    module = _load("governance_freeze", ROOT / "scripts" / "_governance_freeze.py")
    report = module.check_governance_freeze(ROOT)
    assert report["valid"] is True, report["violations"]
    assert "experiment_registry.yaml" not in report["unapproved_new_files"]


def test_operational_registries_are_not_hash_blocking() -> None:
    manifest = yaml.safe_load(
        (ROOT / "governance" / "governance_freeze_manifest.yaml").read_text()
    )
    blocking = set(manifest.get("blocking_hash_files", []) or [])
    for name in (
        "daily_pipeline_registry.yaml",
        "entrypoint_registry.yaml",
        "capability_registry.yaml",
    ):
        assert name not in blocking
    for name in (
        "system_constitution.yaml",
        "authority_registry.yaml",
        "output_routing_policy.yaml",
        "incentive_policy.yaml",
    ):
        assert name in blocking
