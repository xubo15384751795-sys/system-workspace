# System 大规模验证与收尾路线图（跨设备执行）

> 状态：跨设备执行交接清单
> 基线日期：2026-07-26（Asia/Singapore）
> 适用仓库：`xubo15384751795-sys/system-workspace`
> 权限边界：本文件是计划与验收口径，不授予研究候选、影子产物或测试结果进入默认运行路径的权限。

## 1. 目的

这个项目已经拥有较厚的单元测试、治理测试和故障阻断测试。下一阶段的重点不是继续堆普通测试数量，而是证明以下能力在真实默认路径中成立：

1. 干净环境可以重建并运行；
2. 完整默认链可以在隔离环境端到端执行；
3. 真实数据具备时点一致性、版本可追踪性和稳定获取能力；
4. 失败不会污染权威状态，恢复不会复用旧产物；
5. 定期深度验证真实运行并能阻止不合格变更；
6. 长期运行不会出现性能、存储、状态或语义漂移。

## 2. 审计基线

### 2.1 已验证的测试基线

2026-07-25/26 本地完整检查：

| 测试面 | 结果 |
|---|---:|
| 根测试套件 | 1088 passed, 10 skipped, 2 failed |
| Framework | 425 passed, 63 skipped |
| Harvester | 182 passed |
| Workbench | 248 passed |
| Learning Hub | 52 passed |

根套件的两个失败均来自当前产物语义与测试枚举不一致：

- `framework_output.status=degraded_partial` 未被当前契约测试接受；
- `judgment.decision=ACTIVE_WATCH` 未被当前契约测试接受。

这不是算法失败，而是生产者、消费者和测试之间的状态语义漂移。

### 2.2 CI 基线

- 最新主线 `CI Minimal Gate` 在提交 `0db72d9` 上通过；
- `merge-gate`、四个包测试、Python 3.12/3.13 integration 均通过；
- Nightly 在此前多个调度周期连续失败；
- Weekly Governance 最近一次调度失败；
- Nightly/Weekly 仍有脚本迁移后的旧路径：
  - `scripts/architecture_reality_audit.py`
  - `scripts/operator_registry_audit.py`
- 当前有效路径位于 `scripts/commands/weekly/`；
- GitHub 仓库为 private，当前套餐无法启用传统 branch protection。不能把“merge-gate 有运行”当成“merge-gate 被服务器强制”。

### 2.3 当前运行态基线

审计开始时完整 freshness verdict 为 `FAIL`，主要包括：

- `signal_consensus` 过期；
- ETF panel 内容过期；
- OFR FSI cache 内容过期；
- CISS cache 内容过期；
- `readme_first`、`signal_card`、`signal_consensus`、`work_brief` 与较新的 `system_index` 不属于同一闭合刷新链。

监控覆盖报告仍为 `FAIL`，包含：

- 多个 weekly 任务的 TTL 短于实际调度周期；
- 若干产物没有 content clock；
- 大量未分类监控盲区，其中包含历史、研究、手工和可退役资产。

注意：完整根测试中有测试直接调用真实 `sys refresh`，因此审计测试刷新了 gitignored 的 `Data/` 和 `Output/` 生成态。这一现象本身就是测试隔离缺口。执行后续任务时，不应把当前生成态视为未经测试污染的操作基线。

## 3. 总体执行顺序

```text
P0-1 定期 CI 与合并强制
  ↓
P0-2 测试隔离与状态契约统一
  ↓
P0-3 全链 callable E2E
  ↓
P0-4 默认运行 freshness/monitoring 闭环
  ↓
P1-1 真实数据/PIT/发布验证
  ├── P1-2 历史回放与前向 shadow
  └── P1-3 故障恢复、性能与 soak
        ↓
P1-4 覆盖率、属性、变异与安全基线
        ↓
P2-1 研究遗产与登记表收尾
```

不得跳过 P0 阶段，以研究结果、局部测试通过或新鲜文件时间戳替代默认路径闭环。

---

## 4. P0-1：修复定期深度 CI 与合并强制

### 目标

让 push/PR、Nightly、Weekly 三层验证都在当前主线真实可运行，并保证合并门不能被无意绕过。

### 输入

- `.github/workflows/ci.yml`
- `.github/workflows/nightly.yml`
- `.github/workflows/weekly-governance.yml`
- `scripts/verify_merge.py`
- `scripts/commands/weekly/`
- 当前 GitHub Actions 运行记录

