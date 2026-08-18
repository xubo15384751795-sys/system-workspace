# Structural Workbench

Evidence ingestion, NLP pipeline, ML signal layer, and shared contracts for structural-risk research.

## Layout

```
src/
  workbench/    # core API: contracts, freshness, evidence dashboard, NLP entry
  nlp/          # Structural NLP library — extraction, mapping, promotion (owns NLP-domain protocols)
  ml/           # ML signal writers, graph embeddings, regime detectors
  benchmarks/   # benchmark runners (market-feedback)
contracts/
  workbench/    # JSON schemas, prompt sections, templates, checklists
agents/
  harness/  # agent runner (tools, hooks, policies, workflows)
tests/          # pytest suite
Data/           # local data (gitignored)
```

## Independence & Protocol Interface

Workbench is a standalone tool. It communicates with other modules solely through file-based protocols defined in `contracts/`:

| Protocol | Schema | Description |
|----------|--------|-------------|
| Provider release | `data_provider_release.schema.json` | Data ingestion output format |
| Evidence panel | `evidence_panel.schema.json` | Evidence data format |
| Model run | `model_run.schema.json` | Model execution output |
| ML signal | `ml_signal.schema.json` | ML signal output |
| Report artifact | `report_artifact.schema.json` | Report output |

The Harvester, Learning Hub, Framework, and orchestration projects are
workspace members under `packages/`; they are independently installable but
share the root workspace lock and are not sibling submodules.

## Structural NLP

The `src/nlp/` package is the canonical owner of structural NLP work: ingestion,
chunking, extraction, variable mapping, candidate export, promotion, and
hard-case evaluation. NLP-domain protocol shapes (`nlp_event_card`,
`nlp_candidate_ledger`, `nlp_promotion_log`) are defined and validated here.

Root-level `protocols/nlp_*.schema.json` files are compatibility mirrors during
migration. Protocol consolidation into this library is planned next.

Workbench product Q&A (`nlp_query` / `nlp_answer`) lives in `src/workbench/nlp.py`
and uses cross-module schemas at the workspace `protocols/` layer.

## Quick start

```bash
uv sync --locked --all-packages
uv run --locked python -m pytest packages/workbench/tests -q
```
