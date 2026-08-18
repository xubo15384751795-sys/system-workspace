"""Lightweight text similarity for CaseLab cases.

Bypasses sentence-transformers by extracting structural keywords
from text (handles Chinese + English) and computing overlap-based
similarity. Fast, no model download needed.

Used by CaseSimilarityEngine when event_text is provided.
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np


# ── Structural keyword vocabulary ────────────────────────────────────────
# English keywords that map to structural concepts.
# Chinese text is matched by character n-gram on these English representations.

STRUCTURAL_KEYWORDS: dict[str, list[str]] = {
    # Stress / crisis
    "stress": ["stress", "压力", "紧张", "crisis", "危机"],
    "liquidity": ["liquidity", "流动性", "流动", "funding", "融资"],
    "spiral": ["spiral", "螺旋", "反馈", "self-reinforcing", "自我强化"],
    "forced_selling": ["forced", "selling", "被迫", "抛售", "强制", "liquidat"],
    "margin_call": ["margin", "call", "保证金", "追保", "补保"],
    "deposit_run": ["deposit", "run", "存款", "挤兑", "bank run"],
    "contagion": ["contagion", "传染", "蔓延", "spillover", "溢出"],
    "default": ["default", "违约", "破产", "bankrupt"],
    "crash": ["crash", "崩盘", "暴跌", "collapse"],

    # Leverage / balance sheet
    "leverage": ["leverage", "杠杆", "负债", "borrowing"],
    "duration": ["duration", "maturity", "期限", "错配", "久期"],
    "repo": ["repo", "回购", "repurchase"],
    "balance_sheet": ["balance", "sheet", "资产负债表", "资产"],
    "collateral": ["collateral", "抵押", "担保", "margin"],
    "securitization": ["securitiz", "证券化", "结构化", "tranche", "CDO", "MBS"],

    # Asymmetry / visibility
    "asymmetry": ["asymmetr", "不对称", "信息差", "opacity", "不透明"],
    "visibility": ["visibility", "可见性", "透明度", "transparency"],
    "risk_transfer": ["risk", "transfer", "风险转移", "风险迁移", "转嫁"],
    "counterparty": ["counterparty", "交易对手", "对手方"],
    "concentration": ["concentration", "集中", "集中度", "dominan"],

    # Volatility / market
    "volatility": ["volatility", "波动", "vol", "波动率"],
    "correlation": ["correlation", "相关性", "相关", "corr"],
    "drawdown": ["drawdown", "回撤", "跌幅"],
    "spread": ["spread", "利差", "价差", "credit spread"],
    "dislocation": ["dislocation", "错位", "mispricing"],

    # Positioning / flows
    "positioning": ["positioning", "仓位", "持仓", "crowded"],
    "flow": ["flow", "资金流", "流入", "流出", "capital flow"],
    "capex": ["capex", "资本开支", "资本支出", "capital expenditure"],
    "concentration_risk": ["集中风险", "单客户", "单点故障"],

    # Tech / AI
    "compute": ["compute", "算力", "GPU", "芯片", "semiconductor"],
    "platform": ["platform", "平台", "ecosystem", "生态"],
    "lock_in": ["lock-in", "lock_in", "锁定", "绑定", "switching cost"],
    "ai": ["AI", "artificial intelligence", "人工智能", "模型", "LLM", "GPT"],
    "scaling": ["scaling", "scale", "规模化", "规模"],

    # Macro / policy
    "policy": ["policy", "政策", "监管", "regulation", "央行", "Fed", "central bank"],
    "intervention": ["intervention", "干预", "bailout", "救助", "backstop"],
    "dollar": ["dollar", "美元", "USD", "汇率", "exchange rate"],
    "inflation": ["inflation", "通胀", "CPI", "物价"],
    "rate_hike": ["rate hike", "加息", "利率上升", "tightening"],

    # IPO / capital markets
    "ipo": ["IPO", "上市", "public offering", "listing"],
    "valuation": ["valuation", "估值", "定价", "pricing"],
    "growth": ["growth", "增长", "扩张", "revenue growth"],

    # Relief / deleveraging / compression
    "relief": ["relief", "缓解", "回落", "easing", "压力缓解"],
    "deleveraging": ["deleveraging", "去杠杆", "减杠杆", "debt reduction", "杠杆下降"],
    "compression": ["compression", "压缩", "低波动", "volatility compression", "波动压缩"],
    "stabilization": ["stabilization", "稳定", "企稳", "stabilizing", "趋于稳定"],
    "recovery": ["recovery", "恢复", "反弹", "回升", "rebound"],
    "normalization": ["normalization", "正常化", "回归正常", "return to normal"],
    "calm": ["calm", "平静", "quiet", "低活跃", "low activity"],
    "anchor_relief": ["anchor relief", "锚缓解", "锚定改善", "anchoring改善"],
    "path_improvement": ["path improvement", "路径改善", "通道改善", "D改善"],
    "curvature_compressed": ["curvature compressed", "曲率压缩", "K压缩", "低曲率"],
    "shadow_unwind": ["shadow unwind", "影子去杠杆", "交叉减仓", "X下降"],
    "macro_easing": ["macro easing", "宏观宽松", "政策宽松", "货币宽松"],
}

# Build reverse lookup: keyword_fragment → concept
_KEYWORD_TO_CONCEPT: dict[str, str] = {}
for concept, keywords in STRUCTURAL_KEYWORDS.items():
    for kw in keywords:
        _KEYWORD_TO_CONCEPT[kw.lower()] = concept


def extract_structural_keywords(text: str) -> Counter[str]:
    """Extract structural concept keywords from mixed Chinese/English text.

    Returns Counter of concept → frequency.
    """
    text_lower = text.lower()
    counts: Counter[str] = Counter()

    for concept, keywords in STRUCTURAL_KEYWORDS.items():
        for kw in keywords:
            count = len(re.findall(re.escape(kw.lower()), text_lower))
            if count > 0:
                counts[concept] += count

    return counts


def keyword_similarity(text_a: str, text_b: str) -> float:
    """Compute structural keyword overlap between two texts.

    Returns Jaccard-like similarity on structural concepts,
    weighted by frequency.
    """
    kw_a = extract_structural_keywords(text_a)
    kw_b = extract_structural_keywords(text_b)

    if not kw_a or not kw_b:
        return 0.0

    # Weighted Jaccard
    all_concepts = set(kw_a.keys()) | set(kw_b.keys())
    intersection = sum(min(kw_a.get(c, 0), kw_b.get(c, 0)) for c in all_concepts)
    union = sum(max(kw_a.get(c, 0), kw_b.get(c, 0)) for c in all_concepts)

    if union == 0:
        return 0.0

    return intersection / union


def keyword_cosine_similarity(text_a: str, text_b: str) -> float:
    """Compute cosine similarity on structural keyword vectors.

    More discriminating than Jaccard — accounts for relative frequencies.
    """
    kw_a = extract_structural_keywords(text_a)
    kw_b = extract_structural_keywords(text_b)

    if not kw_a or not kw_b:
        return 0.0

    all_concepts = sorted(set(kw_a.keys()) | set(kw_b.keys()))
    vec_a = np.array([kw_a.get(c, 0) for c in all_concepts], dtype=float)
    vec_b = np.array([kw_b.get(c, 0) for c in all_concepts], dtype=float)

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0

    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def top_shared_concepts(text_a: str, text_b: str, n: int = 5) -> list[tuple[str, float]]:
    """Return top N shared structural concepts with their min-frequency."""
    kw_a = extract_structural_keywords(text_a)
    kw_b = extract_structural_keywords(text_b)

    shared: list[tuple[str, float]] = []
    for concept in set(kw_a.keys()) & set(kw_b.keys()):
        score = float(min(kw_a[concept], kw_b[concept]))
        shared.append((concept, score))

    shared.sort(key=lambda x: x[1], reverse=True)
    return shared[:n]
