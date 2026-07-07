# Data Quality Rules

## 1. Dataset Role

Governance page for data admission into reports, diagnostics, and paper outputs.

## 2. Required Checks

- source identity
- local raw path
- processed path when applicable
- frequency policy
- missingness policy
- release lag or no-lookahead policy
- allowed-use tags

## 3. Allowed Uses

Data that passes these checks may enter the role specified by its manifest.

## 4. Forbidden Uses

- corpus documents as formal data without a structured dataset manifest
- benchmark indicators as proxy core without explicit reclassification
- paper claims from unmanifested notebook outputs

## 5. Manifest Requirements

Use schemas under `docs/schemas/`.

## 6. Related Code

- `src/data/quality/manifest.py`
- `src/data/quality/selector.py`
- `src/data/gateway/evidence_router.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
