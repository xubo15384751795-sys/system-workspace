# Architecture Reality Decisions

**Authority level:** Constitution layer — overrides all audit reports, historical
documents, and module-level claims except `system_constitution.yaml`.

**Created:** 2026-06-16
**Last reviewed:** 2026-06-16

---

## 1. Highest Architecture Principles

### 1.1 Four-Layer Division

| Layer | Responsibility |
|-------|---------------|
| **Harvester** | Sole data and evidence entry. Acquisition, processing, provenance, quality, TTL, snapshots. |
| **Framework** | Core judgment layer. Consumes Harvester evidence bundles only. Does not acquire data. |
| **Workbench** | User entry, display, Q&A, run navigation, explanations. |
| **Learning Hub** | Feedback, correction, governance memory, error attribution, improvement queue. |

### 1.2 Hard Principles

```text
Framework has no acquisition authority.
All evidence enters through Harvester.
Experimental artifacts are gradient sources, not judgment sources.
```

- **Framework** can express data needs but cannot fetch data, read API keys, or make HTTP requests to providers.
- **Harvester** is the sole entry point for all data, including: provider data, NLP extraction results, CaseLab event cards, user annotations, ML outputs, backtest results, market feedback, file imports, external API results, and snapshots.
- **Framework** consumes evidence bundles published by Harvester. It does not care how data was obtained — only whether evidence is fresh, provenance is complete, quality is acceptable, and the protocol is satisfied.
- **Experimental artifacts** (backtest, ML, Qlib, experimental NLP) can influence training, calibration, weight adjustment candidates, feedback, gradient tasks, and error attribution. They cannot directly produce core judgments, current state assessments, or trade decisions.

### 1.3 Evidence Flow

```text
Correct:
  source -> Harvester -> evidence bundle -> Framework judgment

Forbidden:
  source -> Framework judgment (direct)
  experimental_output -> Framework core_judgment (direct)
```

Experimental feedback flows through:

```text
experimental_feedback -> Harvester -> Learning Hub / calibration
```

Not:

```text
experimental_output -> Framework judgment
```

---

## 2. Legacy DataHub Freeze

### 2.1 Status

The legacy DataHub acquisition layer (`src/data/data_sources.py`, `src/data/gateway/data_hub.py`, `src/data/adapters/`) is frozen. It is retained for:

- Legacy replay
- Dual-path comparison
- Migration validation

### 2.2 Rules

1. `build_system()` only allows Harvester backend for production runs.
2. `ALLOW_LEGACY_DATAHUB` cannot affect the main system — it is for replay/compare only.
3. `data_sources.py` and `data_hub.py` are marked `LEGACY_COMPATIBILITY_ONLY`.
4. Legacy acquisition is removed from the public API.
5. Boundary tests forbid Framework main paths from containing API keys or HTTP client imports.

### 2.3 Sunset

Legacy files have a `retire_after: 2026-07-15` deadline. After that date, they move to `scripts/archive/` and are removed from all import paths.

---

## 3. Evidence Bundle Protocol

### 3.1 Required Fields

Every Harvester evidence release must contain:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique release identifier |
| `source` | string | Data source (FRED, SEC, etc.) |
| `created_at` | ISO-8601 | When the evidence was created |
| `expires_at` | ISO-8601 | When the evidence expires (created_at + ttl_days) |
| `ttl_days` | integer | Time-to-live in days (default: 3) |
| `provenance` | object | Source, method, vintage |
| `quality_status` | enum | `fresh`, `acceptable_lag`, `stale`, `missing` |
| `schema_version` | string | Schema version identifier |
| `allowed_use` | array | `core_judgment`, `research`, `training_feedback` |
| `stale_behavior` | enum | `block`, `warn`, `allow_with_marking` |

### 3.2 Core Judgment Constraints

Core judgment only permits evidence that is:

```text
fresh + quality pass/warn + allowed_use includes core_judgment
```

### 3.3 Stale Evidence Usage

| Use case | Stale evidence allowed? | Requirement |
|----------|------------------------|-------------|
| Core judgment | No | Must block or degrade |
| Research | Yes | Must show stale warning |
| Training / feedback | Yes | Must mark as stale |
| User override | Yes | Explicit user acknowledgment |

