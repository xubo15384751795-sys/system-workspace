# X_t - Shadow Accumulation

## 1. Definition

`X_t` measures hidden, delayed, or poorly verified risk mass that can later be
forced into observable realization.

## 2. What It Is Not

- Not leverage alone.
- Not private credit alone.
- Not a claim that hidden risk is fully observable.

## 3. Mechanism

`X_t` accumulates when exposure can be carried under delayed recognition,
imperfect verifiability, or positional power; it realizes when paths contract or
anchors force recognition.

## 4. Observable Traces

- emergency facility usage
- unrealized loss accumulation
- off-balance-sheet or delayed-reporting proxies
- maturity mismatch pressure

## 5. Benchmark Controls

- leverage benchmarks
- broad stress benchmarks
- funding and liquidity controls

## 6. Rejection Gate

If shadow proxies only repackage leverage benchmarks, the interpretation should
be narrowed to leverage context.

## 7. Related Cases

- [2008 GFC](../cases/2008_GFC.md)
- [2023 SVB](../cases/2023_SVB.md)

## 8. Related Code

- `src/proxies/x_shadow_accumulation.py`
- `src/derivation/structural_layers.py`

## 9. Paper Usage

Core diagnostic channel. Use as a latent-pressure proxy, not complete hidden-risk measurement.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
