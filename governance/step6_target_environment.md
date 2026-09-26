# Step 6 — Target Environment Bootstrap + Formal Proof

Status: `LOCAL_REHEARSAL_PASS_TARGET_BOOTSTRAP_PENDING`

Step 6 moves the formal reliability proof to the eventual target environment.
The Mac remains a rehearsal host only. No 14-day formal proof has been started
on the Mac, and no existing Mac/launchd evidence is silently reclassified as
Linux/systemd evidence.

## Local Rehearsal

The bounded local rehearsal surface is already available:

- clean-shell import and CLI execution without ambient `PYTHONPATH`;
- locked workspace installation through `uv sync --locked --all-packages`;
- explicit temporary Data/Output roots through `RuntimeContext`;
- failure propagation and single execution-spine tests;
- committed publication evidence from the r10 scheduled-path rehearsal;
- isolated structural restore fidelity from Step 5E-A.

These demonstrate that the runtime can migrate. They do not constitute target
host proof or a reliability qualification window.

The latest bounded rehearsal also passed the locked install, clean-shell import,
portable `pipeline validate` (83 steps / 40 edges), and the focused portable,
failure-propagation, and execution-spine suites (15 tests). A compatibility shim
was repaired so it no longer exports the removed `STEP_ENV` symbol; this did not
change scheduler identity, provider routing, or reliability rules.

## Target Bootstrap Contract

The first target is intentionally small:

```text
Linux
  → dedicated service user
  → uv locked environment
  → systemd service + timer
  → persistent Data / Output
  → host implementation of SecretProvider
  → snapshot / restore mechanism
```

The service and timer templates are:

- `configs/systemd/verity-daily.service.in`
- `configs/systemd/verity-daily.timer`

The service template contains placeholders rather than Mac paths. It passes
the canonical scheduler identity through environment metadata and invokes the
installed `verity` entrypoint. `EnvironmentFile` is only a host adapter for
the provider-neutral `SecretProvider`; domain code does not depend on the
file's location.

Docker, Kubernetes, distributed execution, and microservices are excluded
from the default bootstrap. Introducing one would require an independent
architecture decision.

## Shadow Observation

After target bootstrap, the first target runs use:

```text
trigger_kind=scheduled
scheduler_kind=systemd
authority=shadow
isolated Output
shared current pointer disabled
promotion_allowed=false
```

The comparison must preserve the same execution spine and compare provider
decision, raw acquisition identity, canonical lineage, M/D result,
`neutral_state`, generation contents, failure propagation, runtime, and
recovery. Shadow is an observation boundary; it must not elevate authority or
write decision-consumer surfaces.

## Formal 14-Day Proof

Formal proof starts only after target bootstrap and target shadow observation
are accepted. The verifier remains
`tools/verify_data_reliability_window.py`; its existing scheduler-neutral
qualification rule is unchanged. A qualified day requires:

```text
accepted release
∧ accepted scheduler
∧ scheduled trigger
∧ provider decision usable
∧ freshness usable
∧ core chain complete
∧ committed generation
∧ authority not diagnostic-only
```

The proof requires 14 qualified days and 14 consecutive qualified days. A
same-day retry does not add a day. Failed runs remain in evidence history;
carry-forward does not become fresh success.

The five required scenario classes remain explicit:

1. stale/cache expiry;
2. schema/parity drift;
3. fallback/carry-forward;
4. provider failure;
5. recovery.

The machine-readable status is
`governance/step6_target_environment.yaml`. The repeatable bounded readiness
audit is `tools/audit/step6_target_environment.py`.
