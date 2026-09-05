# Paper-Code Alignment Map

Purpose: this file is an alignment audit between the paper and the implementation. It is not an API document, a paper table of contents, or a data-flow diagram. Each row maps one paper symbol, concept, or core claim to an implementation object where one exists.

Status vocabulary:

- `EXACT`: implementation directly realizes the paper definition or computation.
- `APPROXIMATE`: implementation chooses a concrete admissible form for an open paper definition.
- `DIVERGENT`: implementation choice materially differs from the paper claim or protocol.
- `MISSING`: paper has no code counterpart, or code has no paper counterpart.
- `N/A`: pure theory or engineering surface that does not need a counterpart.

Correspondence types: `Definition`, `Computation`, `Diagnostic`, `Threshold`, `Mechanism`, `Engineering`.

## Scope Notes

The current audit treats Sections 2.5-2.7 of the paper as representational critique rather than code obligations. The code implements the consequence of that critique through a four-channel structural architecture, operator-order diagnostics, and non-scalar state evolution. It does not implement the scalar-compression information theorem itself.

The current audit also treats `src/ml/` as exploratory unless a future paper revision explicitly promotes anomaly, reflexivity, or narrative detectors into paper-aligned claims. The configuration already defaults `ml.enabled` to `false`.

## Section 2: CAPM Critique And Incompressibility

| ID | Paper Symbol / Concept | Paper Location | Code Location | Code Symbol | Type | Status | Notes |
|---|---|---|---|---|---|---|---|
| C2.1 | Evolving filtered probability structure `(Omega_t, F_t, P_t)` | Section 2.4, lines 139-156 | none | none | Definition | MISSING | The code does not model sample-space, sigma-algebra, or measure evolution directly. This is acceptable only if Section 2 remains a theoretical critique. |
| C2.2 | Theorem 1, scalar information loss | Section 2.5, Appendix B.1 | none | none | Diagnostic | MISSING | No mutual-information or quantizer diagnostic exists. Recommended boundary: theory only, not implementation claim. |
| C2.3 | Theorem 2, infinite-dimensional evolution | Section 2.6, Appendix B.2 | none | none | N/A | N/A | Pure ambient-space theorem; no direct code counterpart required. |
| C2.4 | Path-rank condition / order-sensitive output separation | Section 2.7, Appendix B.5 | `src/operators/operator_algebra.py`, `src/operators/operator_diagnostics.py` | `commutator_vector`, `lie_bracket_vector`, `path_rank_diagnostics`, `sequence_non_commutativity_score` | Diagnostic | APPROXIMATE | Code now reports reduced finite-sequence path-rank witnesses over adjacent operator swaps, but not the paper's full positive-measure path-rank condition. |
| C2.5 | Structural output map `T(z, p)` | Section 2.7, lines 245-279 | `src/operators/operator_algebra.py`, `src/operators/event_to_operator.py` | `apply_operator_sequence`, operator post-state | Computation | APPROXIMATE | Code computes realized operator-path outputs for `M/D/K/X`, but there is no named general `T(z,p)` abstraction or scalar-blind path-rank audit. |

## Section 4: Anchor-Mismatch Dynamic System

