from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from src.core.representation.graph_repr import StructuralGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopologySummary:
    name: str
    values: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class TopologySummaryBuilder(Protocol):
    def summarize(self, graph: StructuralGraph) -> TopologySummary:
        ...


@dataclass(frozen=True)
class NullTopologySummaryBuilder:
    name: str = "topology_stub"

    def summarize(self, graph: StructuralGraph) -> TopologySummary:
        return TopologySummary(
            name=self.name,
            values={},
            metadata={
                "status": "stub",
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "available_backends": available_tda_backends(),
                "todo": (
                    "TODO: prototype persistent homology summaries over structural state windows.",
                    "TODO: evaluate giotto-tda graph/time-series transformers against Core graph semantics.",
                ),
            },
        )


def available_tda_backends() -> tuple[str, ...]:
    available: list[str] = []
    try:
        import gudhi  # type: ignore  # noqa: F401

        available.append("gudhi")
    except ImportError:
        logger.debug("Gudhi topology backend is unavailable")
    try:
        import gtda  # type: ignore  # noqa: F401

        available.append("giotto-tda")
    except ImportError:
        logger.debug("giotto-tda topology backend is unavailable")
    return tuple(available)
