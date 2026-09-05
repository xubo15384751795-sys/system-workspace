from __future__ import annotations

import importlib.util
import subprocess
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


def _write_cleanup_epoch(root: Path, **coverage_overrides) -> Path:
    coverage = {
        "covers_subsequent_commits": True,
        "layers": ["L3"],
        "path_prefixes": ["governance/", "protocols/", "module_contexts/", "system_runtime/"],
        "paths": [".pre-commit-config.yaml"],
    }
    coverage.update(coverage_overrides)
    decision = root / "governance" / "routing_decisions" / "2026-09-cleanup-epoch.yaml"
    decision.parent.mkdir(parents=True, exist_ok=True)
    decision.write_text(
        yaml.safe_dump(
            {
                "cynefin_domain": "complex",
                "status": "active",
                "probe": {
                    "scope": "Phase 1-3 L3 files",
                    "preregistered_expectation": "in-scope L3 commits reuse this epoch",
                    "observation_window": "14 days after migration",
                    "rollback": "revert the step commit",
                },
                "epoch_coverage": coverage,
            }
        ),
        encoding="utf-8",
    )
    return decision


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


def test_non_pace_governance_record_does_not_substitute_for_decision(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    record = tmp_path / "governance" / "routing_decisions" / "research-freeze.yaml"
    record.parent.mkdir(parents=True)
    record.write_text(
        yaml.safe_dump(
            {
                "schema_version": "routing_decision_record.v1",
                "task_id": "research-freeze",
                "status": "FROZEN",
            }
        ),
        encoding="utf-8",
    )
    errors = module.check_paths(
        ["PACE.md", "governance/routing_decisions/research-freeze.yaml"],
        tmp_path,
    )
    assert errors and "cynefin_domain required" in errors[0]


def test_active_epoch_covers_subsequent_in_scope_l3_commit(tmp_path: Path) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    _write_cleanup_epoch(tmp_path)
    assert module.check_paths(["protocols/event.schema.json"], tmp_path) == []
    assert module.check_paths([".pre-commit-config.yaml"], tmp_path) == []


def test_active_epoch_does_not_cover_l4_or_out_of_scope_l3(tmp_path: Path) -> None:
    module = _load_module()
    tmp_path.joinpath("PACE.md").write_text(
        "---\nschema_version: test\nlayers:\n"
        "  L4:\n    paths: [PACE.md]\n"
        "  L3:\n    prefixes: [protocols/, governance/, configs/]\n"
        "  L2:\n    prefixes: [packages/]\n"
        "  L1:\n    prefixes: [Output/sandbox/]\n"
        "---\n# test\n",
        encoding="utf-8",
    )
    _write_cleanup_epoch(tmp_path)
    l4_errors = module.check_paths(["PACE.md"], tmp_path)
    assert l4_errors and "PACE violation" in l4_errors[0]
    errors = module.check_paths(["configs/freshness_policy.yaml"], tmp_path)
    assert errors and "PACE violation" in errors[0]


def test_inactive_epoch_does_not_cover_later_commits(tmp_path: Path) -> None:
    module = _load_module()
    _write_pace(tmp_path)
    _write_cleanup_epoch(tmp_path)
    decision = tmp_path / "governance" / "routing_decisions" / "2026-09-cleanup-epoch.yaml"
    data = yaml.safe_load(decision.read_text(encoding="utf-8"))
    data["status"] = "closed"
    decision.write_text(yaml.safe_dump(data), encoding="utf-8")
    errors = module.check_paths(["protocols/event.schema.json"], tmp_path)
    assert errors and "PACE violation" in errors[0]


def test_repo_cleanup_epoch_covers_in_scope_l3_without_restaging() -> None:
    module = _load_module()
    epoch = ROOT / "governance" / "routing_decisions" / "2026-09-cleanup-epoch.yaml"
    assert epoch.is_file()
    assert module.validate_decision(epoch) == []
    assert module.check_paths(
        ["governance/daily_pipeline_registry.yaml", "protocols/evidence.schema.json"],
        ROOT,
    ) == []
    l4_errors = module.check_paths(["PACE.md"], ROOT)
    assert l4_errors and "PACE violation" in l4_errors[0]


def test_changed_paths_uses_merge_base_diff(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()

    def fake_run(command, **kwargs):
        assert command[-1] == "origin/main...HEAD"
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="PACE.md\ngovernance/routing_decisions/probe.yaml\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module._changed_paths(tmp_path, "origin/main") == [
        "PACE.md",
        "governance/routing_decisions/probe.yaml",
    ]