| ID | Paper Symbol / Concept | Paper Location | Code Location | Code Symbol | Type | Status | Notes |
|---|---|---|---|---|---|---|---|
| C4.1 | Primitive state `z_t = (S_t,A_t,L_t,V_t,P_t,tau_t)` | Section 4.1 | `src/core/models.py`, `src/derivation/structural_layers.py` | `StructuralPrimitiveState`, `build_primitive_state` | Definition | EXACT | Six variables are explicit: subject, anchor, liquidation feasibility, verifiability density, positional power, latency. |
| C4.2 | `M_t = M(S_t,A_t)` | Section 4.2 | `src/derivation/structural_layers.py` | `mismatch = abs(subject - anchor)` | Computation | APPROXIMATE | Paper leaves `M` open; code chooses absolute subject-anchor gap after reduced-form primitive construction. |
| C4.3 | `D_t = [d0 + ...]_+` | Section 4.2 | `src/derivation/structural_layers.py` | `dof = max(0.0, ...)` | Computation | EXACT | Sign-restricted positive-part closure is implemented with configurable coefficients. |
| C4.4 | ODE layer for `M_t,D_t,K_t,X_t^agg` | Section 4.3 | `src/dynamics/state_evolution.py` | `DiffraxODEEngine`, `_drift_numpy`, `_solve_diffrax`, `_solve_scipy_or_rk4` | Computation | APPROXIMATE | Code evolves a six-dimensional mapped state, with `M/D/K/X` embedded through `DefaultStateSpaceMapping`; this is an implementation-specific reduced form, not a literal paper ODE. |
| C4.5 | Toy sign-restricted closure | Appendix A | `src/derivation/structural_layers.py`, `src/dynamics/state_evolution.py` | `sign_restricted_reduced_form_v1`, `_drift_numpy` | Computation | APPROXIMATE | Code uses a toy reduced-form default. It should be documented as illustrative, not calibrated. |
| C4.6 | Effective transition curvature `K_t = K(g_t)` | Section 4.4 | `src/dynamics/state_evolution.py` | `spectral_abscissa`, `jacobian_frobenius_norm`, `spectral_abscissa_drift` | Computation | APPROXIMATE | Paper leaves `K` open; code chooses Jacobian spectral/Frobenius diagnostics and proxy curvature. |
| C4.7 | Shadow density / measure-valued evolution `X_t(xi)` | Section 4.5 | `src/core/models.py`, `src/derivation/structural_layers.py` | `ShadowMassState`, `ShadowMassBucket`, `build_shadow_mass_state` | Computation | APPROXIMATE | Paper is measure-valued; code uses four maturity buckets: immediate, short, medium, long. |
| C4.8 | Aggregate shadow mass `X_t^agg = int X_t(xi) dxi` | Section 4.5 | `src/core/models.py`, `src/derivation/structural_layers.py` | `ShadowMassState.aggregate_mass` | Computation | APPROXIMATE | Code sums a discrete bucket approximation, so exact relative to the discretization, approximate relative to the continuous paper object. |
| C4.9 | Forced realization `R_t(xi)` | Section 4.5 | `src/core/models.py`, `src/derivation/structural_layers.py` | `ShadowMassBucket.realization_intensity` | Computation | APPROXIMATE | Four-bucket realization intensity is a reduced-form discretization. |
| C4.10 | `Pi_t = int R_t(xi) X_t(xi) dxi` | Section 4.8 / 4.10 | `src/core/models.py`, `src/derivation/structural_layers.py`, `src/derivation/singular_detector.py` | `forced_realization_pressure`, `_forced_realization_pressure` | Computation | APPROXIMATE | Code computes the discrete bucket sum and passes it into the singular detector. |
| C4.11 | Singular set `S`: `D_t <= eps_D`, `K_t >= K*`, `Pi_t >= Pi*` | Section 4.8 | `src/derivation/singular_detector.py`, `config.yaml` | `_joint_hitting_trigger`, `thresholds.joint_hitting` | Threshold | DIVERGENT | Thresholds are fixed defaults (`-0.65`, `0.65`, `0.65`) rather than calibrated on frozen training windows as required by the paper evaluation protocol. |
| C4.12 | Structural singular time `tau_S` / first hitting time | Section 4.8, Appendix D | `src/core/models.py`, `src/dynamics/state_evolution.py`, `src/derivation/singular_detector.py`, `src/simulation/agent_based_lab.py` | `structural_singular_time`, `threshold_hit_time`, `first_singular_step` | Diagnostic | APPROXIMATE | Snapshot/provenance now expose a canonical structural singular time when available; current detector records `0.0` for current-state joint hits and ODE diagnostics provide horizon hit time. |
| C4.13 | Proposition 2 well-posedness / admissibility | Section 4.6, Appendix C | `src/core/pipeline.py`, `src/dynamics/state_evolution.py` | non-finite checks, fallback solvers | Mechanism | APPROXIMATE | Code checks numerical validity and non-finite states but does not implement explicit inward-boundary/admissibility proofs or guards for all constrained primitive coordinates. |

## Section 5: Reflexivity

| ID | Paper Symbol / Concept | Paper Location | Code Location | Code Symbol | Type | Status | Notes |
|---|---|---|---|---|---|---|---|
| C5.1 | Perceived signals `M_hat`, `K_hat`, `X_hat` | Section 5.1 | `src/core/models.py`, `src/derivation/belief_builder.py` | `StructuralBeliefState`, `ChannelBeliefState` | Definition | APPROXIMATE | Code builds uncertainty-aware channel beliefs, but it does not explicitly name perceived-vs-true channels. |
| C5.2 | Reflexive drift replacement `F -> F^ref` | Section 5.2 | `src/mechanisms/default_mechanisms.py`, `src/operators/operator_registry.py`, `src/core/pipeline.py` | mechanism terms, reflexive operators, `_multi_reflexivity` | Mechanism | DIVERGENT | Paper describes formal insertion into drift laws. Code mainly shifts proxies through mechanism/operator terms and escalates on reflexivity flags; it does not replace the ODE drift with a named `F_ref`. |
| C5.3 | Reflexivity tracker | UI/runtime concept | `src/ml/ml_reflexivity.py`, `src/ui/components/regime_badge.py`, `src/core/pipeline.py` | `DTWReflexivityDetector`, `reflexivity_flags` | Diagnostic | MISSING (paper) | Code has a tracker-like diagnostic surface, but paper does not specify this detector. Treat as exploratory or add a paper note. |

