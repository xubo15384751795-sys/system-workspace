# Event Replay

## 1. Purpose

Replay historical windows through evidence, proxy, operator, diagnostic, and
report layers.

## 2. Inputs

- run window
- data manifests
- event log
- proxy definitions
- benchmark panel

## 3. Outputs

- replay report
- diagnostic output manifest
- case memo
- paper-grade figures when approved

## 4. Boundary Rules

- Replays do not create new claims automatically.
- Event order analysis is diagnostic unless claim registry upgrades it.

## 5. Failure Modes

- lookahead through revised data
- event chronology errors
- overreading one case as universal law

## 6. Related Code

- `src/benchmarks/historical_replay.py`
- `scripts/run_historical_replay.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