### 输出

- 修复后的 Nightly 与 Weekly workflow；
- 一个明确的 required-merge 替代方案；
- 每次运行绑定 commit SHA 的验证清单；
- 调度失败通知与责任人/处理路径。

### 预计影响文件

- `.github/workflows/ci.yml`
- `.github/workflows/nightly.yml`
- `.github/workflows/weekly-governance.yml`
- `scripts/verify_merge.py`
- `governance/routing_decisions/<dated-ci-enforcement-decision>.yaml`

### 必须验证

1. Nightly、Weekly 所有脚本路径存在；
2. 三个 workflow 使用一致的安装和 `PYTHONPATH` 口径；
3. Nightly 不在缺少根包或治理种子的情况下运行包测试；
4. schema/freshness 检查在必要产物缺失时失败，不能无条件 PASS；
5. merge-gate 的 manifest 与当前 SHA 一致；
6. push、PR、schedule、manual-dispatch 四种触发都测试；
7. 记录无法使用 branch protection 时采用的替代强制策略。

### 验收标准

- 当前 SHA 的 Nightly 与 Weekly 手工运行均为绿色；
- 后续连续 14 天定期运行全绿；
- 注入错误脚本路径、缺失产物、失败测试时均阻止通过；
- 不存在 `continue-on-error`、`|| true` 或“产物不存在即跳过并 PASS”的 required path；
- merge-gate 绕过方式和补偿控制有书面、机器可检查的记录。

### 不能做什么

- 不能通过删除失败步骤让 workflow 变绿；
- 不能把 required 失败降级为 warning；
- 不能把 clean-checkout PASS 表述为真实运行态 freshness PASS；
- 不能为了启用分支保护而公开仓库，除非用户另行明确批准。

---

## 5. P0-2：隔离状态型测试并统一状态契约

### 目标

让完整测试在临时工作区运行，不触碰操作态 `Data/`、`Output/`、ledger、latest 指针或真实 run history；同时消除状态枚举漂移。

### 输入

- `scripts/verify_merge.py::STATEFUL_ROOT_TESTS`
- `tests/test_sys_entrypoints.py`
- `tests/test_workbench_tools.py`
- `tests/test_output_current.py`
- `tests/test_current_artifact_chain.py`
- `tests/test_current_refresh_bundle.py`
- 当前 schema、协议和状态生产者

### 输出

- 独立 `tmp_path`/sandbox workspace fixture；
- 可复制的最小 Harvester release 和 current-output fixture；
- 单一状态枚举/contract 来源；
- 被 merge-gate 排除的状态型测试迁移清单。

### 预计影响文件

- `tests/conftest.py`
- `tests/fixtures/**`
- `tests/test_sys_entrypoints.py`
- `tests/test_workbench_tools.py`
- `tests/test_output_current.py`
- `tests/test_current_artifact_chain.py`
- `tests/test_current_refresh_bundle.py`
- `scripts/verify_merge.py`
- 相关 schema/contract 文件

### 必须验证

1. 测试前后真实 `Data/`、`Output/` 内容哈希不变；
2. `sys refresh` 支持显式 workspace/output root；
3. `degraded_partial`、`ACTIVE_WATCH` 等状态由单一契约定义；
4. 生产者、schema、reader、CLI 和测试使用同一版本；
5. 旧状态迁移或兼容必须显式，不能无限扩充测试白名单；
6. 21 个被排除文件逐个分类为：
   - 已 hermetic；
   - 仍需 operator-workspace 验证；
   - 应拆分为 source-independent 和 stateful 两部分。

### 验收标准

- 根完整套件 0 failed；
- 测试前后操作态哈希一致；
- merge-gate 中不再排除可 hermetic 的测试；
- 状态 schema、生产者和消费者不存在未登记枚举；
- 测试可在全新 clone 中重复运行三次并产生相同结果。

### 不能做什么

- 不能只把新状态字符串追加到测试集合而不更新权威契约；
- 不能清空或恢复用户的真实 `Data/Output` 来制造隔离；
- 不能把状态型测试全部删除；
- 不能把 gitignored 生成态当作稳定测试 fixture。

---

## 6. P0-3：完成默认主链 callable E2E

### 目标

