"""Workbench NLP protocol/import contracts (hermetic).

Refresh + grounded ask flows live in test_workbench_nlp_operator.py.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nlp_protocol_schemas_exist() -> None:
    for name in ["nlp_query.schema.json", "nlp_answer.schema.json"]:
        schema = json.loads((ROOT / "protocols" / name).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_workbench_nlp_does_not_import_framework_or_harvester() -> None:
    text = (ROOT / "packages" / "workbench" / "src" / "workbench" / "nlp.py").read_text(
        encoding="utf-8"
    )
    assert "from src." not in text
    assert "import src." not in text
    assert "import harvester" not in text
