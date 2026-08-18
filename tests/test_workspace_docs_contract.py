from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_workspace_docs_use_monorepo_bootstrap_reality() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    layout = (ROOT / "governance/repo_layout_map.md").read_text(encoding="utf-8")
    schedule = (ROOT / "governance/pipeline_schedule.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    workbench_readme = (ROOT / "packages/workbench/README.md").read_text(encoding="utf-8")
    protocols = (ROOT / "protocols/README.md").read_text(encoding="utf-8")
    validation_policy = (ROOT / "governance/ml_validation_policy.yaml").read_text(encoding="utf-8")
    framework_app = (ROOT / "packages/framework/src/api/app.py").read_text(encoding="utf-8")
    framework_assembly = (ROOT / "packages/framework/src/runtime/assembly.py").read_text(encoding="utf-8")
    admitted_evidence = (ROOT / "packages/framework/src/data_access/admitted_evidence.py").read_text(encoding="utf-8")
    dual_path = (ROOT / "packages/framework/scripts/dual_path_compare.py").read_text(encoding="utf-8")
    data_paths = (ROOT / "packages/framework/src/data/paths.py").read_text(encoding="utf-8")

    assert not (ROOT / ".gitmodules").exists()
    assert "Repository Layout (monorepo workspace)" in readme
    assert "packages/orchestration/" in readme
    assert "learning_hub orchestration" in bootstrap
    assert "git clone --recurse-submodules" not in readme
    assert ".gitmodules" in readme  # explicit statement that the file is absent
    assert "Current canonical workspace" in layout
    assert "Historical pre-consolidation layout" in layout
    assert "packages/orchestration/" in layout
    assert "entrypoint_registry.yaml" in layout
    assert "second hand-written list" in layout
    assert "Historical Daily / Weekly / On-Demand Reference" in schedule
    assert "daily_pipeline_registry.yaml" in schedule
    assert "uv sync --locked --all-packages" in workbench_readme
    assert "pip install -e" not in workbench_readme
    assert "packages/workbench/src/nlp/" in protocols
    assert "Workbench/src/" not in protocols
    assert "packages/workbench/src/workbench/judgment/layer.py" in validation_policy
    assert "Workbench/src/" not in validation_policy
    for active_source in (framework_app, framework_assembly, admitted_evidence, dual_path):
        assert "Workbench/data_providers" not in active_source
    assert 'project_root / "packages" / "harvester" / "contracts"' in data_paths


def test_compiled_pipeline_docs_validator_passes() -> None:
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline, validate_pipeline_docs

    paths = WorkspacePaths(root=ROOT)
    pipeline = load_pipeline(paths)
    assert validate_pipeline_docs(paths, pipeline) == []
