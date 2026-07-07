from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable

from src.core.models import ProxyReading


@dataclass(frozen=True)
class StructuralNode:
    node_id: str
    value: float | None = None
    kind: str = "channel"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuralEdge:
    source: str
    target: str
    weight: float = 1.0
    edge_type: str = "association"
    directed: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class GraphBuilderHook(Protocol):
    def __call__(self, graph: "StructuralGraph") -> "StructuralGraph":
        ...


@dataclass
class StructuralGraph:
    nodes: list[StructuralNode] = field(default_factory=list)
    edges: list[StructuralEdge] = field(default_factory=list)
    feature_hooks: dict[str, Callable[["StructuralGraph"], Any]] = field(default_factory=dict)
    builder_hooks: tuple[GraphBuilderHook, ...] = ()

    def register_feature_hook(self, name: str, hook: Callable[["StructuralGraph"], Any]) -> None:
        self.feature_hooks[name] = hook

    def compute_feature(self, name: str) -> Any:
        hook = self.feature_hooks[name]
        return hook(self)

    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.nodes)

    def node_map(self) -> dict[str, StructuralNode]:
        return {node.node_id: node for node in self.nodes}

    def adjacency(self, include_reverse_for_directed: bool = True) -> dict[str, list[StructuralEdge]]:
        adjacent: dict[str, list[StructuralEdge]] = defaultdict(list)
        for node in self.nodes:
            adjacent[node.node_id] = []
        for edge in self.edges:
            adjacent[edge.source].append(edge)
            if include_reverse_for_directed or not edge.directed:
                adjacent[edge.target].append(edge)
        return dict(adjacent)

    def with_builder_hooks(self, hooks: Iterable[GraphBuilderHook]) -> "StructuralGraph":
        return StructuralGraph(
            nodes=list(self.nodes),
            edges=list(self.edges),
            feature_hooks=dict(self.feature_hooks),
            builder_hooks=tuple(hooks),
        )

    def apply_builder_hooks(self) -> "StructuralGraph":
        graph = self
        for hook in self.builder_hooks:
            graph = hook(graph)
        return graph


@runtime_checkable
class GraphBuilder(Protocol):
    def build(self, state: ProxyReading | Mapping[str, float]) -> StructuralGraph:
        ...


@dataclass(frozen=True)
class ChannelGraphBuilder:
    edges: tuple[StructuralEdge, ...] = ()
    hooks: tuple[GraphBuilderHook, ...] = ()

    def build(self, state: ProxyReading | Mapping[str, float]) -> StructuralGraph:
        channel_values = _coerce_channels(state)
        nodes = [StructuralNode(node_id=channel, value=value) for channel, value in channel_values.items()]
        graph = StructuralGraph(nodes=nodes, edges=list(self.edges), builder_hooks=self.hooks)
        return graph.apply_builder_hooks()


def build_graph(
    state: ProxyReading | Mapping[str, float],
    edges: Iterable[StructuralEdge] | None = None,
    hooks: Iterable[GraphBuilderHook] | None = None,
) -> StructuralGraph:
    builder = ChannelGraphBuilder(edges=tuple(edges or ()), hooks=tuple(hooks or ()))
    return builder.build(state)


def connected_components(graph: StructuralGraph) -> tuple[tuple[str, ...], ...]:
    adjacency = graph.adjacency(include_reverse_for_directed=True)
    visited: set[str] = set()
    components: list[tuple[str, ...]] = []
    for node_id in graph.node_ids():
        if node_id in visited:
            continue
        stack = [node_id]
        members: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            members.append(current)
            for edge in adjacency.get(current, []):
                neighbor = edge.target if edge.source == current else edge.source
                if neighbor not in visited:
                    stack.append(neighbor)
        components.append(tuple(sorted(members)))
    return tuple(components)


def degree_summary(graph: StructuralGraph) -> dict[str, float]:
    summary = {node_id: 0.0 for node_id in graph.node_ids()}
    for edge in graph.edges:
        weight = abs(float(edge.weight))
        summary[edge.source] = summary.get(edge.source, 0.0) + weight
        summary[edge.target] = summary.get(edge.target, 0.0) + weight
    return summary


def graph_todo_stub() -> dict[str, str]:
    return {
        "advanced_builder": "TODO: map operator traces and temporal transitions into multi-layer structural graphs.",
        "centrality": "TODO: add path-aware centrality once the graph layer has stable semantics.",
        "temporal_graph": "TODO: support rolling graph snapshots for dynamic fragmentation and flow analysis.",
    }


def to_networkx(graph: StructuralGraph):
    """
    Convert the lightweight Core graph into a NetworkX graph when available.

    The Core dataclass graph remains the canonical internal representation; the
    NetworkX object is an optional interoperability view for feature work.
    """

    try:
        import networkx as nx  # type: ignore
    except Exception:
        return None

    nx_graph = nx.DiGraph() if any(edge.directed for edge in graph.edges) else nx.Graph()
    for node in graph.nodes:
        nx_graph.add_node(node.node_id, value=node.value, kind=node.kind, **dict(node.metadata))
    for edge in graph.edges:
        nx_graph.add_edge(
            edge.source,
            edge.target,
            weight=float(edge.weight),
            edge_type=edge.edge_type,
            directed=bool(edge.directed),
            **dict(edge.metadata),
        )
    return nx_graph


def _coerce_channels(state: ProxyReading | Mapping[str, float]) -> dict[str, float]:
    if isinstance(state, Mapping):
        source = state
    else:
        source = {
            "M": state.M,
            "D": state.D,
            "K": state.K,
            "X": state.X,
        }
    return {channel: _finite_or_zero(source.get(channel, 0.0)) for channel in ("M", "D", "K", "X")}


def _finite_or_zero(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0