从“脚本存在、模块可导入”升级为“默认主链在隔离环境真实执行并产生闭合产物”。

### 输入

- `governance/daily_run_sequence.yaml`
- `governance/daily_pipeline_registry.yaml`
- `scripts/_pipeline_runner.py`
- `scripts/_daily_run_executor.py`
- `tests/test_daily_pipeline_callable_e2e.py`
- 当前 14 个 callable main-chain step

### 输出

- 默认主链全部 callable 的可执行测试；
- subprocess/callable 等价性报告；
- 正常、降级、阻断、恢复四套 E2E fixture；
- 每个步骤的输入、输出、run_id 和失败行为证据。

### 预计影响文件

- `scripts/_pipeline_runner.py`
- `scripts/_daily_run_executor.py`
- `governance/daily_pipeline_registry.yaml`
- `governance/daily_run_sequence.yaml`
- `tests/test_daily_pipeline_callable_e2e.py`
- 新增的 E2E fixtures/tests

### 必须验证

1. 不只是 `resolve_callable()`，每个默认步骤都实际运行；
2. 同一 run 的产物共享 run_id、as_of 和输入 release；
3. 上游失败时后代不执行并记录 `blocked_upstream`；
4. candidate/shadow 写入不能越权到 authoritative current；
5. callable 与 subprocess 对相同输入产生语义等价结果；
6. 重复运行具备幂等性或明确 append-only 语义；
7. dry-run、quick、standard、full 模式边界一致。

### 验收标准

- 默认主链 100% 有 callable 执行测试；
- 正常、降级、阻断、恢复四套场景通过；
- 生成产物通过 schema、freshness、lineage 和 authority 检查；
- callable 模式经过至少 14 天 shadow evidence 后才可考虑成为默认；
- 默认切换必须有人工 routing decision 和回滚路径。

### 不能做什么

- 不能因为模块可导入就声称 E2E 完成；
- 不能在没有等价性证据时删除 subprocess 回退；
- 不能把 research-only 步骤混入默认主链；
- 不能在测试中写真实 current。

---

## 7. P0-4：关闭默认运行 freshness 与监控链

### 目标

使 release → measurement → quality → judgment/gates → current → learning 的一次运行形成可核验的同源闭环。

### 输入

- `scripts/freshness_validator.py`
- `scripts/check_output_freshness.py`
- `scripts/artifact_monitoring_audit.py`
- `governance/daily_pipeline_registry.yaml`
- `Output/current/*`
- `Output/system_learning/latest/monitoring_coverage.json`

### 输出

- 统一 freshness 执行器；
- per-artifact content clock；
- 监控覆盖分类；
- 同一运行链 lineage；
- stale/partial refresh 的确定性恢复路径。

### 必须验证

1. 文件 mtime 与内容时钟分开判断；
2. freshness 必须在消费和写 current 前执行；
3. `signal_consensus` 等 current 产物必须属于同一次运行；
4. weekly TTL 与 schedule 的关系由明确政策决定；
5. 监控盲区按以下类别分类：
   - authoritative；
   - decision-adjacent shadow；
   - research；
   - manual/on-demand；
   - archived/retire；
6. Hub source 与 ledger 的领先/落后可检测；
7. 失败后不得继续写后代权威产物。

### 验收标准

- full freshness verdict PASS；
- ordering issues = 0；
- closure-chain issues = 0；
- authoritative 和 decision-adjacent 产物监控覆盖 100%；
- 未覆盖资产全部有分类与责任人；
- 连续 14 天定期运行没有 partial refresh。

### 不能做什么

- 不能通过延长所有 TTL 掩盖执行缺失；
- 不能用“文件存在”替代“内容新鲜”；
- 不能让 stale 数据以部分均值或静默 renormalization 继续进入判断；
- 不能把 archived/research 资产误列为权威覆盖缺口。

---

## 8. P1-1：真实数据、PIT 与发布认证

### 目标

验证外部数据不是“能下载一次”，而是在发布日期、有效日期、修订、节假日、限流和 schema 变化下仍然可审计、可阻断、可重放。

### 输入

- Harvester provider 与 release contract；
- benchmark/cross-asset panels；
- FRED、CBOE、OFR、ECB CISS、Yahoo ETF 等数据源；
- `vintage_date`、release catalog、quality reports；
- 当前 `no_future_dates` 规则。

### 已知风险

