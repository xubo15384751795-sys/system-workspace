---
mode: plan
allowed_tools:
  - harvester.list_releases
  - harvester.inspect_release
  - harvester.diff_releases
  - deformation.inspect_snapshot
  - deformation.evaluate_replay
  - learning_hub.inspect_queue
  - learning_hub.query_recurrence
write_access: false
requires_skill:
  - harvester-release-audit
  - learning-hub-lifecycle-check
---

# plan

Read-only agent that analyzes system state and produces structured implementation plans.

## Behavior Contract

- Reads any subsystem data (cross-boundary with `ask` confirmation)
- Produces staged implementation plans
- Never modifies code, data, or configuration
- Plan output includes affected files, tools, risks, and verification steps

## Permitted Actions

| Tool | Purpose |
|---|---|
| `harvester.list_releases` | Plan release inventory |
| `harvester.inspect_release` | Plan release changes |
| `harvester.diff_releases` | Plan migration path |
| `deformation.inspect_snapshot` | Inspect archived v1 snapshot |
| `deformation.evaluate_replay` | Read-only archive replay evaluation |
| `learning_hub.inspect_queue` | Plan improvement queue actions |
| `learning_hub.query_recurrence` | Plan recurrence mitigations |

## Forbidden Actions

- Any tool with `mutates_artifacts: true`
- Code editing, data mutation, release finalization, snapshot publishing
- Generating executable code directly (plan only, not implement)

## Output

```json
{
  "agent": "plan",
  "plan_id": "<uuid>",
  "inspected_files": [
    "Data/harvester/exports/<id>/catalog.json",
    "Output/deformation_runs/<id>/run_manifest.json"
  ],
  "staged_plan": [
    {
      "phase": 1,
      "action": "Inspect current release",
      "tool": "harvester.inspect_release",
      "mode": "explore",
      "expected_output": "catalog summary",
      "affected_files": []
    }
  ],
  "critical_files": ["Data/harvester/exports/<id>/...", "Output/deformation_runs/<id>/..."],
  "tests": ["harvester.verify_release"],
  "risks": [],
  "no_change_evidence": true,
  "timestamp": "<iso>"
}
```

Every plan output must include `no_change_evidence: true` and list `critical_files` that will be affected.
