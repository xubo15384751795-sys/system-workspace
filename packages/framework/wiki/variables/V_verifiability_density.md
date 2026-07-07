# V_t - Verifiability Density

## 1. Definition

`V_t` represents how densely market states can be verified through public,
timely, structured evidence.

## 2. What It Is Not

- Not truth itself.
- Not disclosure volume alone.
- Not news sentiment.

## 3. Mechanism

Low verifiability lets hidden pressure accumulate because actors cannot price,
audit, or settle disagreements quickly enough.

## 4. Observable Traces

- delayed filings
- stale valuations
- reduced balance-sheet transparency
- wider uncertainty around private exposures

## 5. Benchmark Controls

- disclosure frequency controls
- volatility and spread controls
- observability coverage measures

## 6. Rejection Gate

If verifiability measures only reproduce known volatility/spread stress, the
interpretation should be weakened.

## 7. Related Cases

- [2008 GFC](../cases/2008_GFC.md)
- [2023 SVB](../cases/2023_SVB.md)

## 8. Related Code

- `src/observability/observability_schema.py`
- `src/observability/event_observability_classifier.py`

## 9. Paper Usage

Use as a primitive that helps explain shadow accumulation and delayed realization.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
