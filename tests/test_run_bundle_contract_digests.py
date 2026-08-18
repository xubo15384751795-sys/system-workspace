"""RunBundle evidence and contract-digest boundary tests."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_bundle import RunBundle


def test_evidence_digest_changes_when_generation_bytes_change(tmp_path: Path) -> None:
    bundle = RunBundle.start(mode="digest_test", root=tmp_path, update_pointer=False)
    generation = tmp_path / "Output" / "candidate"
    generation.mkdir(parents=True)
    artifact = generation / "provider_panel.json"
    artifact.write_text('{"value": 1}\n', encoding="utf-8")
    bundle.record_step("provider", status="success", returncode=0)
    bundle.record_artifact(artifact)

    first = bundle.evidence_digest(generation)
    artifact.write_text('{"value": 2}\n', encoding="utf-8")
    second = bundle.evidence_digest(generation)
    assert first != second


def test_contract_digests_are_written_to_manifest_and_artifact_index(tmp_path: Path) -> None:
    bundle = RunBundle.start(mode="digest_test", root=tmp_path, update_pointer=False)
    artifact = tmp_path / "Output" / "candidate.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("candidate\n", encoding="utf-8")
    bundle.record_artifact(artifact)
    digests = {
        "plan_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "generation_digest": "c" * 64,
        "admission_digest": "d" * 64,
    }
    bundle.set_contract_digests(**digests)

    manifest = json.loads((bundle.run_dir / "manifest.json").read_text(encoding="utf-8"))
    index = json.loads((bundle.run_dir / "artifact_index.json").read_text(encoding="utf-8"))
    assert manifest["contract_digests"] == digests
    assert index[0]["contract_digests"] == digests
