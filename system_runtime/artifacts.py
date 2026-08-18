"""Atomic artifact writer for authoritative and candidate outputs."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .events import EventEnvelope, JsonlEventStore
from .paths import WorkspacePaths

logger = logging.getLogger(__name__)


class ArtifactBoundaryError(RuntimeError):
    pass


class ArtifactStore:
    """The only new-code boundary allowed to mutate Output artifacts."""

    def __init__(self, paths: WorkspacePaths | None = None):
        self.paths = paths or WorkspacePaths.discover()

    def resolve_output(self, relative: str | Path) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ArtifactBoundaryError(f"output path must be relative: {relative}")
        resolved = (self.paths.output / relative_path).resolve()
        if self.paths.output.resolve() not in resolved.parents:
            raise ArtifactBoundaryError(f"output path escapes Output/: {relative}")
        return resolved

    def write_json(self, relative: str | Path, payload: Mapping[str, Any]) -> Path:
        target = self.resolve_output(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(dict(payload), handle, indent=2, ensure_ascii=False, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                logger.debug("Temporary artifact file already absent during cleanup: %s", temporary)
            raise
        return target

    def append_event(self, relative: str | Path, event: EventEnvelope) -> Path:
        target = self.resolve_output(relative)
        JsonlEventStore(target).append(event)
        return target
