"""Application infrastructure for the System workspace.

This package is the stable import boundary for orchestration, pipeline
compilation, artifact publication, and event storage.  Domain packages remain
independently installable; ``system_runtime`` composes them without reaching
into their source directories.
"""

from .paths import WorkspacePaths, discover_workspace

__all__ = ["WorkspacePaths", "discover_workspace"]
