"""pre_finalize_release — release finalization gate.

Delegates to hooks.pre_tool_use.pre_finalize_release for core logic.
This module exists as a standalone entry point so that the governance
layer can reference it by name in hook chains.
"""

from hooks.pre_tool_use import pre_finalize_release

__all__ = ["pre_finalize_release"]
