# SEC EDGAR

## 1. Dataset Role

Official filing source. Can support verifiability, bank balance-sheet, issuer,
and case diagnostics when structured.

## 2. Source And Access

SEC EDGAR API, filings, and extracted structured fields.

## 3. Frequency Policy

Use filing date and public availability. Do not use period-end accounting data
as if it were known before filing.

## 4. Allowed Uses

- structured filing fields after manifest
- case diagnostics
- observability checks

## 5. Forbidden Uses

- PDF/table extraction as formal data without structured registration
- lookahead from later filings into earlier decision dates

## 6. Manifest Requirements

- filing manifest
- extraction schema
- no-lookahead check

## 7. Related Code

- `src/data/adapters/public_adapters.py`
- `src/observability/`

## 8. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
