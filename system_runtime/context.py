"""The single portable application runtime context.

Path discovery happens at the application boundary. Lower layers receive a
``RuntimeContext`` (or a narrower typed value from it) instead of guessing a
repository parent, reading a launchd plist, or depending on ambient
``PYTHONPATH``.
"""
from __future__ import annotations

import os
import platform
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Protocol

from .paths import WorkspacePaths
from .secrets import SecretProvider, default_secret_provider


class Clock(Protocol):
    """Clock dependency used by runtime code that must be deterministic."""

    def now(self) -> datetime:
        """Return an aware UTC timestamp."""


@dataclass(frozen=True)
class SystemClock:
    """Default wall clock for local/scheduled execution."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class SchedulerContext:
    """Scheduler-neutral trigger metadata."""

    trigger_kind: str = "manual"
    scheduler_kind: str = "operator"
    scheduler_id: str = "operator"
    schedule_id: str = ""
    trigger_id: str = ""

    @classmethod
    def from_environment(cls) -> "SchedulerContext":
        return cls(
            trigger_kind=os.environ.get("SYSTEM_TRIGGER_KIND", "manual").strip().lower()
            or "manual",
            scheduler_kind=os.environ.get("SYSTEM_SCHEDULER_KIND", "operator").strip().lower()
            or "operator",
            scheduler_id=os.environ.get("SYSTEM_SCHEDULER_ID", "operator").strip()
            or "operator",
            schedule_id=os.environ.get("SYSTEM_SCHEDULE_ID", "").strip(),
            trigger_id=os.environ.get("SYSTEM_TRIGGER_ID", "").strip(),
        )


@dataclass(frozen=True)
class HostContext:
    """Host identity without assuming macOS, launchd, or a repository path."""

    host_id: str
    platform: str

    @classmethod
    def from_environment(cls) -> "HostContext":
        host_id = os.environ.get("SYSTEM_HOST_ID", "").strip() or socket.gethostname()
        return cls(host_id=host_id or "unknown-host", platform=platform.system().lower())


@dataclass(frozen=True)
class ExecutionIdentity:
    """Run/release identity carried by every runtime evidence surface."""

    run_id: str = ""
    release_id: str = ""

    def with_run_id(self, run_id: str) -> "ExecutionIdentity":
        return replace(self, run_id=str(run_id))


_CURRENT_CONTEXT: ContextVar["RuntimeContext | None"] = ContextVar(
    "verity_runtime_context", default=None
)


@dataclass(frozen=True)
class RuntimeContext:
    """Portable runtime dependencies resolved once at the application edge."""

    workspace: Path
    data_root: Path
    output_root: Path
    external_roots: Mapping[str, Path] = field(default_factory=dict)
    secrets: SecretProvider = field(default_factory=default_secret_provider)
    scheduler: SchedulerContext = field(default_factory=SchedulerContext.from_environment)
    host: HostContext = field(default_factory=HostContext.from_environment)
    clock: Clock = field(default_factory=SystemClock)
    provider_config: Mapping[str, Any] = field(default_factory=dict)
    execution_identity: ExecutionIdentity = field(default_factory=ExecutionIdentity)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", Path(self.workspace).expanduser().resolve())
        object.__setattr__(self, "data_root", Path(self.data_root).expanduser().resolve())
        object.__setattr__(self, "output_root", Path(self.output_root).expanduser().resolve())
        object.__setattr__(
            self,
            "external_roots",
            MappingProxyType(
                {
                    str(key): Path(value).expanduser().resolve()
                    for key, value in self.external_roots.items()
                }
            ),
        )
        object.__setattr__(self, "provider_config", MappingProxyType(dict(self.provider_config)))

    @classmethod
    def discover(
        cls,
        root: Path | None = None,
        *,
        data_root: Path | None = None,
        output_root: Path | None = None,
        secrets: SecretProvider | None = None,
        scheduler: SchedulerContext | None = None,
        host: HostContext | None = None,
        clock: Clock | None = None,
        provider_config: Mapping[str, Any] | None = None,
        execution_identity: ExecutionIdentity | None = None,
    ) -> "RuntimeContext":
        active = _CURRENT_CONTEXT.get()
        if (
            active is not None
            and root is None
            and data_root is None
            and output_root is None
            and secrets is None
            and scheduler is None
            and host is None
            and clock is None
            and provider_config is None
            and execution_identity is None
        ):
            return active

        workspace = WorkspacePaths(root.expanduser().resolve()) if root else WorkspacePaths.discover()
        resolved_data = data_root or workspace.data
        resolved_output = output_root or workspace.output
        external_roots = {
            key: Path(value)
            for key, value in {
                "paper": os.environ.get("PAPER_ROOT", "").strip(),
                "horizon": os.environ.get("HORIZON_ROOT", "").strip(),
            }.items()
            if value
        }
        return cls(
            workspace=workspace.root,
            data_root=resolved_data,
            output_root=resolved_output,
            external_roots=external_roots,
            secrets=secrets or default_secret_provider(),
            scheduler=scheduler or SchedulerContext.from_environment(),
            host=host or HostContext.from_environment(),
            clock=clock or SystemClock(),
            provider_config=provider_config or {},
            execution_identity=execution_identity or ExecutionIdentity(
                release_id=os.environ.get("SYSTEM_RELEASE_ID", "").strip()
            ),
        )

    @classmethod
    def from_paths(cls, paths: WorkspacePaths, **kwargs: Any) -> "RuntimeContext":
        return cls.discover(
            paths.root,
            data_root=kwargs.pop("data_root", paths.data),
            output_root=kwargs.pop("output_root", paths.output),
            **kwargs,
        )

    @property
    def paths(self) -> WorkspacePaths:
        """Compatibility view for APIs that still accept ``WorkspacePaths``."""
        return WorkspacePaths(
            self.workspace,
            data_root_override=self.data_root,
            output_root_override=self.output_root,
        )

    @property
    def root(self) -> Path:
        """Compatibility alias for the resolved workspace root."""
        return self.workspace

    @property
    def current(self) -> Path:
        return self.paths.current

    def surface(self, name: str) -> Path:
        return self.paths.surface(name)

    def with_execution(self, *, run_id: str = "", release_id: str | None = None) -> "RuntimeContext":
        identity = replace(
            self.execution_identity,
            run_id=run_id or self.execution_identity.run_id,
            release_id=(
                self.execution_identity.release_id
                if release_id is None
                else str(release_id)
            ),
        )
        return replace(self, execution_identity=identity)

    def with_roots(
        self,
        *,
        data_root: Path | None = None,
        output_root: Path | None = None,
    ) -> "RuntimeContext":
        """Return the same runtime dependencies with explicit data/output roots."""
        return replace(
            self,
            data_root=data_root or self.data_root,
            output_root=output_root or self.output_root,
        )

    @contextmanager
    def activate(self) -> Iterator["RuntimeContext"]:
        token = _CURRENT_CONTEXT.set(self)
        try:
            yield self
        finally:
            _CURRENT_CONTEXT.reset(token)

    @classmethod
    def current_context(cls) -> "RuntimeContext":
        context = _CURRENT_CONTEXT.get()
        return context if context is not None else cls.discover()


__all__ = [
    "Clock",
    "ExecutionIdentity",
    "HostContext",
    "RuntimeContext",
    "SchedulerContext",
    "SystemClock",
]
