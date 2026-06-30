# Checkpoint: capability-upgrade-master

- mission: Full functional capability upgrade (P1 judgment inputs → P4 Workbench UX)
- decisions:
  - Wave 1 (2026-06-30): governance cross_asset closure, `_data_paths.py`, harvester `--exports-root`, callable batch 1
  - claim_ceiling_lift fulfilled via existing `claim_ladder_policy.yaml` + `layer.py` tier wiring (no new governance file)
  - K/X quality: gate-validated against Harvester releases; enrich harvester quality_reports in Wave 2
- open_threads:
  - P1: K/X harvester quality sidecar metrics; merged_data consolidation
  - P2: callable main chain (11 steps); Learning Hub recurrence → next_actions
  - P3: ML walk-forward; Strategy Lab 90d shadow; Backtest/Qlib bridge
  - P4: Workbench step runner UI; evidence drill-down; agent routing authority
- do_not_touch:
  - `deformation-framework/src/_legacy/data/` (sealed)
  - Sigma core proxy rules without claim_registry change
- next_agent_action:
  - Wave 3: ML walk-forward; Strategy Lab 90d shadow; CaseLab/NLP E2E
  - Optional: stage measurement_quality into Harvester release bundle

## Phase map

| Phase | Track | Exit criteria |
|-------|-------|---------------|
| P1 | Data authority + gates | cross_asset core_judgment_allowed; K/X in_progress→fulfilled; claim ladder tier≥2 in judgment |
| P2 | Pipeline + Hub memory | ≥15 callable steps; next_actions cites improvement_queue |
| P3 | Experimental promotion | ML walk-forward artifact; strategy_lab 90d outcomes file |
| P4 | Workbench UX | `sys run <step>`; evidence_grade contributor drill-down |
