from __future__ import annotations

from dataclasses import dataclass

from src.runtime.system_api import StructuralSystemAPI


@dataclass
class TerminalService(StructuralSystemAPI):
    """Backward-compatible terminal wrapper over the runtime application API."""
    pass
