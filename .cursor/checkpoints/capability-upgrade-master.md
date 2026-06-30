# Checkpoint: capability-upgrade-master

- mission: Full functional capability upgrade (P1 judgment inputs → P4 Workbench UX)
- decisions:
  - Wave 2 (2026-06-30): measurement_quality report; callable chain expansion
  - Wave 3 (2026-06-30): shadow_outcomes_90d, qlib bridge, experimental_validation in signal_card
  - claim_ceiling_lift fulfilled via existing `claim_ladder_policy.yaml` + `layer.py` tier wiring (no new governance file)
  - K/X quality: gate-validated against Harvester releases; enrich harvester quality_reports in Wave 2
  - Wave 4 (2026-06-30): system run STEP_ID, contributor_drill_down, agent_routing_authority.yaml
- open_threads:
  - CaseLab unit tests; NLP golden set E2E
- do_not_touch:
  - `deformation-framework/src/_legacy/data/` (sealed)
  - Sigma core proxy rules without claim_registry change
- next_agent_action:
  - Optional: CaseLab/NLP E2E; stage measurement_quality into Harvester release bundle

## Phase map

| Phase | Track | Exit criteria |
|-------|-------|---------------|
| P1 | Data authority + gates | cross_asset core_judgment_allowed; K/X in_progress→fulfilled; claim ladder tier≥2 in judgment |
| P2 | Pipeline + Hub memory | ≥15 callable steps; next_actions cites improvement_queue |
| P3 | Experimental promotion | ML walk-forward artifact; strategy_lab 90d outcomes file |
| P4 | Workbench UX | `sys run <step>`; evidence_grade contributor drill-down |
