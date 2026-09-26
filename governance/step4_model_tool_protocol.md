# Step 4 — Model / Tool Protocol Convergence

Status: `COMPLETE_BOUNDED`

The first bounded slice is complete for the accepted default M/D path:

```text
explicit input capability
  → ModelHost
  → neutral_pressure_md
  → generic ModelResult
  → NeutralPressureStateAdapter
  → DecisionEvidence
  → existing judgment/publication compatibility projection
```

The M/D algorithm remains the causal-z-score/component-mean algorithm. The
plugin has no scheduler, secret, Dagster, publication, or production-authority
responsibility. Judgment reads `decision_evidence` first; the old M/D-shaped
fields are isolated in `judgment/model_evidence.py` as a compatibility reader.

Only `data_access` is abstracted in this slice because it is the capability
actually used by the accepted path. Historical windows, calendars, statistics,
calibration, simulation, and artifact storage remain concrete implementation
details until a second model demonstrates a real need for those ports.

This does not promote M/D beyond diagnostic authority and does not claim that
the legacy builder can be deleted. The remaining compatibility debt is listed
in `governance/step4_model_tool_protocol.yaml`.
