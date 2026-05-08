from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.nlp import answer_question


def test_nlp_protocol_schemas_exist() -> None:
    for name in ["nlp_query.schema.json", "nlp_answer.schema.json"]:
        schema = json.loads((ROOT / "protocols" / name).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_answer_question_is_grounded_and_schema_valid() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True)
    payload = answer_question("why is current risk WATCH?", top_k=3)

    schema = json.loads((ROOT / "protocols" / "nlp_answer.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors
    assert payload["schema_version"] == "workbench.nlp_answer.v1"
    assert payload["citations"]
    assert any("No external provider acquisition" in item for item in payload["limits"])


def test_sys_ask_writes_last_answer() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True)
    result = subprocess.run(
        [str(ROOT / "sys"), "ask", "what evidence supports the current check?"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Citations:" in result.stdout
    answer_path = ROOT / "Output" / "workbench" / "nlp" / "last_answer.json"
    payload = json.loads(answer_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "workbench.nlp_answer.v1"
    assert payload["citations"]


def test_workbench_nlp_does_not_import_framework_or_harvester() -> None:
    text = (ROOT / "Workbench" / "src" / "workbench" / "nlp.py").read_text(encoding="utf-8")
    assert "from src." not in text
    assert "import src." not in text
    assert "import harvester" not in text