## Section 6: CAPM Local Boundary

| ID | Paper Symbol / Concept | Paper Location | Code Location | Code Symbol | Type | Status | Notes |
|---|---|---|---|---|---|---|---|
| C6.1 | Low-distortion neighborhood `N_delta(z*)` | Section 6 | none | none | Diagnostic | MISSING | README mentions CAPM-local boundary status as a future UI target; no implementation exists. |
| C6.2 | Local CAPM-like reduction | Section 6 | none | none | Mechanism | MISSING | No code path tests or displays CAPM-local reduction conditions. |

## Section 7: Empirical Interface

| ID | Paper Symbol / Concept | Paper Location | Code Location | Code Symbol | Type | Status | Notes |
|---|---|---|---|---|---|---|---|
| C7.1 | Three signatures: non-commutativity, mean-field gap, shadow maturity profile | Section 7.1 | `src/operators/operator_algebra.py`, `src/derivation/structural_layers.py`, `src/core/models.py` | `sequence_non_commutativity_score`, `MeanFieldGapState`, `ShadowMassState.buckets` | Diagnostic | APPROXIMATE | All three exist in reduced form; non-commutativity is pairwise/operator-sequence, not a full path-rank statistic. |
| C7.2 | `D_t^proxy` basket | Section 7.2.1 | `src/data/contracts.py`, `src/data/data_sources.py`, `src/derivation/proxy_builder.py` | `dof_*` presets, `D_PROXY`, D basket map | Computation | EXACT | Depth, hedge/risk-transfer breadth, and funding access are present through presets and aggregation. |
| C7.3 | `K_t^proxy` basket | Section 7.2.2 | `src/data/contracts.py`, `src/data/data_sources.py`, `src/derivation/proxy_builder.py` | `curvature_*` presets, `K_PROXY`, K basket map | Computation | EXACT | Jump/volatility, refinancing, and liquidation-path instability proxies exist. |
| C7.4 | `X_t^proxy` basket | Section 7.2.3 | `src/data/contracts.py`, `src/data/data_sources.py`, `src/derivation/proxy_builder.py` | `shadow_*` presets, `X_PROXY`, X basket map | Computation | EXACT | Emergency credit, BTFP, and issuer filing pulse proxies exist. |
| C7.5 | `M_t^proxy` aggregation | Section 7.2.4 | `src/derivation/proxy_builder.py`, `src/data/data_sources.py` | `_weighted_l1`, `M_PROXY` | Computation | APPROXIMATE | Code uses weighted/mean absolute basket values for `M`; paper permits proxy aggregation but should name the operator in implementation notes. |
| C7.6 | Measurement bridge `H_Lambda` | Section 7.2 | `src/data/gateway/bridge.py`, `src/data/quality/manifest.py`, `src/core/pipeline.py` | `DataHubBridge`, `DataEvidenceManifest`, provenance manifests | Mechanism | APPROXIMATE | Code has an evidence/admission bridge, but the formal `H_Lambda` mapping is not named in code. |
| C7.7 | Joint stress score `Sigma_t` | Section 7.4 / 7.5 | `src/derivation/singular_detector.py`, `src/operators/operator_diagnostics.py` | `sigma_t`, `singular_pressure` | Computation | EXACT | Weighted positive stress aggregation is implemented; defaults equal weights unless config changes. |
| C7.8 | Forward singular risk `P_S(t)` / `p_hat_S(t)` | Section 7.4 / 7.6 | `src/derivation/belief_builder.py`, `src/simulation/agent_based_lab.py` | `sigma_breach_prob`, `singular_probability` | Computation | APPROXIMATE | Code has probability-like belief and simulation outputs, but no calibrated forward classifier with frozen train/evaluation windows. |
| C7.9 | Pre-registered evaluation protocol | Section 7.5 | `src/core/calibration.py`, `config.yaml` | `FrozenThresholds`, threshold protocol metadata | Mechanism | DIVERGENT | Code records calibration/evaluation protocol metadata and frozen config thresholds, but still does not implement empirical calibration-mode vs evaluation-mode separation or forward-window locking. |
| C7.10 | Case A, March 2020 Treasury stress | Section 7.4.2 / case-linked grounding | `src/simulation/case_studies.py` | none specific | Mechanism | MISSING | Scenario lab has `subprime_2008`, `cdo_tranching`, and `ltcm_1998`, but no March 2020 case. |
| C7.11 | Case B, March 2023 SVB stress | Section 7.4.2 / case-linked grounding | `src/simulation/case_studies.py` | none specific | Mechanism | MISSING | Scenario lab has no SVB/regional-bank case. Data presets include BTFP/primary credit but not a named SVB scenario. |

## Reverse Direction: Code Without Paper Counterpart

