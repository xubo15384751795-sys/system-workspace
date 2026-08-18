"""CaseLab → System adapter.

Reads CaseLab markdown files (Obsidian vault) and returns CaseProfile /
EntityProfile objects consumable by System's NLP pipeline.

No NLP required for basic operation — parses YAML frontmatter and
markdown section headers via regex. Structural vectors are computed
by the rule-based engine in structural_vector.py.

Usage:
    from nlp.caselab.adapter import CaseLabAdapter

    adapter = CaseLabAdapter("/Users/a1/Paper")
    cases = adapter.load_cases()        # list[CaseProfile]
    entities = adapter.load_entities()  # list[dict]
    mechanisms = adapter.load_mechanisms()  # list[dict]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nlp.caselab.structural_vector import (
    compute_entity_structural_vector,
    compute_structural_vector,
)


# ── Section header patterns ──────────────────────────────────────────────
# CaseLab uses multiple header formats. We match by semantic meaning.

_SECTION_ALIASES: dict[str, list[str]] = {
    "positioning": [
        r"中文定位",
        r"Chinese Positioning",
        r"English Positioning",
        r"一句话定位",
    ],
    "counter_intuitive": [
        r"反常识点",
        r"Counter-Intuitive",
        r"Core Counter-Intuitive",
    ],
    "mechanism_break": [
        r"机制断点",
        r"Mechanism Break",
        r"Core Mechanism",
    ],
    "risk_migration": [
        r"风险迁移",
        r"Risk Migration",
    ],
    "feedback_loop": [
        r"反馈环",
        r"Feedback Loop",
    ],
    "inertia_source": [
        r"历史惯性来源",
        r"Inertia Source",
    ],
    "non_transferable": [
        r"不可迁移点",
        r"Non-transferable",
    ],
    "reality_mapping": [
        r"现实映射",
        r"Reality Mapping",
    ],
    "trade_interface": [
        r"交易接口",
        r"Trade Interface",
        r"交易.*决策",
    ],
    "thesis": [
        r"一句话结论",
        r"One-line Thesis",
    ],
    "dna": [
        r"DNA",
        r"Institutional DNA",
        r"组织性格",
    ],
    "inertia": [
        r"Inertia",
        r"惯性",
    ],
    "timeline": [
        r"Timeline",
        r"塑形时间轴",
        r"Shaping Timeline",
    ],
    "irreplaceable": [
        r"不可替代",
        r"Irreplaceable",
    ],
    "system_function": [
        r"系统功能",
        r"System Function",
    ],
    "key_connections": [
        r"关键连接",
        r"Key Connections",
    ],
    "supporting_conditions": [
        r"托举条件",
        r"Supporting Conditions",
    ],
}

# Build compiled regex → semantic key lookup
_SECTION_PATTERNS: list[tuple[re.Pattern, str]] = []
for key, patterns in _SECTION_ALIASES.items():
    for p in patterns:
        _SECTION_PATTERNS.append((re.compile(rf"^##\s+.*{p}", re.MULTILINE | re.IGNORECASE), key))


def _parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and return (metadata, body)."""
    text = text.strip()
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        # Try line-by-line extraction for malformed YAML
        meta = {}
        for line in text[3:end].strip().split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("-") and not line.startswith("#"):
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if key and val:
                    # Handle list-like values
                    if val.startswith("[") and val.endswith("]"):
                        try:
                            meta[key] = yaml.safe_load(val)
                        except Exception:
                            meta[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",")]
                    elif key == "case_type":
                        meta[key] = val
                    elif key == "type":
                        meta[key] = val
                    elif key not in meta:
                        meta[key] = val
    body = text[end + 3:].strip()
    return meta, body


def _extract_section(body: str, semantic_key: str) -> str:
    """Extract text under a section matched by semantic key."""
    patterns = [p for p, k in _SECTION_PATTERNS if k == semantic_key]
    for pattern in patterns:
        match = pattern.search(body)
        if match:
            start = match.end()
            # Find next ## heading
            next_heading = re.search(r"^##\s", body[start:], re.MULTILINE)
            end = start + next_heading.start() if next_heading else len(body)
            return body[start:end].strip()
    return ""


def _clean_bracket_link(s: str) -> str:
    """Remove [[ ]] from Obsidian wikilinks."""
    return re.sub(r"\[\[([^\]]+)\]\]", r"\1", str(s))


