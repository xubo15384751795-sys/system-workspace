from __future__ import annotations

from pathlib import Path
from workbench.paths import workspace_root as _workspace_root

from nlp.extraction.schemas import StructuralEventCard


ROOT = _workspace_root()
OUTPUT_NLP = ROOT / "Output" / "nlp"


def write_extraction_report(
    card: StructuralEventCard,
    *,
    validation: dict | None = None,
    out_dir: Path | None = None,
) -> Path:
    target_dir = out_dir or OUTPUT_NLP / "extraction_reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{card.event_id}.md"

    lines = [
        f"# {card.event_name}",
        "",
        f"- Event ID: `{card.event_id}`",
        f"- Status: `{card.status}`",
        "- Admission: candidate only; not canonical evidence.",
        "",
        "## Evidence Quotes",
    ]
    lines.extend(f"- {quote}" for quote in card.evidence_quotes)
    lines.extend(["", "## Variable Mapping"])
    for variable, values in card.variable_mapping.model_dump().items():
        if values:
            lines.append(f"- `{variable}`: {', '.join(values)}")
    if validation is not None:
        lines.extend(["", "## Validation", f"- Valid: `{validation.get('valid')}`"])
        for error in validation.get("errors", []):
            lines.append(f"- Error: {error}")
        for warning in validation.get("warnings", []):
            lines.append(f"- Warning: {warning}")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
