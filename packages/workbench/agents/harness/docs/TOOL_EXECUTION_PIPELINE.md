# Tool execution pipeline (Structural Research Harness)

This documents the **intended** order of operations for governed tool calls.  
Implementation: `tools/registry.py` (`run_tool`). Policy hooks: `hooks/pre_tool_use.py`, `hooks/post_tool_use.py`.

## Ordered stages

1. **Resolve tool** — Look up `ToolSpec` by id; unknown tools fail fast.
2. **Mode allowlist** — Reject if current agent mode is not in `allowed_modes` (and explore-mode hides mutation tools).
3. **Prechecks** — Run any `required_prechecks` registered for the tool (extension point).
4. **Risk classification** — `hooks/risk_classifier.classify` for policy metadata.
5. **Pre-tool policy** — `hooks/pre_tool_use.evaluate`: boundary rules, feature flags, permissions.yaml.  
   Outcomes: allow, ask (logged), deny, require_manual_review. **Hook allow never overrides a global deny.**
6. **Dry run** — If `dry_run=True`, return success without invoking the handler.
7. **Execute handler** — `ToolSpec.handler(input, dry_run)`; exceptions are caught and **never** leak raw tracebacks to clients.
8. **Post-failure hook** — On exception or `ok=False`, `post_tool_failure` and structured failure events.
9. **Postchecks** — On success:
   - `write_event` → `post_tool_use` + Learning Hub ingestion via `system_event_writer`
   - `post_verify` → record verification evidence after validation-style tools

## Relationship to Claude Code

This matches the same narrative as a mature agent runtime: **validate → gate → execute → observe**, with hooks as a **policy layer** rather than ad-hoc checks.

## Related files

- `tools/registry.py` — orchestration
- `hooks/pre_tool_use.py` — policy evaluation chain
- `hooks/post_tool_use.py` — post_success / post_failure
- `policies/boundary_rules.yaml`, `policies/permissions.yaml`, `policies/feature_flags.yaml`
