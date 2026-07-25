# Governance as commitments

Governance is enforceable only when a named producer makes a testable promise
to a named consumer. Rules that cannot be rewritten in this form have no owner;
they enter the sunset queue rather than becoming another universal obligation.

| Producer | Promise | Consumer | Verification |
|---|---|---|---|
| Harvester | Releases are immutable and carry provenance, checksums and freshness state. | Framework, Workbench | Harvester package tests and release validation |
| Framework | Every diagnosis declares its evidence links, validity domain and uncertainty; it never fetches providers. | Workbench | Framework contract tests |
| Workbench | Current readout is published only from admitted, same-run artifacts and exposes blockers. | User, operators | current-bridge and publication tests |
| Learning Hub | Ledgers are append-only/derived, credit only changes review priority, and normal monitoring is silent. | All modules | Hub lifecycle and governance tests |
| Protocols | Schema versions coexist across migrations and do not encode one module's private implementation. | Producers and consumers | producer-consumer contract tests |
| Governance runtime | A failed admission blocks descendants and creates zero authoritative side effects. | S1 modules, user | incident-injection acceptance tests |
| Daily pipeline (`daily_pipeline_registry.yaml`) | Each step names an owner, inputs, outputs and failure behavior; the executor enforces the declared dependency result. | Downstream steps | registry/sequence and failure-propagation tests |
| Authority graph (`authority_graph_policy.yaml`) | Runtime topology cannot create a path from research/sandbox to core without an authorized bridge. | Judgment and publication gates | authority graph invariant test |
| Freshness (`configs/freshness_policy.yaml`) | Each owning producer supplies a content clock; consumers reject stale evidence before use. | Framework, Workbench, judgment | module freshness and hard-fail tests |
| Output routing (`output_routing_policy.yaml`) | Only run-local, lineage-valid candidates may replace current; rejected runs keep authoritative state unchanged. | Workbench and user | routing and current-chain tests |
| Incentive (`incentive_policy.yaml`) | Learning Hub credit can prioritize review but never grant authority. | Review queue | incentive anti-gaming tests |
| Experimental submissions (`experimental_submission_registry.yaml`) | Submitters declare expiry and rollback; the registry cannot promote to canonical. | Reviewers | supervisor exception tests |
| Proxy quality (`proxy_quality_rules.yaml`) | Proxy owners declare coverage, missingness and validity-domain deviations without changing judgment. | Operators | owner package quality tests |
| ML validation (`ml_validation_policy.yaml`) | ML owners disclose split, leakage and holdout evidence; outputs remain calibration-only until gated. | Capability board | ML integrity tests |
| Data retention (`data_retention_policy.yaml`) | Artifact owners declare retention and live dependencies before archival; active bridge inputs are preserved. | Runtime and auditors | retention dry-run checks |
| Capability registry (`capability_registry.yaml`) | Every capability states a real owner, maturity and allowed claims; registration alone proves no runtime effect. | Router and user | capability reality audit |
| Entrypoint registry (`entrypoint_registry.yaml`) | Command owners keep executable paths live and classify compatibility shims explicitly. | Operators and CI | entrypoint existence tests |
| Feedback sampling (`feedback_sampling_policy.yaml`) | Learning Hub deduplicates observations and separates accepted evidence from golden calibration samples. | Calibration consumers | sample-factory tests |
| Claim ladder (`claim_ladder_policy.yaml`) | Claim producers stay below their evidence ceiling; shadow language never becomes live permission. | Workbench and user | claim-ladder tests |
| Mechanism calibration (`mechanism_calibration_gate.yaml`) | Research owners preregister common-sample incremental evidence; promotion eligibility remains review evidence only. | Capability board | calibration-gate tests |

Sunset candidates are rules with no producer, no consumer, no observable
verification, or no consequence for violation. Initial candidates are generic
“all modules must” prose with no named writer, duplicated path lists already
owned by `system_constitution.yaml`, success-reporting requirements, and any
registry status that no executor consumes. Their destination is the existing
deferred-work/governance-thinning process; this page does not grant a new
authority or create a second registry.
