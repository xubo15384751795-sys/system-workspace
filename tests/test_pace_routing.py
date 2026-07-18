from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "commands" / "ci" / "check_pace_routing.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_pace_routing", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pace(root: Path) -> None:
    root.joinpath("PACE.md").write_text(
        "---\nschema_version: test\nlayers:\n"
        "  L4:\n    paths: [PACE.md]\n"
        "  L3:\n    prefixes: [protocols/, governance/]\n"
        "  L2:\n    prefixes: [packages/]\n"
        "  L1:\n    prefixes: [Output/sandbox/]\n"
        "---\n# test\n",
        encoding="utf-8",
    )


def test_l1_l2_change_needs_no_routing_decision(tmp_path: Path) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    assert module.check_paths(["packages/x.py", "Output/sandbox/a.json"], tmp_path) == []


def test_l3_change_without_decision_is_rejected(tmp_path: Path) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    errors = module.check_paths(["protocols/event.schema.json"], tmp_path)
    assert errors and "PACE violation" in errors[0]


def test_complex_decision_requires_complete_probe(tmp_path: Path) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    decision = tmp_path / "governance" / "routing_decisions" / "probe.yaml"
    decision.parent.mkdir(parents=True)
    decision.write_text(
        yaml.safe_dump({"cynefin_domain": "complex", "probe": {"scope": "small"}}),
        encoding="utf-8",
    )
    errors = module.check_paths(
        ["protocols/event.schema.json", "governance/routing_decisions/probe.yaml"],
        tmp_path,
    )
    assert errors and "observation_window" in errors[0]


def test_complete_complex_probe_allows_l4_change(tmp_path: Path) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    decision = tmp_path / "governance" / "routing_decisions" / "probe.yaml"
    decision.parent.mkdir(parents=True)
    decision.write_text(
        yaml.safe_dump({
            "cynefin_domain": "complex",
            "probe": {
                "scope": "small",
                "preregistered_expectation": "deviation falls",
                "observation_window": "30 days",
                "rollback": "remove hook",
            },
        }),
        encoding="utf-8",
    )
    assert module.check_paths(
        ["PACE.md", "governance/routing_decisions/probe.yaml"],
        tmp_path,
    ) == []
