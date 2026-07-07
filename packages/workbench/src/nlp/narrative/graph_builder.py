from __future__ import annotations

from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

from pydantic import BaseModel, Field

from nlp.extraction.schemas import ExtractedEntity, StructuralEventCard
from nlp.extraction.relation_extractor import ExtractedRelation

ROOT = _workspace_root()

STRUCTURAL_NODE_TYPES = [
    "institution",
    "regulator",
    "asset",
    "collateral",
    "policy_tool",
    "risk_event",
    "anchor",
    "liquidity_path",
    "market",
    "currency",
    "valuation_method",
    "narrative",
]


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str = "entity"
    variables: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    evidence_chunk_id: str = ""
    confidence: float = 0.5


class StructuralGraph(BaseModel):
    graph_id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0

    def model_post_init(self, _ctx):
        self.node_count = len(self.nodes)
        self.edge_count = len(self.edges)


def build_graph_from_entities(
    entities: list[ExtractedEntity],
    *,
    relations: list[ExtractedRelation] | None = None,
    graph_id: str = "entity_graph",
) -> StructuralGraph:
    """Build an entity-relationship graph from extracted entities and relations.

    Each entity becomes a node. Relations between entities become directed edges.
    """
    relations = relations or []
    nodes: list[GraphNode] = []
    node_ids: set[str] = set()

    for entity in entities:
        nid = entity.text.lower().replace(" ", "_")[:80]
        if nid in node_ids:
            continue
        node_ids.add(nid)
        nodes.append(
            GraphNode(
                id=nid,
                label=entity.text,
                node_type=entity.type,
                variables=list(entity.variable_hint),
                metadata={"chunk_id": entity.chunk_id},
            )
        )

    edges: list[GraphEdge] = []
    edge_ids: set[tuple[str, str, str]] = set()
    for rel in relations:
        sid = rel.source.lower().replace(" ", "_")[:80]
        tid = rel.target.lower().replace(" ", "_")[:80]
        key = (sid, tid, rel.relation)
        if key in edge_ids:
            continue
        if sid not in node_ids or tid not in node_ids:
            continue
        edge_ids.add(key)
        edges.append(
            GraphEdge(
                source=sid,
                target=tid,
                relation=rel.relation,
                evidence_chunk_id=rel.chunk_id,
                confidence=rel.confidence,
            )
        )

    return StructuralGraph(graph_id=graph_id, nodes=nodes, edges=edges)


def build_graph_from_event_cards(
    cards: list[StructuralEventCard],
    *,
    graph_id: str = "event_graph",
) -> StructuralGraph:
    """Build a graph from structural event cards.

    Events become nodes. Variable overlap creates weighted edges
    between events with shared structural signatures.
    """
    nodes: list[GraphNode] = []
    node_ids: set[str] = set()

    for card in cards:
        nid = card.event_id
        if nid in node_ids:
            continue
        node_ids.add(nid)
        populated_vars = [
            v for v in ("S", "A", "L", "V", "P", "tau")
            if card.variable_mapping.model_dump().get(v)
        ]
        nodes.append(
            GraphNode(
                id=nid,
                label=card.event_name,
                node_type="event",
                variables=populated_vars,
                metadata={
                    "status": card.status,
                    "confidence": card.confidence.get("variable_mapping", 0.0),
                },
            )
        )

    edges: list[GraphEdge] = []
    edge_ids: set[tuple[str, str, str]] = set()
    for i, card_a in enumerate(cards):
        for j, card_b in enumerate(cards):
            if j <= i:
                continue
            shared = _shared_variables(card_a, card_b)
            if len(shared) < 2:
                continue
            key = (card_a.event_id, card_b.event_id, "variable_overlap")
            if key in edge_ids:
                continue
            edge_ids.add(key)
            edges.append(
                GraphEdge(
                    source=card_a.event_id,
                    target=card_b.event_id,
                    relation="variable_overlap",
                    confidence=round(len(shared) / 6, 2),
                )
            )

    return StructuralGraph(graph_id=graph_id, nodes=nodes, edges=edges)


def build_institution_asset_risk_graph(
    entities: list[ExtractedEntity],
    relations: list[ExtractedRelation],
    *,
    graph_id: str = "institution_asset_risk",
) -> StructuralGraph:
    """Build a filtered graph showing only institution-asset-risk connections.

    This is the subgraph most relevant for S-A-L-V-P-tau analysis.
    """
    all_nodes = build_graph_from_entities(entities, relations=relations, graph_id=graph_id)

    institution_ids = {n.id for n in all_nodes.nodes if n.node_type in ("institution", "regulator")}
    asset_ids = {n.id for n in all_nodes.nodes if n.node_type in ("asset", "collateral", "liability")}
    risk_ids = {n.id for n in all_nodes.nodes if n.node_type in ("risk_event", "valuation_gap")}
    policy_ids = {n.id for n in all_nodes.nodes if n.node_type == "policy_tool"}
    relevant_ids = institution_ids | asset_ids | risk_ids | policy_ids

    filtered_nodes = [n for n in all_nodes.nodes if n.id in relevant_ids]
    filtered_edges = [
        e for e in all_nodes.edges
        if e.source in relevant_ids and e.target in relevant_ids
    ]

    return StructuralGraph(graph_id=graph_id, nodes=filtered_nodes, edges=filtered_edges)


def export_graph_mermaid(graph: StructuralGraph) -> str:
    """Export a StructuralGraph as a Mermaid flowchart diagram."""
    lines: list[str] = ["graph TD"]
    safe_id = lambda s: s.replace("-", "_").replace(" ", "_").replace(".", "_")

    for node in graph.nodes:
        shape = _node_shape(node.node_type)
        sid = safe_id(node.id)
        lines.append(f'    {sid}["{node.label}"]')

    for edge in graph.edges:
        ss = safe_id(edge.source)
        ts = safe_id(edge.target)
        label = edge.relation.replace("_", " ")
        lines.append(f'    {ss} -->|"{label}"| {ts}')

    return "\n".join(lines)


def export_graph_json(graph: StructuralGraph, out_path: Path | None = None) -> Path:
    target = out_path or (ROOT / "Output" / "nlp" / "graphs" / f"{graph.graph_id}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(graph.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def _shared_variables(a: StructuralEventCard, b: StructuralEventCard) -> list[str]:
    va = a.variable_mapping.model_dump()
    vb = b.variable_mapping.model_dump()
    return [
        v for v in ("S", "A", "L", "V", "P", "tau")
        if va.get(v) and vb.get(v)
    ]


def _node_shape(node_type: str) -> str:
    shapes = {
        "institution": "[( )]",
        "regulator": "[( )]",
        "asset": "[()]",
        "collateral": "[()]",
        "liability": "[()]",
        "policy_tool": "{{ }}",
        "risk_event": "> ]",
        "valuation_gap": "> ]",
        "event": "[[ ]]",
        "anchor": "(( ))",
        "liquidity_path": "> ]",
    }
    return shapes.get(node_type, "[ ]")
