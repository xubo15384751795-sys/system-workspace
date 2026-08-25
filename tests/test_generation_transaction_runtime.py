"""Runtime tests for immutable generation publication and admission isolation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts._runtime_io import surface_dir
from scripts.reconcile_generation import main as reconcile_generation_main
from system_runtime.publish_admission import (
    AUTHORITY_ALLOW,
    AUTHORITY_BLOCK,
    AUTHORITY_DIAGNOSTIC_ONLY,
    PublishAdmission,
)
from system_runtime.publish_transaction import (
    CompatibilityMigrationRequired,
    PublishTransaction,
    TransactionState,
)


def _contract_digests(tx: PublishTransaction) -> dict[str, str]:
    assert tx.generation_digest is not None
    return {
        "plan_digest": hashlib.sha256(b"compiled-plan").hexdigest(),
        "evidence_digest": hashlib.sha256(f"{tx.run_id}:evidence".encode()).hexdigest(),
        "generation_digest": tx.generation_digest,
    }


def test_publish_transaction_rejects_unsafe_run_id_before_prepare(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="safe path component"):
        PublishTransaction("../escaped", tmp_path / "Output" / "runs" / "escaped")


def _admit(
    tx: PublishTransaction,
    *,
    status: str = "success",
    authority: str = AUTHORITY_ALLOW,
) -> bool:
    tx.prepare()
    tx.activate()
    (tx.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    tx.write_lineage()
    token = PublishAdmission.evaluate(
        run_status=status,
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=authority,
        generation_id=tx.run_id,
        **_contract_digests(tx),
    )
    return tx.admit(token)


def test_generation_commit_switches_one_live_pointer_and_persists_journal(tmp_path: Path) -> None:
    tx = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(tx)
    target = tx.commit_generation(tmp_path)
    tx.deactivate()

    assert (tmp_path / "Output" / "live").resolve() == target
    for surface in ("current", "position", "judgment", "trade_decision", "trade_ledger", "quality", "system_learning"):
        assert (tmp_path / "Output" / surface).resolve() == target / surface
    assert (tmp_path / "Output" / "ledgers").resolve() == target / "trade_ledger"
    assert (target / "latest_run_id.txt").read_text(encoding="utf-8").strip() == "run_a"
    assert (target / "current" / "latest_run_id.txt").read_text(encoding="utf-8").strip() == "run_a"
    lineage = json.loads((target / "lineage.json").read_text(encoding="utf-8"))
    assert {
        "latest_run_id.txt",
        "current/latest_run_id.txt",
    }.issubset({entry["path"] for entry in lineage["files"]})
    assert PublishTransaction.reconcile(tmp_path)["status"] == "complete"
    with sqlite3.connect(tx.journal_path) as db:
        assert db.execute("select count(*) from domain_transitions").fetchone()[0] >= 5


def test_generation_commit_can_target_an_isolated_output_root(tmp_path: Path) -> None:
    isolated_output = tmp_path / "dual-track" / "native" / "Output"
    tx = PublishTransaction("run_isolated", isolated_output / "runs" / "run_isolated")
    assert _admit(tx)
    try:
        target = tx.commit_generation(tmp_path, output_root=isolated_output)

        assert target == isolated_output / "generations" / "run_isolated"
        assert (isolated_output / "live").resolve() == target
        assert (isolated_output / "current").resolve() == target / "current"
        assert PublishTransaction.reconcile(
            tmp_path,
            output_root=isolated_output,
        )["status"] == "complete"
        assert not (tmp_path / "Output").exists()
    finally:
        tx.deactivate()


def test_prepare_failure_never_exposes_a_live_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tx = PublishTransaction("run_prepare_failure", tmp_path / "Output" / "runs" / "run_prepare_failure")
    original_mkdir = Path.mkdir
    failed_path = tx.run_dir / "publish_candidate" / "current"

    def fail_prepare(path: Path, *args, **kwargs):
        if path == failed_path:
            raise OSError("injected prepare failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_prepare)
    with pytest.raises(OSError, match="injected prepare failure"):
        tx.prepare()

    assert tx.state == TransactionState.PREPARING
    assert not (tmp_path / "Output" / "live").exists()


def test_materialization_failure_preserves_previous_live_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    second = PublishTransaction("run_materialization_failure", tmp_path / "Output" / "runs" / "run_materialization_failure")
    assert _admit(second)
    import system_runtime.publish_transaction as publish_module

    original_replace = publish_module.os.replace
    target = tmp_path / "Output" / "generations" / second.run_id

    def fail_materialization(source, destination):
        if Path(source) == second.generation_dir and Path(destination) == target:
            raise OSError("injected materialization failure")
        return original_replace(source, destination)

    monkeypatch.setattr(publish_module.os, "replace", fail_materialization)
    try:
        with pytest.raises(OSError, match="injected materialization failure"):
            second.commit_generation(tmp_path)
        assert second.state == TransactionState.RECOVERY_REQUIRED
        assert (tmp_path / "Output" / "live").resolve() == active
        assert not target.exists()
        assert PublishTransaction.reconcile(tmp_path)["status"] == "recovery_required"
    finally:
        second.deactivate()


def test_journal_boundary_failure_leaves_materialized_generation_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    second = PublishTransaction("run_journal_failure", tmp_path / "Output" / "runs" / "run_journal_failure")
    assert _admit(second)
    original_journal = second._journal

    def fail_after_materialization(step: str, message: str):
        if step == "commit_generation" and message.startswith("materialized="):
            raise OSError("injected journal boundary failure")
        return original_journal(step, message)

    monkeypatch.setattr(second, "_journal", fail_after_materialization)
    try:
        with pytest.raises(OSError, match="injected journal boundary failure"):
            second.commit_generation(tmp_path)
        assert (tmp_path / "Output" / "live").resolve() == active
        assert PublishTransaction.reconcile(tmp_path)["status"] == "recovery_required"
        assert (tmp_path / "Output" / "generations" / second.run_id).is_dir()
    finally:
        second.deactivate()


def test_diagnostic_only_generation_requires_integrity_pass(tmp_path: Path) -> None:
    tx = PublishTransaction("run_diagnostic", tmp_path / "Output" / "runs" / "run_diagnostic")
    tx.prepare()
    tx.activate()
    (tx.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    tx.write_lineage()
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_DIAGNOSTIC_ONLY,
        generation_id=tx.run_id,
        **_contract_digests(tx),
    )
    try:
        assert token.integrity_verdict == "PASS"
        assert token.diagnostic_verdict == "PASS"
        assert token.authority_verdict == AUTHORITY_DIAGNOSTIC_ONLY
        assert tx.admit(token)
        target = tx.commit_generation(tmp_path)
        admission = json.loads((target / "admission.json").read_text(encoding="utf-8"))
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        assert admission["publish_integrity_verdict"] == "PASS"
        assert admission["diagnostic_publish_verdict"] == "PASS"
        assert admission["decision_authority_verdict"] == AUTHORITY_DIAGNOSTIC_ONLY
        assert manifest["authority"] == AUTHORITY_DIAGNOSTIC_ONLY
    finally:
        tx.deactivate()


def test_decision_denial_can_publish_same_run_diagnostic_generation(tmp_path: Path) -> None:
    tx = PublishTransaction("run_denied", tmp_path / "Output" / "runs" / "run_denied")
    try:
        assert _admit(tx, authority=AUTHORITY_BLOCK)
        target = tx.commit_generation(tmp_path)
        admission = json.loads((target / "admission.json").read_text(encoding="utf-8"))
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        assert admission["publish_integrity_verdict"] == "PASS"
        assert admission["diagnostic_publish_verdict"] == "PASS"
        assert admission["decision_authority_verdict"] == AUTHORITY_BLOCK
        assert manifest["authority"] == AUTHORITY_BLOCK
    finally:
        tx.deactivate()


def test_blocked_admission_preserves_active_generation(tmp_path: Path) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    second = PublishTransaction("run_b", tmp_path / "Output" / "runs" / "run_b")
    try:
        assert _admit(second, status="partial_failure") is False
        assert second.state == TransactionState.PREPARED
        assert (tmp_path / "Output" / "live").resolve() == active
        assert not (tmp_path / "Output" / "generations" / "run_b").exists()
    finally:
        second.deactivate()


def test_missing_required_readme_preserves_active_generation(tmp_path: Path) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    second = PublishTransaction("run_missing_readme", tmp_path / "Output" / "runs" / "run_missing_readme")
    second.prepare()
    second.activate()
    (second.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    second.write_lineage()
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=["current/00_READ_ME_FIRST.md", "current/framework_output.json"],
        candidate_artifacts=["current/framework_output.json"],
        candidate_run_id=second.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=second.run_id,
        **_contract_digests(second),
    )
    try:
        assert second.admit(token) is False
        admission = json.loads((second.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert admission["integrity_verdict"] == "BLOCK"
        assert "REQUIRED_ARTIFACT_MISSING" in admission["reason_codes"]
        assert (tmp_path / "Output" / "live").resolve() == active
    finally:
        second.deactivate()


def test_reconcile_reports_pointer_switch_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    second = PublishTransaction("run_b", tmp_path / "Output" / "runs" / "run_b")
    assert _admit(second)

    import system_runtime.publish_transaction as publish_module

    original_replace = publish_module.os.replace

    def fail_live_pointer(source, destination):
        if Path(source).name.startswith(".live.next."):
            raise OSError("injected live pointer failure")
        return original_replace(source, destination)

    monkeypatch.setattr(publish_module.os, "replace", fail_live_pointer)
    try:
        with pytest.raises(OSError, match="injected live pointer failure"):
            second.commit_generation(tmp_path)
        assert second.state == TransactionState.RECOVERY_REQUIRED
        assert (tmp_path / "Output" / "live").resolve() == active
        reconciliation = PublishTransaction.reconcile(tmp_path)
        assert reconciliation["status"] == "recovery_required"
        assert reconciliation["interrupted_generation"].endswith("run_b")
    finally:
        second.deactivate()


def test_reconcile_classifies_successful_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "Output" / "current"
    target.mkdir(parents=True)
    (target / "state.txt").write_text("old\n", encoding="utf-8")
    candidate = tmp_path / "Output" / "runs" / "run_rollback" / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "state.txt").write_text("new\n", encoding="utf-8")

    tx = PublishTransaction("run_rollback", tmp_path / "Output" / "runs" / "run_rollback")
    tx.state = TransactionState.ADMITTED
    import system_runtime.publish_transaction as publish_module

    original_replace = publish_module.os.replace

    def fail_candidate_swap(source, destination):
        if Path(source) == candidate and Path(destination) == target:
            raise OSError("injected candidate swap failure")
        return original_replace(source, destination)

    monkeypatch.setattr(publish_module.os, "replace", fail_candidate_swap)
    assert tx.commit(target, candidate) is False
    assert tx.state == TransactionState.ROLLED_BACK
    assert (target / "state.txt").read_text(encoding="utf-8") == "old\n"

    state = PublishTransaction.reconcile(tmp_path)
    assert state["status"] == "rollback"
    assert state["rolled_back_run"] == "run_rollback"


def test_compatibility_link_failure_happens_before_live_pointer_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    second = PublishTransaction("run_b", tmp_path / "Output" / "runs" / "run_b")
    assert _admit(second)
    # Force the transaction to prepare a compatibility link rather than
    # taking the already-correct-link fast path.
    (tmp_path / "Output" / "current").unlink()

    import system_runtime.publish_transaction as publish_module

    original_replace = publish_module.os.replace

    def fail_compatibility_link(source, destination):
        if Path(source).name.startswith(".current.next."):
            raise OSError("injected compatibility-link failure")
        return original_replace(source, destination)

    monkeypatch.setattr(publish_module.os, "replace", fail_compatibility_link)
    try:
        with pytest.raises(OSError, match="injected compatibility-link failure"):
            second.commit_generation(tmp_path)
        assert second.state == TransactionState.RECOVERY_REQUIRED
        assert (tmp_path / "Output" / "live").resolve() == active
    finally:
        second.deactivate()


def test_real_compatibility_directory_requires_explicit_migration(tmp_path: Path) -> None:
    current = tmp_path / "Output" / "current"
    current.mkdir(parents=True)
    tx = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    try:
        assert _admit(tx)
        with pytest.raises(CompatibilityMigrationRequired):
            tx.commit_generation(tmp_path)
        assert current.is_dir() and not current.is_symlink()
        assert tx.generation_dir.exists()
    finally:
        tx.deactivate()


def test_generation_mode_without_candidate_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "1")
    monkeypatch.delenv("SYSTEM_GENERATION_DIR", raising=False)
    with pytest.raises(RuntimeError, match="SYSTEM_GENERATION_DIR"):
        surface_dir("current")
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "0")


def test_lineage_tamper_blocks_before_pointer_switch(tmp_path: Path) -> None:
    tx = PublishTransaction("run_tampered", tmp_path / "Output" / "runs" / "run_tampered")
    tx.prepare()
    tx.activate()
    candidate = tx.candidate_dirs["current"] / "framework_output.json"
    candidate.write_text("original\n", encoding="utf-8")
    tx.write_lineage()
    candidate.write_text("tampered\n", encoding="utf-8")
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=tx.run_id,
        **_contract_digests(tx),
    )
    try:
        assert tx.admit(token) is False
        admission = json.loads((tx.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert "LINEAGE_CHECKSUM_MISMATCH" in admission["reason_codes"]
        assert not (tmp_path / "Output" / "live").exists()
    finally:
        tx.deactivate()


@pytest.mark.parametrize("token_generation_id", [None, "different-run"])
def test_admission_token_must_match_transaction_generation(
    tmp_path: Path, token_generation_id: str | None
) -> None:
    tx = PublishTransaction("run_token", tmp_path / "Output" / "runs" / "run_token")
    tx.prepare()
    tx.activate()
    (tx.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    tx.write_lineage()
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=token_generation_id,
        **_contract_digests(tx),
    )
    try:
        assert tx.admit(token) is False
        admission = json.loads((tx.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert admission["integrity_verdict"] == "BLOCK"
        assert "GENERATION_ID_MISMATCH" in admission["reason_codes"]
        assert not (tmp_path / "Output" / "live").exists()
    finally:
        tx.deactivate()


def test_admission_token_must_match_generation_lineage_digest(tmp_path: Path) -> None:
    tx = PublishTransaction("run_generation_digest", tmp_path / "Output" / "runs" / "run_generation_digest")
    tx.prepare()
    tx.activate()
    (tx.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    tx.write_lineage()
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=tx.run_id,
        plan_digest=hashlib.sha256(b"compiled-plan").hexdigest(),
        evidence_digest=hashlib.sha256(b"evidence").hexdigest(),
        generation_digest=hashlib.sha256(b"wrong-lineage").hexdigest(),
    )
    try:
        assert tx.admit(token) is False
        admission = json.loads((tx.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert admission["integrity_verdict"] == "BLOCK"
        assert "GENERATION_DIGEST_MISMATCH" in admission["reason_codes"]
    finally:
        tx.deactivate()


def test_admission_token_must_match_bound_plan_and_evidence_digests(tmp_path: Path) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    tx = PublishTransaction("run_digest_mismatch", tmp_path / "Output" / "runs" / "run_digest_mismatch")
    tx.prepare()
    tx.activate()
    (tx.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    tx.write_lineage()
    expected = _contract_digests(tx)
    tx.bind_contract_digests(
        plan_digest=expected["plan_digest"],
        evidence_digest=expected["evidence_digest"],
    )
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=tx.run_id,
        plan_digest=hashlib.sha256(b"wrong-plan").hexdigest(),
        evidence_digest=hashlib.sha256(b"wrong-evidence").hexdigest(),
        generation_digest=expected["generation_digest"],
    )
    try:
        assert tx.admit(token) is False
        admission = json.loads((tx.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert {"PLAN_DIGEST_MISMATCH", "EVIDENCE_DIGEST_MISMATCH"} <= set(
            admission["reason_codes"]
        )
        assert (tmp_path / "Output" / "live").resolve() == active
    finally:
        tx.deactivate()


def test_candidate_old_run_identity_blocks_before_pointer_switch(tmp_path: Path) -> None:
    first = PublishTransaction("run_a", tmp_path / "Output" / "runs" / "run_a")
    assert _admit(first)
    active = first.commit_generation(tmp_path)
    first.deactivate()

    tx = PublishTransaction("run_new", tmp_path / "Output" / "runs" / "run_new")
    tx.prepare()
    tx.activate()
    candidate = tx.candidate_dirs["current"] / "framework_output.json"
    candidate.write_text(json.dumps({"run_id": "run_old"}) + "\n", encoding="utf-8")
    tx.write_lineage()
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        artifact_run_ids={"current/framework_output.json.run_id": "run_old"},
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=tx.run_id,
        **_contract_digests(tx),
    )
    try:
        assert tx.admit(token) is False
        admission = json.loads((tx.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert "LINEAGE_MISMATCH" in admission["reason_codes"]
        assert (tmp_path / "Output" / "live").resolve() == active
    finally:
        tx.deactivate()


def test_daily_candidate_identity_scan_reads_nested_provenance(tmp_path: Path) -> None:
    from scripts.daily_run import _candidate_identity_contracts

    candidate = tmp_path / "candidate" / "current"
    candidate.mkdir(parents=True)
    (candidate / "framework_output.json").write_text(
        json.dumps(
            {
                "run_id": "run_new",
                "provenance": {
                    "run_id": "run_new",
                    "source_release_id": "release-1",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    run_ids, release_ids = _candidate_identity_contracts(tmp_path / "candidate")
    assert run_ids["current/framework_output.json.run_id"] == "run_new"
    assert run_ids["current/framework_output.json.provenance.run_id"] == "run_new"
    assert release_ids["current/framework_output.json.provenance.source_release_id"] == "release-1"


def test_lineage_rejects_unlisted_artifact_and_wrong_run_id(tmp_path: Path) -> None:
    tx = PublishTransaction("run_unlisted", tmp_path / "Output" / "runs" / "run_unlisted")
    tx.prepare()
    tx.activate()
    candidate = tx.candidate_dirs["current"] / "framework_output.json"
    candidate.write_text("original\n", encoding="utf-8")
    tx.write_lineage()
    (tx.candidate_dirs["current"] / "unlisted.txt").write_text("late\n", encoding="utf-8")
    lineage = json.loads((tx.generation_dir / "lineage.json").read_text(encoding="utf-8"))
    lineage["run_id"] = "previous-run"
    (tx.generation_dir / "lineage.json").write_text(
        json.dumps(lineage, indent=2) + "\n", encoding="utf-8"
    )
    token = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=tx.run_id,
        **_contract_digests(tx),
    )
    try:
        assert tx.admit(token) is False
        admission = json.loads((tx.generation_dir / "admission.json").read_text(encoding="utf-8"))
        assert admission["integrity_verdict"] == "BLOCK"
        assert any("run_id mismatch" in item for item in admission["lineage_violations"])
        assert any("unlisted artifact" in item for item in admission["lineage_violations"])
        assert not (tmp_path / "Output" / "live").exists()
    finally:
        tx.deactivate()


def test_reconcile_detects_generation_without_live_pointer(tmp_path: Path) -> None:
    generations = tmp_path / "Output" / "generations"
    generations.mkdir(parents=True)
    (generations / "orphan_generation").mkdir()
    state = PublishTransaction.reconcile(tmp_path)
    assert state["status"] == "recovery_required"
    assert reconcile_generation_main(["--root", str(tmp_path), "--fail-on-recovery"]) == 1
