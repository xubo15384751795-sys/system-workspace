"""Runtime context: paths, config, and environment injection.

Replaces scattered hardcoded `/Users/a1/System/...` strings with a single
injectable RuntimePaths dataclass.  Every module that needs to read or write
files receives a RuntimePaths (or the full RuntimeContext) via its
constructor — never by importing a module-level constant.

Design principles:
  - Anchor:  RuntimePaths is the single root anchor for all file I/O.
  - Isolation: tests / CI / agent sandboxes inject their own paths.
  - Immutability: frozen dataclasses prevent accidental mutation mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


# ── Runtime Paths ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuntimePaths:
    """Single source of truth for every directory the system touches.

    All fields are absolute paths.  Callers must not append to them with
    string concatenation — use the provided factory methods or the
    `Path / "subdir"` operator.
    """

    project_root: Path
    data_root: Path
    output_root: Path
    cache_root: Path
    run_root: Path
    logs_root: Path
    harvester_root: Path
    lab_root: Path
    snapshot_dir: Path
    fred_cache_dir: Path

    # ── Factory methods ──────────────────────────────────────────────────

    @classmethod
    def from_project_root(cls, project_root: str | Path) -> "RuntimePaths":
        """Build paths from a project root (the directory containing Data/, Output/, etc.)."""
        root = Path(project_root).expanduser().resolve()
        cwd = Path.cwd().resolve()
        data_root = root / "Data"
        if root == cwd.parent and (cwd / "pyproject.toml").is_file():
            data_root = cwd / ".cache" / "data"
        elif data_root.is_symlink():
            data_root = root / "data"
        if data_root.is_symlink():
            data_root = root / ".cache" / "data"
        return cls(
            project_root=root,
            data_root=data_root,
            output_root=root / "Output",
            cache_root=root / ".cache",
            run_root=root / "Output" / "deformation_runs",
            logs_root=root / "Output" / "logs",
            harvester_root=data_root / "harvester",
            lab_root=data_root / "structural_lab",
            snapshot_dir=data_root / "structural_lab" / "snapshots",
            fred_cache_dir=data_root / "structural_lab" / "runtime" / "fred_cache",
        )

    @classmethod
    def discover(cls) -> "RuntimePaths":
        """Auto-discover project root by walking up from this file.

        The project root is identified by the presence of marker files
        (ROUTING_CONSTITUTION.md, FRAMEWORK_CONTRACT.md, WORKBENCH_SPEC.md).
        Falls back to Path.cwd() if discovery fails.
        """
        markers = ("ROUTING_CONSTITUTION.md", "FRAMEWORK_CONTRACT.md", "WORKBENCH_SPEC.md")
        candidate = Path(__file__).resolve().parents[2]
        for _ in range(6):
            if any((candidate / m).is_file() for m in markers):
                return cls.from_project_root(candidate)
            candidate = candidate.parent
        return cls.from_project_root(Path.cwd())

    @classmethod
    def for_test(cls, tmp_path: str | Path) -> "RuntimePaths":
        """Build paths rooted at a temporary directory (for tests)."""
        root = Path(tmp_path).resolve()
        return cls(
            project_root=root,
            data_root=root / "Data",
            output_root=root / "Output",
            cache_root=root / ".cache",
            run_root=root / "Output" / "deformation_runs",
            logs_root=root / "Output" / "logs",
            harvester_root=root / "Data" / "harvester",
            lab_root=root / "Data" / "structural_lab",
            snapshot_dir=root / "Data" / "structural_lab" / "snapshots",
            fred_cache_dir=root / "Data" / "structural_lab" / "runtime" / "fred_cache",
        )

    # ── Derived paths (computed on demand, not stored) ───────────────────

    @property
    def event_log_path(self) -> Path:
        return self.logs_root / "event_log.jsonl"

    @property
    def text_log_path(self) -> Path:
        return self.logs_root / "text_log.jsonl"

    @property
    def snapshot_store_path(self) -> Path:
        return self.lab_root / "runtime" / "system.duckdb"

    @property
    def processed_dir(self) -> Path:
        return self.lab_root / "processed"

    def ensure_dirs(self) -> None:
        """Create all directories that must exist before a run."""
        for d in [
            self.output_root,
            self.cache_root,
            self.run_root,
            self.logs_root,
            self.snapshot_dir,
            self.fred_cache_dir,
            self.processed_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


# ── Runtime Config ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunMode:
    """Describes the execution environment for the current run."""

    name: str  # "local", "test", "ci", "agent_sandbox", "replay", "experiment"
    use_mock: bool = False
    ml_enabled: bool = False
    export_image: bool = False
    image_width: int = 1400

    @classmethod
    def local(cls) -> "RunMode":
        return cls(name="local", use_mock=False, ml_enabled=False, export_image=True)

    @classmethod
    def test(cls) -> "RunMode":
        return cls(name="test", use_mock=True, ml_enabled=False, export_image=False)

    @classmethod
    def replay(cls) -> "RunMode":
        return cls(name="replay", use_mock=False, ml_enabled=False, export_image=True)

    @classmethod
    def agent_sandbox(cls) -> "RunMode":
        return cls(name="agent_sandbox", use_mock=True, ml_enabled=False, export_image=False)


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable configuration snapshot for a single run.

    Built from the raw config dict at assembly time.  Every subsystem
    receives this (or a subset) rather than reaching into a mutable dict.
    """

    run_date: str | None = None
    run_type: str = "WEEKLY"
    mock_seed: int = 42
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    proxy_weights: Mapping[str, Any] = field(default_factory=dict)
    mechanism_config: Mapping[str, Any] = field(default_factory=dict)
    operator_config: Mapping[str, Any] = field(default_factory=dict)
    evidence_config: Mapping[str, Any] = field(default_factory=dict)
    output_config: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw_config(
        cls, raw: Mapping[str, Any], run_date: str | None = None, run_type: str | None = None
    ) -> "RuntimeConfig":
        from src.core.calibration import build_proxy_weights, build_thresholds

        thresholds = build_thresholds(raw)
        proxy_weights = build_proxy_weights(raw)
        return cls(
            run_date=run_date,
            run_type=run_type or str(raw.get("run_type", "WEEKLY")),
            mock_seed=int(raw.get("mock_seed", 42)),
            thresholds={
                "sigma": thresholds.sigma,
                "dof_collapse": thresholds.dof_collapse,
                "curvature_spike": thresholds.curvature_spike,
                "forced_realization": thresholds.forced_realization,
                "joint_hitting_enabled": thresholds.joint_hitting_enabled,
            },
            proxy_weights={
                "M": proxy_weights.M,
                "D": proxy_weights.D,
                "K": proxy_weights.K,
                "X": proxy_weights.X,
            },
            mechanism_config=dict(raw.get("mechanisms", {})),
            operator_config=dict(raw.get("operators", {})),
            evidence_config=dict(raw.get("evidence", {})),
            output_config=dict(raw.get("output", {})),
        )


