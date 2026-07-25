---
schema_version: system.pace.v1
layers:
  L4:
    cadence: "quarterly or rarer"
    paths:
      - governance/system_constitution.yaml
      - ROUTING_CONSTITUTION.md
      - MODULES.md
      - FOLDER_OWNERSHIP.md
      - PACE.md
  L3:
    cadence: "monthly to quarterly"
    prefixes:
      - governance/
      - protocols/
      - module_contexts/
      - .github/workflows/
      - system_runtime/
    paths:
      - .pre-commit-config.yaml
  L2:
    cadence: "daily to weekly"
    prefixes:
      - packages/
      - scripts/
      - system_cli/
      - caselab_context/
      - caselab_runtime/
      - research_terminal/
  L1:
    cadence: "minutes to days"
    prefixes:
      - Output/sandbox/
      - tests/
---

# PACE — change at the speed of the layer

| Layer | What lives here | Change posture |
|---|---|---|
| L1 — probe | `Output/sandbox/`, disposable experiments and test probes | Change freely. No authority, no promotion, easy deletion. |
| L2 — service | module implementation, commands and product surfaces | Small reviewed changes; ordinary tests and rollback. |
| L3 — control | protocols, registries, CI, runtime coordination and module contracts | A routing decision is mandatory. Version schemas; run old and new versions together during migration. |
| L4 — identity | constitution, ownership and routing identity | Change rarely. A routing decision plus an explicit observation window and rollback is mandatory. |

The rule is deliberately asymmetric: L1/L2 move first, while L3/L4 absorb the
change slowly through version coexistence. A fast layer must never silently
rewrite a slow layer's meaning.

Enforcement: `scripts/commands/ci/check_pace_routing.py`. A staged change that
touches L3/L4 must include a new or changed file under
`governance/routing_decisions/`. That decision must declare a Cynefin domain; a
complex-domain decision must also preregister its scope, expected observation,
observation window and rollback.
