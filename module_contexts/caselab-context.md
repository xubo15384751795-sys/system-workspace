# CaseLab Context Layer

Use this thread when the task mentions:

- context layer
- entity DNA
- regime context
- contextual meaning
- action interpretation
- context packet
- `caselab_context`
- premise interpreter

## Owns

- Symbolic context resolution from Paper knowledge
- Hybrid note retrieval (TF-IDF / Ollama dense) with 2-hop graph expansion
- Quality-aware rerank for historical analogies
- Context feedback log
- Trade idea context enrichment
- MCP server for AI clients (`caselab_context.mcp_server`)

## Primary locations

| Component | Path |
|---|---|
| Context runtime | `caselab_context/` |
| Feedback loop runtime | `caselab_runtime/` |
| Paper architecture | `/Users/a1/Paper/90_Admin/Context Layer Architecture.md` |
| Resolver rules | `/Users/a1/Paper/09_Models/System/Contextual Meaning Resolver.md` |
| Learning pipeline | `/Users/a1/Paper/data_pipeline/features/`, `learning/`, `embeddings/` |

## Read first

- `90_Admin/Context Layer Architecture.md` (Paper)
- `caselab_context/resolve_meaning.py`
- `caselab_context/retrieve_context.py`
- `90_Admin/System-Feedback-Loop.md` (Paper)

## CLI

```bash
cd /Users/a1/System
python3 -m caselab_context.index_paper
python3 -m caselab_context.build_embeddings --reindex
python3 -m caselab_context.resolve_meaning --actor "Goldman Sachs" --verb ipo --object public_market --json
python3 -m caselab_context.run_samples
python3 -m caselab_context.mcp_server
python3 -m caselab_context.enrich_agent_context --date YYYY-MM-DD
```

MCP primary tool: `query_world_model`. Config: `caselab_context/mcp.cursor.json`.

Python SDK:

```python
from caselab_context.world_model import query
response = query("Goldman Sachs", "ipo", "public_market")
# response.context_packet, response.regime_source, response.warnings, response.world_state
```

```bash
python3 -m caselab_runtime.feedback.collect_reviews
python3 -m caselab_runtime.policies.build_policy_from_paper
```

Learning layer (Paper):

```bash
cd /Users/a1/Paper
python3 data_pipeline/features/build_feature_matrix.py --demo
python3 data_pipeline/learning/train_baseline.py
python3 data_pipeline/learning/evaluate.py
python3 data_pipeline/learning/calibrate.py
python3 data_pipeline/embeddings/build_note_embeddings.py --reindex
```

## Boundaries

- Context Layer explains premises; it does not auto-trade.
- Vector retrieval finds similarity; resolver rules explain meaning.
- Human review remains required before `quality: core` promotion.

## Promises

- We explain premises and historical context without granting signal or trade authority.
- Retrieved similarity remains distinct from mechanism evidence and promotion.

## Relies On

- Paper promises worldview provenance and review state.
- Selectors promise inbox hypotheses cannot bypass CaseLab and evidence gates.
