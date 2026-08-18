## Change summary

- What changed:
- Master-plan item / routing decision:
- Why this is in scope:

## Evidence

- Plan digest / policy hash:
- Code SHA:
- Default path exercised:
- Tests and commands:
- Remote CI / required check evidence:

## Data and Output mutation

- [ ] No `Data/` mutation
- [ ] No `Output/` mutation
- [ ] Mutation was explicitly authorized and is described below

If `Data/` or `Output/` changed, record before/after hashes, run/release/
generation IDs, and the exact rollback command. Do not use a focused test or
dry-run as evidence of zero mutation without checking the relevant paths.

## Runtime and governance boundaries

- [ ] Default scheduler / Dagster / CLI path is identified.
- [ ] Failure, partial, blocked, and authority semantics are explicit.
- [ ] Provider/release/vintage and same-run lineage are explicit where relevant.
- [ ] No new raw URL, credential, or network sink was introduced.
- [ ] No remote ruleset, branch protection, PR, push, or deployment change is
      implied by this PR.
- [ ] Local Git hooks are advisory and bypassable (`git push --no-verify`);
      server-side required-check evidence is recorded separately and is the
      final enforcement authority when available.

## Rollback and residual risk

- Rollback:
- Known residual risk:
- Follow-up owner and trigger:

## Final checklist

- [ ] Scope/diff reviewed against the plan.
- [ ] Focused tests pass.
- [ ] Required-path tests pass or the blocker is recorded.
- [ ] Clean-room / package / recovery evidence is included where applicable.
- [ ] The change is not being described as production-deployed before commit,
      push, and runtime evidence exist.
