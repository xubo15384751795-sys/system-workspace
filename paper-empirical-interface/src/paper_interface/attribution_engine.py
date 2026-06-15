"""
Attribution Engine v2 — 语义校准 + 二阶归因 + Regime 识别

核心改进：
1. 通道语义精确化
2. 二阶归因（动量、加速度）
3. Regime label
4. X 通道子层拆分
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 通道语义定义
# ============================================================

CHANNEL_SEMANTICS = {
    "M": {
        "name": "Anchor Mismatch",
        "economic_meaning": "期限结构压缩程度 — 收益率曲线相对历史均值的偏离",
        "positive_means": "曲线压缩/趋平 → 利率锚定处于非舒展状态",
        "negative_means": "曲线陡峭/舒展 → 利率锚定正常",
        "direction": "asymmetric",  # 特殊：T10Y2Y 低 = 压力，DFF 低 = 宽松
        "variables": {
            "FRED:T10Y2Y": {
                "role": "期限利差",
                "direction": "inverted",  # 低值 = 压力
                "intuition": "曲线趋平/倒挂 = 锚定错配压力上升",
            },
            "FRED:DFF": {
                "role": "政策利率",
                "direction": "normal",  # 高值 = 压力
                "intuition": "利率高 = 融资成本压力",
            },
        },
    },
    "D": {
        "name": "Path Feasibility",
        "economic_meaning": "风险释放路径的畅通程度",
        "positive_means": "路径受阻 — 风险释放通道被压制（Compression/Suppression State）",
        "negative_means": "路径畅通 — 风险正在正常释放",
        "direction": "asymmetric",
        "sub_channels": {
            "D_release": {
                "name": "Release Path Stress",
                "description": "传统风险释放路径压力",
                "variables": ["FRED:BAMLH0A0HYM2", "FRED:VIXCLS"],
                "direction": "normal",  # 高值 = 压力高 = 正在释放
            },
            "D_suppression": {
                "name": "Risk Release Suppression",
                "description": "风险释放被压制的状态",
                "variables": ["FRED:BAMLH0A0HYM2", "FRED:VIXCLS"],
                "direction": "inverted",  # 低值 = 压制状态 = 潜在蓄压
            },
        },
        "variables": {
            "FRED:BAMLH0A0HYM2": {
                "role": "信用利差",
                "direction": "inverted",  # 低值 = 路径压制
                "intuition": "HY spread 低 = 信用宽松 = 风险释放通道被压制",
            },
            "FRED:VIXCLS": {
                "role": "波动率",
                "direction": "inverted",  # 低值 = 路径压制
                "intuition": "VIX 低 = 波动率平静 = 风险释放动力不足",
            },
            "H41:discount_window": {
                "role": "贴现窗口",
                "direction": "inverted",  # 低值 = 流动性充裕
                "intuition": "贴现窗口低 = 银行不需要紧急流动性",
            },
        },
    },
    "K": {
        "name": "Transition Deformation",
        "economic_meaning": "市场规则是否正在从常态价格发现切换到跳跃/尾部/波动率反馈模式",
        "positive_means": "转换变形高 — 市场进入非线性定价模式",
        "negative_means": "转换变形低 — 市场仍在常态交易规则",
        "direction": "normal",
        "variables": {
            "FRED:VIXCLS": {
                "role": "波动率水平",
                "direction": "normal",
                "intuition": "VIX 高 = 市场进入恐慌定价",
            },
            "CBOE:SKEW": {
                "role": "尾部风险",
                "direction": "normal",
                "intuition": "SKEW 高 = 尾部风险定价上升",
            },
            "CBOE:VVIX": {
                "role": "波动率的波动率",
                "direction": "normal",
                "intuition": "VVIX 高 = 波动率本身不稳定",
            },
        },
    },
    "X": {
        "name": "Shadow Accumulation",
        "economic_meaning": "隐藏结构性压力的积累程度",
        "positive_means": "影子积累高 — 潜在压力正在堆积",
        "negative_means": "影子积累低 — 隐藏压力较少",
        "direction": "normal",
        "sub_channels": {
            "X_liquidity": {
                "name": "Official Liquidity Facility",
                "description": "官方流动性工具使用",
                "variables": ["H41:primary_credit", "H41:btfp"],
                "direction": "normal",
            },
            "X_corporate": {
                "name": "Corporate Shadow Activity",
                "description": "企业/市场行为脉冲",
                "variables": ["SEC:0000072971"],
                "direction": "normal",
            },
        },
        "variables": {
            "H41:primary_credit": {
                "role": "一级信贷",
                "direction": "normal",
                "intuition": "高 = 银行依赖 Fed 紧急信贷",
            },
            "H41:btfp": {
                "role": "银行定期融资计划",
                "direction": "normal",
                "intuition": "高 = 银行需要长期融资支持",
            },
            "SEC:0000072971": {
                "role": "SEC filing pulse",
                "direction": "normal",
                "intuition": "高 = 企业融资/披露活动增加",
            },
        },
    },
}


# ============================================================
# Regime 定义
# ============================================================

REGIME_RULES = [
    {
        "name": "Compressed Calm Regime",
        "label": "压缩型平静",
        "description": "市场表层稳定，但锚定结构未完全舒展；信用和波动率宽松，风险释放路径被压制",
        "condition": lambda m, d, k, x: m > 0.3 and d > 0.3 and k < 0 and abs(x) < 0.5,
        "tradeability": "WATCHLIST",
        "watch_vars": ["T10Y2Y", "VIXCLS", "BAMLH0A0HYM2"],
    },
    {
        "name": "Full Mismatch Regime",
        "name": "Full Mismatch Regime",
        "label": "全面错配",
        "description": "多个通道同时显示高压力，市场结构处于紧张状态",
        "condition": lambda m, d, k, x: m > 1.5 and d > 1.5 and k > 1.0,
        "tradeability": "TRADE",
        "watch_vars": ["T10Y2Y", "VIXCLS", "MOVE", "primary_credit"],
    },
    {
        "name": "Volatility Transition Regime",
        "label": "波动率转换",
        "description": "市场正在从低波动向高波动切换，转换变形启动",
        "condition": lambda m, d, k, x: k > 1.0 and (m > 0.5 or d > 0.5),
        "tradeability": "TRADE",
        "watch_vars": ["VIXCLS", "VVIX", "SKEW", "MOVE"],
    },
    {
        "name": "Shadow Accumulation Regime",
        "label": "影子积累",
        "description": "隐藏压力正在堆积，但尚未显性化",
        "condition": lambda m, d, k, x: x > 1.5 and k < 0.5,
        "tradeability": "WATCHLIST",
        "watch_vars": ["primary_credit", "btfp", "SEC_filings"],
    },
    {
        "name": "Curve Stress Regime",
        "label": "曲线压力",
        "description": "期限结构异常，但其他通道尚未跟进",
        "condition": lambda m, d, k, x: m > 1.5 and d < 0.5 and k < 0.5,
        "tradeability": "WATCHLIST",
        "watch_vars": ["T10Y2Y", "DFF", "SOFR"],
    },
    {
        "name": "Normal Expansion",
        "label": "正常扩张",
        "description": "各通道处于正常或宽松状态",
        "condition": lambda m, d, k, x: m < 0.3 and d < 0.3 and k < 0.3 and x < 0.3,
        "tradeability": "IGNORE",
        "watch_vars": [],
    },
]


@dataclass
class VariableAttribution:
    """单个变量的归因"""
    series_id: str
    role: str
    latest_value: float
    mean_5y: float
    std_5y: float
    z_score: float
    z_clipped: float
    direction: str  # "normal" or "inverted"
    weight: float
    contribution: float
    intuition: str
    
    # 二阶
    change_1w: Optional[float] = None
    change_1m: Optional[float] = None
    change_3m: Optional[float] = None
    z_change_1m: Optional[float] = None


@dataclass
class ChannelAttribution:
    """通道归因"""
    channel_id: str
    channel_name: str
    economic_meaning: str
    level: float
    level_interpretation: str
    positive_means: str
    negative_means: str
    
    variables: list[VariableAttribution] = field(default_factory=list)
    
    # 子通道
    sub_channels: dict[str, float] = field(default_factory=dict)
    
    # 二阶
    momentum_1w: Optional[float] = None
    momentum_1m: Optional[float] = None
    momentum_3m: Optional[float] = None
    acceleration: Optional[float] = None


@dataclass
class RegimeResult:
    """Regime 识别结果"""
    regime_name: str
    regime_label: str
    description: str
    tradeability: str  # TRADE / WATCHLIST / IGNORE
    watch_vars: list[str]


@dataclass
class AttributionReport:
    """完整归因报告"""
    date: str
    channels: dict[str, ChannelAttribution]
    regime: RegimeResult
    summary: str


class AttributionEngine:
    """
    归因引擎 v2
    
    隔离原则：只读取 ProxyComputer 输出，不修改现有模块
    """
    
    def __init__(self, proxy_computer, window: int = 260):
        self.pc = proxy_computer
        self.window = window
    
    def _compute_variable_attribution(
        self,
        series_id: str,
        channel_id: str,
        weight: float,
    ) -> Optional[VariableAttribution]:
        """计算单个变量的归因"""
        semantics = CHANNEL_SEMANTICS[channel_id]
        var_semantics = semantics["variables"].get(series_id, {})
        
        series = self.pc._get_series(series_id)
        if len(series) < 4:
            return None
        
        # 过滤到有效窗口
        effective_window = min(self.window, len(series))
        window_data = series.iloc[-effective_window:]
        
        mean = float(window_data.mean())
        std = float(window_data.std())
        latest = float(series.iloc[-1])
        
        # z-score
        if std > 0:
            z_raw = (latest - mean) / std
            z_clipped = float(np.clip(z_raw, -3, 3))
        else:
            z_raw = 0.0
            z_clipped = 0.0
        
        direction = var_semantics.get("direction", "normal")
        
        # 根据方向调整贡献
        if direction == "inverted":
            contribution = z_clipped * weight * -1  # 反向
        else:
            contribution = z_clipped * weight
        
        # 二阶变化
        change_1w = self._compute_change(series, 5)
        change_1m = self._compute_change(series, 22)
        change_3m = self._compute_change(series, 66)
        z_change_1m = self._compute_z_change(series, 22)
        
        return VariableAttribution(
            series_id=series_id,
            role=var_semantics.get("role", series_id),
            latest_value=latest,
            mean_5y=mean,
            std_5y=std,
            z_score=z_raw,
            z_clipped=z_clipped,
            direction=direction,
            weight=weight,
            contribution=contribution,
            intuition=var_semantics.get("intuition", ""),
            change_1w=change_1w,
            change_1m=change_1m,
            change_3m=change_3m,
            z_change_1m=z_change_1m,
        )
    
    def _compute_change(self, series: pd.Series, periods: int) -> Optional[float]:
        """计算绝对变化"""
        if len(series) < periods + 1:
            return None
        return float(series.iloc[-1] - series.iloc[-periods - 1])
    
    def _compute_z_change(self, series: pd.Series, periods: int) -> Optional[float]:
        """计算 z-score 变化"""
        if len(series) < periods + self.window:
            return None
        
        # 当前 z-score
        current_window = series.iloc[-min(self.window, len(series)):]
        current_mean = current_window.mean()
        current_std = current_window.std()
        if current_std > 0:
            current_z = (series.iloc[-1] - current_mean) / current_std
        else:
            current_z = 0
        
        # N 天前的 z-score
        past_series = series.iloc[:-periods]
        past_window = past_series.iloc[-min(self.window, len(past_series)):]
        past_mean = past_window.mean()
        past_std = past_window.std()
        if past_std > 0:
            past_z = (past_series.iloc[-1] - past_mean) / past_std
        else:
            past_z = 0
        
        return float(current_z - past_z)
    
    def _compute_channel_attribution(self, channel_id: str) -> ChannelAttribution:
        """计算通道归因"""
        semantics = CHANNEL_SEMANTICS[channel_id]
        from paper_interface.proxy_computer import PROXY_BASKETS
        config = PROXY_BASKETS[channel_id]
        
        # 计算每个变量的归因
        variables = []
        total_contribution = 0
        total_weight = 0
        
        for series_id, weight, invert in zip(
            config.series_ids, config.weights, config.invert
        ):
            var_attr = self._compute_variable_attribution(
                series_id, channel_id, weight
            )
            if var_attr:
                variables.append(var_attr)
                total_contribution += var_attr.contribution
                total_weight += weight
        
        level = total_contribution / total_weight if total_weight > 0 else 0
        
        # 子通道
        sub_channels = {}
        if "sub_channels" in semantics:
            for sub_id, sub_def in semantics["sub_channels"].items():
                sub_vars = [v for v in variables if v.series_id in sub_def["variables"]]
                if sub_vars:
                    sub_level = sum(v.contribution for v in sub_vars) / len(sub_vars)
                    sub_channels[sub_id] = sub_level
        
        # 二阶动量
        proxy_series = self.pc.compute_proxy(channel_id)
        momentum_1w = self._compute_change(proxy_series, 5)
        momentum_1m = self._compute_change(proxy_series, 22)
        momentum_3m = self._compute_change(proxy_series, 66)
        acceleration = self._compute_acceleration(proxy_series)
        
        # 解读 level
        level_interp = self._interpret_level(channel_id, level)
        
        return ChannelAttribution(
            channel_id=channel_id,
            channel_name=semantics["name"],
            economic_meaning=semantics["economic_meaning"],
            level=level,
            level_interpretation=level_interp,
            positive_means=semantics["positive_means"],
            negative_means=semantics["negative_means"],
            variables=variables,
            sub_channels=sub_channels,
            momentum_1w=momentum_1w,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            acceleration=acceleration,
        )
    
    def _compute_acceleration(self, series: pd.Series) -> Optional[float]:
        """计算加速度（动量的变化）"""
        if len(series) < 44:
            return None
        momentum_recent = series.iloc[-1] - series.iloc[-22]
        momentum_prior = series.iloc[-22] - series.iloc[-44]
        return float(momentum_recent - momentum_prior)
    
    def _interpret_level(self, channel_id: str, level: float) -> str:
        """解读通道水平"""
        if abs(level) < 0.3:
            return "中性"
        elif level > 1.5:
            return "极端偏高"
        elif level > 0.5:
            return "偏高"
        elif level < -1.5:
            return "极端偏低"
        elif level < -0.5:
            return "偏低"
        return "轻微偏离"
    
    def _identify_regime(
        self, channels: dict[str, ChannelAttribution]
    ) -> RegimeResult:
        """识别 regime"""
        m = channels["M"].level
        d = channels["D"].level
        k = channels["K"].level
        x = channels["X"].level
        
        for rule in REGIME_RULES:
            if rule["condition"](m, d, k, x):
                return RegimeResult(
                    regime_name=rule["name"],
                    regime_label=rule["label"],
                    description=rule["description"],
                    tradeability=rule["tradeability"],
                    watch_vars=rule["watch_vars"],
                )
        
        return RegimeResult(
            regime_name="Unclassified",
            regime_label="未分类",
            description="当前状态不匹配任何已知模式",
            tradeability="WATCHLIST",
            watch_vars=[],
        )
    
    def generate_report(self) -> AttributionReport:
        """生成完整归因报告"""
        channels = {}
        for channel_id in ["M", "D", "K", "X"]:
            channels[channel_id] = self._compute_channel_attribution(channel_id)
        
        regime = self._identify_regime(channels)
        
        # 生成摘要
        summary = self._generate_summary(channels, regime)
        
        return AttributionReport(
            date=str(self.pc._get_series("FRED:T10Y2Y").index[-1].date()),
            channels=channels,
            regime=regime,
            summary=summary,
        )
    
    def _generate_summary(
        self,
        channels: dict[str, ChannelAttribution],
        regime: RegimeResult,
    ) -> str:
        """生成文字摘要"""
        lines = []
        
        lines.append(f"## 市场状态：{regime.regime_label} ({regime.regime_name})")
        lines.append(f"")
        lines.append(f"**可交易性：{regime.tradeability}**")
        lines.append(f"")
        lines.append(f"> {regime.description}")
        lines.append(f"")
        
        if regime.watch_vars:
            lines.append(f"**观察变量：** {', '.join(regime.watch_vars)}")
            lines.append(f"")
        
        lines.append("---")
        lines.append("")
        
        for ch_id, ch in channels.items():
            lines.append(f"### {ch_id} 通道：{ch.channel_name}")
            lines.append(f"- **经济含义：** {ch.economic_meaning}")
            lines.append(f"- **当前水平：** {ch.level:+.2f} ({ch.level_interpretation})")
            lines.append(f"- **正向含义：** {ch.positive_means}")
            lines.append(f"- **负向含义：** {ch.negative_means}")
            
            # 二阶
            if ch.momentum_1w is not None:
                lines.append(f"- **动量：** 1周 {ch.momentum_1w:+.2f} | 1月 {ch.momentum_1m:+.2f} | 3月 {ch.momentum_3m:+.2f}" if ch.momentum_1m and ch.momentum_3m else "")
            if ch.acceleration is not None:
                lines.append(f"- **加速度：** {ch.acceleration:+.2f}")
            
            # 子通道
            if ch.sub_channels:
                lines.append(f"- **子通道：**")
                for sub_id, sub_val in ch.sub_channels.items():
                    lines.append(f"  - {sub_id}: {sub_val:+.2f}")
            
            # 变量归因
            lines.append(f"- **变量归因：**")
            lines.append(f"  | 变量 | 角色 | 最新值 | 5年均值 | z-score | 方向 | 贡献 | 直觉 |")
            lines.append(f"  |------|------|--------|---------|---------|------|------|------|")
            
            for v in ch.variables:
                dir_str = "↑正向" if v.direction == "normal" else "↓反向"
                lines.append(
                    f"  | {v.series_id} | {v.role} | {v.latest_value:.2f} | "
                    f"{v.mean_5y:.2f} | {v.z_score:+.2f} | {dir_str} | "
                    f"{v.contribution:+.3f} | {v.intuition} |"
                )
            
            lines.append("")
        
        return "\n".join(lines)


def format_attribution_markdown(report: AttributionReport) -> str:
    """格式化为 Markdown"""
    lines = []
    
    lines.append(f"# M/D/K/X 归因报告")
    lines.append(f"**日期：** {report.date}")
    lines.append(f"**版本：** v2.0 (语义校准 + 二阶归因)")
    lines.append(f"")
    lines.append(report.summary)
    
    return "\n".join(lines)
