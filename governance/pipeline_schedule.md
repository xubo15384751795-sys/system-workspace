# Pipeline Schedule — Daily / Weekly / On-Demand

> Updated 2026-07-11b. Shadow card + evaluate_pending restored to daily; velocity gate recorded on signal card / ledger.
> Authority: `governance/daily_run_sequence.yaml` (order + schedule); registry metadata in `daily_pipeline_registry.yaml`.

## Daily (29 steps) — Signal-blocking, every run

These steps form the core signal chain. If any fails, the same-day judgment or trade path is affected.

| # | Step | Purpose |
|---|------|---------|
| 1 | harvester | Data acquisition |
| 2 | etf_refresh | ETF panel refresh (Harvester release) |
| 3 | paper_sync | Paper world model sync |
| 4 | caselab_index | CaseLab index update |
| 5 | structural_replay | M/D/K/X structural measurement |
| 6 | bridge | Bridge replay → current |
| 7 | quality_validation | Data quality checks |
| 8 | regime_detection | HMM regime detection |
| 9 | archive_hmm_calibration_snapshot | Dated HMM snapshot for calibration history |
| 10 | k_measurement_gate | K measurement gate |
| 11 | x_measurement_gate | X measurement gate |
| 12 | caselab_signal | CaseLab daily signal |
| 13 | judgment_layer | Judgment card generation |
| 14 | judgment_promotion_gate | Promotion gate |
| 15 | trade_decision | Trade decision |
| 16 | risk_gate | Risk gate |
| 17 | record_trade_decision | Record to ledger (incl. velocity_gate_state) |
| 18 | signal_card | Signal card output (incl. Velocity Gate section) |
| 19 | signal_consensus | Signal consensus |
| 20 | market_feedback | Market feedback diagnostics |
| 21 | refresh_cross_asset_panel | ETF workspace mirror (yfinance); content-freshness guarded |
| 22 | evaluate_pending | 1d/1w/1m outcomes + WATCH counterfactuals |
| 23 | strategy_lab_shadow | Daily shadow decision card |
| 24 | shadow_outcomes_90d | Aggregate shadow card outcomes |
| 25 | freshness_validator | Output + content freshness validation |
| 26 | system_index | System index |
| 27 | current_status | Daily status.json snapshot |
| 28 | work_brief | Work brief |
| 29 | record_daily_run_event | Hub run event + calibration snapshot |

**Automation:** macOS `com.system.daily-run` launchd → `scripts/orchestrate.sh daily` (default 07:00 local).

## Weekly (42 steps) — Monday UTC or `--force-weekly`

Validation, calibration, learning, governance, and reporting. These do **not** change same-day judgment when skipped on a daily run.

### Moved to weekly 2026-07-03 (governance slim)
- `build_policy_from_paper` — Paper-derived agent policy
- `run_operator_detections` — operator activations (research-only)
- `measurement_quality_report` — K/X quality sidecar
- `build_data_gaps` — Harvester data-request gap scan
- ~~`refresh_cross_asset_panel`~~ — restored to **daily** (2026-07-11); workspace mirror via yfinance, Harvester export remains canonical when fresher
- ~~`evaluate_pending`~~ — restored to **daily** (2026-07-11); WATCH/NO_TRADE counterfactual returns included
- `judgment_accuracy_report` — eval_log aggregation
- `evidence_grade_report` — evidence grade contributors
- `build_artifact_registry` — routing-policy artifact registry

### Validation (weekly)
- `validate_proxy_observation_catalog` — proxy catalog vs Harvester panels
- `signal_monitor` — M+K prediction tracking
- `judgment_replay_audit` — replay audit of judgment quality
- `trade_decision_replay` — trade decision calibration report
- `claim_evaluator` — verify past claims against outcomes
- `claim_ladder_tracker` — cross-run claim progression

### Governance (weekly)
- `hmm_stability_audit` — HMM degeneracy + calibration history
- `architecture_reality_audit` — architecture vs reality
- `operator_registry_audit` — operator registry health
- `build_authority_graph` — authority graph rebuild
- `governance_status` — governance status report

### Learning (weekly)
- `learning_hub_feedback` — aggregate feedback for Hub
- `proxy_quality_report` — proxy quality metrics
- `mechanism_calibration` — mechanism causal calibration
- `learning_summary` — comprehensive learning summary
- `judgment_calibration_event` — judgment calibration event
- `trade_calibration_event` — trade calibration event
- `export_feedback` — export feedback to Paper
- `suggest_paper_updates` — suggest Paper updates
- `promote_paper_inbox` — promote Paper inbox items
- `collect_reviews` — collect reviews
- `build_feedback_sample_pool` — feedback sample pool append
- `evaluate_feedback_samples` — forward-outcome on feedback pool
- `backfill_judgment_calibration` — calibration backfill

### ML validation hardening (weekly, review-only)
- `asof_integrity_check` — future-data leakage detection
- `baseline_comparison` — system vs naive baselines
- `walk_forward_validation` — rolling-origin OOS validation
- `qlib_structural_bridge` — Qlib vs structural backtest bridge
- `threshold_review_bridge` — missed_stress → review candidates

### Reporting (weekly)
- `readme_first` — README generation
- `next_actions` — promotion-gate next actions
- `change_analysis` — trend/anomaly analysis
- ~~`strategy_lab_shadow`~~ — restored to **daily** (2026-07-11)
- ~~`shadow_outcomes_90d`~~ — restored to **daily** (2026-07-11; needs ETF panel)
- `build_overlay_shadow_report` — SPY overlay shadow metrics
- `build_event_replay_factory` — event-window replay samples
- `archive_daily_snapshots` — Output archival

## On-Demand

Not in the daily/weekly pipeline. Run manually when needed:

- `python3 scripts/architecture_reality_audit.py` — architecture vs reality
- `python3 scripts/build_governance_drag_report.py` — complexity drag score
- `python3 scripts/daily_run.py --force-weekly` — run weekly block on any day
- `just strategy-backtest` / `just strategy-shadow` — Strategy Lab
- `make audit` — architecture reality audit (legacy alias)

## Rationale

Steps move from daily → weekly when this test is **no**:

> Does this step's output change the **same-day judgment or trade decision**?

Sidecars, batch calibration, governance reports, and workspace mirror refreshes stay weekly even if useful for humans.

## Flags

- `--force-weekly` — run weekly steps on any day
- `--skip-harvester` — skip data fetch
- `--skip-etf` — skip ETF refresh
- `--dry-run` — print plan without executing

## Governance drag

```bash
python3 scripts/build_governance_drag_report.py
```

Target: **daily steps ≤ 29** (ETF mirror + shadow + evaluate_pending restored 2026-07-11), total drag score **< 25/80** (see `Output/system_learning/latest/governance_drag_report.json`).
