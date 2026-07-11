"""MCP server exposing CaseLab Context Layer to AI clients."""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from caselab_context.build_embeddings import build_from_index, save_embeddings
from caselab_context.index_paper import INDEX_PATH, build_index, load_index, write_index
from caselab_context.load_context import (
    default_regime,
    load_current_regime,
    load_entity_dna,
)
from caselab_context.regime_from_indicators import infer_regime_from_indicators
from caselab_context.resolve_meaning import build_context_packet
from caselab_context.retrieve_context import EMBEDDINGS_PATH, retrieve_similar_reranked
from caselab_context.world_model import query as world_model_query

mcp = FastMCP(
    "caselab-context",
    instructions=(
        "CaseLab Context Layer: resolve actor+action+regime into contextual meaning packets "
        "and retrieve similar cases/mechanisms from the Paper world model."
    ),
)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def resolve_context(
    actor: str,
    verb: str,
    action_object: str,
    liquidity: str = "",
    rates: str = "",
    credit: str = "",
    regulation: str = "",
    market_mood: str = "",
    technology_cycle: str = "",
    use_indicator_regime: bool = False,
    min_quality: str = "",
) -> str:
    """Resolve contextual meaning for an actor action under the current or overridden regime."""
    regime_override: dict[str, str] | None = None
    overrides = {
        "liquidity": liquidity,
        "rates": rates,
        "credit": credit,
        "regulation": regulation,
        "market_mood": market_mood,
        "technology_cycle": technology_cycle,
    }
    if any(overrides.values()):
        regime_override = default_regime()
        for key, value in overrides.items():
            if value:
                regime_override[key] = value
    packet = build_context_packet(
        actor,
        verb,
        action_object,
        regime=regime_override,
        use_indicator_regime=use_indicator_regime and regime_override is None,
        min_quality=min_quality or None,
    )
    return _json(packet)


@mcp.tool()
def query_world_model(
    actor: str,
    verb: str,
    action_object: str,
    use_indicator_regime: bool = True,
    min_quality: str = "useful",
    evaluate_state: bool = True,
) -> str:
    """Primary world-model entrypoint: context packet + regime evidence + world_state + warnings."""
    response = world_model_query(
        actor,
        verb,
        action_object,
        use_indicator_regime=use_indicator_regime,
        min_quality=min_quality,
        evaluate_state=evaluate_state,
    )
    return _json(response.to_dict())


@mcp.tool()
def evaluate_world_state(machine_id: str = "") -> str:
    """Evaluate executable state machines (e.g. credit_cycle) from latest indicators."""
    from caselab_context.state_machine_runtime import evaluate_world_state as run_eval

    ids = [machine_id] if machine_id else None
    return _json(run_eval(machine_ids=ids))


@mcp.tool()
def get_indicator_regime() -> str:
    """Infer regime axes from latest FRED-processed indicators in Paper data_pipeline."""
    return _json(infer_regime_from_indicators())


@mcp.tool()
def search_similar_notes(
    query: str,
    top_k: int = 5,
    actor: str = "",
    verb: str = "",
    action_object: str = "",
    min_quality: str = "",
) -> str:
    """Search Paper notes with hybrid retrieval, 2-hop graph expansion, and quality-aware rerank."""
    results = retrieve_similar_reranked(
        query,
        top_k=top_k,
        actor=actor,
        verb=verb,
        obj=action_object,
        min_quality=min_quality or None,
    )
    return _json({"query": query, "results": results})


@mcp.tool()
def get_entity_dna(actor: str) -> str:
    """Load Entity DNA behavioral defaults for an actor from Paper."""
    return _json(load_entity_dna(actor))


@mcp.tool()
def get_current_regime() -> str:
    """Load the latest Regime Context from Paper, or defaults if none is published."""
    regime = load_current_regime() or default_regime()
    return _json({"regime": regime})


@mcp.tool()
def rebuild_world_model_index(reindex: bool = True, backend: str = "auto") -> str:
    """Rebuild Paper index and embeddings used by context retrieval."""
    records = build_index() if reindex or not INDEX_PATH.exists() else load_index()
    if reindex:
        write_index(records)
    payload = build_from_index(records, backend=backend)
    save_embeddings(EMBEDDINGS_PATH, payload)
    return _json(
        {
            "count": len(records),
            "backend": payload.get("backend"),
            "embed_model": payload.get("embed_model"),
            "graph_edges": len((payload.get("graph") or {}).get("edges") or []),
            "index_path": str(INDEX_PATH),
            "embeddings_path": str(EMBEDDINGS_PATH),
        }
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
