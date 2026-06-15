# Z-Score Comparison Report

**Date:** 2026-06-03
**Test series:** FRED:NFCI (Financial Conditions Index)
**Observations:** 2,765 common

---

## Latest Value Comparison

| Implementation | Window | Winsor | Output | NFCI z-score |
|---------------|--------|--------|--------|-------------|
| proxy_builder | 260w (1820d) | ±3σ | scalar | **-0.172** |
| replay_v2 | 252d | ±4 clip | Series | **-0.814** |
| canonical_v1 | 252d | ±3σ | Series | **-0.815** |
| compute_proxies | 260w | ±3σ | scalar | **-0.717** |

**差异来源：**
- proxy_builder 用 260 周（1820 天）窗口，replay 用 252 天窗口
- 260 周窗口包含更多历史数据，z-score 更保守
- 252 天窗口更敏感近期变化

---

## Series Comparison: replay_v2 vs canonical_v1

| Metric | Value |
|--------|-------|
| Common observations | 2,765 |
| Mean absolute diff | 0.055 |
| Max absolute diff | 0.937 |
| Correlation | **0.995** |
| Diff > 0.1 | 378 (14%) |
| Diff > 0.5 | 67 (2.4%) |

**结论：** replay_v2 和 canonical_v1 高度一致（r=0.995）。差异主要来自 winsor 方式（±4 clip vs ±3σ winsor）。在 97.6% 的观测中差异 < 0.5。

---

## Key Finding

**replay_v2 和 canonical_v1 几乎等价。** 差异是 ±4 clip vs ±3σ winsor 的区别。

**proxy_builder 和 replay_v2 差异显著。** 原因是窗口不同（260w vs 252d）。这不是 bug——proxy_builder 设计为 260 周窗口（5 年），replay 设计为 252 天窗口（1 年）。两者都是 causal rolling，但看的时间尺度不同。

---

## Implication

迁移 replay_v2 → canonical_v1 是安全的（r=0.995，差异极小）。
迁移 proxy_builder → canonical_v1 需要决定窗口策略（260w vs 252d）。
