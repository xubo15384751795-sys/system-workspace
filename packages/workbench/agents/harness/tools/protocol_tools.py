"""protocol_tools — governed protocol and contract validation tools."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from tools.registry import ToolResult, ToolSpec, _register


HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
WORKBENCH_SRC = WORKBENCH_ROOT / "src"

CONTRACT_VALIDATORS: dict[str, str] = {
    "provider-release": "validate_provider_release",
    "evidence-panel": "validate_evidence_panel",
    "model-run": "validate_model_run",
    "report-artifacts": "validate_report_artifacts",
    "ml-signal": "validate_ml_signal",
    "ml-signal-manifest": "validate_ml_signal_manifest",
}


def _contract_validator() -> tuple[type[Exception], dict[str, Callable[[Path], None]]]:
    if str(WORKBENCH_SRC) not in sys.path:
        sys.path.insert(0, str(WORKBENCH_SRC))
    from workbench import contract_validator

    validators = {
        contract_type: getattr(contract_validator, func_name)
        for contract_type, func_name in CONTRACT_VALIDATORS.items()
    }
    return contract_validator.ValidationError, validators


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKBENCH_ROOT))
    except ValueError:
        return str(path.resolve())


def _h_validate_contract(input: dict, dry_run: bool) -> ToolResult:
    contract_type = str(
        input.get("contract_type") or input.get("kind") or input.get("type") or ""
    ).strip()
    target_raw = str(input.get("target_path") or input.get("path") or "").strip()

    if not contract_type:
        return ToolResult(
            ok=False,
            tool_id="protocols.validate_contract",
            errors=["protocols.validate_contract requires contract_type=<kind>"],
        )
    if contract_type not in CONTRACT_VALIDATORS:
        return ToolResult(
            ok=False,
            tool_id="protocols.validate_contract",
            evidence={
                "validation": {
                    "contract_type": contract_type,
                    "target_path": target_raw,
                    "valid": False,
                    "errors": [f"unsupported contract_type: {contract_type}"],
                    "allowed_contract_types": sorted(CONTRACT_VALIDATORS),
                }
            },
            errors=[f"unsupported contract_type: {contract_type}"],
        )
    if not target_raw:
        return ToolResult(
            ok=False,
            tool_id="protocols.validate_contract",
            errors=["protocols.validate_contract requires target_path=<file-or-directory>"],
        )

    target = Path(target_raw)
    if not target.is_absolute():
        target = WORKBENCH_ROOT / target

    ValidationError, validators = _contract_validator()
    errors: list[str] = []
    valid = False
    try:
        validators[contract_type](target)
        valid = True
    except ValidationError as exc:
        errors = [str(exc)]
    except OSError as exc:
        errors = [str(exc)]

    validation = {
        "contract_type": contract_type,
        "target_path": _display_path(target),
        "valid": valid,
        "errors": errors,
    }
    return ToolResult(
        ok=valid,
        tool_id="protocols.validate_contract",
        summary=(
            f"Contract validation passed for {validation['target_path']}"
            if valid
            else f"Contract validation failed for {validation['target_path']}"
        ),
        artifacts=[validation["target_path"]],
        evidence={"validation": validation},
        errors=errors,
    )


_register(ToolSpec(
    id="protocols.validate_contract",
    description=(
        "Validate Workbench protocol contract payloads through the governed "
        "contract validator"
    ),
    subsystem="protocols",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_validate_contract,
))
