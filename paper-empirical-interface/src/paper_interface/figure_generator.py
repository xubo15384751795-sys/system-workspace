"""
Figure Generator - 生成论文需要的图表

使用 matplotlib 生成论文格式的图表
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from typing import Optional


# 论文风格设置
PAPER_STYLE = {
    "figure.figsize": (10, 6),
    "figure.dpi": 150,
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "legend.fontsize": 10,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
}

# 通道颜色
CHANNEL_COLORS = {
    "M": "#E74C3C",  # 红色 - 锚定错配
    "D": "#3498DB",  # 蓝色 - 路径可行性
    "K": "#2ECC71",  # 绿色 - 转换变形
    "X": "#9B59B6",  # 紫色 - 影子积累
}


class FigureGenerator:
    """
    生成论文需要的图表
    
    隔离原则：
    - 只读取计算结果，不修改任何模块
    - 输出标准格式的图表
    """
    
    def __init__(self, output_dir: str | Path = "/Users/a1/System/paper-empirical-interface/output/figures"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 应用论文风格
        plt.rcParams.update(PAPER_STYLE)
    
    def plot_proxy_time_series(
        self,
        proxy_data: pd.DataFrame,
        title: str = "Anchor-Mismatch Proxy Channels",
        highlight_periods: list[dict] = None,
        save_name: str = "proxy_time_series",
    ) -> plt.Figure:
        """
        绘制代理通道时间序列
        
        Args:
            proxy_data: ProxyComputer.compute_all_proxies() 的输出
            title: 图表标题
            highlight_periods: 高亮时间段 [{"start": "2020-03-01", "end": "2020-04-30", "label": "COVID"}]
            save_name: 保存文件名
        """
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes = axes.flatten()
        
        for idx, channel in enumerate(["M", "D", "K", "X"]):
            if channel not in proxy_data.columns:
                continue
            
            ax = axes[idx]
            series = proxy_data[channel].dropna()
            
            ax.plot(series.index, series.values, 
                   color=CHANNEL_COLORS[channel], linewidth=1.5, alpha=0.8)
            ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
            
            # 高亮压力期间
            if highlight_periods:
                for period in highlight_periods:
                    ax.axvspan(
                        pd.Timestamp(period["start"]),
                        pd.Timestamp(period["end"]),
                        alpha=0.2, color='red',
                        label=period.get("label", "")
                    )
            
            ax.set_title(f"{channel} Channel ({self._get_channel_description(channel)})")
            ax.set_ylabel("Z-Score")
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.xaxis.set_major_locator(mdates.YearLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        fig.suptitle(title, fontsize=14, fontweight='bold')
        plt.tight_layout()
        
        # 保存
        fig.savefig(self.output_dir / f"{save_name}.pdf", bbox_inches='tight')
        fig.savefig(self.output_dir / f"{save_name}.png", bbox_inches='tight')
        
        return fig
    
    def plot_case_study(
        self,
        case_name: str,
        proxy_data: pd.DataFrame,
        stress_scores: pd.Series,
        key_events: list[dict],
        save_name: str = "",
    ) -> plt.Figure:
        """
        绘制案例分析图
        
        Args:
            case_name: 案例名称
            proxy_data: 案例期间的代理数据
            stress_scores: 压力评分
            key_events: 关键事件列表
            save_name: 保存文件名
        """
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[2, 1])
        
        # 上图：代理通道
        for channel in proxy_data.columns:
            if channel in CHANNEL_COLORS:
                series = proxy_data[channel].dropna()
                ax1.plot(series.index, series.values,
                        color=CHANNEL_COLORS[channel], linewidth=1.5,
                        label=f"{channel} Channel", alpha=0.8)
        
        # 标记关键事件
        for event in key_events:
            event_date = pd.Timestamp(event["date"])
            ax1.axvline(x=event_date, color='red', linestyle=':', alpha=0.7)
            ax1.annotate(
                event["event"][:30] + "..." if len(event["event"]) > 30 else event["event"],
                xy=(event_date, ax1.get_ylim()[1]),
                xytext=(10, 10), textcoords='offset points',
                fontsize=8, rotation=45, alpha=0.7,
            )
        
        ax1.set_title(f"{case_name}: Proxy Channels")
        ax1.set_ylabel("Z-Score")
        ax1.legend(loc='upper left')
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
        
        # 下图：压力评分
        if not stress_scores.empty:
            ax2.fill_between(stress_scores.index, stress_scores.values,
                            alpha=0.3, color='red')
            ax2.plot(stress_scores.index, stress_scores.values,
                    color='red', linewidth=1.5)
            ax2.set_title("Joint Stress Score Σ_t")
            ax2.set_ylabel("Score")
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        # 保存
        if not save_name:
            save_name = case_name.lower().replace(" ", "_").replace(":", "")
        
        fig.savefig(self.output_dir / f"{save_name}.pdf", bbox_inches='tight')
        fig.savefig(self.output_dir / f"{save_name}.png", bbox_inches='tight')
        
        return fig
    
    def plot_signature_quantities(
        self,
        non_commutativity: pd.Series,
        mean_field_gap: pd.Series,
        save_name: str = "signature_quantities",
    ) -> plt.Figure:
        """
        绘制特征量图
        
        Args:
            non_commutativity: 非交换性指标
            mean_field_gap: 平均场差距
            save_name: 保存文件名
        """
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        
        # 非交换性
        if not non_commutativity.empty:
            ax1.plot(non_commutativity.index, non_commutativity.values,
                    color='#E74C3C', linewidth=1.5)
            ax1.fill_between(non_commutativity.index, non_commutativity.values,
                            alpha=0.3, color='#E74C3C')
            ax1.set_title("Event-Sequence Non-Commutativity Δ_t^NC")
            ax1.set_ylabel("NC Index")
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        
        # 平均场差距
        if not mean_field_gap.empty:
            ax2.plot(mean_field_gap.index, mean_field_gap.values,
                    color='#3498DB', linewidth=1.5)
            ax2.fill_between(mean_field_gap.index, mean_field_gap.values,
                            alpha=0.3, color='#3498DB')
            ax2.set_title("Mean-Field Gap G_t^mf")
            ax2.set_ylabel("Gap")
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        
        plt.tight_layout()
        
        fig.savefig(self.output_dir / f"{save_name}.pdf", bbox_inches='tight')
        fig.savefig(self.output_dir / f"{save_name}.png", bbox_inches='tight')
        
        return fig
    
    def plot_shadow_maturity_profile(
        self,
        shadow_maturity: pd.DataFrame,
        save_name: str = "shadow_maturity",
    ) -> plt.Figure:
        """
        绘制影子质量期限分布
        
        Args:
            shadow_maturity: 期限分布 DataFrame
            save_name: 保存文件名
        """
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # 热力图
        if not shadow_maturity.empty:
            # 只显示最近 2 年的数据
            recent = shadow_maturity.tail(504)
            
            im = ax.imshow(recent.values.T, aspect='auto', cmap='YlOrRd',
                          interpolation='nearest')
            
            # 设置刻度
            ax.set_yticks(range(len(recent.columns)))
            ax.set_yticklabels(recent.columns)
            
            # X 轴日期
            tick_positions = np.linspace(0, len(recent) - 1, 10, dtype=int)
            ax.set_xticks(tick_positions)
            ax.set_xticklabels([recent.index[i].strftime('%Y-%m') for i in tick_positions],
                              rotation=45)
            
            ax.set_title("Shadow Mass Maturity Profile m_t(B)")
            ax.set_xlabel("Date")
            ax.set_ylabel("Maturity Bucket")
            
            plt.colorbar(im, ax=ax, label="Shadow Mass")
        
        plt.tight_layout()
        
        fig.savefig(self.output_dir / f"{save_name}.pdf", bbox_inches='tight')
        fig.savefig(self.output_dir / f"{save_name}.png", bbox_inches='tight')
        
        return fig
    
    def _get_channel_description(self, channel: str) -> str:
        """获取通道描述"""
        descriptions = {
            "M": "Anchor Mismatch",
            "D": "Path Feasibility",
            "K": "Transition Deformation",
            "X": "Shadow Accumulation",
        }
        return descriptions.get(channel, channel)
