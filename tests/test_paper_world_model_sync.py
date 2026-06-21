"""Paper world model sync — schema validation and manifest tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import sync_paper_world_model as spwm

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def _write_case(paper_dir: Path, name: str = "sample-case") -> Path:
    path = paper_dir / "01_Cases" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
type: case
case_type: structural
status: candidate
main_entity: Test Entity
review_status: approved
mechanisms:
  - sample-mechanism
tags:
  - test
---

# Sample Case
""",
        encoding="utf-8",
    )
    return path


def _write_mechanism(paper_dir: Path, name: str = "sample-mechanism") -> Path:
    path = paper_dir / "03_Mechanisms" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
type: mechanism
name: Sample Mechanism
confidence: medium
review_status: needs_review
observable_signals:
  - signal_a
---

# Sample Mechanism
""",
        encoding="utf-8",
    )
    return path


def test_paper_world_model_schema_exists() -> None:
    schema_path = ROOT / "protocols" / "paper_world_model.schema.json"
    assert schema_path.exists()


def test_paper_world_model_schema_is_valid_json() -> None:
    schema_path = ROOT / "protocols" / "paper_world_model.schema.json"
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert data["properties"]["schema_version"]["const"] == "paper_world_model.v1"


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_sync_writes_manifest_and_validates(tmp_path: Path) -> None:
    paper_dir = tmp_path / "Paper"
    output_dir = tmp_path / "out" / "paper_world_model"
    report_dir = tmp_path / "out" / "report"

    _write_case(paper_dir)
    _write_mechanism(paper_dir)

    result = spwm.run_sync(
        paper_dir=paper_dir,
        output_dir=output_dir,
        report_dir=report_dir,
        quiet_on_success=True,
    )

    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "paper_world_model.v1"
    assert manifest["record_counts"]["cases"] == 1
    assert manifest["record_counts"]["mechanisms"] == 1
    assert "paper_mtime_hash" in manifest
    assert result["cases"] == 1


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_validate_records_reports_invalid_review_status() -> None:
    errors = spwm.validate_records(
        {
            "cases": [
                {
                    "case_id": "bad",
                    "source_file": "01_Cases/bad.md",
                    "review_status": "not_a_real_status",
                }
            ]
        }
    )
    assert errors
    assert errors[0]["record_id"] == "bad"


def test_paper_root_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom-paper"
    custom.mkdir()
    monkeypatch.setenv("PAPER_ROOT", str(custom))
    from importlib import reload

    import caselab_context.paper_paths as paper_paths

    reload(paper_paths)
    assert paper_paths.paper_root() == custom.resolve()


def test_data_authority_registry_lists_paper_world_model() -> None:
    text = (ROOT / "governance" / "authority_registry.yaml").read_text(encoding="utf-8")
    assert "Data/paper_world_model/" in text
    assert "world_model_sync" in text
