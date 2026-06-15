# Known Limitations

**Date:** 2026-06-03
**Source:** P3 Cleanup Sprint — TODO/FIXME scan

---

## Graph / Topology / TDA (Future Research)

These are planned research directions for the `core/representation/` and `core/metrics/` modules. They are NOT bugs or missing features — they are explicit future work items.

### topology_stub.py

- Prototype persistent homology summaries over structural state windows
- Evaluate giotto-tda graph/time-series transformers against Core graph semantics

### graph_repr.py

- Map operator traces and temporal transitions into multi-layer structural graphs
- Add path-aware centrality once the graph layer has stable semantics
- Support rolling graph snapshots for dynamic fragmentation and flow analysis

### graph_features.py

- Add temporal edge semantics before interpreting edge absence as true fragmentation
- Replace bottleneck proxy with path-sensitive flow constraints when graph semantics mature
- Learn redundancy groups from adjudication history rather than fixed tags

### persistence.py

- Extend persistence evidence to rolling topology summaries when TDA is activated
- Add persistence-of-graph-state once temporal graph builders are stable

---

## Status

All 11 TODOs are in the graph/topology/TDA research area. These modules are:
- **Not in active core path** — no replay, no SigmaVector, no framework_output depends on them
- **Not paper modules** — they have real code (ellipsized stubs), just not yet implemented
- **Research directions** — intended for future structural analysis enhancements

**No action needed now.** These will be addressed when the graph/TDA research thread is activated.
