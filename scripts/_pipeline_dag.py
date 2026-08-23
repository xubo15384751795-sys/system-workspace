"""Compatibility import surface for the Orchestration pipeline DAG."""
from __future__ import annotations

from orchestration import pipeline_dag as _impl
from orchestration.pipeline_dag import *  # noqa: F401,F403

# Private compatibility names were imported by the legacy test/executor path.
_propagates_failure = _impl._propagates_failure
_edges = _impl._edges
