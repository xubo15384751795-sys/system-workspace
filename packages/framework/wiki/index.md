# Structural Risk Lab Wiki

This wiki anchors the policy/knowledge layer of the project. The system flow is:

```text
raw evidence -> cleaned data -> proxy/diagnostic code -> wiki interpretation -> paper output
```

The wiki may interpret evidence, but it cannot create evidence. It may prepare
paper language, but it cannot bypass the [Claim Registry](claims/claim_registry.md).

## Variables

- [S_t - Subject Configuration](variables/S_subjects.md)
- [A_t - Anchor Configuration](variables/A_anchors.md)
- [L_t - Liquidation Path Feasibility](variables/L_liquidation_paths.md)
- [V_t - Verifiability Density](variables/V_verifiability_density.md)
- [P_t - Positional Power](variables/P_positional_power.md)
- [tau_t - Latency](variables/tau_latency.md)
- [M_t - Anchor Mismatch](variables/M_anchor_mismatch.md)
- [D_t - Effective Degrees Of Freedom](variables/D_degrees_of_freedom.md)
- [K_t - Transition Curvature](variables/K_transition_curvature.md)
- [X_t - Shadow Accumulation](variables/X_shadow_accumulation.md)

## Mechanisms

- [Scalar Compression Failure](mechanisms/scalar_compression_failure.md)
- [Anchor Mismatch](mechanisms/anchor_mismatch.md)
- [Path Contraction](mechanisms/path_contraction.md)
- [Shadow Accumulation](mechanisms/shadow_accumulation.md)
- [Forced Realization](mechanisms/forced_realization.md)
- [Reflexive Feedback](mechanisms/reflexive_feedback.md)
- [Non-Commutativity](mechanisms/non_commutativity.md)
- [Curvature Deformation](mechanisms/curvature_deformation.md)
- [Crisis Singularity](mechanisms/crisis_singularity.md)

## Cases

- [Case Template](cases/template_case.md)
- [1998 LTCM](cases/1998_LTCM.md)
- [2008 GFC](cases/2008_GFC.md)
- [2015 CHF Peg Break](cases/2015_CHF_peg_break.md)
- [2020 Treasury Basis](cases/2020_treasury_basis.md)
- [2022 LDI](cases/2022_LDI.md)
- [2023 SVB](cases/2023_SVB.md)
- [2024-08-05 Yen Carry Stress](cases/2024_08_05_yen_carry.md)

## Institutions

- [AQR](institutions/AQR.md)
- [Man AHL](institutions/Man_AHL.md)
- [Brevan Howard](institutions/Brevan_Howard.md)
- [DE Shaw](institutions/DE_Shaw.md)
- [Two Sigma](institutions/Two_Sigma.md)
- [Bridgewater](institutions/Bridgewater.md)
- [Goldman Sachs](institutions/Goldman_Sachs.md)
- [BIS](institutions/BIS.md)
- [OFR](institutions/OFR.md)
- [Federal Reserve](institutions/Fed.md)

## Literature

- [Systemic Risk](literature/systemic_risk.md)
- [Intermediary Asset Pricing](literature/intermediary_asset_pricing.md)
- [Shadow Banking](literature/shadow_banking.md)
- [Market Microstructure](literature/market_microstructure.md)
- [Financial ML](literature/financial_ml.md)
- [Geometric Finance](literature/geometric_finance.md)

## Source And Dataset Notes

Dataset/source notes now live in Harvester:

- [Dataset Notes](../../Structural%20Risk%20Harvester/docs/datasets/README.md)

## Methods

- [Proxy Construction](methods/proxy_construction.md)
- [Residualization](methods/residualization.md)
- [Morphology Classifier](methods/morphology_classifier.md)
- [Benchmark Design](methods/benchmark_design.md)
- [Event Replay](methods/event_replay.md)
- [Rejection Gates](methods/rejection_gates.md)

## Claims

- [Claim Registry](claims/claim_registry.md)
- [Formal Claims](claims/formal_claims.md)
- [Empirical Claims](claims/empirical_claims.md)
- [Speculative Claims](claims/speculative_claims.md)
- [Rejected Or Weakened Claims](claims/rejected_or_weakened_claims.md)

## Operating Rule

If a page supports a paper-facing sentence, that sentence must trace to one of:

- a registered data manifest
- a diagnostic output manifest
- a formal argument
- a case memo marked as diagnostic grounding
- a claim registry entry