| ID | Code Function | Code Location | Type | Status | Notes |
|---|---|---|---|---|---|
| R1 | Data evidence and quality escalation | `src/data/gateway/bridge.py`, `src/data/quality/manifest.py`, `src/core/pipeline.py` | Mechanism | MISSING (paper) | Paper should add a short data-admissibility statement. Code suppresses all-mock research interpretation. |
| R2 | Operator registry taxonomy: compression, curvature, shadow transfer, realization, intervention | `src/operators/operator_registry.py` | Mechanism | APPROXIMATE | Paper discusses reflexive/state-dependent operators but not this five-family taxonomy. This is an implementation design choice. |
| R3 | Scenario lab and crisis case harness | `src/simulation/agent_based_lab.py`, `src/simulation/case_studies.py` | Mechanism | MISSING (paper) | Paper mentions case-linked diagnostics and evaluation, but not simulation as a falsification support tool. |
| R4 | ML anomaly/reflexivity/narrative detectors | `src/ml/ml_anomaly.py`, `src/ml/ml_reflexivity.py`, `src/ml/ml_narrative.py`, `config.yaml` | Mechanism | MISSING (paper) | These are optional/exploratory; `config.yaml` defaults `ml.enabled: false`. Keep out of paper-aligned claims unless promoted. |
| R5 | Mean-field gap benchmark choice | `src/derivation/structural_layers.py` | Definition | DIVERGENT | Paper defines a mean-field fragility gap but does not specify the decoupled representative benchmark. Code chooses `decoupled_representative_shadow_load_v1`; this must be documented or formalized. |
| R6 | Distributional/Bayesian belief-layer path | `src/core/models.py`, `src/derivation/belief_builder.py`, `docs/DISTRIBUTIONAL_STATE_MIGRATION.md` | Mechanism | MISSING (paper) | Code implements normal belief summaries and stores an upgrade path. Paper only lightly treats noisy perceived signals. |
| R7 | API, terminal, runtime, UI plumbing | `src/api/`, `src/terminal/`, `src/runtime/`, `src/ui/` | Engineering | N/A | Engineering surfaces do not require paper counterparts unless they make scientific claims. |

## High-Priority Gaps

1. `C4.11` and `C7.9`: singular thresholds are configured defaults, not train-window-calibrated and forward-frozen thresholds. This is the most important methodological divergence.
2. `R5`: the mean-field benchmark is underspecified at the paper level and concretely chosen in code. Either formalize `decoupled_representative_shadow_load_v1` or label it as an implementation benchmark.
3. `C2.4` / `C2.5`: code has a reduced finite-sequence path-rank witness, but no positive-measure path-rank audit. Add a stronger diagnostic if Proposition 1 is meant to be inspectable beyond realized event sequences.
4. `C4.12`: first hitting is now surfaced as `structural_singular_time`, but its semantics are still mixed between ODE horizon hitting and current-state detector hitting.
5. `C5.2`: reflexivity should either be downgraded in paper to mechanism/proxy shifts or upgraded in code to a named `F_ref` drift replacement.
6. `C7.10` / `C7.11`: add named March 2020 and SVB scenario/case harnesses if case-linked grounding is meant to be reproducible from code.

## Direction Decisions

Recommended decisions for the current paper/code boundary:

1. Treat Section 2 as theoretical critique. Add an implementation note saying the code operationalizes the consequences rather than the theorems.
2. Keep `src/ml/` exploratory for now. Consider moving it under `src/exploratory/` or adding explicit doc labels.
3. Do not expand the current paper into full Bayesian belief formalization. Leave the distributional belief layer as a future-work implementation path.
4. Add small paper statements for data admissibility and scenario-lab falsification support, because those code surfaces strengthen rather than dilute the main framework.

## Proposed Paper Notes

Suggested implementation note:

> Sections 2.5-2.7 are theoretical results about scalar compression limits. The implementation does not attempt to compute the information-loss or infinite-dimensionality theorems directly; it operationalizes their consequence by replacing scalar compression with a four-channel structural state, event-order diagnostics, shadow-maturity profiles, and singular-regime checks.

Suggested data-admissibility sentence for Section 7:

> The measurement bridge requires minimum data admissibility across proxy blocks; implementation configurations with insufficient real evidence are flagged or suppressed.

Suggested scenario-lab sentence for Section 7 evaluation protocol:

> Falsification can be supported by mechanism simulation in scenario labs: if simulated dynamics under specified parameter regimes do not produce the predicted ordering of channel responses, the corresponding mechanism claim is weakened.

## Maintenance Rule

Update this file whenever:

- the paper introduces or removes a mathematical symbol, diagnostic, threshold, or mechanism;
- code adds a scientific diagnostic, proxy, detector, threshold, or mechanism;
- a status changes among `EXACT`, `APPROXIMATE`, `DIVERGENT`, and `MISSING`.
