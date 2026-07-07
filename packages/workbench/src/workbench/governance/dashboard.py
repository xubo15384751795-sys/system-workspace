from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .inventory import GovernanceArtifact, normalize_artifact


def render_governance_dashboard(artifacts: list[dict[str, Any] | GovernanceArtifact]) -> str:
    """Render a governance dashboard as Markdown with status counts and artifact inventory."""
    normalized = [
        artifact if isinstance(artifact, GovernanceArtifact) else normalize_artifact(artifact)
        for artifact in artifacts
    ]
    counts = Counter(item.status for item in normalized)
    lines = [
        "# Governance Dashboard",
        "",
        "## Status Counts",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status in ("ALIVE", "ALIVE_WEAK", "PASSIVE", "ZOMBIE", "DECORATIVE"):
        lines.append(f"| {status} | {counts.get(status, 0)} |")
    lines += [
        "",
        "## Artifact Inventory",
        "| Artifact | Type | Consumer | Impact | Status | Risk |",
        "|---|---|---|---|---|---|",
    ]
    for item in normalized:
        row = asdict(item)
        lines.append(
            f"| {row['artifact_id']} | {row['artifact_type']} | {row['consumer'] or ''} | "
            f"{row['decision_impact'] or ''} | {row['status']} | {row['risk_level']} |"
        )
    return "\n".join(lines) + "\n"


def write_governance_dashboard(path: str | Path, artifacts: list[dict[str, Any] | GovernanceArtifact]) -> str:
    """Render and write the governance dashboard to *path*. Returns the rendered text."""
    dashboard = render_governance_dashboard(artifacts)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dashboard, encoding="utf-8")
    return dashboard
