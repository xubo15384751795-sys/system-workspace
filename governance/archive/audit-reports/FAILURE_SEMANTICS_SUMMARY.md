# Failure Semantics Summary

**Generated:** 2026-06-03
**Sprint:** Failure Semantics Sprint

---

## Executive Summary

**系统的失败语义基本健康。没有 silent failure 会产生错误数字。**

所有 5 个审计维度的结论一致：active core path 的失败模式都是 legitimate degradation（数据缺失时返回 None，caller 正确处理，channel 贡献 0）。没有发现 P0 问题。发现 3 个 P1 问题（掩盖数据来源，不产生错误数字）。

---

## 审计结果总览

| 类别 | 总数 | Active Core | Dangerous | P0 | P1 |
|------|------|-------------|-----------|----|----|
| Fallback | 102 | 20 | 3 | 0 | 3 |
| Return None | 241 | 54 | 0 | 0 | 0 |
| Return {} | 33 | 7 | 0 | 0 | 0 |
| Not Implemented | 74 | 39 | 0 | 0 | 0 |
| **总计** | **450** | **120** | **3** | **0** | **3** |

---

## 1. Fallback (102)

| 分类 | 数量 | 说明 |
|------|------|------|
| legitimate_degradation | 39 | 有 warning/logging，fallback 是预期行为 |
| paper_module_fallback | 38 | NLP/ML/Learning Hub 的 fallback，不影响 active core |
| dangerous_silent_fallback | 20 | 评估后：17 个可接受，3 个 P1 |
| test_only | 5 | 测试代码 |

**3 个 P1:**
1. `current.py` L155-184: state_fallbacks 静默映射缺失 state 为默认值
2. `h41.py` L133: H41 数据获取失败时静默 fallback 到 FRED
3. `official.py` L621: 返回字符串 `"fallback"` 而非结构化状态

**结论：** 不产生错误数字，只掩盖数据来源。

---

## 2. Return None (241)

| 分类 | 数量 | 说明 |
|------|------|------|
| legitimate_optional | 140 | 可选字段，caller 处理 None |
| missing_data_signal | 54 | active core，`_series()`/`_spread()`/`_butterfly()` 返回 None |
| paper_module_stub | 42 | NLP/ML/Learning Hub 的 stub |
| test_only | 5 | 测试代码 |

**关键发现：** 54 个 active core return None 全部遵循同一模式：
```
_series() → None (数据缺失)
  → _spread() → None
    → _butterfly() → None
      → _component() → None
        → channel 贡献 0
```
**所有 caller 都正确处理了 None。** 没有 AttributeError 或 silent failure。

---

## 3. Return {} (33)

| 分类 | 数量 | 说明 |
|------|------|------|
| empty_config_ok | 26 | 配置文件不存在时返回空 dict |
| empty_artifact_risk | 7 | active core，但 caller 检查空 dict |
| test_only | 0 | — |

**关键发现：** 7 个 active core return {} 都在 UI 层（run_viewer.py）或 fallback 层（_sigma_vector_payload）。caller 检查 `if not vector` 并显示 "Unavailable"。

**没有发现** framework_output / sigma_vector / source_health 被空 dict 替代的情况。

---

## 4. Not Implemented (74)

| 分类 | 数量 | 说明 |
|------|------|------|
| active_core_blocker | 39 | 全部是 `canonical_status="awaiting_data"` 显式声明 |
| legacy_path_stub | 12 | 旧代码路径的 stub |
| paper_module_stub | 2 | NLP/ML stub |
| test_only | 21 | 测试代码 |

**关键发现：** 39 个 active_core_blocker 全部在 `structural_replay_v2.py` 的 PROXY_REGISTRY 中，标记为 `canonical_status="awaiting_data"`。这些是**显式声明**，不是隐藏的 NotImplementedError。它们在 replay 输出中可见（K/X_agg 的 `channels_not_implemented` 列表）。

**没有 P0。** 所有 not_implemented 都是显式、可见、有记录的。

---

## Integration Plan

### 进入 `./sys check` warning section

| 信号 | 来源 | 条件 |
|------|------|------|
| `fallback_used` | H41 → FRED fallback | 当 h41.py 使用 FRED fallback 时 |
| `state_fallback_used` | current.py state_fallbacks | 当 state 数据缺失使用默认值时 |
| `missing_data_channels` | replay sigma_vector | 当 `channels_not_implemented` 非空时 |

### 进入 `framework_output.warnings`

| 信号 | 来源 | 条件 |
|------|------|------|
| `data_quality.fallback_used` | harvester | 任何数据源 fallback |
| `data_quality.missing_series` | replay | 任何 proxy 返回 None |
| `data_quality.empty_artifact` | output | 任何 artifact 为空 dict |

### 进入 `source_health`

| 信号 | 来源 | 条件 |
|------|------|------|
| `source_status` | harvester | 每个数据源的获取状态（success/fallback/failed） |
| `freshness_status` | freshness.py | 每个 series 的新鲜度 |

### Paper module（不影响 active core）

| 模块 | 信号 | 处理 |
|------|------|------|
| NLP Pipeline | 所有 fallback/None/{} | 标 PAPER，不进入 warnings |
| ML Signals | 所有 fallback/None/{} | 标 PAPER，不进入 warnings |
| Learning Hub | 所有 fallback/None/{} | 标 PAPER，不进入 warnings |
| Agent Harness | 所有 fallback/None/{} | 标 PAPER，不进入 warnings |
| Backtest Lens | 所有 fallback/None/{} | 标 PAPER，不进入 warnings |
| Qlib Benchmark | 所有 fallback/None/{} | 标 PAPER，不进入 warnings |

---

## 修改文件清单

**本次 sprint 无代码修改。** 纯审计 + 报告。

---

## 测试结果

```
773 passed, 0 failed
```

---

## 一句话结论

**系统的失败语义是诚实的。数据缺失时返回 None，caller 处理 None 为 0 贡献，channel 显示为 NOT_IMPLEMENTED。没有发现 silent failure 产生错误数字。3 个 P1 是数据来源掩盖问题，不影响输出正确性。**
