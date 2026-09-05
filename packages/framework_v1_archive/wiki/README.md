# Wiki Layer Contract

The wiki is the policy/knowledge layer for the Structural Risk Lab. It is not a
generic note archive. Its job is to preserve definitions, interpretation
boundaries, case diagnoses, institution context, method rules, dataset roles,
and the claim registry. Dataset/source ownership notes live in the peer
Harvester system under `../../Structural Risk Harvester/docs/datasets/`.

Every non-template wiki page should link back to
[`claim_registry.md`](claims/claim_registry.md) when it contains interpretive or
paper-facing language.

## Allowed

- Define variables and say what they are not.
- Connect mechanisms to cases and datasets.
- Mark institution materials as corpus context, not proxy data.
- Weaken or reject claims when evidence is insufficient.
- Point to code and reports with explicit role labels.

## Forbidden

- Creating empirical claims outside `wiki/claims/claim_registry.md`.
- Treating PDF/chart extraction as formal data without a manifest.
- Letting benchmark indicators define `Sigma_t` core proxies.
- Turning case diagnosis into universal crisis sequence claims.

## Page Families

- `variables/`: stable definitions for `S/A/L/V/P/tau/M/D/K/X`
- `mechanisms/`: structural mechanisms and rejection gates
- `cases/`: event diagnoses and diagnostic grounding
- `institutions/`: public institutional corpus context
- `literature/`: research literature map
- `methods/`: proxy, benchmark, replay, residualization, and rejection methods
- `claims/`: formal, diagnostic, empirical, speculative, weakened, and rejected claims
