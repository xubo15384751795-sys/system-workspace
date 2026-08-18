# Learning Hub Lifecycle Check

## Trigger
When assessing subsystem health, improvement queue depth, event ingestion pipeline integrity, or auto-approval readiness.
Triggered before any `learning_hub.ingest_events`, `learning_hub.write_verification_record`, or when improvement queue shows > 50 stale items.
Also triggered when event ingestion failure rate exceeds 20%.

## Scope
- Improvement queue lifecycle state tracking
- Proposed → Approved → Implemented → Verified → Failed state transitions
- Event ingestion pipeline health
- Recurrence pattern detection (which subystems/rule_ids fail most)
- Auto-approval readiness assessment
- Subsystem health scoring

## Read First
- `Output/system_learning/latest/improvement_queue.md`
- `Output/system_learning/latest/system_health_report.md`
- `Output/system_learning/events/events_<date>.jsonl` — recent events
- `policies/boundary_rules.yaml` — `boundary.deny.learninghub-modifies-peer-source`
- `policies/feature_flags.yaml` — `learning_hub.auto_approval: disabled`, `learning_hub.llm_issue_classifier: exploratory`
- `packages/learning_hub/src/governance/codebase`
- `packages/workbench/agents/harness/tools/task_router.py` — routing and expert activation logic

## Steps

### Step 1: Inspect Queue
```
system tools run learning_hub.inspect_queue --mode explore --json
```
Analyze: total items, by state (Proposed/Approved/Implemented/Verified/Failed), by subsystem, by severity, by priority. Identify items stale > 30 days.

### Step 2: State Transition Audit
For each queue item, trace lifecycle:
```
Proposed → Approved → Implemented → Verified → Failed (recycle)
```
Identify:
- Items stuck in `Proposed` > 14 days (unreviewed)
- Items stuck in `Approved` > 30 days (unimplemented)
- Items in `Failed` without re-proposal
- Items marked `Verified` without verification event

### Step 3: Event Ingestion Health
```
system tools run learning_hub.query_recurrence --mode explore pattern=event_ingestion
```
Analyze event ingestion pipeline:
- Events written vs events ingested (loss rate)
- Ingestion failures by error type
- Event log file size and rotation health

### Step 4: Recurrence Pattern Detection
```
system tools run learning_hub.query_recurrence --mode explore pattern=boundary
system tools run learning_hub.query_recurrence --mode explore pattern=deny
system tools run learning_hub.query_recurrence --mode explore pattern=verification
```
Identify: most frequent rule_id violations, subsystems with highest deny rate, verification failures by category.

### Step 5: Auto-Approval Readiness
```python
from policies.feature_flags import is_enabled, get_feature
feat = get_feature("learning_hub.auto_approval")
assert feat.is_disabled  # must be disabled
# Check promotion requirements:
# - governance_board_review (pending)
# - approval_accuracy_threshold_met (not met)
# - false_positive_rate_audit (not done)
```

### Step 6: Subsystem Health Scoring
Based on collected data, score each subsystem on:
- Event success rate (target: > 90%)
- Verification pass rate (target: > 85%)
- Queue turnover rate (target: > 70% items closed within 30 days)
- Policy violation rate (target: < 5% of invocations)

## Required Evidence
- [ ] Queue state report (by state, subsystem, severity, staleness)
- [ ] State transition audit (stuck items, failed items, verification gaps)
- [ ] Event ingestion health (loss rate, failure types, log health)
- [ ] Recurrence pattern report (top rule_ids, subsystems, failure categories)
- [ ] Auto-approval readiness assessment
- [ ] Subsystem health scores (all subsystems)
- [ ] Recommended improvements (items to add to queue)

## Forbidden
- Modifying peer subsystem source code (`boundary.deny.learninghub-modifies-peer-source`)
- Enabling `learning_hub.auto_approval` without governance board review
- Promoting `learning_hub.llm_issue_classifier` output to paper or production
- Marking items as `Verified` without verification event evidence
- Treating recurrence patterns as proof of causation without investigation

## Output Artifact
```json
{
  "audit_id": "learning-hub-lifecycle-<date>",
  "audit_type": "learning_hub_lifecycle",
  "verdict": "PASS | FAIL | PARTIAL",
  "evidence": {
    "queue": {
      "total": 0,
      "by_state": {},
      "by_subsystem": {},
      "stale_count": 0
    },
    "state_transitions": {
      "stuck_items": [],
      "failed_items": [],
      "verification_gaps": []
    },
    "ingestion_health": {
      "loss_rate": 0.0,
      "failure_types": {},
      "log_health": "ok"
    },
    "recurrence_patterns": {
      "top_rule_ids": [],
      "top_subsystems": [],
      "top_failure_categories": []
    },
    "auto_approval_readiness": {
      "status": "disabled",
      "blockers": ["governance_board_review", "accuracy_threshold", "fp_audit"]
    },
    "subsystem_scores": {
      "harvester": {"event_success": 0.0, "verification_pass": 0.0, "queue_turnover": 0.0, "violation_rate": 0.0},
      "deformation": {...},
      "learning_hub": {...}
    }
  },
  "recommended_improvements": [],
  "output_path": "Output/system_learning/audits/learning-hub-lifecycle-<date>.json"
}
```
