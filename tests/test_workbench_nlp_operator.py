"""Operator-bound Workbench NLP ask/grounding checks (needs refreshed Output)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.nlp import answer_question


def test_answer_question_is_grounded_and_schema_valid() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True, cwd=str(ROOT))
    payload = answer_question("why is current risk WATCH?", top_k=3)

    schema = json.loads((ROOT / "protocols" / "nlp_answer.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors
    assert payload["schema_version"] == "workbench.nlp_answer.v1"
    assert payload["citations"]
    assert any("No external provider acquisition" in item for item in payload["limits"])
    assert payload["evidence_boundary"] == "retrieval_citation_only"
    assert all(item["evidence_kind"] == "RETRIEVAL_CITATION" for item in payload["citations"])
    assert all(item["canonical_evidence"] is False for item in payload["citations"])
    assert all(item["promotion_allowed"] is False for item in payload["citations"])


def test_sys_ask_writes_last_answer() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True, cwd=str(ROOT))
    result = subprocess.run(
        [str(ROOT / "sys"), "ask", "what evidence supports the current check?"],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    assert "Citations:" in result.stdout
    answer_path = ROOT / "Output" / "workbench" / "nlp" / "last_answer.json"
    payload = json.loads(answer_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "workbench.nlp_answer.v1"
    assert payload["citations"]
