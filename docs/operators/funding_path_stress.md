# Operator: `FUNDING_PATH_STRESS`

Family: `compression` (pre-realization)
Status: **prototype** — spec + detector are in place; realized-case calibration is
still light (see §5). Not yet allowed to affect core judgment authority; runs as
a research-only overlay under `allowed_to_affect_core_judgment: false`.

This spec follows the 6-part operator template proposed in the capability-upgrade
plan: `inputs`, `trigger`, `persistence`, `invalidation`, `historical case`,
`position translation`. Everything in this doc is *what the operator claims to
observe*, not a promise about trade P/L.

---

## 1. Inputs (proxies)

Purpose: catch stress on the funding rail before it prints in HY / equity vol.
Everything here must be in `Data/harvester/exports/latest/data/benchmark_panel.parquet`.

| role                         | series (panel `series_id`)             | notes |
|------------------------------|----------------------------------------|-------|
| overnight funding vs. floor  | `DERIVED:SOFR_IORB_SPREAD`             | primary. positive spread = funding trading rich vs. floor. |
| RRP drain                    | `FRED:RRPONTSYD`                       | fast declines = cash leaves RRP; combined with reserve moves flags balance-sheet stress. |
| reserve balances             | `FRED:WRESBAL`                         | weekly. contraction = plumbing tightening. |
| TGA                          | `FRED:WTREGEN`                         | weekly. rapid build = reserves drained even without policy action. |
| CP–Tbill spread              | `DERIVED:CP_TBILL_SPREAD`              | corporate funding stress echo. |
| Fed liquidity backstops      | `H41:btfp`, `H41:discount_window`      | if these move, part of the operator becomes non-invertible (see §4). |
| confirmation — rates vol     | `CBOE:MOVE`                            | not a trigger. only used to reject noise. |

Failure modes of these proxies (must be recorded in `panel.quality_flag` or in
`KNOWN_DATA_GAPS`):

- `DERIVED:SOFR_IORB_SPREAD` starts 2021-07 → operator cannot be evaluated on
  2019-09 with SOFR alone; historical replay must fall back to
  `DERIVED:CP_TBILL_SPREAD` + reserve/TGA path (see §5).
- Reserve balances / TGA are weekly (Wednesdays) → daily activation must not
  demand fresh values every day; interpolate as "held" with a `stale=True`
  marker rather than forward-projected.

## 2. Trigger

An activation candidate is emitted for date *t* when **all** of the following
hold on the same window:

1. `z_5d(SOFR_IORB_SPREAD) ≥ +1.5σ` **or** absolute spread ≥ +5bp for at least
   3 of the last 5 business days. *(pre-2021 windows: substitute
   `z_20d(CP_TBILL_SPREAD) ≥ +1.5σ`.)*
2. Balance-sheet path: `ΔWRESBAL_4w < 0` **or** `ΔWTREGEN_4w > 0` at a rate in
   the top decile of the trailing 5-year window. This is the "path" part — the
   operator does not fire on a single-day spike alone.
3. `MOVE` is not simultaneously collapsing (`z_20d(MOVE) > −1σ`). If MOVE is
   deeply negative, we suspect data-alignment or a benign carry episode rather
   than funding stress.

Trigger score (`activation ∈ [0, 1]`):
```
activation = clip(
    0.5 * softclip(z_5d(SOFR_IORB_SPREAD), 3σ)
  + 0.3 * softclip(-ΔWRESBAL_4w_pctile, 1.0)
  + 0.2 * softclip( ΔWTREGEN_4w_pctile, 1.0),
    0.0, 1.0,
)
```
Threshold for "candidate emitted": `activation ≥ 0.55`. Threshold for "operator
counts against risk-budget": `activation ≥ 0.70` **and** persistence gate in §3
passes.

## 3. Persistence

A single-day trigger is treated as noise. The operator only enters the run
bundle when:

- `activation ≥ 0.55` on at least 3 of the last 5 business days, **and**
- the 5-day mean of `SOFR_IORB_SPREAD` (or CP–Tbill fallback) is above its
  60-day median.

