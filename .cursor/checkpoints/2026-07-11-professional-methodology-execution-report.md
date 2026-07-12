# 执行报告：专业能力升级方案 S1–S10（真落实轮）

**日期**: 2026-07-11  
**模式**: 加深实现 + 测量路径接线；决策默认路径仍需人工晋升  
**检查点**: `.cursor/checkpoints/2026-07-11-professional-methodology-s1-s10.md`

---

## 本轮相对「空壳完成」的实质变化

| 步 | 之前 | 现在 |
|---|---|---|
| S1 | helper 未接线 | **`_freq_aware_zscore` → 稳健 z（median/MAD）** |
| S2 | K 面只在 shadow | **jump / VIX 比率 / VRP 进入 registry `canonical_voting`** |
| S3 | OR 事件率 24.9% | **主评 `or_tight` ≈12.4%；双定义对照写入报告** |
| S5 | 仅 EWMA CISS | **+ rolling PCA；DynamicFactorMQ 在稠密子样本可用时启用** |
| S7 | 手搓启发式 q/r | **`UnobservedComponents` MLE + 因果滤波；修 leading-NaN 方差爆炸** |
| S8 | 公式未接 paper | **`paper_portfolio` 连续仓位 + gate 硬平仓** |
| S10 | 固定均值滤波挂名 | **`hmmlearn` Sticky HMM + 跳跃惩罚 regime** |
| Batch-2 | 未采购 | **CFTC TFF + NY Fed PD 已拉取缓存；FINRA 注册（手动 CSV）** |

---

## 最新同框（or_tight，bootstrap=50）

事件率 ≈ **12.4%**（loose OR 仍约 24.9%；AND ≈ 8.3%）。

| Method | ROC-AUC | 备注 |
|---|---:|---|
| k_surface | 0.597 | AUC 最高 |
| jump_regime | 0.576 | select_candidate 按 AUC+PR 胜出；增量检验通过 |
| kalman_anchor | 0.551 | 已修复，有读数 |
| incumbent_velocity | 0.532 | 基线 |
| sticky_hmm | 0.483 | 加深后仍未击败 velocity |
| cusum / bocpd | &lt;0.5 | 仍不晋升 |

**晋升裁决**: `jump_regime` 在本轮配置下曾报 `PROMOTION_ELIGIBLE`，但 bootstrap 阈值敏感；**未改默认决策路径**（仍需人工授权）。velocity EXIT 杀开关保留。

---

## 治理边界（诚实）

1. 稳健 z 已进入测量变换路径 → 后续 replay 产出会变，需重跑 structural_replay。  
2. 连续仓位已进入 **paper 影子**，不是 live。  
3. CISS/CUSUM/Sticky-HMM 未硬推上位。  
4. Batch-2 已进 harvester external 缓存，需下一次 release 打进 panel 后 X_agg 新代理才有数。

---

## 验证

- `pytest tests/test_professional_methods.py tests/test_paper_portfolio.py` → passed  
- `PYTHONPATH=scripts python3 scripts/run_professional_methodology.py --event-logic or_tight`  
- CFTC/NYFed fetch → `Data/harvester/raw/external_indicators/`
