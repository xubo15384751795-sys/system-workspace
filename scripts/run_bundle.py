"""Run Bundle — atomic, self-contained record of every pipeline execution.

Each run produces an independent directory: Output/runs/{run_id}/
containing:
  manifest.json      — top-level descriptor (run_id, mode, timing, status)
  input_snapshot.json — fingerprints of all input artifacts at run start
  steps.jsonl         — one JSON line per completed step
  decision_trace.json — judgment/trade decisions captured during the run
  signal_trace.json   — framework/sigma signals captured during the run
  artifact_index.json — paths and hashes of all artifacts produced

Output/current/ is updated via symlink (latest_run -> most recent bundle)
so downstream consumers always find the freshest output.

Usage as library:
    from run_bundle import RunBundle
    bundle = RunBundle.start(mode="daily_pipeline")
    # ... run steps ...
    bundle.record_step("harvester", status="success", duration_s=12.3)
    # ... capture traces ...
    bundle.capture_decision_trace(judgment_data)
    bundle.capture_signal_trace(framework_data)
    bundle.finish(status="success")

Usage as CLI (for testing):
    python3 scripts/run_bundle.py --mode test --dry-run
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from _runtime_io import ROOT, ensure_dir
RUNS_DIR = ROOT / "Output" / "runs"
LATEST_POINTER = ROOT / "Output" / "current" / "latest_run_id.txt"

# Artifacts to fingerprint at input snapshot time
INPUT_ARTIFACTS = [
    "Output/current/framework_output.json",
    "Output/current/status.json",
    "Output/current/quality_validation.json",
    "Output/current/signal_card.json",
    "Output/current/work_brief.json",
    "Output/judgment/latest.json",
    "Output/trade_decision/latest.json",
    "Output/trade_decisions/latest.json",
]


def _generate_run_id(mode: str) -> str:
    """Generate a unique run_id: {mode}_{YYYYMMDD}_{HHMMSS}_{short_hash}."""
    now = datetime.now(UTC)
    ts = now.strftime("%Y%m%d_%H%M%S")
    # Short random-ish suffix to avoid collision on same-second reruns
    entropy = os.urandom(3).hex()
    return f"{mode}_{ts}_{entropy}"


def _safe_relative(path: Path, base: Path) -> str:
    """Compute relative path, falling back to absolute if not a subpath."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _fingerprint(path: Path, base: Path | None = None) -> dict[str, Any] | None:
    """Return size + sha256 of a file, or None if missing."""
    if not path.exists():
        return None
    data = path.read_bytes()
    ref = base if base is not None else ROOT
    return {
        "path": _safe_relative(path, ref),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest()[:16],
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
    }