- ETF、OFR FSI、CISS 内容曾实际过期；
- benchmark panel 在 2026-07-25 包含 2026-07-26、2026-07-27 的 IORB 有效日期；
- 当前质量报告对所有序列统一允许 `as_of + 5 days`，这会把 IORB 的特殊规则扩散到其他序列；
- Yahoo ETF rate-limit 修复尚缺真实计划任务证据。

### 输出

- 逐数据源日期语义和 lag policy；
- PIT fixture/cassette；
- live provider canary；
- schema drift 和 revision replay；
- release promotion 的硬阻断条件。

### 验收标准

- 每个权威 series 声明 observation/effective/release/vintage 日期语义；
- 未来有效值只按逐 series 规则允许；
- 无许可未来值、未知 schema、超限 staleness 阻止 release finalize；
- provider canary 连续 30 天有机器可读证据；
- 同一 vintage 可重建相同 release hash；
- 网络失败、限流、部分数据源失败均不会发布伪完整 release。

### 不能做什么

- 不能为所有数据源使用统一未来日期缓冲；
- 不能把缓存成功视为真实网络成功；
- 不能用最新修订数据冒充历史当时可得数据；
- 不能把 reconstructed/scenario 数据标为 sourced。

---

## 9. P1-2：历史回放、静默期与前向 Shadow

### 目标

证明方法不仅能解释已知危机，也能在平静期控制假阳性，并在真正的前向样本中保持增量信息。

### 输入

- 冻结的 crisis windows；
- quiet/control windows；
- public baselines；
- purged/embargoed folds；
- judgment/trade ledgers；
- capability board 与研究分支否定结论。

### 输出

- 统一 common-sample 评估；
- 多折 purged walk-forward；
- 危机期、平静期、恢复期分层报告；
- calibration、lead time、false-positive、opportunity-cost 报告；
- 60–90 天 forward shadow evidence。

### 验收标准

- 所有候选与 incumbent 使用相同样本；
- folds、embargo、标签和阈值在运行前冻结；
- 包含危机、平静、恢复和数据缺失窗口；
- 报告增量信息而不只报告单模型 AUC/Sharpe；
- forward shadow 达到预注册样本/时间要求；
- 人工 promotion decision 记录 common-sample、增量、稳定性和回滚条件。

### 不能做什么

- 不能因为 `PROMOTION_ELIGIBLE` 自动改默认路径；
- 不能修改失败理论的标签、符号或阈值来恢复通过；
- 不能把后见之明 crisis selection 当作前向证据；
- 不能重新测试 wrong-sign F2，除非先有新的 dated preregistration。

---

## 10. P1-3：故障恢复、性能与长期 Soak

### 目标

把已有 10/12 场景控制闭环扩展为覆盖全部默认步骤、外部源、发布边界和长时间运行的系统级证明。

### 场景

- provider timeout/rate limit/schema change；
- disk full、permission denied、partial write；
- process kill 位于 release/current 切换中间；
- wrong latest pointer；
- stale manifest、cross-run artifact reuse；
- concurrent scheduler invocation；
- duplicate event/ledger append；
- clock skew、holiday、DST；
- large panel、memory pressure、slow dependency；
- recovery run 与旧失败 run 并存。

### 输出

- fault-injection matrix；
- atomic publish/recovery tests；
- 性能基线；
- 7 天和 30 天 soak 报告；
- run storage/ledger growth policy。

### 验收标准

- 所有阻断场景均满足 DETECTED/BLOCKED/UNCHANGED；
- 恢复必须产生新 run，不能复用旧失败状态；
- current 发布为原子切换；
- 重复调度不会并发写坏 latest/ledger；
- 建立每个模式的运行时间、峰值内存和磁盘预算；
- 7 天 soak 无泄漏，30 天运行无未解释状态漂移。

### 不能做什么

- 不能只 mock executor 返回值而不验证真实 writer；
- 不能只验证失败码，不验证权威状态未改变；
- 不能在性能测试中缩小到失去代表性的数据规模；
- 不能让测试故障触及真实操作态。

---

## 11. P1-4：覆盖率、属性、变异、兼容性与安全

### 目标

建立“测试能发现错误”的证据，而不是只统计测试数量。

### 输出

- 风险加权覆盖率；
- property-based tests；
- mutation score；
- performance benchmark；
- Python/依赖兼容矩阵；
- lint/type/security required gates。

