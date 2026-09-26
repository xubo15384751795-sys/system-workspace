"""Explicit workspace path discovery.

Runtime code must not infer the repository root with ``parents[N]``.  A caller
may inject ``SYSTEM_WORKSPACE_ROOT``; local development falls back to walking
upward for the repository marker.  Installed applications therefore work from
any current directory while tests can inject an isolated workspace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_ENV = "SYSTEM_WORKSPACE_ROOT"
WORKSPACE_MARKER = Path("governance/daily_pipeline_registry.yaml")
DATA_ROOT_ENV = "SYSTEM_DATA_ROOT"
OUTPUT_ROOT_ENV = "SYSTEM_OUTPUT_ROOT"
GENERATION_ENV = "SYSTEM_GENERATION_DIR"
GENERATION_MODE_ENV = "SYSTEM_GENERATION_MODE"

# Cross-run mutable surfaces live under Output/state/ and are never scoped to
# a generation candidate.  Keep this set in sync with
# governance/output_routing_policy.yaml groups.state.
CROSS_RUN_STATE_SURFACES = frozenset({
    "alerts",
    "benchmarks",
    "caselab",
    "caselab_runtime",
    "claim_ladder",
    "evaluations",
    "feedback_samples",
    "health",
    "hmm_stability",
    "logs",
    "market_feedback",
    "ml_signals",
    "runtime",
    "runtime_events",
    "sandbox",
    "strategy_lab",
    "validation",
})


def generation_mode_enabled() -> bool:
    """Return whether the caller is on the post-migration generation path."""
    return os.environ.get(GENERATION_MODE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _state_relative(name: str) -> str | None:
    rel = str(name or "").strip("/")
    if not rel or rel == "state" or rel.startswith("state/"):
        return None
    head = rel.split("/", 1)[0]
    if head in CROSS_RUN_STATE_SURFACES:
        return rel
    return None


def output_surface(root: Path, name: str) -> Path:
    """Resolve an output surface through the active generation when present.

    Cross-run state surfaces always resolve under ``Output/state/<name>``,
    even when a generation transaction is active.  Production writers of
    generation-scoped surfaces must never infer a candidate path themselves.
    The generation transaction sets ``SYSTEM_GENERATION_DIR`` before importing
    writer modules; outside a transaction this preserves the compatibility
    surface for read-only tools and explicit emergency paths.
    """
    state_rel = _state_relative(name)
    configured_output = os.environ.get(OUTPUT_ROOT_ENV, "").strip()
    output_root = Path(configured_output).expanduser().resolve() if configured_output else root / "Output"
    if state_rel is not None:
        return output_root / "state" / state_rel
    generation = os.environ.get(GENERATION_ENV, "").strip()
    if generation:
        return Path(generation).expanduser().resolve() / name
    return output_root / name


def discover_workspace(start: Path | None = None) -> Path:
    override = os.environ.get(WORKSPACE_ENV)
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / WORKSPACE_MARKER).is_file():
            raise RuntimeError(f"{WORKSPACE_ENV} is not a System workspace: {root}")
        return root

    candidates = [Path(start or Path.cwd()).resolve(), Path(__file__).resolve().parent]
    seen: set[Path] = set()
    for candidate in candidates:
        for directory in (candidate, *candidate.parents):
            if directory in seen:
                continue
            seen.add(directory)
            if (directory / WORKSPACE_MARKER).is_file():
                return directory
    raise RuntimeError(
        f"Cannot locate System workspace; set {WORKSPACE_ENV} to the repository root"
    )


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    data_root_override: Path | None = None
    output_root_override: Path | None = None

    @classmethod
    def discover(cls, start: Path | None = None) -> "WorkspacePaths":
        return cls(discover_workspace(start))

    @property
    def governance(self) -> Path:
        return self.root / "governance"

    @property
    def output(self) -> Path:
        configured = self.output_root_override or os.environ.get(OUTPUT_ROOT_ENV, "").strip()
        return Path(configured).expanduser().resolve() if configured else self.root / "Output"

    @property
    def data(self) -> Path:
        configured = self.data_root_override or os.environ.get(DATA_ROOT_ENV, "").strip()
        return Path(configured).expanduser().resolve() if configured else self.root / "Data"

    @property
    def harvester_exports(self) -> Path:
        """Harvester evidence-release exports root (Phase 4.1).

        Canonical location is ``Data/harvester/exports``. The legacy
        ``packages/harvester/data`` path is an alias (see repo_layout_map.md);
        new code must use this property, not ``Path(__file__).parents[3]``.
        """
        return self.data / "harvester" / "exports"

    @property
    def pipeline_spec(self) -> Path:
        return self.governance / "daily_pipeline_registry.yaml"

    @property
    def current(self) -> Path:
        override = os.environ.get("CURRENT_OUTPUT_DIR")
        if override:
            return Path(override).resolve()
        if self.output_root_override or os.environ.get(OUTPUT_ROOT_ENV, "").strip():
            return self.output / "current"
        return output_surface(self.root, "current")

    def surface(self, name: str) -> Path:
        """Return a named output surface under the active generation."""
        if self.output_root_override or os.environ.get(OUTPUT_ROOT_ENV, "").strip():
            state_rel = _state_relative(name)
            if state_rel is not None:
                return self.output / "state" / state_rel
            generation = os.environ.get(GENERATION_ENV, "").strip()
            if generation:
                return Path(generation).expanduser().resolve() / name
            return self.output / name
        return output_surface(self.root, name)