class RunBundle:
    """Atomic run record — one instance per pipeline execution."""

    def __init__(self, run_id: str, mode: str, run_dir: Path, root: Path, tag: str | None = None) -> None:
        self.run_id = run_id
        self.mode = mode
        self.tag = tag
        self.run_dir = run_dir
        self._root = root
        self.started_at = datetime.now(UTC)
        self._steps: list[dict[str, Any]] = []
        self._decision_traces: list[dict[str, Any]] = []
        self._signal_traces: list[dict[str, Any]] = []
        self._feedback_items: list[dict[str, Any]] = []
        self._step_file: Path | None = None

    # ── lifecycle ──────────────────────────────────────────────

    @classmethod
    def start(cls, mode: str = "unknown", root: Path | None = None, tag: str | None = None) -> RunBundle:
        """Create a new run bundle, write input snapshot, return handle."""
        resolved_root = root or ROOT
        base = root / "Output" / "runs" if root else RUNS_DIR
        run_id = _generate_run_id(mode)
        run_dir = base / run_id
        ensure_dir(run_dir)

        bundle = cls(run_id, mode, run_dir, root=resolved_root, tag=tag)
        bundle._step_file = run_dir / "steps.jsonl"
        bundle._write_input_snapshot()
        bundle._write_manifest()  # initial manifest
        bundle._update_latest_pointer(root)
        return bundle

    def record_step(
        self,
        name: str,
        status: str = "success",
        duration_s: float = 0,
        returncode: int = 0,
        detail: str = "",
        input_artifacts: list[str | Path] | None = None,
    ) -> None:
        """Record one pipeline step result.

        Args:
            name: Step identifier.
            status: "success", "failed", "timeout", "error".
            duration_s: Wall-clock seconds.
            returncode: Process exit code.
            detail: Optional human-readable note.
            input_artifacts: Optional list of paths this step consumed.
                Each is fingerprinted (sha256) and recorded for per-step
                input provenance — enabling "what did this step see?" queries.
        """
        entry = {
            "step": name,
            "status": status,
            "duration_s": round(duration_s, 2),
            "returncode": returncode,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if detail:
            entry["detail"] = detail[:500]

        # Per-step input fingerprinting
        if input_artifacts:
            hashes: dict[str, str] = {}
            for art in input_artifacts:
                p = Path(art)
                if p.exists():
                    try:
                        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                        hashes[_safe_relative(p, self._root)] = h
                    except OSError:
                        pass
            if hashes:
                entry["input_hashes"] = hashes

        self._steps.append(entry)

        # Append to steps.jsonl for incremental visibility
        if self._step_file:
            with self._step_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def capture_decision_trace(self, data: dict[str, Any]) -> None:
        """Capture a judgment/trade decision snapshot."""
        self._decision_traces.append({
            "captured_at": datetime.now(UTC).isoformat(),
            "data": _scrub_large_values(data),
        })

    def capture_signal_trace(self, data: dict[str, Any]) -> None:
        """Capture a framework/sigma signal snapshot."""
        self._signal_traces.append({
            "captured_at": datetime.now(UTC).isoformat(),
            "data": _scrub_large_values(data),
        })

    def add_feedback_pending(
        self,
        item: str,
        *,
        source: str = "",
        validation_type: str = "manual_review",
        priority: str = "medium",
        metadata: dict | None = None,
    ) -> None:
        """Record an item that needs future validation or feedback.

        Used to track: HMM signal quality, regime label accuracy,
        prediction calibration, claim ladder progression, etc.

        Args:
            item: Human-readable description
            source: Origin module/script
            validation_type: Category of validation needed
            priority: "high", "medium", "low"
            metadata: Optional structured data (claim_tier, mechanism_hypothesis,
                      watch_conditions, invalidation_conditions, etc.)
        """
        entry = {
            "item": item,
            "source": source,
            "validation_type": validation_type,
            "priority": priority,
            "added_at": datetime.now(UTC).isoformat(),
        }
        if metadata:
            entry["metadata"] = metadata
        self._feedback_items.append(entry)

    def record_artifact(self, path: str | Path) -> None:
        """Record an artifact produced during this run.

        Appends to artifact_index.json incrementally.
        """
        p = Path(path)
        entry = _fingerprint(p, base=self._root)
        if entry is None:
            return

        index_path = self.run_dir / "artifact_index.json"
        existing: list[dict] = []
        if index_path.exists():
            try:
                existing = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Failed to load artifact index from %s, resetting", index_path, exc_info=True)
                existing = []
        existing.append(entry)
        index_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def finish(self, status: str = "success") -> Path:
        """Finalize the bundle — write all summary files, return run_dir."""
        now = datetime.now(UTC)
        elapsed = (now - self.started_at).total_seconds()

        # Write decision trace
        if self._decision_traces:
            (self.run_dir / "decision_trace.json").write_text(
                json.dumps(self._decision_traces, indent=2, default=str, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        # Write signal trace
        if self._signal_traces:
            (self.run_dir / "signal_trace.json").write_text(
                json.dumps(self._signal_traces, indent=2, default=str, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        # Write feedback pending
        if self._feedback_items:
            (self.run_dir / "feedback_pending.json").write_text(
                json.dumps(self._feedback_items, indent=2, default=str, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        # Overwrite manifest with final data
        self._write_manifest(
            finished_at=now.isoformat(),
            duration_s=round(elapsed, 1),
            status=status,
        )

        # Ensure artifact_index.json exists even if empty
        index_path = self.run_dir / "artifact_index.json"
        if not index_path.exists():
            index_path.write_text("[]\n", encoding="utf-8")

        return self.run_dir

    # ── internal ───────────────────────────────────────────────

    def _write_input_snapshot(self) -> None:
        """Fingerprint key input artifacts at run start."""
        root = self._root
        snapshot = {}
        for rel in INPUT_ARTIFACTS:
            fp = _fingerprint(root / rel, base=root)
            if fp is not None:
                snapshot[rel] = fp
            else:
                snapshot[rel] = {"path": rel, "status": "missing"}

        # Also snapshot the harvester latest release
        catalog = root / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
        if catalog.exists():
            snapshot["harvester_latest_catalog"] = _fingerprint(catalog, base=root)

        (self.run_dir / "input_snapshot.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_manifest(
        self,
        finished_at: str | None = None,
        duration_s: float | None = None,
        status: str = "running",
    ) -> None:
        """Write or overwrite manifest.json."""
        manifest = {
            "run_id": self.run_id,
            "mode": self.mode,
            "tag": self.tag,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at,
            "duration_s": duration_s,
            "status": status,
            "steps_count": len(self._steps),
            "steps_succeeded": sum(1 for s in self._steps if s.get("status") == "success"),
            "steps_failed": sum(1 for s in self._steps if s.get("status") not in ("success",)),
            "decision_traces": len(self._decision_traces),
            "signal_traces": len(self._signal_traces),
            "run_dir": _safe_relative(self.run_dir, self._root),
        }
        (self.run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _update_latest_pointer(self, root: Path | None = None) -> None:
        """Update the latest_run_id.txt pointer in Output/current/."""
        pointer = root / "Output" / "current" / "latest_run_id.txt" if root else LATEST_POINTER
        ensure_dir(pointer.parent)
        pointer.write_text(self.run_id + "\n", encoding="utf-8")


def _scrub_large_values(data: dict[str, Any], max_bytes: int = 50_000) -> dict[str, Any]:
    """Trim values that would bloat the trace file."""
    scrubbed = {}
    for k, v in data.items():
        s = json.dumps(v, default=str)
        if len(s) > max_bytes:
            scrubbed[k] = f"[trimmed: {len(s)} bytes]"
        else:
            scrubbed[k] = v
    return scrubbed


def latest_run_dir(root: Path | None = None) -> Path | None:
    """Return the path to the most recent run bundle, or None."""
    pointer = root / "Output" / "current" / "latest_run_id.txt" if root else LATEST_POINTER
    if not pointer.exists():
        return None
    run_id = pointer.read_text(encoding="utf-8").strip()
    base = root / "Output" / "runs" if root else RUNS_DIR
    run_dir = base / run_id
    return run_dir if run_dir.exists() else None


# ── CLI ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run bundle (test mode)")
    parser.add_argument("--mode", default="test", help="Run mode label")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print(f"Would create run bundle with mode={args.mode}")
        print(f"  run_id pattern: {args.mode}_YYYYMMDD_HHMMSS_xxxx")
        print(f"  output: Output/runs/<run_id>/")
    else:
        bundle = RunBundle.start(mode=args.mode)
        print(f"Created run bundle: {bundle.run_id}")
        print(f"  directory: {bundle.run_dir}")
        bundle.record_step("test_step", status="success", duration_s=0.1)
        run_dir = bundle.finish(status="success")
        print(f"  finished: {run_dir}")
        print(f"  manifest: {run_dir / 'manifest.json'}")
