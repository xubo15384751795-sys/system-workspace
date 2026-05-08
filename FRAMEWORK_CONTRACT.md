# Framework Contract

A framework integrates with the Workbench by publishing protocol-shaped outputs.
The Workbench reads those outputs; it does not inspect framework internals.

## Required Files

1. `framework.yaml`
2. framework output JSON
3. run manifest
4. evidence links
5. basic summary
6. advanced diagnosis
7. next actions

## Required Boundary

Frameworks consume admitted evidence. They do not acquire external provider data.

## Output Shape

Framework output must expose:

- `basic`: user-facing status, pressure, confidence, and summary
- `advanced`: framework-specific diagnosis
- `evidence_links`: files or dashboards supporting the diagnosis
- `next_actions`: suggested follow-up inspection steps
- `artifacts`: report, manifest, and dashboard paths
