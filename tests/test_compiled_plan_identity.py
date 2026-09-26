"""Cross-entrypoint identity contract for the compiled execution plan."""
from __future__ import annotations

import json
from pathlib import Path

from system_cli.app import main
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import load_pipeline
from system_runtime.plan_apply import build_plan

ROOT = Path(__file__).resolve().parents[1]


def test_cli_plan_artifact_and_authority_graph_share_identity(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SYSTEM_WORKSPACE_ROOT", str(ROOT))
    paths = WorkspacePaths(root=ROOT)
    compiled = load_pipeline(paths)

    assert main(["pipeline", "validate"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["plan_digest"] == compiled.plan_digest
    assert cli_payload["edges"] == len(compiled.edges)
    assert cli_payload["profiles"] == {
        name: len(compiled.projection(name))
        for name in sorted(compiled.profiles)
    }

    artifact = build_plan(paths, profile="daily", code_sha="identity-test")
    assert artifact.plan_digest == compiled.plan_digest
    assert artifact.edges == {
        consumer: tuple(producers)
        for consumer, producers in compiled.edges.items()
        if consumer in artifact.steps
        and any(producer in artifact.steps for producer in producers)
    }

    from verity.runtime._authority_graph import build_authority_graph

    graph = build_authority_graph(ROOT)
    assert graph["plan_digest"] == compiled.plan_digest
    assert graph["compiled_plan"]["plan_digest"] == compiled.plan_digest
    assert graph["compiled_plan"]["edges"] == {
        consumer: list(producers)
        for consumer, producers in sorted(compiled.edges.items())
    }
