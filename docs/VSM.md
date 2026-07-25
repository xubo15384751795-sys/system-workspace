# Viable System Model — one-page health check

```mermaid
flowchart TB
  S5["S5 Identity<br/>system constitution and ownership"]
  S4["S4 Intelligence and future<br/>Paper, CaseLab, research, capability board, hypotheses inbox"]
  S3["S3 Operations control<br/>daily pipeline, registry, admission and publication gates"]
  S2["S2 Coordination<br/>protocols, schemas, version coexistence, event envelopes"]
  S1["S1 Operating units<br/>Harvester | Framework | Workbench | Learning Hub"]
  E["Environment<br/>providers, markets, users, evidence time"]
  S5 --> S4
  S5 --> S3
  S4 <--> S3
  S3 --> S2
  S2 <--> S1
  S1 <--> E
  S1 -. "exceptions only" .-> S3
```

The May failure mode was an oversized S3: more central checks and registries
reduced S1's ability to regulate itself. The target state is distributed
regulation: each S1 unit owns its assertions and tests; S2 owns only the shared
shape; S3 admits, blocks and aggregates exception heartbeats; S4 runs reversible
probes; S5 changes rarely.

Before a governance change, answer four questions:

1. Which system is being fed: S1, S2, S3, S4 or S5?
2. Is S3 absorbing logic that belongs to an S1 owner?
3. Does normal operation stay silent while deviations remain traceable?
4. Can the affected S1 unit detect the injected failure without a global path oracle?

Do not approve an S3 addition unless it removes at least as much central logic,
or it is a true cross-module admission/publication boundary.
