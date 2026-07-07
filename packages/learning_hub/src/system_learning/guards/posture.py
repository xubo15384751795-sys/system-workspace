"""Research posture engine — the promotion-path half of the Learning Hub.

Low confidence limits the claim level, it does not cancel the research action.
This renders the registry's graded postures into a digest: for each entity,
what we can say, what to watch, what to upgrade, what is forbidden — plus an
overall daily posture derived from the highest-priority live action.

Guards block; posture promotes. Both read the same registry.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .registry import DEFAULT_REGISTRY_RELPATH, Registry, load_registry

POSTURE_DIR_RELPATH = "Output/system_learning/research_posture"


@dataclass(frozen=True)
class PostureEntry:
    entity: str
    kind: str
    status: str
    level: str
    action_type: str
    can_say: str
    watch: list[str]
    upgrade_path: list[str]
    forbidden: list[str]


@dataclass
class ResearchPostureDigest:
    generated_at: str
    overall_posture: str
    overall_reason: str
    entries: list[PostureEntry] = field(default_factory=list)

    def by_action(self, action_type: str) -> list[PostureEntry]:
        return [e for e in self.entries if e.action_type == action_type]


def build_posture_digest(registry: Registry, now: datetime | None = None) -> ResearchPostureDigest:
    now = now or datetime.now(UTC)
    entries: list[PostureEntry] = []
    for e in registry.with_posture():
        p = e.posture
        entries.append(
            PostureEntry(
                entity=e.name,
                kind=e.kind,
                status=e.status,
                level=p.level,
                action_type=p.action_type,
                can_say=p.can_say,
                watch=list(p.watch),
                upgrade_path=list(p.upgrade_path),
                forbidden=list(p.forbidden),
            )
        )

    overall, reason = _derive_overall(entries, registry.posture_priority)
    return ResearchPostureDigest(
        generated_at=now.isoformat(),
        overall_posture=overall,
        overall_reason=reason,
        entries=entries,
    )


def _derive_overall(entries: list[PostureEntry], priority: tuple[str, ...]) -> tuple[str, str]:
    """Overall posture = highest-priority live action present (BLOCKED excluded)."""
    for action in priority:
        matched = [e for e in entries if e.action_type == action]
        if matched:
            reason = "; ".join(f"{m.entity} ({m.status})" for m in matched[:2])
            return action, reason
    return "IGNORE", "no live research action in registry"


def write_posture(digest: ResearchPostureDigest, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "research_posture.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at": digest.generated_at,
                "overall_posture": digest.overall_posture,
                "overall_reason": digest.overall_reason,
                "entries": [asdict(e) for e in digest.entries],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        f"# Research Posture — {digest.generated_at[:10]}",
        "",
        f"**Overall posture:** {digest.overall_posture}",
        f"**Reason:** {digest.overall_reason}",
        "",
        "_Confidence-aware but action-oriented: low confidence limits the claim "
        "level, not the research action._",
        "",
    ]

    actions_seen: list[str] = []
    for e in digest.entries:
        if e.action_type not in actions_seen:
            actions_seen.append(e.action_type)

    # Readable ordering: live actions first, BLOCKED/IGNORE last.
    def _rank(a: str) -> int:
        return {"ACTIVE_WATCH": 0, "ROBUSTNESS_TEST": 1, "DATA_REPAIR": 2,
                "QUIET_WATCH": 3, "IGNORE": 4, "BLOCKED": 5}.get(a, 9)

    for action in sorted(actions_seen, key=_rank):
        lines.append(f"## {action}")
        lines.append("")
        for e in digest.by_action(action):
            lines.append(f"### {e.entity}  ·  {e.level}  ·  {e.status}")
            if e.can_say:
                lines.append(f"- **Can say:** {e.can_say}")
            if e.watch:
                lines.append(f"- **Watch:** {', '.join(e.watch)}")
            if e.upgrade_path:
                lines.append(f"- **Upgrade path:** {', '.join(e.upgrade_path)}")
            if e.forbidden:
                lines.append(f"- **Forbidden:** {', '.join(e.forbidden)}")
            lines.append("")

    md_path = out_dir / "RESEARCH_POSTURE.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def run_research_posture(
    system_root: Path,
    *,
    registry_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[ResearchPostureDigest, dict[str, Path]]:
    system_root = Path(system_root)
    reg_path = registry_path or (system_root / DEFAULT_REGISTRY_RELPATH)
    registry = load_registry(reg_path)
    digest = build_posture_digest(registry, now=now)
    paths = write_posture(digest, system_root / POSTURE_DIR_RELPATH)
    return digest, paths
