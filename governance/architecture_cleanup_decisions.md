# Architecture Cleanup Decisions

**Created:** 2026-06-17
**Authority:** Highest governance level — referenced by README.md, MODULES.md, system_constitution.yaml
**Supersedes:** Any conflicting root script count targets or ad-hoc cleanup rules

---

## Core Principle

```
系统允许探索，但不允许未登记的探索影响判断；
系统允许复杂，但复杂必须有身份、边界和生命周期；
系统允许模块独立使用，但模块协作必须通过契约和证据链。
```

---

## Decisions

### D1: Structure over count

Root scripts are measured by **structural role**, not by file count.

Every root script must be one of:
1. **User entry**: ./sys, check, ask, refresh, open
2. **Pipeline entry**: daily_run and step wrappers
3. **Governance entry**: audit, freshness, quality, registry

If a script contains module business logic, it should eventually live in that module.
Root scripts only do dispatch, never hide business logic.

### D2: subprocess now, module runner later

`daily_run.py` uses subprocess today. That's acceptable, but each subprocess step
must be registered with module-runner-grade metadata in `daily_pipeline_registry.yaml`:

- owner
- mode (subprocess)
- future_callable (module:function)
- input_contract
- output_contract
- failure_behavior
- affects_core_judgment

Future migration: change `mode: subprocess` to `mode: callable`. No architecture rewrite.

### D3: Deferred work must be declared at highest level

Any task that cannot be completed short-term must be registered in
`governance/deferred_work_register.yaml` with:

- id, title, owner, status
- reason for deferral
- review_date, hard_deadline
- risk_if_ignored, fallback_if_expired

Deferred work cannot be forgotten — it must have a maturity date.

### D4: All data converges toward Harvester

Harvester is the canonical data authority. Non-Harvester data is allowed only as
marked transitional/research evidence. Unmarked non-Harvester data cannot affect
core judgment.

Modules request data from Harvester via `governance/data_request_registry.yaml`,
not by permanently bypassing Harvester with direct acquisition.

### D5: Output/current is authority only

`Output/current/` contains only current authority entry points:

```
00_READ_ME_FIRST.md
framework_output.json
status.json
quality_validation.json
freshness_manifest.json
next_actions.md
artifact_navigator.*
learning_summary.md
system_health.md
```

Legacy display (latest_report.html, latest_dashboard.json, latest_screenshot.png,
latest_run) must not live in Output/current. Move to Output/archive/legacy_display/.

### D6: Modules must be independently usable

```
Harvester    — can be used standalone as evidence release builder
Framework    — can be used standalone as structural diagnostics engine
Workbench    — can be used standalone as artifact navigator / judgment UI
Learning Hub — can be used standalone as governance memory / run audit
System       — is the composition of all modules, not a monolithic dependency
```

Future monorepo structure (if pursued):

```
packages/harvester
packages/framework
packages/workbench
packages/learning_hub
```

### D7: Clean and traceable are not in conflict

- Module boundaries are clean: clear ownership, clear contracts.
- Collaboration chains are traceable: every data flow has provenance.
- Experiments exist: but they have identity, owner, TTL, and cannot impersonate judgment.
- Complexity is allowed: but it must have structure, lifecycle, and accountability.

---

## Referenced by

- README.md (top)
- MODULES.md (top)
- governance/system_constitution.yaml
- governance/deferred_work_register.yaml
- governance/data_request_registry.yaml
- governance/output_routing_policy.yaml
- governance/module_contract_registry.yaml