---

## 4. Snapshot TTL Rules

### 4.1 Default Policy

```yaml
snapshot_policy:
  default_ttl_days: 3
  force_refresh_after_days: 3
  core_judgment_on_expired_snapshot: blocked
  research_use_on_expired_snapshot: allowed_with_stale_warning
  training_feedback_on_expired_snapshot: allowed_if_marked_stale
  user_override_allowed: true
```

### 4.2 Behavior

- Snapshots expire after 3 days by default.
- Core judgment on an expired snapshot must block or degrade confidence.
- Research and training can use stale data but must explicitly mark it.
- Other TTL values are user-configurable; 3 days is the default.

---

## 5. Module Status System

### 5.1 Status Enum

| Status | Meaning |
|--------|---------|
| `CANONICAL` | Main chain capability with real data, tests, and entry points |
| `ACTIVE_PARTIAL` | Runnable but has explicit blockers |
| `REAL_EXPERIMENTAL` | Has real artifacts; research/training use only |
| `PROTOTYPE_RETAIN` | Prototype retained, awaiting validation |
| `PAPER_RETAIN` | Design/code only, not connected to live system |
| `SHADOW_ACTIVE` | Produces diagnostics/records only; cannot execute authority or affect core judgment |
| `BLOCKED` | Blocked by data, dependency, or governance rule |
| `FROZEN` | Paused, not expanding |
| `RETIRED` | Decommissioned, history only |
| `UNKNOWN` | Not audited, must be resolved by deadline |

### 5.2 Transition Rules

| From | To | Requirements |
|------|----|-------------|
| `UNKNOWN` | Any | Must audit within 30 days |
| `PAPER_RETAIN` | `ACTIVE_PARTIAL` | Real data flow + at least 1 test |
| `SHADOW_ACTIVE` | `ACTIVE_PARTIAL` | Public API/CLI boundary + tests + explicit authority to act |
| `ACTIVE_PARTIAL` | `CANONICAL` | Zero blockers + all promotion_requirements met + tests passing |
| `CANONICAL` | `ACTIVE_PARTIAL` | New blocker identified |
| Any | `FROZEN` | Explicit governance decision with reason |
| Any | `RETIRED` | Explicit governance decision + no active consumers |
| `REAL_EXPERIMENTAL` | `CANONICAL` | Must pass through `ACTIVE_PARTIAL` first |

### 5.3 Audit Cadence

- `CANONICAL` modules: audit every 30 days
- `ACTIVE_PARTIAL` modules: audit every 14 days
- `UNKNOWN` modules: audit within 30 days of assignment
- All modules: audit on any governance-significant change

---

## 6. Experimental Artifacts

### 6.1 Position

Backtest, ML, Qlib, and experimental NLP are:

```text
Used for training, calibration, feedback, gradient tasks.
Not used for core judgment.
```

### 6.2 What They Can Influence

- Which variables need attention
- Which proxies should be downweighted
- Which mechanisms need more data
- Which historical analogies are invalid
- Which rules need re-evaluation

### 6.3 What They Cannot Directly Write

- `core_judgment`
- `current_state`
- `trade_decision`

---

## 7. System Run Reaction

Every system run must output a structured reaction, not just a directional call.

### 7.1 Required Fields

```yaml
reaction:
  decision: watch | request_data | refresh_snapshot | lower_confidence | research_only
  basis:
    - factor: <M|D|K|X>
      contribution: <0.0-1.0>
      direction: raises_concern | reduces_confidence | supports | neutral
      evidence: <reference>
  bottlenecks:
    - stale_snapshot
    - weak_caselab_match
    - low_proxy_quality
  next_best_actions:
    - refresh Harvester snapshot
    - request better D evidence
    - collect comparable historical cases
```

### 7.2 Principle

The system must provide: conclusion, basis with contribution weights, limiting factors, and the single most valuable next data request. This is "reverse differentiation" — not just a conclusion but the gradient of what would improve it.

---

## 8. Documentation Hierarchy

### 8.1 Four Layers

**Layer 1: Constitution** (highest authority)

