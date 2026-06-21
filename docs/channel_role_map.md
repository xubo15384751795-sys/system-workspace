# Channel Role Map

**Version:** 1.0  
**Date:** 2026-06-19  
**Status:** Active — replaces 4-channel average as primary interpretation framework

---

## Core Principle

M/D/K/X are **structural state detectors**, not directional predictors.

Each channel answers a specific question about the current market structure.
The system does NOT predict "will the market go up or down."
Instead, it identifies "what state are we in, and what actions are permitted."

---

## Channel Roles

### M — Anchor Repricing Detector

**Question it answers:** Is the macro anchor (policy/valuation) being repriced?

| Aspect | Detail |
|--------|--------|
| What it measures | Policy-valuation gap, macro momentum |
| Valid range | Typically -4 to +4 |
| When M < 0 | Macro anchor in relief/m accommodative mode |
| When M > 0 | Macro anchor under stress, repricing risk |
| Best use | Regime change detection — large M swings predict vol spikes |
| NOT for | Directional prediction (29y agreement: 48.3%) |
| Key stat | Large M swings (>1.5σ in 5d) predict 21d vol increase (p=0.011) |

**Permitted actions when M is active:**
- Flag "anchor repricing risk"
- Lower directional conviction
- Allow "RESEARCH_REVIEW" status

**Forbidden actions:**
- Generate BUY/SELL signals from M alone
- Claim M predicts market direction

---

### D — Path Compression Detector

**Question it answers:** Is the market's action space narrowing?

| Aspect | Detail |
|--------|--------|
| What it measures | Path geometry, deformation, contraction |
| Valid range | Typically -4 to +4 |
| When D < 0 | Path expanding, action space wide |
| When D > 0 | Path compressing, action space narrowing |
| Best use | Identifying when markets are "coiling" before a move |
| NOT for | Directional prediction (29y agreement: 48.2%) |
| Key stat | D>0 predicts future vol decrease (mean reversion, p<0.001) |

**Permitted actions when D is active:**
- Flag "path compression — expect eventual resolution"
- Increase monitoring frequency
- Allow "WATCH" status

**Forbidden actions:**
- Predict direction of resolution
- Use D as standalone signal

---

### K — Curvature Stress Detector

**Question it answers:** Is the structural curvature abnormal?

| Aspect | Detail |
|--------|--------|
| What it measures | Credit spread curvature, VIX term structure, tail risk |
| Valid range | Typically -4 to +4 |
| When K < 0 | Low structural stress, curvature compressed |
| When K > 0 | Elevated structural stress, curvature expanding |
| Best use | Confirmation signal, vol regime indicator |
| NOT for | Standalone directional prediction (29y agreement: 49.5%) |
| Key stat | r=+0.09 with 21d forward vol (p<0.001). Best single channel (37% of years). |
| Caveat | Works in some years (2026: 61%), fails in others (2024: 45%). Regime-dependent. |

**Permitted actions when K is active:**
- Confirm X's stress readings
- Adjust confidence level
- Allow "SMALL_SIZE_ALLOWED" when K and X agree

**Forbidden actions:**
- Use K as sole directional signal
- Assume K will work in all regimes

---

### X — Primary Stress/Volatility Detector

**Question it answers:** Is there hidden leverage accumulation or cross-market stress?

| Aspect | Detail |
|--------|--------|
| What it measures | Cross-market leverage, shadow exposure, stress propagation |
| Valid range | Typically -4 to +4 |
| When X < 0 | Low cross-market stress, leverage contained |
| When X > 0 | Elevated cross-market stress, leverage building |
| Best use | PRIMARY risk indicator. Best vol/stress detector in the system. |
| NOT for | Directional prediction (29y agreement: 45.6%) |
| Key stat | r=+0.34 with 21d forward vol (p<0.001). 88% stress event detection. 89% vol spike detection. |
| Strength | Highest signal-to-noise ratio of all channels for risk detection |

**Permitted actions when X is active:**
- Enter "STRESS_WATCH" mode
- Block directional trades
- Increase hedging
- Generate "NO_TRADE" gate

**Forbidden actions:**
- Ignore X when it flags stress
- Use X for directional alpha

---

## Interaction Rules

### When channels agree

| Scenario | Action |
|----------|--------|
| X>0 and K>0 | **STRESS_WATCH** — high confidence stress detection |
| M swings sharply + X>0 | **REGIME_CHANGE_RISK** — anchor repricing + stress |
| M<0 and K<0 and X<0 | **ALL_CLEAR** — low stress, allow directional hypothesis |
| D>0 + any other >0 | **COMPRESSION_STRESS** — narrowing + stress = watch for resolution |

### When channels disagree

| Scenario | Action |
|----------|--------|
| X>0 but K<0 | Stress in leverage, not in curvature — **WATCH** |
| K>0 but X<0 | Curvature stress, no leverage — **RESEARCH_REVIEW** |
| M>0 but K<0 and X<0 | Anchor stress only — **WATCH**, not TRADE |
| Any 2 channels split | **NO_TRADE** — insufficient consensus |

### Automatic silence rules

| Condition | Action |
|-----------|--------|
| Channel rolling 6m agreement < 48% | **MUTE** — channel has no predictive value |
| Channel data < 252 days | **MUTE** — insufficient calibration |
| Channel value at extreme (>3σ) | **FLAG** — possible data error or regime extreme |

---

## Action Gate Hierarchy

From most restrictive to least:

1. **NO_TRADE** — system says "do nothing"
2. **WATCH** — monitor, no action
3. **RESEARCH_REVIEW** — investigate, paper trade only
4. **SMALL_SIZE_ALLOWED** — tiny position, strict stops
5. **DIRECTIONAL_HYPOTHESIS_ONLY** — can express view, not execute

Default state: **RESEARCH_REVIEW**

Only channels that pass their calibration check AND agree with at least one other channel can upgrade the gate.

---

## Deprecation Notice

**`4-channel average` is deprecated as of 2026-06-19.**

29-year backtest shows 4-channel average has 45.6% directional agreement — worse than any individual channel and well below the buy-and-hold baseline (~56%).

The average was mixing directional signals (M, K) with risk signals (X, D), producing a meaningless composite.

Use this Channel Role Map instead.
