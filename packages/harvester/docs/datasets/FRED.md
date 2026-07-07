# FRED

## 1. Dataset Role

Official/public data access route for many proxy and benchmark series.

## 2. Source And Access

Federal Reserve Economic Data API or downloaded releases.

## 3. Frequency Policy

Each series needs native frequency, target frequency, release lag, and
aggregation policy.

## 4. Allowed Uses

- proxy core when series is structurally registered
- benchmark/control when series is broad stress or volatility
- paper output only after manifest and no-lookahead check

## 5. Forbidden Uses

- implicit release timing assumptions
- mixing benchmark series into proxy core without explicit registry change

## 6. Manifest Requirements

- series-level manifest
- no-lookahead check
- allowed-use tag

## 7. Related Code

- `src/data/adapters/public_adapters.py`
- `src/data/gateway/data_hub.py`

## 8. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
