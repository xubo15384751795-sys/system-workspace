from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orchestration.run_parity import compare_daily_run_bundles


_IDS = {
    "observation_id": "obs_00000000000000000000000000000001",
    "measurement_id": "mea_00000000000000000000000000000001",
    "evidence_id": "evd_00000000000000000000000000000001",
    "claim_id": "clm_00000000000000000000000000000001",
}


def _write_run(root: Path, name: str, *, value: float = 1.0, run_id: str) -> Path:
    run = root / name
    generation = run / "publish_candidate"
    current = generation / "current"
    current.mkdir(parents=True)
    output = {"value": value, "generated_at": "different", "run_id": run_id}
    output_path = current / "framework_output.json"
    output_path.write_text(json.dumps(output) + "\n", encoding="utf-8")
    output_sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    (generation / "lineage.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "files": [{"path": "current/framework_output.json", "sha256": output_sha}],
            }
        ),
        encoding="utf-8",
    )
    (generation / "admission.json").write_text(
        json.dumps(
            {
                "authority_verdict": "ALLOW",
                "release_id": "release-2026-08-25",
                "plan_digest": "plan-1",
                "vintage_date": "2026-08-25",
            }
        ),
        encoding="utf-8",
    )
    (generation / "manifest.json").write_text(
        json.dumps(
            {
                "status": "accepted",
                "release_id": "release-2026-08-25",
                "plan_digest": "plan-1",
                "vintage_date": "2026-08-25",
            }
        ),
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "success",
                "release_id": "release-2026-08-25",
                "authority_mode": "authoritative",
                "contract_digests": {"plan_digest": "plan-1"},
            }
        ),
        encoding="utf-8",
    )
    (run / "run_outcome.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "release_id": "release-2026-08-25",
                "execution_status": "SUCCESS",
                "admission_verdict": "PASS",
                "publish_status": "COMMITTED",
                "authority_mode": "authoritative",
            }
        ),
        encoding="utf-8",
    )
    (run / "input_snapshot.json").write_text(
        json.dumps(
            {
                "panel": {
                    "sha256": "input-1",
                    "size_bytes": 1,
                    "mtime": "different-between-tracks",
                }
            }
        ),
        encoding="utf-8",
    )
    step = {
        "step": "judgment_layer",
        "status": "success",
        "returncode": 0,
        "canonical_ids": _IDS,
        "timestamp": "different",
        "run_id": run_id,
    }
    (run / "steps.jsonl").write_text(json.dumps(step) + "\n", encoding="utf-8")
    return run


def test_isolated_run_pair_requires_all_authority_surfaces_and_matches(tmp_path: Path) -> None:
    legacy = _write_run(tmp_path, "legacy", run_id="legacy-1")
    native = _write_run(tmp_path, "native", run_id="native-1")

    report = compare_daily_run_bundles(legacy, native)

    assert report["status"] == "MATCH"
    assert report["promotion_allowed"] is False
    assert report["dimensions"] == {
        "inputs": "MATCH",
        "identity": "MATCH",
        "steps": "MATCH",
        "canonical_lineage": "MATCH",
        "publication": "MATCH",
        "generation_surfaces": "MATCH",
    }


def test_isolated_run_pair_surfaces_step_failure_as_mismatch(tmp_path: Path) -> None:
    legacy = _write_run(tmp_path, "legacy", run_id="legacy-1")
    native = _write_run(tmp_path, "native", run_id="native-1")
    (native / "steps.jsonl").write_text(
        json.dumps(
            {
                "step": "judgment_layer",
                "status": "blocked_upstream",
                "blocked_by": ["harvester"],
                "canonical_ids": _IDS,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = compare_daily_run_bundles(legacy, native)

    assert report["status"] == "MISMATCH"
    assert report["dimensions"]["steps"] == "MISMATCH"


def test_isolated_run_pair_missing_lineage_is_incomplete(tmp_path: Path) -> None:
    legacy = _write_run(tmp_path, "legacy", run_id="legacy-1")
    native = _write_run(tmp_path, "native", run_id="native-1")
    (native / "publish_candidate" / "lineage.json").unlink()

    report = compare_daily_run_bundles(legacy, native)

    assert report["status"] == "INCOMPLETE"
    assert report["required_evidence_errors"]["native"]["lineage_error"] == "missing"
