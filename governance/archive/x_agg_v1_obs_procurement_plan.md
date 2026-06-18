# X_agg v1 (off-balance-sheet) — data procurement plan

Status: proposal · Author: assessment 2026-05-31 · Relates to
[`canonical_proxy_spec.yaml`](canonical_proxy_spec.yaml) §X_agg.v1, and the
`awaiting_data` shell `X_agg_canonical_NOT_IMPLEMENTED_v1_off_balance_sheet`
in `scripts/structural_replay_v2.py:1406`.

## 1. Canonical requirement (the red line)

From `canonical_proxy_spec.yaml` (§4.5 + §7.2.3 + Table 6), sub-basket
`v1_off_balance_sheet` must measure **off-visible-balance-sheet exposure**:

- OBS-to-assets ratio
- derivatives notional / balance sheet
- contingent liabilities

Constraints carried by the `X_agg` StateVariable `core_contract`:

- `allowed_groups`: `off_balance_sheet`, `hidden_leverage_canonical`,
  `shadow_funding_substitution`
- **`forbidden_groups` includes `broad_financial_conditions_composite`** —
  a macro stress/conditions index does **not** qualify. (This is why the
  current sole X_agg voter, `NFCILEVERAGE`, is itself a red-line problem.)
- Must be independent of M / D / K (`must_be_independent_of`).
- Frequency: quarterly is acceptable (the shell declares `freq="quarterly"`).
- §7.2.3 equal-weight rule: v1/v2/v3 share weight 1/3 each unless a training
  step replaces and freezes weights.

## 2. Candidate sources — fidelity vs effort (honest ranking)

The code note already names the canonical source. The two paths originally
scoped (SEC XBRL, FRED Z.1) are both *proxies of that canonical source*.

| Path | Source | Canonical fidelity | Effort | Verdict |
|------|--------|--------------------|--------|---------|
| **C (canonical)** | FFIEC FR Y-9C **Schedule HC-L** (BHC) / Call Report **RC-L** — unused commitments, letters of credit, derivatives notional by type, securities lending; RC total assets for the ratio | **High** — literally the OBS schedule | High — new provider, quarterly bulk flat-file/SDF parse, RSSD/CIK mapping; Y-9C history back to 1986 | **Phase 2 target** |
| **B** | SEC XBRL **frames API** (`data.sec.gov/api/xbrl/frames/us-gaap/{Concept}/USD/CY{Y}Q{Q}I.json`): `DerivativeNotionalAmount`, `GuaranteeObligationsMaximumExposure`, commitment / `LossContingency` concepts, joined to `Assets` | Medium — issuer-level GAAP, but bank derivative tagging is sparse/inconsistent | Medium — extend existing `sec.py` (currently submissions/filing-pulse only) with an XBRL fetch; fixed dealer-bank CIK basket | **Phase 1 interim** |
| **A** | FRED Z.1 Financial Accounts / H.8 | **Low** — no clean system-level OBS-to-assets or derivatives-notional series; broker-dealer leverage / repo lean v2/v3, and a composite risks the `broad_financial_conditions_composite` red line | Low — `fred` provider already fetches arbitrary IDs | **Reject for v1**; reconsider only for v2/v3 |

Recommendation: **do not** fill v1 from FRED Z.1 (wrong instrument + red-line
risk). Phase the work: B as an interim real voter, C as the canonical target.

## 3. Phased plan

### Phase 1 — interim (SEC XBRL, ~existing provider extension) — ✅ DONE 2026-05-31
1. ✅ Extended `structural-risk-harvester/src/harvester/providers/sec.py` with
   `_fetch_companyconcept(cik, tag)` (XBRL companyconcept) + `_fetch_obs_to_assets`,
   dispatched in `fetch_series` on `OBS_SERIES_ID` (separate from filing-pulse).
