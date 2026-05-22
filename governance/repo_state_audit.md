# Repo State Audit — 2026-05-21 (updated 2026-05-22)

**Auditor:** routing assist  
**Scope:** `/Users/a1/System` 仓库结构、命名一致性、文档/现实漂移  
**Verdict (2026-05-22):** Phase 1 完成 — git 布局锁定、文档对齐、symlink 就位。Phase 3 剩余：`scripts/` 分流。

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

### Phase 3 — 仍 open

- [ ] 顶层 `scripts/` 非 wrapper 脚本归 owning module
- [ ] `Output/system_learning/events/` legacy 路径完全迁移到 runtime log

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

### P2 — 顶层 scripts 名实不符 → **open**

28 个 `.py`；非 wrapper 清单在 `repo_layout_map.md` §6。迁移 pending。

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

## 3. 建议下一步

1. **scripts/ 分流** — 按 `repo_layout_map.md` §6 表，移动后保留 thin wrapper
2. **runtime log 迁移** — 废弃 `Output/system_learning/events/` 的非 Hub writer
3. **Submodule pin 清理** — 各子仓库 commit 本地改动后更新 parent gitlink
