# Checkpoint: decision-loop-effective-size

- mission: Close shadow decision loop — stance×size × public_λ0 × velocity EXIT; fix Paper WM freshness freeze. Within constitution; no live.
- decisions:
  - paper_portfolio target *= trade_decision.effective_size on live/latest day (`scale_by_effective_size=true`)
  - Multi-day backfill historical days keep scale=1.0 (no anachronistic stance)
  - paper_sync on hash match refreshes `synced_at` (TTL heartbeat) so size is not permanently stepped down
  - trade_decision_layer uses **live** paper freshness (not judgment-card cache) for size step-down
  - residual onset λ remains 0; dual alerts level/onset unchanged in spirit
  - schema_version paper_portfolio.v3
- open_threads:
  - Next daily append applies effective_size to new NAV row (already-booked days not rewritten)
  - 90d shadow acceptance continues via daily appends
  - "No approved Paper sources" discount still possible when CaseLab match set is empty — separate from freshness
- do_not_touch: live execution; residual promotion; Batch-2; caselab_context WIP
- next_agent_action: Monitor next daily_run paper_portfolio row for effective_size field and scaled target
- acceptance:
  - tests: 19 passed (paper_portfolio + sync heartbeat + trade_decision stance_size)
  - after fix: trade_decision size 0.25→0.5 once Paper WM fresh (stale note cleared)
  - routing: governance/routing_decisions/2026-07-11-decision-loop-effective-size.yaml