# ── Runtime Context (the top-level injectable) ───────────────────────────────

@dataclass(frozen=True)
class RuntimeContext:
    """All runtime state injected into the system at assembly time.

    This is the single object passed through the system.  No module
    should bypass it to read globals, env vars, or config files.
    """

    paths: RuntimePaths
    config: RuntimeConfig
    mode: RunMode

    @classmethod
    def local(cls, project_root: str | Path | None = None) -> "RuntimeContext":
        root = Path(project_root) if project_root else RuntimePaths.discover().project_root
        return cls(
            paths=RuntimePaths.from_project_root(root),
            config=RuntimeConfig(),
            mode=RunMode.local(),
        )

    @classmethod
    def test(cls, tmp_path: str | Path) -> "RuntimeContext":
        return cls(
            paths=RuntimePaths.for_test(tmp_path),
            config=RuntimeConfig(),
            mode=RunMode.test(),
        )

    @classmethod
    def from_raw_config(
        cls,
        raw: Mapping[str, Any],
        *,
        project_root: str | Path | None = None,
        run_date: str | None = None,
        run_type: str | None = None,
        mode: RunMode | None = None,
    ) -> "RuntimeContext":
        root = Path(project_root) if project_root else RuntimePaths.discover().project_root
        return cls(
            paths=RuntimePaths.from_project_root(root),
            config=RuntimeConfig.from_raw_config(raw, run_date=run_date, run_type=run_type),
            mode=mode or RunMode.local(),
        )
