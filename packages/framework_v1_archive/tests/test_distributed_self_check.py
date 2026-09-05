from __future__ import annotations

from pathlib import Path

from src.validation.architecture_self_check import run_framework_self_check


def test_framework_self_check_is_exception_only_for_clean_tree(tmp_path: Path) -> None:
    src = tmp_path / "packages/framework/src"
    (src / "core").mkdir(parents=True)
    (src / "core/model.py").write_text("VALUE = 1\n", encoding="utf-8")
    report = run_framework_self_check(workspace_root=tmp_path, src_root=src)
    assert report["deviation_count"] == 0


def test_framework_self_check_owns_network_boundary(tmp_path: Path) -> None:
    src = tmp_path / "packages/framework/src"
    (src / "core").mkdir(parents=True)
    (src / "core/model.py").write_text("import requests\n", encoding="utf-8")
    report = run_framework_self_check(workspace_root=tmp_path, src_root=src)
    findings = report["checks"]["framework_http_imports"]
    assert findings and findings[0]["import"] == "requests"