2. ✅ Builds quarterly **derivatives-notional-to-assets** over the dealer-bank
   CIK basket: per quarter, sum numerator (`DerivativeNotionalAmount` →
   `NotionalAmountOfDerivatives` fallback) ÷ sum `Assets` across banks that
   reported both. Live result: 33 quarters 2010→2026, basket effectively
   JPM/BAC/GS (Citi/MS/WFC don't tag notional at top level — the documented
   fidelity limit; handled gracefully).
3. ✅ Registered `OBS_DERIV_TO_ASSETS` in `configs/series_registry.yaml`
   (`off_balance_sheet` / `obs_to_assets` / quarterly / not model-input).
4. ✅ Wired Deformation ProxySpec `X_agg_v1_obs_to_assets_candidate`
   (`candidate_pending_promotion`, NON-voting) + added `"quarterly"` to the
   replay `Freq` tables. Tests: `tests/test_providers_sec_xbrl.py` (6) +
   governance gate updated; full harvester suite 158 passed, governance 55 passed.

### Phase 2 — canonical (FFIEC Y-9C HC-L)
1. New `ffiec` provider pulling quarterly FR Y-9C bulk files (Chicago Fed BHC
   database, free, 1986→). Parse Schedule HC-L OBS items + HC total assets.
2. Aggregate across the BHC universe → system OBS/assets and
   derivatives-notional/assets.
3. Promote v1 ProxySpec to `canonical_voting` **only after**: independence
   check vs M/D/K passes, and §7.2.3 weighting is honored.

## 4. Landing it: two-step wiring (confirmed patterns)

**Step 1 — harvester registry** (`series_registry.yaml`), shape per existing
entries:
```yaml
OBS_DERIV_TO_ASSETS:
  canonical_id: OBS_DERIV_TO_ASSETS
  provider_priority: [sec]        # Phase 1; [ffiec] in Phase 2
  measurement_block: off_balance_sheet
  structural_role: obs_to_assets
  frequency: quarterly
  unit: ratio
  required_for_release: false
  required_for_model_input: false
  quality_expectation: observed
  description: "Aggregate derivatives notional / total assets, large dealer banks."
```
Series then flow into `benchmark_panel.parquet` as
`series_id = "SEC:OBS_DERIV_TO_ASSETS"` (namespaced like `FRED:DCPF3M`,
`CBOE:SKEW`, `H41:primary_credit`).

**Step 2 — Deformation ProxySpec** (`scripts/structural_replay_v2.py`):
replace the `awaiting_data` shell at line 1406 with a real voter, mirroring
the confirmed pattern of `D_cp_bill_funding_access`:
```python
ProxySpec(
    name="X_agg_v1_obs_to_assets",
    target_variable="X_agg",
    tier="core",
    freq="quarterly",
    raw_series=("SEC:OBS_DERIV_TO_ASSETS",),
    raw_family="SEC_OBS",
    independence_group="off_balance_sheet",
    mechanism="obs_to_assets_or_derivatives_notional",
    transform="quarterly OBS/assets ratio, rolling z-score",
    builder=lambda p: _component(_level(p, "SEC:OBS_DERIV_TO_ASSETS"), freq="quarterly"),
    canonical_status="canonical_voting",   # Phase 2 only; Phase 1 -> "candidate"
    canonical_subbasket="X_agg.v1_off_balance_sheet",
    canonical_alignment_note="OBS/assets from SEC XBRL (P1) / FFIEC Y-9C HC-L (P2).",
),
```

## 5. Open gates before v1 may vote
- §7.2.3 equal-weight (1/3) with v2/v3 — but v2 (`NFCILEVERAGE`) is itself a
  red-line composite and v3 has no data; decide whether X_agg votes on a
  single canonical sub-basket meanwhile, or stays `NOT_IMPLEMENTED` until ≥2
  clean sub-baskets exist.
- Independence of OBS/assets from M (funding gaps), D (depth), K (curvature).
- Quarterly→daily alignment / forward-fill policy for the panel join.
