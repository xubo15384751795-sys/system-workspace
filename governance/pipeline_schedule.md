# Pipeline Schedule — Daily / Weekly / On-Demand

> Updated 2026-06-20. Slimmed from 35 daily → 25 daily, 13 steps moved to weekly.

## Daily (25 steps) — Signal-blocking, every run

These steps form the core signal chain. If any fails, the daily judgment is affected.

| # | Step | Purpose |
|---|------|---------|
| 1 | harvester | Data acquisition |
| 2 | etf_refresh | ETF panel refresh |
| 3 | paper_sync | Paper world model sync |
| 4 | caselab_index | CaseLab index update |
| 5 | build_policy_from_paper | Agent policy from Paper rules |
| 6 | structural_replay | M/D/K/X structural measurement |
| 7 | bridge | Bridge replay → current |
| 8 | quality_validation | Data quality checks |
| 9 | regime_detection | HMM regime detection |
| 10 | k_measurement_gate | K measurement gate |
| 11 | x_measurement_gate | X measurement gate |
| 12 | caselab_signal | CaseLab daily signal |
| 13 | judgment_layer | Judgment card generation |
| 14 | judgment_promotion_gate | Promotion gate |
| 15 | trade_decision | Trade decision |
| 16 | risk_gate | Risk gate |
| 17 | record_trade_decision | Record to ledger |
| 18 | signal_card | Signal card output |
| 19 | signal_consensus | Signal consensus |
| 20 | signal_monitor | M+K prediction tracking |
| 21 | market_feedback | Market feedback |
| 22 | evaluate_pending | Forward-outcome checks (daily-only mode) |
| 23 | freshness_validator | Output freshness validation |
| 24 | system_index | System index |
| 25 | work_brief | Work brief |

## Weekly (30 steps) — Monday UTC or `--force-weekly`

Validation, calibration, learning, governance, and reporting. These run on Monday
(or any day with `--force-weekly`). They never block the daily signal chain.

### Validation (weekly)
- `judgment_replay_audit` — replay audit of judgment quality
- `trade_decision_replay` — trade decision calibration report
- `claim_evaluator` — verify past claims against realized outcomes
- `claim_ladder_tracker` — cross-run claim progression

### Governance (weekly)
- `hmm_stability_audit` — HMM degeneracy checks
- `architecture_reality_audit` — architecture vs reality
- `operator_registry_audit` — operator registry health
- `build_authority_graph` — authority graph rebuild
- `governance_status` — governance status report

### Learning (weekly)
- `learning_hub_feedback` — aggregate feedback for Hub
- `proxy_quality_report` — proxy quality metrics
- `proxy_lifecycle` — proxy lifecycle evaluation
- `mechanism_calibration` — mechanism causal calibration
- `learning_summary` — comprehensive learning summary
- `judgment_calibration_event` — judgment calibration event
- `trade_calibration_event` — trade calibration event
- `export_feedback` — export feedback to Paper
- `suggest_paper_updates` — suggest Paper updates
- `promote_paper_inbox` — promote Paper inbox items
- `collect_reviews` — collect reviews

### ML Validation Hardening (weekly, review-only)
- `asof_integrity_check` — future-data leakage detection
- `baseline_comparison` — system vs naive baselines
- `walk_forward_validation` — rolling-origin OOS validation
- `threshold_review_bridge` — missed_stress → review candidates

### Reporting (weekly)
- `readme_first` — README generation
- `next_actions` — next actions planning
- `change_analysis` — trend/anomaly analysis
- `strategy_lab_shadow` — shadow backtest
- `archive_daily_snapshots` — archival
- `backfill_judgment_calibration` — calibration backfill

## On-Demand

These are not in the daily/weekly pipeline. Run manually when needed:

- `just strategy-backtest` — Strategy Lab backtesting
- `just strategy-shadow` — Strategy Lab shadow analysis
- `just strategy-backfill` — Strategy Lab backfill
- `just audit-reality` — Architecture reality audit
- `just nightly` — Full test suite + audit
- `make audit` — Architecture reality audit
- `scripts/build_governance_drag_report.py` — Complexity drag report

## Rationale

Steps were moved from daily to weekly based on this test:

> Does this step's output change the **same-day judgment or trade decision**?

If no — it's validation, calibration, reporting, or governance — it belongs in weekly.
If yes — it's signal-blocking — it stays daily.

## Flags

- `--force-weekly` — run weekly steps on any day
- `--skip-harvester` — skip data fetch
- `--skip-etf` — skip ETF refresh
- `--dry-run` — print plan without executing

## Governance Drag Score

Run `python3 scripts/build_governance_drag_report.py` to check system complexity.
The drag score feeds into the incentive engine as a complexity penalty.

Target: keep daily active steps ≤ 25, total drag score < 25/80.
