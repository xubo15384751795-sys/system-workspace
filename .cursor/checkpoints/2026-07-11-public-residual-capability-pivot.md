# Checkpoint: public-residual-capability-pivot

- mission: Public-level tool + residual onset A/B; paper continuous sizing; weekly 3-table board. No Batch-2 / gate_sweep / Sticky-HMM / k_surface promotion.
- decisions:
  - Level stress = equal-weight causal PIT(OFR, NFCI, CISS)
  - Residual A (`level`): velocity/CUSUM on (channel_PIT − public_PIT)
  - Residual B (`velocity`): onset on (channel_velocity_PIT − public_velocity_PIT) — no double-diff
  - Paper default: `residual_mode=velocity`, **`onset_lambda=0.0`** until board passes
  - Board compares A vs B incremental + NAV schemes including `public_lambda0`
  - Board run 2026-07-11: **both A and B fail** (β₂&lt;0, ΔPR&lt;0) → recommendation = use λ=0
  - Explicitly not done: Batch-2, gate_sweep, Sticky-HMM/DFM, k_surface promotion, live wiring
- open_threads:
  - Residual onset research-shelved after A and B both failed incremental; next residual attempt needs a new *hypothesis*, not another method stack
  - Optionally schedule `run_capability_board` weekly
- do_not_touch: live execution; Output/current; k_surface promotion; Batch-2 expansion; more residual variants without a new hypothesis
- next_agent_action: Operate paper on public_lambda0 (λ=0). Treat residual as research-only unless a new residual hypothesis is proposed and clears the three tables.
- acceptance:
  - tests: test_public_residual_stress + test_paper_portfolio passed (13)
  - entrypoints: run_capability_board (v2), paper_portfolio λ=0
  - artifacts: Output/validation/capability_board/*
