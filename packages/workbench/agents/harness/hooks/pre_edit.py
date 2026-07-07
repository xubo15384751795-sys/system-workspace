"""pre_edit — specialized pre-edit hook.

Delegates to hooks.pre_tool_use.pre_edit for core logic.
This module exists as a standalone entry point so that the governance
layer can reference it by name in hook chains.
"""

from hooks.pre_tool_use import pre_edit

__all__ = ["pre_edit"]
