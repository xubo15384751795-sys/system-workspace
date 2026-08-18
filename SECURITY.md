# Security Policy

This repository contains governed research and data-acquisition runtime code.
Please do not disclose credentials, private market data, or a suspected
security issue in a public issue or pull request.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting channel for this repository when
it is enabled. If that channel is unavailable, contact the repository owner
through a private GitHub message and include:

- the affected commit or branch;
- the smallest reproducible proof, without secrets or private data;
- impact, prerequisites, and likely data exposure; and
- a suggested mitigation or safe disclosure timeline, if known.

Do not test against production data, launchd jobs, external providers, or
third-party systems without explicit authorization.

## Scope

The highest-risk areas are:

- provider egress, endpoint registration, and request DTO validation;
- `system_runtime/` publication, admission, and recovery state machines;
- GitHub Actions and repository governance configuration; and
- credentials, query parameters, logs, notifications, and generated artifacts.

Security findings must be evaluated separately from data-quality or research
methodology issues, although a finding may affect both.

## Handling

Maintainers will acknowledge a report when practical, reproduce it in an
isolated fixture, assign severity and an owner, and record the remediation or
accepted residual risk. A fix is not considered closed until the relevant
negative test or static control is present and the default path is checked.

## Repository checks and enforcement boundary

Local Git hooks are advisory controls, not a security boundary. They can always
be bypassed with `git push --no-verify`, so a local hook pass must never be
reported as remote enforcement. When repository protection is available, the
server-side required check (the exact `merge-gate` context) is the final
authority for accepting a change. If that protection is unavailable, the
repository must state `COMPENSATING_CONTROL_ONLY` and retain the local hook,
SHA-bound manifest, and routing decision as compensating evidence rather than
claiming that the server rejected an unsafe push.