Persistence produces an `entered_at` timestamp. The operator stays "on" until
one of the invalidation conditions in §4 fires; it does **not** decay
automatically.

## 4. Invalidation

The operator turns off (and is recorded as `invalidated`, not `resolved`) when
any of these hold:

- `H41:discount_window` or `H41:btfp` prints a > 20% week-over-week jump, or a
  new named facility appears in the H.4.1 release. This is the "policy erases
  the funding path" case — the operator's compression assumption no longer
  applies because a `LIQUIDITY_FACILITY` intervention is composed on top.
  The activation is *not* rewritten historically; we record
  `superseded_by = LIQUIDITY_FACILITY`.
- `SOFR_IORB_SPREAD` back below +2bp for 5 consecutive days **and** reserve
  balances no longer contracting on a 4-week window.
- Data-quality invalidation: if any of the top-3 inputs is `stale > 10
  business days` or `quality_flag ∈ {revoked, backfilled}`, the activation is
  downgraded to `WATCH_ONLY` and cannot promote through the gate.

Explicit non-invalidation:
- Equity drawdown, HY OAS widening, or VIX spike do **not** by themselves
  invalidate the operator. They may co-occur; they are *separate* evidence
  for other operators (`FORCED_SELLING`, `VOL_SURFACE_KINK`).

## 5. Historical case (calibration anchors)

The operator has to explain at least these windows without hand-tuning per
window:

| window            | expected activation | notes |
|-------------------|---------------------|-------|
| 2019-09-13 → 10-10 | ≥ 0.85 on ≥ 10 of 20 days | repo spike. SOFR–IORB unavailable — use CP–Tbill fallback and RRP/reserve path. |
| 2020-03-09 → 03-27 | ≥ 0.70 early, invalidated after 2020-03-17 | invalidation via `LIQUIDITY_FACILITY` (PDCF/CPFF/MMLF). We want the operator to fire *before* invalidation, not after. |
| 2023-03-08 → 03-15 | ≥ 0.65 for at least 3 days | SVB week. mostly a `DEPOSIT_RUN`, but the funding-path leg should still light up on TGA/reserve motion. |
| 2023-10-19 → 11-01 | ≤ 0.40 throughout      | rates-selloff false-positive window. If the operator fires here, the trigger is over-fit to MOVE. |

Anything else is exploratory. New windows can be added to `caselab_context/`
once we have a written before/after diagnosis.

## 6. Position translation

The operator does **not** emit trade signals. It translates into a risk-side
constraint that overlays whatever base strategy is running:

| activation state              | overlay action                                 |
|-------------------------------|------------------------------------------------|
| `< 0.55`                      | no action                                      |
| `0.55 ≤ · < 0.70` (WATCH)     | freeze new adds in leveraged / carry sleeves; do not size up equity beta |
| `≥ 0.70` and persistence pass | reduce leveraged carry exposure by ≥ 25%; require dual-confirmation (credit or rates vol) before any new long-risk add |
| `invalidated` via facility    | operator turns off, but a `POLICY_BACKSTOP_ACTIVE` flag stays on for 10 business days — do not treat the calm as clean risk-on |
| `invalidated` via data-quality| downgrade to `RESEARCH_REVIEW`; no overlay effect |

The overlay is expressed as a change to the risk-budget register, not as
trades. If a base strategy is not running, the overlay's only observable
output is the `activation`, `state`, `entered_at`, `superseded_by` fields in
the operator record.

---

## Wiring

- Registry entry: `packages/framework_v1_archive/src/operators/operator_registry.py`,
  operator name `FUNDING_PATH_STRESS`, family `compression`.
- Detector: `packages/framework_v1_archive/src/operators/mechanism/funding_path_stress.py`.
- Panel column contract: see §1 table. The detector must fail loudly if any of
  the top-3 series is missing from the panel.
- Governance: initial rollout is `allowed_to_affect_core_judgment: false`. To
  promote, we need at least 10 evaluated activation windows with human labels
  in `Data/feedback_samples/`.
