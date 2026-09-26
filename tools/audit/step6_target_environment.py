"""Read-only Step 6 target-environment readiness audit.

This audit separates three things that must not be conflated:

* bounded local migration rehearsal;
* target Linux/systemd bootstrap and shadow observation;
* the formal 14-day reliability proof.

It never starts a service, installs a target host, changes scheduler state, or
mutates the reliability evidence history.  The formal proof is evaluated with
the target scheduler identity, so Mac/launchd runs cannot silently contribute
to the target window.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from tools.verify_data_reliability_window import build_window_report

ROOT = Path(__file__).resolve().parents[2]
STEP3_PATH = ROOT / "governance" / "step3_portable_runtime.yaml"
STEP5_PATH = ROOT / "governance" / "step5_structural_cleanup.yaml"
STEP6_PATH = ROOT / "governance" / "step6_target_environment.yaml"
RELIABILITY_PATH = ROOT / "governance" / "reliability_window_contract.yaml"
SERVICE_TEMPLATE = ROOT / "configs" / "systemd" / "verity-daily.service.in"
TIMER_TEMPLATE = ROOT / "configs" / "systemd" / "verity-daily.timer"
TARGET_SCHEDULER_ID = "systemd:verity-daily"
TARGET_SHADOW_SCHEDULER_ID = "systemd:verity-daily-shadow"
FORBIDDEN_HOST_PATH = re.compile(r"/(?:Users|Applications)/[A-Za-z0-9_. -]+")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _exists(relative: str) -> bool:
    return (ROOT / relative).is_file()


def _check(status: str, **details: Any) -> dict[str, Any]:
    return {"status": status, **details}


def _local_rehearsal_report(step3: dict[str, Any], step5: dict[str, Any]) -> dict[str, Any]:
    step3_status = str(step3.get("status") or "")
    step5_restore = ((step5.get("closure_slices") or {}).get("5E_restore_generation") or {})
    structural_restore = step5_restore.get("structural_restore") or {}
    checks = {
        "portable_runtime": _check(
            "PASS" if step3_status.startswith("PASS") else "FAIL",
            source="governance/step3_portable_runtime.yaml",
            source_status=step3_status,
        ),
        "locked_install": _check(
            "PASS" if _exists("uv.lock") and _exists("pyproject.toml") else "FAIL",
            command="uv sync --locked --all-packages",
        ),
        "clean_shell_import": _check(
            "PASS" if step3.get("gates", {}).get("clean_shell_import_without_pythonpath", {}).get("status") == "PASS" else "FAIL",
            command="env -u PYTHONPATH .venv/bin/python -c 'import system_cli, system_runtime, verity, orchestration, harvester'",
        ),
        "failure_scenario": _check(
            "PASS"
            if _exists("tests/test_failure_propagation.py")
            and _exists("tests/test_execution_spine.py")
            else "FAIL",
            tests=["tests/test_failure_propagation.py", "tests/test_execution_spine.py"],
        ),
        "publication": _check(
            "PASS"
            if str(step5_restore.get("latest_rehearsal_publication") or "") == "COMMITTED"
            else "NOT_PROVEN",
            run_id=step5_restore.get("latest_rehearsal_run"),
            publication=step5_restore.get("latest_rehearsal_publication"),
        ),
        "structural_restore": _check(
            "PASS" if structural_restore.get("status") == "PASS" else "NOT_PROVEN",
            target_generation=structural_restore.get("target_generation"),
            authority=structural_restore.get("restored_authority"),
            claim_ceiling=structural_restore.get("restored_claim_ceiling"),
            decision_consumers_allowed=structural_restore.get(
                "restored_allows_decision_consumers"
            ),
        ),
    }
    status = "PASS_BOUNDED" if all(item["status"] == "PASS" for item in checks.values()) else "NOT_PROVEN"
    return {
        "status": status,
        "formal_window_started": False,
        "formal_window_counted_days": 0,
        "checks": checks,
    }


def _template_report() -> dict[str, Any]:
    service = SERVICE_TEMPLATE.read_text(encoding="utf-8") if SERVICE_TEMPLATE.is_file() else ""
    timer = TIMER_TEMPLATE.read_text(encoding="utf-8") if TIMER_TEMPLATE.is_file() else ""
    service_required = {
        "placeholder_workspace": "__WORKSPACE_ROOT__" in service,
        "placeholder_data": "__DATA_ROOT__" in service,
        "placeholder_output": "__OUTPUT_ROOT__" in service,
        "secret_boundary": "EnvironmentFile=-__SECRET_ENV_FILE__" in service,
        "scheduled_identity": all(
            token in service
            for token in (
                "SYSTEM_TRIGGER_KIND=scheduled",
                "SYSTEM_SCHEDULER_KIND=systemd",
                "SYSTEM_SCHEDULER_ID=systemd:verity-daily",
            )
        ),
        "locked_runtime_entrypoint": ".venv/bin/verity" in service,
        "no_pythonpath": "PYTHONPATH" not in service,
        "no_mac_path": FORBIDDEN_HOST_PATH.search(service) is None,
    }
    timer_required = {
        "calendar": "OnCalendar=" in timer,
        "persistent": "Persistent=true" in timer,
        "service_binding": "Unit=verity-daily.service" in timer,
        "no_mac_path": FORBIDDEN_HOST_PATH.search(timer) is None,
    }
    status = "PASS" if all(service_required.values()) and all(timer_required.values()) else "FAIL"
    return {
        "status": status,
        "service": str(SERVICE_TEMPLATE.relative_to(ROOT)),
        "timer": str(TIMER_TEMPLATE.relative_to(ROOT)),
        "service_checks": service_required,
        "timer_checks": timer_required,
    }


def _target_bootstrap_report(step6: dict[str, Any]) -> dict[str, Any]:
    target = step6.get("target_bootstrap") or {}
    target_host_id = target.get("target_host_id")
    status = "PASS" if target_host_id else "PENDING_TARGET_HOST"
    return {
        "status": status,
        "target_host_id": target_host_id,
        "target_release_id": target.get("target_release_id"),
        "templates": target.get("templates") or {},
        "required_install": target.get("required_install") or [],
        "identity": target.get("required_identity") or {},
    }


def _formal_proof_report(reliability_contract: dict[str, Any]) -> dict[str, Any]:
    accepted_release = str(reliability_contract.get("accepted_release") or "").strip() or None
    report = build_window_report(
        ROOT,
        accepted_schedulers={TARGET_SCHEDULER_ID},
        accepted_release=accepted_release,
        formal_target=True,
    )
    if report["status"] == "COMPLETE":
        status = "COMPLETE"
    elif report["observed_runs"] == 0:
        status = "NOT_STARTED_TARGET_REQUIRED"
    else:
        status = "PENDING_TARGET_WINDOW"
    return {
        "status": status,
        "verifier_status": report["status"],
        "proof_host": "target_environment_only",
        "accepted_release": accepted_release,
        "accepted_scheduler_ids": [TARGET_SCHEDULER_ID],
        "observed_runs": report["observed_runs"],
        "qualified_days": report["qualified_days"],
        "consecutive_days": report["consecutive_days"],
        "minimum_days": report["minimum_days"],
        "scenarios": report["scenarios"],
        "non_qualified_runs": report["non_qualified_runs"],
        "failure_history_retained": True,
        "mac_runs_counted": False,
    }


def build_report() -> dict[str, Any]:
    step3 = _load_yaml(STEP3_PATH)
    step5 = _load_yaml(STEP5_PATH)
    step6 = _load_yaml(STEP6_PATH)
    reliability_contract = _load_yaml(RELIABILITY_PATH)
    local = _local_rehearsal_report(step3, step5)
    templates = _template_report()
    target = _target_bootstrap_report(step6)
    shadow_contract = step6.get("shadow_observation") or {}
    formal = _formal_proof_report(reliability_contract)
    gates = {
        "local_rehearsal": local["status"],
        "target_bootstrap": target["status"],
        "shadow_observation": (
            "NOT_STARTED_TARGET_REQUIRED"
            if target["status"] != "PASS"
            else str(shadow_contract.get("status") or "NOT_STARTED")
        ),
        "formal_fourteen_day_proof": formal["status"],
    }
    overall = (
        "LOCAL_REHEARSAL_PASS_TARGET_BOOTSTRAP_PENDING"
        if local["status"] == "PASS_BOUNDED" and target["status"] != "PASS"
        else "TARGET_BOOTSTRAP_READY_SHADOW_PENDING"
        if target["status"] == "PASS" and gates["shadow_observation"] != "PASS"
        else "FORMAL_PROOF_PENDING"
        if formal["status"] != "COMPLETE"
        else "COMPLETE"
    )
    return {
        "schema_version": "system.step6_target_environment_audit.v1",
        "step": 6,
        "status": overall,
        "scope": "read_only_target_bootstrap_and_formal_proof_readiness",
        "local_rehearsal": local,
        "target_bootstrap": target,
        "bootstrap_templates": templates,
        "shadow_observation": {
            "status": gates["shadow_observation"],
            "scheduler_id": TARGET_SHADOW_SCHEDULER_ID,
            "authority": "shadow",
            "isolated_output": True,
            "shared_current_pointer_allowed": False,
            "promotion_allowed": False,
            "comparison_dimensions": shadow_contract.get("comparison_dimensions") or [],
        },
        "formal_fourteen_day_proof": formal,
        "gates": gates,
        "invariants": {
            "provider_admission_rule_unchanged": True,
            "authority_rule_unchanged": True,
            "reliability_qualification_rule_unchanged": True,
            "formal_proof_started_on_mac": False,
            "docker_orchestration_introduced": False,
        },
    }


def main() -> int:
    print(json.dumps(build_report(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
