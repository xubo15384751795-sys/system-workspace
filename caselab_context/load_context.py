"""Load Context Layer artifacts from the Paper vault."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

PAPER_ROOT = Path("/Users/a1/Paper")
ENTITY_DIR = PAPER_ROOT / "02_Entities"
RULES_YAML_PATH = PAPER_ROOT / "90_Admin/Context Rules/resolver_rules.yml"
RESOLVER_PATH = PAPER_ROOT / "09_Models/System/Contextual Meaning Resolver.md"
REGIME_DIR = PAPER_ROOT / "90_Admin/Context"


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    return yaml.safe_load(match.group(1)) or {}


def _normalize(value: str) -> str:
    return re.sub(r"[\s_-]+", "_", value.strip().lower())


def find_entity_path(actor: str) -> Path | None:
    target = _normalize(actor)
    if not ENTITY_DIR.exists():
        return None
    for path in ENTITY_DIR.rglob("*.md"):
        meta = _parse_frontmatter(path)
        names = {
            _normalize(meta.get("canonical_name", "")),
            _normalize(path.stem),
        }
        context = meta.get("context_layer") or {}
        if context.get("entity"):
            names.add(_normalize(str(context["entity"])))
        for alias in meta.get("aliases") or []:
            names.add(_normalize(str(alias)))
        names.discard("")
        if target in names:
            return path
    return None


def load_entity_dna(actor: str) -> dict[str, Any]:
    path = find_entity_path(actor)
    if path is None:
        return {"entity": actor, "source_path": None, "context_layer": {}}
    meta = _parse_frontmatter(path)
    return {
        "entity": meta.get("canonical_name") or path.stem,
        "source_path": str(path),
        "context_layer": meta.get("context_layer") or {},
        "dna_tags": meta.get("dna_tags") or [],
        "inertia_tags": meta.get("inertia_tags") or [],
        "related_cases": meta.get("related_cases") or [],
    }


def load_resolver_rules() -> list[dict[str, Any]]:
    # Prefer standalone YAML (architecture convergence target)
    if RULES_YAML_PATH.exists():
        data = yaml.safe_load(RULES_YAML_PATH.read_text(encoding="utf-8")) or {}
        rules = data.get("resolver_rules")
        if isinstance(rules, list):
            return rules
    # Fallback: parse from Markdown (deprecated, kept for compatibility)
    if not RESOLVER_PATH.exists():
        return []
    text = RESOLVER_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    for block in blocks:
        data = yaml.safe_load(block) or {}
        rules = data.get("resolver_rules")
        if isinstance(rules, list):
            return rules
    return []


def default_regime() -> dict[str, str]:
    return load_current_regime() or {
        "liquidity": "abundant",
        "rates": "stable",
        "credit": "expanding",
        "regulation": "loose",
        "market_mood": "risk_on",
        "technology_cycle": "scaling",
    }


def load_current_regime() -> dict[str, str] | None:
    if not REGIME_DIR.exists():
        return None
    candidates = sorted(REGIME_DIR.glob("Regime Context *.md"), reverse=True)
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
        for block in blocks:
            data = yaml.safe_load(block) or {}
            regime = data.get("regime")
            if isinstance(regime, dict):
                return {k: str(v) for k, v in regime.items() if k != "evidence" and k != "indicators" and k != "as_of" and k != "confidence"}
    return None
