# Distributional State Migration

This note proposes the smallest practical migration from scalar structural state to distribution-aware structural state in the current system.

It uses the uploaded paper only as methodological inspiration:

- treat state as a stochastic process rather than a single deterministic recursion
- preserve finite fluctuations instead of collapsing them immediately into means
- track distribution summaries, not just point values
- prefer transformed variables and approximate laws when they are more stable

It does not import the paper's neural-network-specific machinery.

## 1. Reinterpreting `M / D / K / X` as distributional state objects

Today, the code treats the structural channels as point estimates in [`ProxyReading`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/core/models.py:18), then derives a point `sigma_t` and a point escalation decision in [`ThresholdSingularDetector`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/derivation/singular_detector.py:12).

The first distributional reinterpretation should be:

- `M_t` is not one mismatch value but a belief over mismatch severity
- `D_t` is not one degrees-of-freedom value but a belief over compression/freedom state
- `K_t` is not one curvature value but a belief over deformation intensity
- `X_t` is not one shadow-load value but a belief over hidden accumulation/release pressure

In practice, each channel becomes a bounded belief object containing:

- `location`: current best estimate in a transformed channel space
- `scale`: uncertainty or fluctuation width
- `support`: optional lower and upper admissible range
- `confidence`: how much evidence supports the estimate
- `evidence_mass`: how much of the belief comes from direct observed proxies vs inferred structure
- `tail_metrics`: probability of entering dangerous regions
- `back_transform_point`: a scalar view for legacy consumers

This is not yet a full density estimator. It is a distribution summary that can evolve over time.

### Recommended transformed channel views

Do not force the belief to live on the raw proxy scale if that scale is unstable.

- `M`: use a robust mismatch severity transform such as `sign(M) * log1p(abs(M))`
- `D`: use capacity-space or compression-space, for example `log(max(eps, 1 + D))` or a clipped compression score
- `K`: use deformation intensity such as `log1p(max(0, K))`
- `X`: use hidden-load pressure such as `log1p(max(0, X))`

The project can still expose raw `M/D/K/X` alongside these transformed belief coordinates. The distribution should live where moment summaries behave better.

## 2. Minimal viable object design

The existing architecture already has a clean place to add this: keep [`ProxyReading`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/core/models.py:18) and [`StructuralState`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/core/models.py:31), but append a parallel belief layer instead of replacing them.

### `DistributionState`

```python
@dataclass(frozen=True)
class DistributionState:
    family: str                  # "normal", "student_t", "empirical_band"
    transform: str               # "identity", "signed_log1p", "log1p_pos", ...
    mean: float | None
    variance: float | None
    lower_q: float | None        # e.g. 0.1 quantile in transformed space
    upper_q: float | None        # e.g. 0.9 quantile
    support_min: float | None
    support_max: float | None
    confidence: float            # 0..1
    effective_n: float | None
    direct_evidence_weight: float
    structural_evidence_weight: float
    breach_prob: float | None
    singular_mass: float | None
    metadata: Mapping[str, Any]
```

Use this per channel. It is intentionally approximate and storage-friendly.

### `ChannelBeliefState`

```python
@dataclass(frozen=True)
class ChannelBeliefState:
    channel: Literal["M", "D", "K", "X"]
    raw_point: float | None
    transformed_point: float | None
    distribution: DistributionState
    evidence_tags: tuple[str, ...]
    last_update_source: str | None
```

This object bridges current scalar logic and new distribution logic.

### `StructuralBeliefState`

