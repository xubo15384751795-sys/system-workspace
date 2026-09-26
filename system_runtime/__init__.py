"""Application infrastructure for the System workspace.

This package is the stable import boundary for orchestration, pipeline
compilation, artifact publication, and event storage.  Domain packages remain
independently installable; ``system_runtime`` composes them without reaching
into their source directories.
"""

from .context import (
    ExecutionIdentity,
    HostContext,
    RuntimeContext,
    SchedulerContext,
)
from .paths import WorkspacePaths, discover_workspace
from .secrets import SecretProvider

__all__ = [
    "ExecutionIdentity",
    "HostContext",
    "RuntimeContext",
    "SchedulerContext",
    "SecretProvider",
    "WorkspacePaths",
    "discover_workspace",
]
