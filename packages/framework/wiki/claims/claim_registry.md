# Claim Registry

This is the authoritative control surface for paper-facing claims. Agents,
scripts, notebooks, reports, and paper drafts must not expand claims beyond this
registry.

## Claim Levels

| Level | Name | Meaning |
|---:|---|---|
| 1 | Formal / architectural | Can be argued mathematically or structurally. |
| 2 | Diagnostic / proxy-based | Can be tested through proxy interfaces and case morphology. |
| 3 | Empirical / provisional | Requires data support, no-lookahead checks, and benchmark comparison. |
| 4 | Speculative / future work | Not used as a main paper claim. |
| W | Weakened | Allowed only with cautious language. |
| R | Rejected / avoid | Must not appear as a paper claim. |

## Active Claims

| ID | Claim | Level | Status | Evidence | Paper usage |
|---|---|---:|---|---|---|
| C001 | Global scalar sufficiency fails under state-dependence and non-commutativity. | 1 | active | theorem/sketch | core |
| C002 | `M/D/K/X` provide a mechanism-based stress morphology. | 2 | active | proxy/cases | core |
| C003 | `Sigma_t` outperforms NFCI globally. | R | rejected/avoid | not supported | do not claim |
| C004 | `K_proxy` measures true geometric curvature. | W | weakened | proxy only | cautious diagnostic |
| C005 | The same broad stress benchmark level can hide different structural morphologies. | 2/3 | testable | pending benchmark report | core empirical candidate |
| C006 | Portfolio overlays based on structural diagnostics beat 60/40. | 3 | secondary only | pending backtest | appendix only |
| C007 | Research corpus materials can motivate mechanisms but are not formal proxy data. | 1 | active | layer contract | governance |
| C008 | Benchmark indicators are controls and falsification surfaces by default. | 1 | active | proxy benchmark contract | governance |
| C009 | Case pages provide diagnostic grounding, not universal crisis sequence proof. | 2 | active | case pages | cautious |

## Usage Rules

- Add new paper-facing claims here before drafting paper language.
- Mark claims as weakened when proxy interpretation is only indirect.
- Mark claims as rejected when evidence does not support the stronger version.
- Never promote institution commentary into project claims without approval and evidence.
