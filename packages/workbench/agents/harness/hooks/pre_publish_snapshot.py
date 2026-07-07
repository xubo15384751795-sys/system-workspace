"""pre_publish_snapshot — snapshot publishing gate.

Delegates to hooks.pre_tool_use.pre_publish_snapshot for core logic.
This module exists as a standalone entry point so that the governance
layer can reference it by name in hook chains.
"""

from hooks.pre_tool_use import pre_publish_snapshot

__all__ = ["pre_publish_snapshot"]