def _extract_tags(meta: dict[str, Any]) -> list[str]:
    """Extract all tags from YAML, combining tags + mechanisms."""
    tags: list[str] = []
    for t in (meta.get("tags") or []):
        if isinstance(t, str):
            tags.append(t)
    return tags


def _extract_mechanisms(meta: dict[str, Any]) -> list[str]:
    """Extract mechanism names from YAML, combining mechanisms + related_mechanisms."""
    mechs: list[str] = []
    for key in ("mechanisms", "related_mechanisms"):
        for m in (meta.get(key) or []):
            clean = _clean_bracket_link(m).strip()
            if clean:
                mechs.append(clean)
    return list(dict.fromkeys(mechs))  # dedupe preserving order


def _build_narrative_summary(body: str) -> str:
    """Build narrative summary from key sections."""
    parts: list[str] = []
    for key in ("thesis", "counter_intuitive", "positioning"):
        text = _extract_section(body, key)
        if text:
            # Take first 200 chars
            parts.append(text[:200])
    return " | ".join(parts) if parts else ""


def _build_event_patterns(meta: dict[str, Any], body: str) -> list[str]:
    """Derive event_patterns from mechanisms and risk/feedback sections."""
    patterns: list[str] = []
    # From mechanisms
    for m in _extract_mechanisms(meta):
        slug = re.sub(r"[^a-z0-9]+", "_", m.lower()).strip("_")
        patterns.append(slug)
    # From risk migration text
    risk_text = _extract_section(body, "risk_migration")
    if "liquidity" in risk_text.lower() or "spiral" in risk_text.lower():
        patterns.append("liquidity_spiral")
    if "forced" in risk_text.lower() or "selling" in risk_text.lower():
        patterns.append("forced_selling")
    if "counterparty" in risk_text.lower():
        patterns.append("counterparty_risk")
    return list(dict.fromkeys(patterns))


# ── Public data classes ──────────────────────────────────────────────────

@dataclass
class CaseLabCase:
    """A parsed CaseLab case, ready for System consumption."""
    case_id: str
    case_name: str
    vintage: str = ""
    variable_vector: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    narrative_summary: str = ""
    event_patterns: list[str] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    # Extended fields from CaseLab (not in original CaseProfile)
    mechanisms: list[str] = field(default_factory=list)
    related_entities: list[str] = field(default_factory=list)
    related_mechanisms: list[str] = field(default_factory=list)
    case_type: str = ""
    main_entity: str = ""
    country: str = ""
    trade_relevance: str = ""
    non_transferable: str = ""
    feedback_loop: str = ""
    risk_migration: str = ""
    file_path: str = ""

    def to_case_profile_dict(self) -> dict[str, Any]:
        """Convert to CaseProfile-compatible dict for System's NLP pipeline."""
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "vintage": self.vintage,
            "variable_vector": self.variable_vector,
            "tags": self.tags,
            "narrative_summary": self.narrative_summary,
            "event_patterns": self.event_patterns,
            "source_documents": self.source_documents,
            "artifact_class": "historical_case_profile",
            "claim_ceiling": "historical_reference_only",
            "promotion_allowed": False,
        }


@dataclass
class CaseLabEntity:
    """A parsed CaseLab entity."""
    entity_id: str
    entity_name: str
    entity_type: str = ""
    variable_vector: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    positioning: str = ""
    dna_text: str = ""
    inertia_text: str = ""
    non_transferable: str = ""
    related_cases: list[str] = field(default_factory=list)
    related_mechanisms: list[str] = field(default_factory=list)
    country: str = ""
    city: str = ""
    sector: str = ""
    file_path: str = ""


# ── Main adapter ─────────────────────────────────────────────────────────