```text
governance/system_constitution.yaml
governance/architecture_reality_decisions.md
governance/module_authority_registry.yaml
governance/capability_registry.yaml
MODULES.md
```

Decides: who can do what, what status each capability has, what architectural decisions are final.

**Layer 2: Protocol**

```text
protocols/*.schema.json
governance/*_policy.yaml
```

Decides: interfaces, TTL, claim ceilings, promotion gates, data formats.

**Layer 3: Runtime**

```text
Output/current/
Output/system_learning/latest/
Data/system_index/
```

Answers: what actually happened today.

**Layer 4: Evidence**

```text
governance/audit-reports/*
historical reports
old decisions
```

Role: historical evidence only. Cannot override constitution layer.

### 8.2 Conflict Resolution

```text
Old audit report conflicts with capability_registry -> use capability_registry
Old document conflicts with architecture_reality_decisions -> use architecture_reality_decisions
Output/current conflicts with MODULES.md -> trigger architecture reality audit
```

---

## 9. Submodule Structure

### 9.1 Statement

```text
The 4-submodule structure was transitional. Consolidation into packages/
was executed 2026-07-07 (routing decision 2026-07-07-submodule-consolidation).
```

### 9.2 Buffer Period

30-45 days from 2026-06-16. **Executed 2026-07-07** — within the buffer window.

### 9.3 Buffer Period Goals

1. Clear dirty submodule state. ✅ (submodules deinit'd, .gitmodules removed)
2. Unify test entry points. ✅ (conftest.py + _workspace_imports.py retargeted)
3. Unify Python version and dependency strategy. ✅ (requires-python >=3.12, numpy/pandas/pyarrow unified)
4. Clarify migration path. ✅ (routing decision record)
5. Final structure: single-repo workspace with `packages/` directory. ✅

### 9.4 Target Structure (EXECUTED)

```text
System/
├── packages/
│   ├── framework/
│   ├── harvester/
│   ├── workbench/
│   └── learning_hub/
├── protocols/
├── governance/
├── scripts/
├── Data/
└── Output/
```

---

## 10. Architecture Reality Audit

### 10.1 Mechanism

`scripts/architecture_reality_audit.py` — runs weekly or after major changes.

### 10.2 Checks

- Document says forbidden; code still does it.
- Framework appears with API key or HTTP client.
- `MODULES.md` says PAPER but Data/Output has artifacts.
- Deprecated files still imported by main entry points.
- Root scripts directly importing provider clients such as OpenBB.
- Root scripts importing Agent Routing internals instead of using public entrypoints.
- `scripts/daily_run.py` steps missing from `governance/daily_pipeline_registry.yaml`.
- Daily pipeline steps still marked `blocked` or `compatibility`.
- Output artifacts not registered.
- `latest` symlink points to old artifact.
- Experimental artifacts leak into core judgment.
- Dirty submodule files imported by main entry point.

### 10.3 Output

```text
Output/system_learning/latest/architecture_reality_audit.md
```

### 10.4 Purpose

Close the gap between "what humans say should be true" and "what agents verify is actually true."

---

## 11. Artifact Lifecycle

### 11.1 Policy

| Category | TTL | Unregistered | Unconsumed | Stale in main path |
|----------|-----|-------------|------------|-------------------|
| current | none | must register | — | — |
| snapshot | 3 days | — | — | block |
| experimental | 7 days | abandoned report | mark frozen | block |
| training_feedback | 7 days | — | — | allowed if marked stale |

### 11.2 Rules

- 7 days unregistered: enters abandoned report.
- 7 days unconsumed: marked frozen.
- 7 days without refresh but referenced by main entry: block.
- Not deleted immediately, but cannot continue to pretend active.

---

## 12. Verification Criteria

After full implementation, the system must satisfy:

1. Framework main path cannot acquire external data.
2. Harvester is the sole evidence entry point.
3. Expired snapshots cannot support core judgment.
4. Experimental artifacts can only be used for training, calibration, and feedback.
5. Every run produces a reaction with basis, contribution weights, bottlenecks, and next-best-actions.
6. `MODULES.md`, capability registry, and Output reality are consistent.
7. Old audit reports cannot override new architectural decisions.
8. Automated audits continuously discover gaps between documentation ideals and code reality.