```python
@dataclass(frozen=True)
class StructuralBeliefState:
    run_date: str
    channels: Mapping[str, ChannelBeliefState]
    joint_mode: str              # "independent", "diag_cov", "copula_stub"
    covariance: Mapping[str, Mapping[str, float]] | None
    sigma_distribution: DistributionState | None
    escalation_metrics: Mapping[str, float | None]
```
```

For the first migration step, `joint_mode="independent"` is enough. A full `JointStructuralBelief` is optional and should wait.

## 3. How evidence should update these states

The current pipeline is:

`raw data -> proxy M/D/K/X -> event operator sequence -> ODE dynamics -> singular/reflexivity/narrative checks`

The distributional version should keep that order but add a belief update layer after proxy construction and after operator application.

### Update principle

Do not require full Bayesian inference initially. Use structured moment updates.

For each channel:

1. Start from previous channel belief
2. Apply process drift from operator/path logic
3. Inflate uncertainty when evidence is path-sensitive, contradictory, delayed, or provider-divergent
4. Contract uncertainty when multiple direct measurements agree
5. Emit updated mean, variance, quantiles, and breach probabilities

### Evidence translation

- Raw direct proxy:
  moves the channel mean strongly and can reduce variance if repeated evidence is consistent
- Proxy basket disagreement:
  does not just average away; it increases variance or lowers confidence
- Event/operator application:
  shifts the mean and may also widen variance when operators are irreversible, non-commutative, or compressive
- Contradiction across providers:
  should widen variance and increase singular-tail mass, especially for `M` and `X`
- Timing jitter / shadow release ambiguity:
  should be represented as process uncertainty, not discarded as noise

### Simple workable update rule

For transformed channel state `y_t`:

- prior: `(mu_prior, var_prior)`
- process step from operators/events: `mu_pred = mu_prior + drift`, `var_pred = var_prior + process_var`
- evidence blend from new proxy signal `s_t`:
  `mu_post = (1 - alpha) * mu_pred + alpha * s_t`
- variance update:
  `var_post = max(var_floor, (1 - alpha) * var_pred + alpha * obs_var + contradiction_penalty + path_penalty)`

Where:

- `alpha` depends on data freshness and evidence quality
- `contradiction_penalty` rises when components within [`DefaultProxyBuilder`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/derivation/proxy_builder.py:112) disagree materially
- `path_penalty` rises with `non_commutativity_score`, `irreversible_count`, or compression/shadow diagnostics from [`operator_diagnostics`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/operators/operator_diagnostics.py:98)

This is a belief filter, not a full posterior sampler. That is the right level for a first migration.

## 4. How escalation logic should change

Right now escalation is mostly driven by scalar `sigma_t >= sigma_threshold` in [`ThresholdSingularDetector`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/derivation/singular_detector.py:20).

The first change should be additive, not destructive:

- keep the old scalar flag for backward compatibility
- add belief-based escalation metrics beside it

### New escalation metrics

- `P(sigma >= threshold)`
- `P(M in mismatch-danger region)`
- `P(D in compression-danger region)`
- `P(K in curvature-danger region)`
- `P(X in shadow-release region)`
- upper quantile of `sigma`, for example `q90_sigma`
- singular-mass score: probability mass inside a predefined singular region

### Minimal trigger policy

Escalate if any of the following holds:

- scalar legacy trigger fires
- `P(sigma >= threshold) >= p_crit`
- `q90_sigma >= threshold`
- any channel has `singular_mass >= mass_crit`

This is better than a pure point threshold because it catches “not yet breached in mean, but highly unstable” states.

### Singular region definition

For the first version, keep it simple and aligned with the current pressure logic in [`singular_pressure(...)`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/operators/operator_diagnostics.py:53):

- high `M`
- negative/compressed `D`
- high `K`
- high `X`

Then define singular mass as approximate probability that the belief lies in that weighted region.

## 5. What to borrow from the paper and what not to borrow

### Borrow

- State as a stochastic process rather than only a deterministic recursion
- Finite fluctuations matter because small local uncertainty can accumulate through many updates
- Variable transformation before distribution fitting
- Approximate laws are acceptable if they are stable, recursive, and empirically useful
- Distribution evolution matters more than point means alone

### Do not borrow

- Neural-network parameter semantics
- Infinite-width / finite-width derivations as if the structural engine were a deep net
- Paper-specific angle variables or activation-specific identities
- Heavy asymptotic proofs as a design requirement for the system
- Any assumption that fluctuations are i.i.d. noise; here many fluctuations are operator- and path-dependent

The paper is useful as methodology, not as ontology.

## 6. Smallest migration path

The current code shape suggests a four-step migration with minimal breakage.

### Step 1: Add belief objects without changing existing interfaces

Extend [`StructuralState`](/Users/a1/System/Structural%20Deformation%20Research%20System/src/core/models.py:31) with an optional field:

```python
belief_state: StructuralBeliefState | None = None
```

Do not remove:

- scalar `proxy.M/D/K/X`
- `sigma_t`
- `singular_flag`
- `leading_channel`
- `pattern`

This keeps UI, storage, and tests mostly intact.

### Step 2: Build channel beliefs from existing proxy outputs

Add a new builder, for example:

- `src/derivation/belief_builder.py`

Inputs:

- current `ProxyReading`
- optional previous snapshot
- operator diagnostics
- component-level disagreement from proxy baskets

Outputs:

- `StructuralBeliefState`

At this stage, use independent per-channel approximate normals or clipped empirical bands.

### Step 3: Add belief-aware diagnostics beside legacy diagnostics

Add:

- `sigma_breach_prob`
- `sigma_q90`
- `channel_breach_probs`
- `singular_mass`

Store them in snapshot payload JSON and `structural_state` JSON fields, but do not require the UI to consume them yet.

### Step 4: Upgrade escalation policy to dual mode

In the detector layer:

- preserve scalar decision for compatibility
- add a belief-driven decision path
- log both reasons separately

Example:

- `legacy_threshold_breach`
- `distributional_tail_risk`
- `distributional_singular_mass`

This gives explainability and makes rollout safer.

## 7. Strong recommendation

The smartest first move to make this system distributional without breaking it is to add an optional `StructuralBeliefState` beside the existing scalar `ProxyReading` and `StructuralState`, with per-channel transformed mean/variance/quantile summaries and probability-based escalation metrics, while keeping the current scalar pipeline as the compatibility path.
