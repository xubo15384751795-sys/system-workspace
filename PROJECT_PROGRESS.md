# Project Validation Progress

> Generated from `governance/progress/validation_roadmap.yaml` and the append-only `governance/progress/validation_progress_events.jsonl` ledger. Do not edit percentages here.

- Overall completion: **37.1%**
- Remaining: **62.9%**
- Latest evidence event: `2026-07-30T15:35:08Z`

## Phase summary

| Phase | Completion |
|---|---:|
| P0 | 66.4% |
| P1 | 13.5% |
| P2 | 10.0% |

## Workstreams

| Task | State | Completion | Owner | Next gate |
|---|---|---:|---|---|
| P0-1 定期 CI 与合并强制 | `EVIDENCE_ACCUMULATING` | 85.0% | System | Accumulate 14 consecutive days of scheduled Nightly and Weekly evidence. |
| P0-2 测试隔离与状态契约 | `OPERATIONAL_VALIDATION` | 82.5% | System | Record unchanged operator hashes and three repeatable clean-clone runs. |
| P0-3 默认主链 Callable E2E | `EVIDENCE_ACCUMULATING` | 67.5% | Workbench | Complete recovery/equivalence evidence and the 14-day callable shadow window. |
| P0-4 Freshness 与监控闭环 | `CI_GREEN` | 42.5% | System | On the compute device, refresh Harvester and pass the 19-step current chain. |
| P1-1 真实数据、PIT 与发布认证 | `READY` | 10.0% | Harvester | Create an isolated provider/PIT release-certification branch after P0-4. |
| P1-2 历史回放与 Forward Shadow | `READY` | 15.0% | Research | Freeze the common-sample protocol after P1-1. |
| P1-3 故障恢复、性能与 Soak | `READY` | 22.5% | System | Build isolated real-writer fault and recovery fixtures. |
| P1-4 测试有效性、兼容性与安全 | `READY` | 7.5% | System | Establish a risk-weighted coverage baseline. |
| P2-1 研究遗产与登记表收尾 | `READY` | 10.0% | Research | Review the four nonlinear-framework research commits independently. |

## Current blockers

### P0-4 Freshness 与监控闭环

- OFR FSI and CISS release/cache are stale
- 12 current artifacts are stale
- 55 authoritative or decision-adjacent monitoring coverage gaps remain

### P1-1 真实数据、PIT 与发布认证

- P0-4 operational validation must complete first

### P1-2 历史回放与 Forward Shadow

- P1-1 release certification must establish trustworthy inputs

### P1-3 故障恢复、性能与 Soak

- P0-4 atomic current behavior and P1-1 inputs must be stable first

### P1-4 测试有效性、兼容性与安全

- P1-3 should define the highest-risk paths before thresholds are frozen

### P2-1 研究遗产与登记表收尾

- Must be reviewed on a dedicated P2 branch without default-path authority changes

## Updating progress

Validate and display:

```bash
./sys roadmap
python3 scripts/roadmap_progress.py validate
```

Transitions must be appended through the state-machine command or an equivalent reviewed JSONL event. Generated percentages are evidence-derived.
