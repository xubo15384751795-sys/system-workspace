"""Build an isolated workspace for hermetic CLI / current-output tests."""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CURRENT = REPO_ROOT / "tests" / "fixtures" / "current_chain"
MARKER = Path("governance") / "daily_pipeline_registry.yaml"
# Align copied artifact mtimes with fixture as_of so bundle atomicity checks
# (README mtime vs status.generated_at) pass on clean sandboxes.
FIXTURE_EPOCH = datetime(2026, 7, 26, tzinfo=timezone.utc).timestamp()

# Minimal governance/protocol trees needed for WorkspacePaths discovery and
# common CLI readers. Copied (not symlinked) so Windows CI stays portable.
_COPY_TREES = (
    "governance",
    "protocols",
)


def build_sandbox_workspace(target: Path) -> Path:
    """Create ``target`` as a System workspace rooted at ``target``.

    Seeds Output/current and Output/judgment from committed fixtures so
    ``system check/next/doctor`` work without an operator refresh.
    """
    target = target.resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for name in _COPY_TREES:
        src = REPO_ROOT / name
        dst = target / name
        shutil.copytree(
            src,
            dst,
            ignore=shutil.ignore_patterns(
                "archive",
                "routing_decisions",
                "__pycache__",
                "*.pyc",
            ),
        )

    if not (target / MARKER).is_file():
        raise RuntimeError(f"sandbox missing workspace marker: {target / MARKER}")

    current = target / "Output" / "current"
    judgment = target / "Output" / "judgment"
    current.mkdir(parents=True)
    judgment.mkdir(parents=True)

    for name in (
        "framework_output.json",
        "status.json",
        "quality_validation.json",
        "00_READ_ME_FIRST.md",
    ):
        shutil.copy2(FIXTURE_CURRENT / name, current / name)

    # Extra surfaces required by doctor / next / readme contract tests.
    # Note: Windows FS is case-insensitive — do not also write NEXT_ACTIONS.md.
    (current / "latest_run_id.txt").write_text("fixture_run_p0_2_wave2\n", encoding="utf-8")
    (current / "next_actions.md").write_text(
        "# Next Actions (fixture)\n\n- Keep monitoring ACTIVE_WATCH fixture channel.\n",
        encoding="utf-8",
    )

    judgment_src = FIXTURE_CURRENT / "judgment" / "latest.json"
    shutil.copy2(judgment_src, judgment / "latest.json")
    (judgment / "latest.md").write_text(
        "# Judgment (fixture)\n\nDecision: ACTIVE_WATCH\n",
        encoding="utf-8",
    )
    (judgment / "promotion_gate.json").write_text(
        '{\n  "status": "BLOCKED",\n  "blocked_gates": ["fixture_gate", "caselab"],\n'
        '  "forbidden_language": ["buy", "sell"]\n}\n',
        encoding="utf-8",
    )
    (judgment / "promotion_gate.md").write_text(
        "# Promotion Gate (fixture)\n\nstatus: BLOCKED\n",
        encoding="utf-8",
    )

    learning = target / "Output" / "system_learning" / "latest"
    learning.mkdir(parents=True)
    (learning / "governance_status.md").write_text(
        "# Governance Status (fixture)\n\nAll clear in sandbox.\n",
        encoding="utf-8",
    )

    for path in (*current.rglob("*"), *judgment.rglob("*")):
        if path.is_file():
            try:
                os.utime(path, (FIXTURE_EPOCH, FIXTURE_EPOCH))
            except OSError:
                pass

    return target
