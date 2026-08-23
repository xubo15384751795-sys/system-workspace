"""Unified publish transaction (WP2).

Replaces the per-file ``os.replace`` loops in ``_current_publish`` and
``_shadow_publish`` with a single transactional state machine:

::

    PREPARING
    -> PREPARED
    -> ADMITTED
    -> COMMITTING
    -> COMMITTED | ROLLED_BACK | RECOVERY_REQUIRED

Candidate directories are established at run start (before any writer
imports).  On failure, the previous generation is preserved as a
transaction-scoped retired generation, and the failed candidate + journal
are retained for audit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from system_runtime.publish_admission import (
    INTEGRITY_BLOCK,
    PublishAdmission,
)

GENERATION_SURFACES = (
    "current",
    "position",
    "judgment",
    "trade_decision",
    "trade_ledger",
    "quality",
    "system_learning",
)
GENERATION_ENV = "SYSTEM_GENERATION_DIR"
CURRENT_ENV = "CURRENT_OUTPUT_DIR"
SHADOW_ENV = "SHADOW_OUTPUT_DIR"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CompatibilityMigrationRequired(RuntimeError):
    """Raised when old directory surfaces would make a pointer unsafe."""


class TransactionState(str, Enum):
    """States in the publish transaction lifecycle."""

    PREPARING = "PREPARING"
    PREPARED = "PREPARED"
    ADMITTED = "ADMITTED"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


# Class-level state set for introspection / tests
STATES = frozenset(s.value for s in TransactionState)


@dataclass
class PublishTransaction:
    """A single publish transaction for current/decision/shadow candidates.

    Lifecycle:
        1. ``PREPARING``: candidate directories are created at run start.
        2. ``PREPARED``: all candidate artifacts have been written and validated.
        3. ``ADMITTED``: :class:`PublishAdmission` has evaluated to PASS.
        4. ``COMMITTING``: the previous live generation is retired and the
           new generation is being swapped in.
        5. ``COMMITTED``: the new generation is live and the pointer is switched.
        6. ``ROLLED_BACK``: a commit failure occurred; the previous generation
           was restored.
        7. ``RECOVERY_REQUIRED``: rollback itself failed; manual recovery needed.
    """

    run_id: str
    run_dir: Path
    state: TransactionState = TransactionState.PREPARING
    candidate_dirs: dict[str, Path] = field(default_factory=dict)
    retired_dir: Path | None = None
    committed_dir: Path | None = None
    journal: list[dict[str, Any]] = field(default_factory=list)
    generation_digest: str | None = None
    admission_digest: str | None = None
    expected_plan_digest: str | None = None
    expected_evidence_digest: str | None = None

    # Class-level state set for introspection / tests
    STATES = STATES
    VALID_STATES = STATES

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _SAFE_RUN_ID.fullmatch(self.run_id):
            raise ValueError(
                "run_id must be a single safe path component containing only "
                "letters, digits, '.', '_' or '-'"
            )

    def prepare(self) -> None:
        """Create publish_candidate directories at run start.

        Must be called before any writer imports so that ``CURRENT_OUTPUT_DIR``
        and ``SHADOW_OUTPUT_DIR`` redirect writes to the candidate.
        """
        generation = self.run_dir / "publish_candidate"
        for name in GENERATION_SURFACES:
            d = generation / name
            d.mkdir(parents=True, exist_ok=True)
            self.candidate_dirs[name] = d
        # Materialize both run pointers before lineage is sealed.  The root
        # pointer is transaction metadata; the copy under ``current`` is the
        # compatibility pointer read through Output/current.  Keeping both in
        # the candidate makes the pointer part of the same integrity-checked
        # generation rather than a late, unlisted commit artifact.
        for pointer in (
            generation / "latest_run_id.txt",
            self.candidate_dirs["current"] / "latest_run_id.txt",
        ):
            pointer.write_text(self.run_id + "\n", encoding="utf-8")
        # Compatibility aliases used by the existing daily runner while the
        # surface writers are migrated to named generation paths.
        self.candidate_dirs["diagnostic"] = self.candidate_dirs["current"]
        self.candidate_dirs["shadow"] = self.candidate_dirs["position"]
        self._journal("prepare", "candidate directories created")
        self.state = TransactionState.PREPARED

    @property
    def generation_dir(self) -> Path:
        """Candidate generation root created before writer imports."""
        return self.run_dir / "publish_candidate"

    @property
    def journal_path(self) -> Path:
        """Domain journal path, separate from Dagster's event database."""
        return self.run_dir / "domain_journal.sqlite3"

    def activate(self) -> None:
        """Route all generation-aware writers to this candidate."""
        if self.state not in {TransactionState.PREPARED, TransactionState.ADMITTED}:
            raise RuntimeError(f"cannot activate transaction in state {self.state.value}")
        os.environ[GENERATION_ENV] = str(self.generation_dir)
        os.environ[CURRENT_ENV] = str(self.candidate_dirs["current"])
        os.environ[SHADOW_ENV] = str(self.candidate_dirs["position"])
        self._journal("activate", f"generation={self.generation_dir}")

    def deactivate(self) -> None:
        """Remove only environment values owned by this transaction."""
        owned_generations = {str(self.generation_dir)}
        if self.committed_dir is not None:
            owned_generations.add(str(self.committed_dir))
        if os.environ.get(GENERATION_ENV) in owned_generations:
            os.environ.pop(GENERATION_ENV, None)
        owned_current = {str(self.candidate_dirs.get("current", ""))}
        if self.committed_dir is not None:
            owned_current.add(str(self.committed_dir / "current"))
        if os.environ.get(CURRENT_ENV) in owned_current:
            os.environ.pop(CURRENT_ENV, None)
        owned_shadow = {str(self.candidate_dirs.get("position", ""))}
        if self.committed_dir is not None:
            owned_shadow.add(str(self.committed_dir / "position"))
        if os.environ.get(SHADOW_ENV) in owned_shadow:
            os.environ.pop(SHADOW_ENV, None)
        self._journal("deactivate", "generation environment cleared")

    def write_lineage(self) -> Path:
        """Write a same-run checksum inventory before admission."""
        files: list[dict[str, Any]] = []
        for path in sorted(self.generation_dir.rglob("*")):
            if not path.is_file() or path.name in {"lineage.json", "admission.json"}:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({
                "path": str(path.relative_to(self.generation_dir)),
                "sha256": digest,
                "run_id": self.run_id,
            })
        payload = {"schema_version": "system.generation_lineage.v1", "run_id": self.run_id, "files": files}
        target = self.generation_dir / "lineage.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.generation_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        self._journal("lineage", f"files={len(files)}")
        return target

    def bind_contract_digests(
        self,
        *,
        plan_digest: str,
        evidence_digest: str,
    ) -> None:
        """Bind the transaction to the plan/evidence identity it evaluated.

        The admission token is untrusted input until it agrees with the
        digests calculated by the current run.  Keeping these expectations on
        the transaction prevents a caller from constructing a valid-looking
        token for a different plan or evidence set.
        """
        self.expected_plan_digest = plan_digest
        self.expected_evidence_digest = evidence_digest

    def admit(self, admission: PublishAdmission) -> bool:
        """Evaluate admission and transition to ADMITTED or stay PREPARED.

        Returns True if admitted (integrity PASS), False otherwise.
        On BLOCK, the live current/position/NAV/ledger surfaces are NOT
        modified - the previous generation is preserved.
        """
        lineage_violations = self._verify_lineage()
        token_violations: list[str] = []
        if admission.generation_id is None:
            token_violations.append("admission: generation_id missing")
        elif admission.generation_id != self.run_id:
            token_violations.append(
                f"admission: generation_id mismatch ({admission.generation_id!r} != {self.run_id!r})"
            )
        lineage_path = self.generation_dir / "lineage.json"
        actual_generation_digest = (
            hashlib.sha256(lineage_path.read_bytes()).hexdigest()
            if lineage_path.exists()
            else None
        )
        if admission.generation_digest is None:
            token_violations.append("admission: generation_digest missing")
        elif actual_generation_digest != admission.generation_digest:
            token_violations.append(
                "admission: generation_digest mismatch "
                f"({admission.generation_digest!r} != {actual_generation_digest!r})"
            )
        if (
            self.expected_plan_digest is not None
            and admission.plan_digest != self.expected_plan_digest
        ):
            token_violations.append(
                "admission: plan_digest mismatch "
                f"({admission.plan_digest!r} != {self.expected_plan_digest!r})"
            )
        if (
            self.expected_evidence_digest is not None
            and admission.evidence_digest != self.expected_evidence_digest
        ):
            token_violations.append(
                "admission: evidence_digest mismatch "
                f"({admission.evidence_digest!r} != {self.expected_evidence_digest!r})"
            )
        all_violations = [*token_violations, *lineage_violations]
        if all_violations:
            reason_codes = list(admission.reason_codes)
            if token_violations:
                reason_codes.append("GENERATION_ID_MISMATCH")
            if any("generation_digest" in violation for violation in token_violations):
                reason_codes.append("GENERATION_DIGEST_MISMATCH")
            if any("plan_digest" in violation for violation in token_violations):
                reason_codes.append("PLAN_DIGEST_MISMATCH")
            if any("evidence_digest" in violation for violation in token_violations):
                reason_codes.append("EVIDENCE_DIGEST_MISMATCH")
            if any("sha256 mismatch" in violation for violation in lineage_violations):
                reason_codes.append("LINEAGE_CHECKSUM_MISMATCH")
            if lineage_violations and not any(
                code == "LINEAGE_CHECKSUM_MISMATCH" for code in reason_codes
            ):
                reason_codes.append("LINEAGE_INTEGRITY_VIOLATION")
            admission = PublishAdmission(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=admission.authority_verdict,
                reason_codes=reason_codes,
                required_artifacts_missing=list(admission.required_artifacts_missing),
                lineage_violations=all_violations,
                freshness_verdict=admission.freshness_verdict,
                diagnostic_verdict=admission.diagnostic_verdict,
                generation_id=admission.generation_id,
                release_id=admission.release_id,
                artifact_release_ids=dict(admission.artifact_release_ids),
                provider_decision=admission.provider_decision,
                plan_digest=admission.plan_digest,
                evidence_digest=admission.evidence_digest,
                generation_digest=admission.generation_digest,
                canonical_lineage=admission.canonical_lineage,
                decision_lineage=admission.decision_lineage,
            )
        payload_without_digest = {
            "schema_version": "system.publish_admission.v1",
            "run_id": self.run_id,
            **admission.to_dict(),
        }
        digest = hashlib.sha256(
            json.dumps(payload_without_digest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.admission_digest = digest
        payload = {**payload_without_digest, "admission_digest": digest}
        (self.generation_dir / "admission.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self._journal(
            "admit",
            f"integrity={admission.integrity_verdict} authority={admission.authority_verdict}",
        )
        if admission.is_blocked:
            self._journal("admit", "BLOCKED - live surface preserved")
            return False
        self.state = TransactionState.ADMITTED
        return True

    def _verify_lineage(self) -> list[str]:
        """Verify every candidate byte against the pre-admission lineage."""
        lineage_path = self.generation_dir / "lineage.json"
        if not lineage_path.exists():
            return ["lineage.json: missing"]
        try:
            payload = json.loads(lineage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"lineage.json: invalid ({exc})"]
        violations: list[str] = []
        if payload.get("run_id") != self.run_id:
            violations.append(f"lineage.json: run_id mismatch ({payload.get('run_id')!r})")
        entries = payload.get("files")
        if not isinstance(entries, list):
            violations.append("lineage.json: files is not a list")
            return violations
        expected_paths: set[str] = set()
        for item in entries:
            if not isinstance(item, dict):
                violations.append("lineage.json: invalid file entry")
                continue
            relative = str(item.get("path", ""))
            if relative in expected_paths:
                violations.append(f"{relative}: duplicate lineage entry")
            expected_paths.add(relative)
            raw_path = self.generation_dir / relative
            path = raw_path.resolve()
            expected = str(item.get("sha256", ""))
            if not relative or self.generation_dir.resolve() not in path.parents:
                violations.append(f"{relative}: path escapes generation")
                continue
            if not raw_path.is_file() or raw_path.is_symlink():
                violations.append(f"{relative}: missing")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                violations.append(f"{relative}: sha256 mismatch")
            if item.get("run_id") != self.run_id:
                violations.append(f"{relative}: run_id mismatch")
        actual_paths = {
            str(path.relative_to(self.generation_dir))
            for path in self.generation_dir.rglob("*")
            if path.is_file() and path.name not in {"lineage.json", "admission.json"}
        }
        for relative in sorted(actual_paths - expected_paths):
            violations.append(f"{relative}: unlisted artifact")
        for relative in sorted(expected_paths - actual_paths):
            if relative and not any(f"{relative}:" in violation for violation in violations):
                violations.append(f"{relative}: missing")
        return violations

    def commit_generation(self, root: Path) -> Path:
        """Commit the candidate by switching one ``Output/live`` pointer.

        Compatibility paths are stable links to ``live/<surface>``.  Existing
        real directories are deliberately rejected until the explicit,
        recoverable migration command has converted them; silently replacing
        those directories would make rollback and lineage ambiguous.
        """
        if self.state != TransactionState.ADMITTED:
            self._journal("commit_generation", f"rejected: state={self.state.value}")
            raise RuntimeError(f"generation commit requires ADMITTED, got {self.state.value}")

        output = root / "Output"
        generations = output / "generations"
        generations.mkdir(parents=True, exist_ok=True)
        compatibility = {
            "live": output / "live",
            "current": output / "current",
            "position": output / "position",
            "judgment": output / "judgment",
            "trade_decision": output / "trade_decision",
            "trade_ledger": output / "trade_ledger",
            "quality": output / "quality",
            "system_learning": output / "system_learning",
            "ledgers": output / "ledgers",
        }
        blocking = [str(path) for path in compatibility.values() if path.exists() and not path.is_symlink()]
        if blocking:
            self._journal("commit_generation", "compatibility migration required")
            raise CompatibilityMigrationRequired(
                "real compatibility directories require explicit migration: " + ", ".join(blocking)
            )
        for name, path in compatibility.items():
            if name == "live" or not path.is_symlink():
                continue
            expected = os.path.join("live", "trade_ledger" if name == "ledgers" else name)
            if os.readlink(path) != expected:
                raise CompatibilityMigrationRequired(
                    f"compatibility link is not stable: {path} -> {os.readlink(path)}"
                )

        target = generations / self.run_id
        if target.exists():
            raise FileExistsError(f"generation already exists: {target}")
        # Keep the pointer in both metadata locations.  The generation root is
        # the authoritative transaction metadata surface, while
        # ``Output/current`` resolves to ``<generation>/current`` and remains
        # the compatibility surface used by monitoring and older consumers.
        # Writing both from the same commit keeps those readers aligned after
        # the live symlink switches.
        (self.generation_dir / "latest_run_id.txt").write_text(
            self.run_id + "\n", encoding="utf-8"
        )
        (self.generation_dir / "current" / "latest_run_id.txt").write_text(
            self.run_id + "\n", encoding="utf-8"
        )
        admission_payload = json.loads((self.generation_dir / "admission.json").read_text(encoding="utf-8"))
        (self.generation_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "system.generation.v1",
                    "run_id": self.run_id,
                    "status": "accepted",
                    "authority": admission_payload.get("authority_verdict"),
                    "release_id": admission_payload.get("release_id"),
                    "artifact_release_ids": admission_payload.get("artifact_release_ids", {}),
                    "plan_digest": admission_payload.get("plan_digest"),
                    "evidence_digest": admission_payload.get("evidence_digest"),
                    "generation_digest": admission_payload.get("generation_digest"),
                    "admission_digest": admission_payload.get("admission_digest"),
                    "surfaces": list(GENERATION_SURFACES),
                    "lineage": "lineage.json",
                    "admission": "admission.json",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        self.state = TransactionState.COMMITTING
        self._journal("commit_generation", "pointer switch started")
        try:
            os.replace(self.generation_dir, target)
        except Exception as exc:
            self.state = TransactionState.RECOVERY_REQUIRED
            self._journal("commit_generation", f"materialization failed: {exc}")
            raise
        self._journal("commit_generation", f"materialized={target}")

        # Prepare all stable compatibility links before switching Output/live.
        # They point at the stable name ``live/<surface>`` and therefore resolve
        # against the old generation until the final live-pointer replace.  A
        # failure while preparing them cannot expose the new generation.
        try:
            for name, path in compatibility.items():
                if name == "live":
                    continue
                expected = os.path.join("live", "trade_ledger" if name == "ledgers" else name)
                if path.is_symlink() and os.readlink(path) == expected:
                    continue
                if path.exists() or path.is_symlink():
                    raise CompatibilityMigrationRequired(
                        f"compatibility link is not stable: {path} -> {os.readlink(path) if path.is_symlink() else 'real path'}"
                    )
                link_tmp = output / f".{name}.next.{os.getpid()}"
                if link_tmp.exists() or link_tmp.is_symlink():
                    link_tmp.unlink()
                target_name = "trade_ledger" if name == "ledgers" else name
                link_tmp.symlink_to(Path("live") / target_name, target_is_directory=True)
                os.replace(link_tmp, path)

            # The only changing authoritative pointer is Output/live.  All
            # compatibility links above already target this stable name.
            live_tmp = output / f".live.next.{os.getpid()}"
            if live_tmp.exists() or live_tmp.is_symlink():
                live_tmp.unlink()
            live_tmp.symlink_to(target, target_is_directory=True)
            os.replace(live_tmp, compatibility["live"])
        except Exception as exc:
            self.state = TransactionState.RECOVERY_REQUIRED
            self._journal("commit_generation", f"pointer switch failed: {exc}")
            raise

        self.committed_dir = target
        self.state = TransactionState.COMMITTED
        self._journal("commit_generation", "COMMITTED")
        os.environ[GENERATION_ENV] = str(target)
        os.environ[CURRENT_ENV] = str(target / "current")
        os.environ[SHADOW_ENV] = str(target / "position")
        return target

    @staticmethod
    def reconcile(root: Path) -> dict[str, Any]:
        """Classify startup state without mutating any surface."""
        output = root / "Output"
        live = output / "live"
        generations = output / "generations"

        def rolled_back_transaction() -> str | None:
            """Return the newest transaction whose final journal state rolled back."""
            runs = output / "runs"
            if not runs.exists():
                return None
            for journal_path in sorted(runs.glob("*/domain_journal.sqlite3"), reverse=True):
                try:
                    with sqlite3.connect(journal_path) as connection:
                        row = connection.execute(
                            "SELECT state FROM domain_transitions ORDER BY seq DESC LIMIT 1"
                        ).fetchone()
                except sqlite3.Error:
                    continue
                if row and row[0] == TransactionState.ROLLED_BACK.value:
                    return journal_path.parent.name
            return None

        def recovery_required_transaction() -> str | None:
            """Return the newest transaction whose journal requires recovery.

            A failed materialization can leave the previous ``Output/live``
            pointer intact while retaining a prepared candidate.  Looking
            only at the active pointer would incorrectly classify that state
            as complete, so the journal remains authoritative for failed
            commit attempts even when the old generation is still readable.
            """
            runs = output / "runs"
            if not runs.exists():
                return None
            for journal_path in sorted(runs.glob("*/domain_journal.sqlite3"), reverse=True):
                try:
                    with sqlite3.connect(journal_path) as connection:
                        row = connection.execute(
                            "SELECT state FROM domain_transitions ORDER BY seq DESC LIMIT 1"
                        ).fetchone()
                except sqlite3.Error:
                    continue
                if row and row[0] == TransactionState.RECOVERY_REQUIRED.value:
                    return journal_path.parent.name
            return None

        def interrupted_generation() -> str | None:
            """Find a materialized generation whose commit never reached COMMITTED."""
            if not generations.exists():
                return None
            runs = output / "runs"
            for candidate in sorted(generations.iterdir()):
                if not candidate.is_dir():
                    continue
                try:
                    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if manifest.get("status") == "legacy_imported":
                    continue
                run_id = str(manifest.get("run_id") or candidate.name)
                journal_path = runs / run_id / "domain_journal.sqlite3"
                if not journal_path.exists():
                    continue
                try:
                    with sqlite3.connect(journal_path) as connection:
                        row = connection.execute(
                            "SELECT state, step FROM domain_transitions ORDER BY seq DESC LIMIT 1"
                        ).fetchone()
                except sqlite3.Error:
                    return str(candidate)
                if row and (row[0] == TransactionState.RECOVERY_REQUIRED.value or row[0] == TransactionState.COMMITTING.value):
                    return str(candidate)
            return None

        interrupted = interrupted_generation()
        rolled_back = rolled_back_transaction()
        recovery_required = recovery_required_transaction()
        if live.is_symlink():
            target = live.resolve()
            if generations.resolve() not in target.parents:
                return {
                    "status": "recovery_required",
                    "active_generation": str(target),
                    "reason": "Output/live points outside Output/generations",
                }
            if interrupted is not None:
                return {
                    "status": "recovery_required",
                    "active_generation": str(target),
                    "interrupted_generation": interrupted,
                }
            if recovery_required is not None:
                return {
                    "status": "recovery_required",
                    "active_generation": str(target),
                    "recovery_required_run": recovery_required,
                }
            if rolled_back is not None:
                return {
                    "status": "rollback",
                    "active_generation": str(target),
                    "rolled_back_run": rolled_back,
                }
            manifest = {}
            manifest_path = target / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    manifest = {}
            links_ok = True
            for name in ("current", "position", "judgment", "trade_decision", "trade_ledger", "quality", "system_learning", "ledgers"):
                link = output / name
                expected = os.path.join("live", "trade_ledger" if name == "ledgers" else name)
                if not link.is_symlink() or os.readlink(link) != expected:
                    links_ok = False
                    break
            if manifest.get("status") == "legacy_imported" and links_ok:
                status = "complete_legacy_baseline"
            else:
                status = (
                    "complete"
                    if target.is_dir() and (target / "admission.json").exists() and links_ok
                    else "recovery_required"
                )
            return {
                "status": status,
                "active_generation": str(target),
            }
        if rolled_back is not None:
            return {
                "status": "rollback",
                "active_generation": None,
                "rolled_back_run": rolled_back,
            }
        if recovery_required is not None:
            return {
                "status": "recovery_required",
                "active_generation": None,
                "recovery_required_run": recovery_required,
            }
        candidates = sorted((output / "runs").glob("*/publish_candidate")) if (output / "runs").exists() else []
        status = "recovery_required" if candidates or generations.exists() else "no_active_generation"
        return {
            "status": status,
            "active_generation": None,
            "candidates": [str(path) for path in candidates],
            "generation_count": len(list(generations.iterdir())) if generations.exists() else 0,
        }

    def commit(self, target_dir: Path, candidate_dir: Path) -> bool:
        """Atomically swap candidate into target, retiring the old generation.

        Returns True on success, False on failure (rollback attempted).
        """
        if self.state != TransactionState.ADMITTED:
            self._journal("commit", f"rejected: state={self.state.value} (expected ADMITTED)")
            return False

        self.state = TransactionState.COMMITTING
        self._journal("commit", f"retiring {target_dir}")

        try:
            # Retire the previous generation (transaction-scoped).
            pid = os.getpid()
            retired = target_dir.parent / f".{target_dir.name}_retired.{pid}"
            if target_dir.exists():
                os.replace(target_dir, retired)
                self.retired_dir = retired

            # Swap the candidate into place.
            os.replace(candidate_dir, target_dir)
            self._journal("commit", f"swapped {candidate_dir} -> {target_dir}")

            # Clean up the retired generation.
            if self.retired_dir and self.retired_dir.exists():
                shutil.rmtree(self.retired_dir, ignore_errors=True)
                self._journal("commit", "retired generation cleaned up")

            self.state = TransactionState.COMMITTED
            self._journal("commit", "COMMITTED")
            return True

        except Exception as exc:
            self._journal("commit", f"failed: {exc}")
            # Attempt rollback: restore the retired generation.
            if self.retired_dir and self.retired_dir.exists():
                try:
                    if target_dir.exists():
                        shutil.rmtree(target_dir, ignore_errors=True)
                    os.replace(self.retired_dir, target_dir)
                    self.state = TransactionState.ROLLED_BACK
                    self._journal("rollback", "restored previous generation")
                except Exception as rollback_exc:
                    self.state = TransactionState.RECOVERY_REQUIRED
                    self._journal("rollback", f"failed: {rollback_exc}")
            else:
                self.state = TransactionState.RECOVERY_REQUIRED
            return False

    def _journal(self, step: str, message: str) -> None:
        """Append to the transaction journal for audit."""
        recorded_at = datetime.now(UTC).isoformat()
        entry = {
            "step": step,
            "message": message,
            "state": self.state.value,
            "run_id": self.run_id,
            "recorded_at": recorded_at,
        }
        self.journal.append(entry)
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.journal_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS domain_transitions (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        step TEXT NOT NULL,
                        state TEXT NOT NULL,
                        message TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO domain_transitions(recorded_at, run_id, step, state, message) VALUES (?, ?, ?, ?, ?)",
                    (recorded_at, self.run_id, step, self.state.value, message),
                )
        except sqlite3.Error as exc:
            # Keep the in-memory journal for diagnostics, but mark the
            # transaction explicitly so a caller cannot mistake this for a
            # fully journaled commit.
            self.journal.append({
                "step": "journal_error",
                "message": str(exc),
                "state": self.state.value,
                "run_id": self.run_id,
                "recorded_at": recorded_at,
            })

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON / RunBundle consumers."""
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "candidate_dirs": {k: str(v) for k, v in self.candidate_dirs.items()},
            "retired_dir": str(self.retired_dir) if self.retired_dir else None,
            "committed_dir": str(self.committed_dir) if self.committed_dir else None,
            "journal": list(self.journal),
        }