### 建议范围

优先对以下区域做 property/mutation：

- 时间截断与 point-in-time；
- freshness/TTL/ordering；
- proxy 聚合与缺失值；
- admission/promotion/risk gates；
- run_id/lineage；
- atomic current publish；
- ledger dedupe/idempotency；
- sizing 上下界和 fail-closed。

### 验收标准

- 引入 coverage 工具并形成首个基线；
- 核心 gate/authority/freshness 模块设置较高分支覆盖率；
- 关键模块 mutation score 有最低阈值；
- `slow` 和 performance benchmark 不再为空；
- CI 覆盖 Python 3.12、3.13、3.14；
- 使用真正可重建的 lock/constraints；
- packages 纳入 ruff/mypy；
- Semgrep、依赖漏洞、秘密扫描成为真实阻断步骤。

### 不能做什么

- 不能用全仓单一覆盖率百分比掩盖关键路径空白；
- 不能追求 100% 行覆盖而忽略分支/状态空间；
- 不能让安全扫描以 `|| true` 退出；
- 不能使用未维护、未在 CI 使用的 lock 文件声称可复现。

---

## 12. P2-1：研究遗产与登记表收尾

### 目标

保存否定性研究证据，关闭过时登记，不把研究分支变成隐性默认路径。

### 当前待处理

`research/nonlinear-framework` 相对 main 有四个研究提交：

- `ef5d47a`
- `bdac149`
- `f7a161d`
- `611a164`

其结论包括：

- G1 interaction contrast FAIL；
- T6 event battery 修复后重新裁决；
- `W6_FULL_FAIL`；
- four-channel measurement layer frozen。

### 输出

- 对四个提交的审阅记录；
- 决定合并治理证据、保留 research-only 或归档；
- open thread 状态更新；
- deferred-work register 的完成/延期/取消重对账；
- shadow NAV 退化期注释进入未来 90 天验收读取器。

### 验收标准

- 否定结论和 prereg 历史不丢失；
- 不授予研究代码默认执行、判断或 promotion 权限；
- `open_threads.yaml` 与实际分支状态一致；
- deferred item 不再出现“步骤全部完成但 status 仍 in_progress”；
- 所有过期 deadline 有明确完成、延期、取消或替代决定。

### 不能做什么

- 不能删除失败证据；
- 不能通过改名把失败理论重新包装为新默认能力；
- 不能自动合并研究代码；
- 不能 opportunistic 重测 wrong-sign 或失败候选。

---

## 13. 跨设备执行要求

另一台设备开始工作前：

1. 拉取本文件所在分支；
2. 确认 `git status --short` 干净；
3. 不复制当前机器的 gitignored `Data/Output` 作为权威 fixture；
4. 从 P0-1 开始，不并行修改默认路径与研究候选；
5. 每个任务单独分支、单独 PR；
6. 每个 PR 必须包含：
   - 目标；
   - 输入；
   - 输出；
   - 影响文件；
   - 验收命令；
   - 失败证据；
   - 非目标；
   - 回滚方式；
7. 长证据窗口必须记录真实经过时间，不能用重复回放代替；
8. 所有测试产物写入临时目录或显式 candidate root。

## 14. 建议分支拆分

```text
codex/repair-scheduled-ci
codex/hermetic-stateful-tests
codex/unify-runtime-status-contract
codex/callable-e2e-full-chain
codex/freshness-monitoring-closure
codex/provider-pit-release-certification
codex/fault-soak-performance
codex/test-effectiveness-security
codex/nonlinear-research-closeout
```

这些分支名称只是建议，不表示任务已获准合并。

## 15. 最终完成定义

只有同时满足以下条件，才能认为本路线图完成：

- push/PR/Nightly/Weekly 验证真实运行且可强制；
- 根和四包测试全绿；
- 测试不污染操作态；
- 默认主链拥有完整 hermetic E2E；
- freshness、ordering、lineage、monitoring 全闭合；
- 真实数据 canary 和 PIT 测试达到证据窗口；
- 故障、恢复、并发、性能和 soak 达标；
- 候选方法经过 common-sample、增量信息和 forward shadow；
- 研究失败结论被保存；
- 所有默认路径变更均有人工批准和可执行回滚。

在此之前，系统应继续保持 research-only / paper / shadow 的现有限权边界。
