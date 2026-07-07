from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForbiddenImportRule:
    name: str
    source_scope: str
    forbidden_imports: tuple[str, ...]
    severity: str = "high"


FORBIDDEN_IMPORT_RULES = (
    ForbiddenImportRule(
        name="ui_forbidden_subsystem_import",
        source_scope="ui",
        forbidden_imports=("src.data.gateway", "src.proxies", "src.diagnostics", "src.derivation", "harvester"),
        severity="high",
    ),
    ForbiddenImportRule(
        name="deformation_must_not_import_harvester",
        source_scope="deformation",
        forbidden_imports=("harvester", "structural_risk_harvester"),
        severity="critical",
    ),
)

HARVESTER_FORBIDDEN_TERMS = ("M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY", "Sigma_t", "morphology", "claim_registry")
HARVESTER_PATH_TERMS = (
    "Data/harvester/raw",
    "Data/harvester/processed",
    "Data/harvester/corpus",
    "harvester/raw",
    "harvester/processed",
    "harvester/corpus",
)
PROVIDER_WARNING_DIRS = ("src/data/adapters", "src/data/gateway")


def source_scope(rel_path: str, module: str) -> str:
    lowered = rel_path.lower()
    if "/src/ui/" in f"/{lowered}" or module.startswith("ui.") or ".ui." in module:
        return "ui"
    if "structural deformation research system" in lowered:
        return "deformation"
    if "structural risk harvester" in lowered:
        return "harvester"
    return "unknown"


def is_deformation_adapter(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    return "/src/data/adapters/" in f"/{normalized}" or "/src/data/gateway/" in f"/{normalized}"


def is_provider_warning_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    lowered = normalized.lower()
    return "structural deformation research system" in lowered and any(marker in normalized for marker in PROVIDER_WARNING_DIRS)