class CaseLabAdapter:
    """Reads a CaseLab Obsidian vault and returns structured profiles.

    Parameters
    ----------
    vault_path : str or Path
        Root of the CaseLab vault (e.g., /Users/a1/Paper).
    cases_dir : str
        Relative path to cases directory.
    entities_dir : str
        Relative path to entities directory.
    mechanisms_dir : str
        Relative path to mechanisms directory.
    """

    def __init__(
        self,
        vault_path: str | Path,
        *,
        cases_dir: str = "01_Cases",
        entities_dir: str = "02_Entities",
        mechanisms_dir: str = "03_Mechanisms",
    ) -> None:
        self.vault = Path(vault_path)
        self.cases_dir = self.vault / cases_dir
        self.entities_dir = self.vault / entities_dir
        self.mechanisms_dir = self.vault / mechanisms_dir

    # ── Cases ─────────────────────────────────────────────────────────

    def load_cases(self) -> list[CaseLabCase]:
        """Load all cases from 01_Cases/ and compute structural vectors."""
        cases: list[CaseLabCase] = []
        if not self.cases_dir.exists():
            return cases
        for md_file in sorted(self.cases_dir.rglob("*.md")):
            case = self._parse_case(md_file)
            if case:
                cases.append(case)
        return cases

    def _parse_case(self, path: Path) -> CaseLabCase | None:
        """Parse a single case markdown file."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        meta, body = _parse_yaml_frontmatter(text)
        if not meta and not body:
            return None

        # case_id: from YAML case_id field, or filename
        case_id = meta.get("case_id") or path.stem
        case_id = re.sub(r"[^a-z0-9_-]", "_", str(case_id).lower()).strip("_")

        # case_name
        case_name = meta.get("title") or meta.get("canonical_name") or path.stem

        # vintage: from date fields
        vintage = str(meta.get("date") or meta.get("created") or "")

        # mechanisms
        mechanisms = _extract_mechanisms(meta)

        # tags
        tags = _extract_tags(meta)

        # case_type
        case_type = str(meta.get("case_type") or meta.get("category") or "")

        # trade_relevance
        trade_relevance = str(meta.get("trade_relevance") or "")

        # main_entity
        main_entity = _clean_bracket_link(meta.get("main_entity", ""))

        # country
        country = _clean_bracket_link(meta.get("country", ""))

        # related entities
        related_entities = [_clean_bracket_link(e) for e in (meta.get("related_entities") or [])]

        # structural vector (auto-computed)
        variable_vector = compute_structural_vector(
            case_type=case_type,
            mechanisms=mechanisms,
            tags=tags,
            trade_relevance=trade_relevance,
            narrative_text=body[:2000],
        )

        # narrative summary
        narrative_summary = _build_narrative_summary(body)

        # event patterns
        event_patterns = _build_event_patterns(meta, body)

        # key sections
        non_transferable = _extract_section(body, "non_transferable")
        feedback_loop = _extract_section(body, "feedback_loop")
        risk_migration = _extract_section(body, "risk_migration")

        return CaseLabCase(
            case_id=case_id,
            case_name=str(case_name),
            vintage=vintage,
            variable_vector=variable_vector,
            tags=tags,
            narrative_summary=narrative_summary,
            event_patterns=event_patterns,
            mechanisms=mechanisms,
            related_entities=related_entities,
            related_mechanisms=mechanisms,
            case_type=case_type,
            main_entity=main_entity,
            country=country,
            trade_relevance=trade_relevance,
            non_transferable=non_transferable,
            feedback_loop=feedback_loop,
            risk_migration=risk_migration,
            file_path=str(path),
        )

    # ── Entities ──────────────────────────────────────────────────────

    def load_entities(self) -> list[CaseLabEntity]:
        """Load all entities from 02_Entities/ and compute structural vectors."""
        entities: list[CaseLabEntity] = []
        if not self.entities_dir.exists():
            return entities
        for md_file in sorted(self.entities_dir.rglob("*.md")):
            entity = self._parse_entity(md_file)
            if entity:
                entities.append(entity)
        return entities

    def _parse_entity(self, path: Path) -> CaseLabEntity | None:
        """Parse a single entity markdown file."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        meta, body = _parse_yaml_frontmatter(text)
        if not meta and not body:
            return None

        entity_id = meta.get("canonical_name") or path.stem
        entity_id = re.sub(r"[^a-z0-9_-]", "_", str(entity_id).lower()).strip("_")

        entity_name = str(meta.get("canonical_name") or path.stem)
        # Entity type: use entity_type field, fall back to type, infer from directory
        entity_type = str(meta.get("entity_type") or "")
        if not entity_type:
            raw_type = str(meta.get("type") or "").lower()
            if raw_type in ("city", "country", "state", "region", "special_region", "supranational"):
                entity_type = "geo"
            elif raw_type == "company":
                entity_type = "company"
            elif raw_type == "regulator":
                entity_type = "regulator"
            elif raw_type == "school":
                entity_type = "school"
            elif raw_type == "exchange":
                entity_type = "financial-infrastructure"
            else:
                # Infer from directory path
                path_str = str(path).lower()
                if "geo-political" in path_str or "/cities/" in path_str or "/countries/" in path_str or "/states-" in path_str:
                    entity_type = "geo"
                elif "/companies/" in path_str:
                    entity_type = "company"
                elif "/schools/" in path_str:
                    entity_type = "school"
                elif "/regulator" in path_str:
                    entity_type = "regulator"
                elif "/financial-infrastructure" in path_str:
                    entity_type = "financial-infrastructure"
        country = _clean_bracket_link(meta.get("country", ""))
        city = _clean_bracket_link(meta.get("city", ""))
        sector = str(meta.get("sector") or "")

        role = meta.get("role_in_system", "")

        related_mechanisms = [_clean_bracket_link(m) for m in (meta.get("related_mechanisms") or [])]
        related_cases = [_clean_bracket_link(c) for c in (meta.get("related_cases") or [])]
        tags = _extract_tags(meta)

        # structural vector
        variable_vector = compute_entity_structural_vector(
            entity_type=entity_type,
            role_in_system=role,
            sector=sector,
            related_mechanisms=related_mechanisms,
        )

        # key sections
        positioning = _extract_section(body, "positioning")
        dna_text = _extract_section(body, "dna")
        inertia_text = _extract_section(body, "inertia")
        non_transferable = _extract_section(body, "non_transferable")

        return CaseLabEntity(
            entity_id=entity_id,
            entity_name=entity_name,
            entity_type=entity_type,
            variable_vector=variable_vector,
            tags=tags,
            positioning=positioning,
            dna_text=dna_text,
            inertia_text=inertia_text,
            non_transferable=non_transferable,
            related_cases=related_cases,
            related_mechanisms=related_mechanisms,
            country=country,
            city=city,
            sector=sector,
            file_path=str(path),
        )

    # ── Mechanisms ────────────────────────────────────────────────────

    def load_mechanisms(self) -> list[dict[str, Any]]:
        """Load all mechanisms from 03_Mechanisms/."""
        mechanisms: list[dict[str, Any]] = []
        if not self.mechanisms_dir.exists():
            return mechanisms
        for md_file in sorted(self.mechanisms_dir.rglob("*.md")):
            mech = self._parse_mechanism(md_file)
            if mech:
                mechanisms.append(mech)
        return mechanisms

    def _parse_mechanism(self, path: Path) -> dict[str, Any] | None:
        """Parse a single mechanism markdown file."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        meta, body = _parse_yaml_frontmatter(text)
        if not meta and not body:
            return None

        name = meta.get("canonical_name") or path.stem
        related_cases = [_clean_bracket_link(c) for c in (meta.get("related_cases") or [])]
        related_entities = [_clean_bracket_link(e) for e in (meta.get("related_entities") or [])]
        related_variables = [_clean_bracket_link(v) for v in (meta.get("related_variables") or [])]

        return {
            "name": str(name),
            "mechanism_type": str(meta.get("mechanism_type") or ""),
            "tags": _extract_tags(meta),
            "related_cases": related_cases,
            "related_entities": related_entities,
            "related_variables": related_variables,
            "trade_relevance": str(meta.get("trade_relevance") or ""),
            "file_path": str(path),
        }

    # ── Export to System's case_library format ────────────────────────

    def export_cases_to_json(self, output_dir: str | Path) -> int:
        """Export all cases as JSON files compatible with System's CaseRegistry.

        Returns number of files written.
        """
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        count = 0
        for case in self.load_cases():
            out_path = output / f"{case.case_id}.json"
            out_path.write_text(
                __import__("json").dumps(case.to_case_profile_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            count += 1
        return count

    # ── Summary stats ────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return vault statistics."""
        cases = self.load_cases()
        entities = self.load_entities()
        mechanisms = self.load_mechanisms()
        return {
            "total_cases": len(cases),
            "total_entities": len(entities),
            "total_mechanisms": len(mechanisms),
            "cases_by_type": _count_by(cases, "case_type"),
            "entities_by_type": _count_by(entities, "entity_type"),
            "cases_with_vector": sum(1 for c in cases if c.variable_vector),
            "entities_with_vector": sum(1 for e in entities if e.variable_vector),
        }


def _count_by(items: list, attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = getattr(item, attr, "") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts
