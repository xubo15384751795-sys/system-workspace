from __future__ import annotations

import hashlib
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root


ROOT = _workspace_root()
MAPPING_RULES = ROOT / "Data" / "nlp" / "mapping_rules.yaml"
CONFIDENCE_RULES_VERSION = "confidence_rules_v0.1"
EXTRACTOR_VERSION = "structural_nlp_v0.2"
ENTITY_EXTRACTOR_VERSION = "rule_entity_extractor_v0.1"
VARIABLE_MAPPER_VERSION = "rule_variable_mapper_v0.1"
SCHEMA_VALIDATOR_VERSION = "schema_validator_v0.1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def text_sha256(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def mapping_rules_hash(path: Path | None = None) -> str:
    target = path or MAPPING_RULES
    if not target.exists():
        return "sha256:missing"
    return file_sha256(target)


def confidence_rules_version() -> str:
    return CONFIDENCE_RULES_VERSION
