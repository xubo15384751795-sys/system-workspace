# Repo State Audit — 2026-05-21 (updated 2026-05-22, second pass)

**Auditor:** routing assist  
**Scope:** `/Users/a1/System` 仓库结构、命名一致性、文档/现实漂移  
**Verdict (2026-05-22, evening):** Phase 1 完成；Phase 3 收尾通过——`scripts/` 已就地标记、`events/` legacy 已归档、submodule pin 清理铺好执行计划（决策权留给用户）。父仓库范围内的重整结束。

## 重整结论（已锁定，不再三选一）

| 决策 | 结论 | 权威文档 |
|---|---|---|
| 物理布局 | 四个 sister repo **顶层并列** | `governance/repo_layout_map.md` |
| 版本管理 | **git submodule** (`.gitmodules`) | `governance/git_workspace_policy.md` |
| 文档策略 | **文档跟现实**；旧 `Workbench/data_providers/` 等路径退役 | `FOLDER_OWNERSHIP.md`, `MODULES.md` |
| Agent harness | `Workbench/agents/harness/` | `module_contexts/agent-routing.md` |
| system_learning truth | `Data/system_learning/` + `Output/system_learning/` | `governance/runtime_log_contract.md` |

---

## 0. 映射文档

**Authoritative map:** `governance/repo_layout_map.md`  
**Git policy:** `governance/git_workspace_policy.md`

### Phase 1 — 完成 (2026-05-22)

- [x] 四个 sister repo 注册为 git submodule
- [x] 顶层 4 个 compatibility symlink（含 `contracts`）
- [x] `.gitignore` 与 submodule 模型一致
- [x] `FOLDER_OWNERSHIP.md`, `MODULES.md`, `README.md` 对齐现实
- [x] `scripts/bootstrap.sh` → submodule init + symlink 重建
- [x] `system_learning` 收口：`Workbench/Output/system_learning/` 删除；hub cartography 写入 `Data/system_learning/`；`system-learning-hub/data` → symlink

### Phase 3 — 收尾通过 (2026-05-22 evening)

- [x] 顶层 `scripts/` 12 个非 wrapper 脚本就地加 deprecation banner（`#` 注释，零副作用），目标位置写进 banner；物理迁移延后，sys/Justfile/tests/configs 引用面零破坏。详见 `governance/repo_layout_map.md §6`。
- [x] `Output/system_learning/events/` 4 个 legacy `events_*.jsonl` 归档到 `Output/system_learning/legacy/events/`；原目录留 README.md 指向 `runtime/` + `record_runtime_event.py`。
- [~] Submodule pin 清理：父仓内出执行计划 `governance/submodule_commit_plan.md`（每个 submodule dirty 概要 + 切片建议 + parent pin 更新命令）。**实际 commit 留给用户**（commit message / 切片粒度是用户决策）。
- [ ] **追加 open**：peer writer 代码（仍在 4 个 submodule 内）→ `system_learning record`。属于 submodule 内重构，不在本轮父仓收尾范围。

---

## 1. 病灶清单（当前状态）

### P0 — 文档与现实漂移 → **已修复**

| 旧文档路径 | 现实 | 状态 |
|---|---|---|
| `Workbench/data_providers/structural-risk-harvester/` | `structural-risk-harvester/` | 文档已退役 |
| `Workbench/governance/system-learning-hub/` | `system-learning-hub/` | 文档已退役 |
| `Workbench/agent_harness/structural-research-harness/` | `Workbench/agents/harness/` | 文档已更新 |
| 顶层 3 symlink | 4 symlink 存在 | **已修复** |

### P0 — 嵌套 git / 非 submodule → **已修复**

`.gitmodules` 存在；四 repo 为 submodule。工作流见 `governance/git_workspace_policy.md`。

### P1 — system_learning 四方重复 → **已收口**

| 路径 | 角色 | 状态 |
|---|---|---|
| `Data/system_learning/` | 账本 + registries | **canonical** |
| `Output/system_learning/` | runtime + reports + routing decisions | **canonical** |
| `Workbench/Output/system_learning/` | 旧 scratch | **已删除** |
| `system-learning-hub/data/` | alias | **symlink → Data/system_learning/** |

### P2 — Framework 完整子项目 → **已明确**

`Structural Deformation Research System/` 是 git submodule；外层 `scripts/`/`tests/`/`Output/` 分工见 `repo_layout_map.md` §6。

### P2 — 顶层 scripts 名实不符 → **就地标记完成**

12 个非 wrapper 脚本（`structural_replay_v2.py`、`structural_replay_evaluation.py`、`run_c005_morphology_replay.py`、`build_c005_morphology_report.py`、`nlp_ingest.py`、`nlp_extract.py`、`ask_evidence.py`、`openbb_secondary_audit.py`、`repair_openbb_entrypoints.py`、`framework_cli.py`、`audit_boundaries.py`、`prepare_dl_training_data.py`）已加 `DEPRECATED LOCATION (marked 2026-05-22)` banner，目标 submodule 写进各 banner。物理迁移延后到 submodule pin 清理之后做（届时配 thin wrapper）。`repo_layout_map.md §6 §7` 已同步。

### P3 — 噪音 → **已处理**

- [x] `lightning_logs/` gitignore + 删除
- [ ] `.DS_Store` 从 git 历史清除（低优先级）

---

## 2. 好资产（重整时不碰）

- `governance/canonical_proxy_spec.yaml`
- `governance/module_authority_registry.yaml`
- `Output/current/` promotion 链路
- `tests/governance/`, `tests/benchmarks/market_feedback/`
- 全仓 `TODO/FIXME/XXX` 仅 1 处

---

## 3. 建议下一步（父仓收尾后剩余，全部跨入 submodule 边界）

1. **按 `governance/submodule_commit_plan.md` 在 4 个 submodule 内提交在途工作**——这是 dirty pin 唯一的解。
2. **更新 parent gitlink**——4 个 submodule commit 完后 `git add <submodule> && git commit`，让 `git status` 的 `m` 前缀清干净。
3. **物理迁移 12 个 deprecated 脚本**到各 submodule `scripts/`，并在父仓 `scripts/` 留 thin wrapper 调用 submodule 入口。建议放在 submodule pin 清理之后单独一轮。
4. **退役 peer writer**：`Workbench/agents/harness/events/system_event_writer.py` 等 4 处仍在写 `Output/system_learning/events/` 的代码，迁到 `system_learning record`。属于 Hub 接管运行日志的最后一步。
5. **（低优先）** `.DS_Store` 从历史清除（当前 git 已未追踪，只是 working tree 残留）。
