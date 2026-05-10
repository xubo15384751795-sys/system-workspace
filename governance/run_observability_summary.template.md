# Run Observability Summary
Run ID: TEMPLATE

## 1. Authority
- Authority violations: 0
- Authority configs enabled: 0
- Legacy fallback used: NO

## 2. Decision Impact
| Impact | Count |
|---|---:|
| BLOCK | 0 |
| ACTION_REQUIRED | 0 |
| WARN_ONLY | 0 |
| DISPLAY_ONLY | 0 |
| NONE | 0 |

## 3. Semantic Risk
| Concept | Status | Distance | Verdict |
|---|---|---:|---|
| K | PROXY_REDUCED | 3 | Use as partial only |
| X_PRE | DATA_TRUNCATED_PROXY | 4 | Cannot support full-history claim |
| V | NOT_IMPLEMENTED | N/A | V-to-X claim unsupported |

## 4. Report Gate
- Reports checked: 0
- Missing verdict: 0

## 5. Promotion Gate
- Routing decision found: UNKNOWN
- may_promote_current_snapshot: UNKNOWN
- Promotion result: UNKNOWN

## Actionable Verdict
- Verdict: INVESTIGATE
- Severity: MEDIUM
- Owner: governance
- Required Action: Replace template counts with run-local governance observations.
- Closure Condition: Required governance traces exist and promotion decision is explicit.
