"""Repository-level governance controls are present and internally coherent."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_security_policy_and_pull_request_evidence_template_exist() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    template = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    for marker in ("Reporting a vulnerability", "Data and Output", "default path"):
        assert marker in security or marker in template
    for marker in ("before/after hashes", "Rollback", "Remote CI"):
        assert marker.lower() in template.lower()


def test_local_hook_is_advisory_and_server_required_check_is_authoritative() -> None:
    hook = (ROOT / "scripts" / "_pre_push_hook.sh").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    template = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")

    assert "git push --no-verify" in hook
    assert "server-side required check remains authoritative" in hook
    assert "Local Git hooks are advisory controls, not a security boundary" in security
    assert "server-side required check" in security
    assert "bypassable (`git push --no-verify`)" in template
    assert "final enforcement authority" in template


def test_dependabot_covers_uv_and_actions_with_bounded_grouping() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = config["updates"]
    ecosystems = {entry["package-ecosystem"] for entry in updates}
    assert ecosystems == {"uv", "github-actions"}
    for entry in updates:
        assert entry["directory"] == "/"
        assert entry["schedule"]["interval"] == "weekly"
        assert 1 <= int(entry["open-pull-requests-limit"]) <= 3
        groups = entry.get("groups", {})
        assert groups
        assert any(
            set(group.get("update-types", [])) == {"minor", "patch"}
            for group in groups.values()
        )


def test_codeowners_covers_high_risk_runtime_and_egress_paths() -> None:
    text = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    for marker in (
        "/governance/",
        "/system_runtime/",
        "/scripts/daily_run.py",
        "/packages/framework/src/data_access/",
        "/packages/harvester/src/harvester/providers/",
    ):
        assert marker in text
    assert "second qualified reviewer" in text


def test_ci_sast_is_bound_to_the_authoritative_merge_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert "sast" in jobs
    assert "semgrep==1.162.0" in str(jobs["sast"])
    needs = jobs["merge-gate"]["needs"]
    assert "sast" in needs


def test_ci_type_checks_owned_package_boundaries_and_merges_the_result() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    type_job = jobs["package-type-boundaries"]
    assert type_job["needs"] == "lock-integrity"
    assert type_job["timeout-minutes"] == 20
    type_run = "\n".join(
        str(step.get("run", ""))
        for step in type_job["steps"]
        if isinstance(step, dict)
    )
    for marker in (
        "system_runtime",
        "packages/framework/src/api",
        "packages/harvester/src/harvester/core/manifest.py",
        "packages/workbench/src/workbench/external_http.py",
        "packages/orchestration/orchestration",
        "--explicit-package-bases",
    ):
        assert marker in type_run
    assert "continue-on-error" not in str(type_job)

    merge_gate = jobs["merge-gate"]
    assert "package-type-boundaries" in merge_gate["needs"]
    verify_step = next(
        step for step in merge_gate["steps"]
        if step.get("name") == "Verify upstream job results"
    )
    assert "PACKAGE_TYPE_BOUNDARIES_RESULT" in verify_step["env"]
    assert "PACKAGE_TYPE_BOUNDARIES_RESULT" in str(verify_step["run"])


def test_ci_checks_pipeline_documentation_authority() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    lint_steps = workflow["jobs"]["lint"]["steps"]
    runs = [str(step.get("run", "")) for step in lint_steps if isinstance(step, dict)]
    assert "uv run --locked python -m system_cli pipeline docs --check" in runs


def test_ci_header_describes_merge_gate_as_aggregate_authority() -> None:
    header = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").split(
        "name: CI Minimal Gate", 1
    )[0]
    assert "focused checks" in header
    assert "merge-gate" in header
    assert "aggregate authority" in header


def test_justfile_required_gates_do_not_suppress_failures() -> None:
    """The two case-variant entrypoints must remain fail-closed and identical."""
    canonical = (ROOT / "Justfile").read_text(encoding="utf-8")
    compatibility = (ROOT / "justfile").read_text(encoding="utf-8")
    assert canonical == compatibility
    assert "|| true" not in canonical
    assert "|| echo" not in canonical


def test_orchestration_installers_and_watcher_report_failures() -> None:
    orchestrate = (ROOT / "scripts" / "orchestrate.sh").read_text(encoding="utf-8")
    install_block = orchestrate.split("  install-automation)", 1)[1].split("  ;;", 1)[0]
    assert "failed_installers" in install_block
    assert "Automation installers incomplete" in install_block
    assert "|| true" not in install_block

    watcher = (ROOT / "scripts" / "watch_paper_sync.sh").read_text(encoding="utf-8")
    assert "Paper sync failed (exit" in watcher
    assert "|| true" not in watcher


def test_merge_gate_always_runs_and_requires_every_upstream_success() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    merge_gate = workflow["jobs"]["merge-gate"]
    assert merge_gate["if"] == "${{ always() }}"

    needs = merge_gate["needs"]
    assert isinstance(needs, list) and needs
    env = next(
        step["env"]
        for step in merge_gate["steps"]
        if isinstance(step, dict) and step.get("name") == "Verify upstream job results"
    )
    run = next(
        str(step["run"])
        for step in merge_gate["steps"]
        if isinstance(step, dict) and step.get("name") == "Verify upstream job results"
    )
    assert all(f"{job.replace('-', '_').upper()}_RESULT" in env for job in needs)
    assert 'if [[ "$result" != "success" ]]' in run
    assert "exit 1" in run


def test_ci_test_layers_emit_pytest_duration_evidence() -> None:
    for filename in ("ci.yml", "nightly.yml", "weekly-governance.yml"):
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        )
        pytest_runs = [
            (job, str(step.get("run", "")))
            for job in workflow["jobs"].values()
            if isinstance(job, dict)
            for step in job.get("steps", [])
            if isinstance(step, dict) and "pytest" in str(step.get("run", ""))
        ]
        assert pytest_runs, f"{filename} has no pytest evidence"
        assert all("--durations=25" in run for _, run in pytest_runs), filename
        assert all(
            isinstance(job.get("timeout-minutes"), int)
            and job["timeout-minutes"] > 0
            for job, _ in pytest_runs
        ), filename


def test_compute_device_handoff_declares_operator_timeout_and_duration_evidence() -> None:
    handoff = (ROOT / "docs" / "history" / "P0_4_COMPUTE_DEVICE_HANDOFF.md").read_text(encoding="utf-8")
    for marker in (
        "PR / hermetic",
        "Package",
        "Nightly / operator",
        "Compute device",
        "--timeout-seconds 5400",
        "--durations=25",
        "600 seconds",
        "numeric budget",
    ):
        assert marker in handoff


def test_ci_root_contract_job_guards_clean_checkout_data_output_boundary() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["integration"]["steps"]
    before = next(
        step for step in steps
        if step.get("name") == "Clean-checkout Data/Output boundary (before root tests)"
    )
    after = next(
        step for step in steps
        if step.get("name") == "Clean-checkout Data/Output boundary (after root tests)"
    )
    root_tests_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Root contract tests"
    )
    assert steps.index(before) < root_tests_index < steps.index(after)
    assert "--phase before" in str(before["run"])
    assert "--phase after" in str(after["run"])
    assert "system-clean-checkout-boundary.json" in str(before["run"])
    assert "system-clean-checkout-boundary.json" in str(after["run"])
    assert after["if"] == "always()"


def test_vulnerability_ledger_is_explicit_and_schema_bound() -> None:
    ledger = yaml.safe_load(
        (ROOT / "governance" / "vulnerability_exception_ledger.yaml").read_text(encoding="utf-8")
    )
    assert ledger["schema_version"] == "system.vulnerability_exception_ledger.v1"
    assert ledger["status"] == "NOT_ASSESSED"
    assert ledger["assessment"]["tool"] == "NOT_RUN"
    assert ledger["exceptions"] == []
    schema = yaml.safe_load(
        (ROOT / "protocols" / "vulnerability_exception_ledger.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$id"] == "system.vulnerability_exception_ledger.v1"


def test_pre_push_hook_runs_contracts_for_feature_and_merge_gate_for_main(tmp_path: Path) -> None:
    source_hook = ROOT / "scripts" / "_pre_push_hook.sh"
    hook_text = source_hook.read_text(encoding="utf-8")
    assert "installed hook digest differs" in hook_text
    assert "./sys pipeline validate" in hook_text
    assert "tests/test_plan_apply.py" in hook_text
    assert "./sys verify --merge" in hook_text

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "scripts").mkdir()
    tracked_hook = repo / "scripts" / "_pre_push_hook.sh"
    tracked_hook.write_text(source_hook.read_text(encoding="utf-8"), encoding="utf-8")
    tracked_hook.chmod(0o755)
    (repo / "sys").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOOK_LOG\"\n",
        encoding="utf-8",
    )
    (repo / "sys").chmod(0o755)
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_bytes(tracked_hook.read_bytes())
    hook.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\nprintf 'python %s\\n' \"$*\" >> \"$HOOK_LOG\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    log = tmp_path / "hook.log"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOOK_LOG": str(log),
    }

    feature = "refs/heads/feature abc refs/heads/feature 000"
    subprocess.run(
        [str(hook)], input=feature + "\n", text=True, env=env, cwd=repo, check=True
    )
    feature_log = log.read_text(encoding="utf-8").splitlines()
    assert "pipeline validate" in feature_log
    assert any(line.startswith("python -m pytest") for line in feature_log)
    assert "verify --merge" not in feature_log

    log.write_text("", encoding="utf-8")
    main = "refs/heads/feature abc refs/heads/main 000"
    subprocess.run(
        [str(hook)], input=main + "\n", text=True, env=env, cwd=repo, check=True
    )
    main_log = log.read_text(encoding="utf-8").splitlines()
    assert "pipeline validate" in main_log
    assert "verify --merge" in main_log
    assert any(line.startswith("python -m pytest") for line in main_log)

    hook.write_text(hook.read_text(encoding="utf-8") + "\n# local drift\n", encoding="utf-8")
    drift = subprocess.run(
        [str(hook)], input=feature + "\n", text=True, env=env, cwd=repo, capture_output=True
    )
    assert drift.returncode == 1
    assert "digest" in drift.stderr

    assert shutil.which("git")


def test_pre_push_installer_verifies_installed_source_digest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    scripts = repo / "scripts"
    scripts.mkdir()
    source = ROOT / "scripts" / "_pre_push_hook.sh"
    installer = ROOT / "scripts" / "install_pre_push_hook.sh"
    (scripts / "_pre_push_hook.sh").write_bytes(source.read_bytes())
    (scripts / "install_pre_push_hook.sh").write_bytes(installer.read_bytes())
    (scripts / "_pre_push_hook.sh").chmod(0o755)
    (scripts / "install_pre_push_hook.sh").chmod(0o755)

    subprocess.run([str(scripts / "install_pre_push_hook.sh")], cwd=repo, check=True)
    installed = repo / ".git" / "hooks" / "pre-push"
    assert installed.read_bytes() == (scripts / "_pre_push_hook.sh").read_bytes()
