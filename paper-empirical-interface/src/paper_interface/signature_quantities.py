"""
Signature Quantities - 计算论文 §7.1 定义的三个特征量

1. 事件序列非交换性 Δ_t^NC
2. 平均场差距 G_t^mf
3. 影子质量期限分布 m_t(B)
"""

import pandas as pd
import numpy as np
from typing import Optional
from dataclasses import dataclass


@dataclass
class SignatureResult:
    """特征量计算结果"""
    non_commutativity: pd.Series  # Δ_t^NC
    mean_field_gap: pd.Series     # G_t^mf
    shadow_maturity: pd.DataFrame # m_t(B) by maturity bucket
    metadata: dict


class SignatureQuantities:
    """
    计算论文定义的三个特征量
    
    隔离原则：
    - 只使用 ProxyComputer 的输出
    - 不修改任何现有模块
    """
    
    def __init__(self, proxy_data: pd.DataFrame):
        """
        Args:
            proxy_data: ProxyComputer.compute_all_proxies() 的输出
        """
        self.proxy_data = proxy_data
    
    def compute_non_commutativity(
        self,
        channel_a: str = "M",
        channel_b: str = "D",
        window: int = 20,
    ) -> pd.Series:
        """
        计算事件序列非交换性 Δ_t^NC
        
        论文 §7.1: Δ_t^NC = d(T(z_t, p_ab), T(z_t, p_ba))
        
        简化实现：计算两个通道的滚动相关性的时变性
        当相关性不稳定时，表明序列效应是结构性的
        
        Args:
            channel_a: 第一个通道
            channel_b: 第二个通道
            window: 滚动窗口
        
        Returns:
            非交换性指标时间序列
        """
        if channel_a not in self.proxy_data.columns:
            raise ValueError(f"Channel {channel_a} not in proxy data")
        if channel_b not in self.proxy_data.columns:
            raise ValueError(f"Channel {channel_b} not in proxy data")
        
        a = self.proxy_data[channel_a].dropna()
        b = self.proxy_data[channel_b].dropna()
        
        # 对齐索引
        common_idx = a.index.intersection(b.index)
        a = a.loc[common_idx]
        b = b.loc[common_idx]
        
        # 计算滚动相关性
        rolling_corr = a.rolling(window=window, min_periods=10).corr(b)
        
        # 非交换性 = 滚动相关性的波动率
        # 高波动率 = 序列效应是结构性的
        nc = rolling_corr.rolling(window=window, min_periods=10).std()
        
        return nc
    
    def compute_mean_field_gap(
        self,
        channel: str = "X",
        reference_window: int = 260,
    ) -> pd.Series:
        """
        计算平均场差距 G_t^mf
        
        论文 §7.1: G_t^mf = |X_t^agg - X̄_t^mf|
        
        简化实现：当前值与长期均值的偏离
        
        Args:
            channel: 通道名称
            reference_window: 参考窗口（长期均值）
        
        Returns:
            平均场差距时间序列
        """
        if channel not in self.proxy_data.columns:
            raise ValueError(f"Channel {channel} not in proxy data")
        
        x = self.proxy_data[channel].dropna()
        
        # 长期均值作为平均场近似
        x_mf = x.rolling(window=reference_window, min_periods=52).mean()
        
        # 差距
        gap = (x - x_mf).abs()
        
        return gap
    
    def compute_shadow_maturity_profile(
        self,
        x_proxy: pd.Series,
        maturity_buckets: Optional[list[float]] = None,
    ) -> pd.DataFrame:
        """
        计算影子质量期限分布 m_t(B)
        
        论文 §7.1: m_t(B) = ∫_B X_t(ξ)dξ
        
        简化实现：使用不同期限的 H41 数据作为代理
        
        Args:
            x_proxy: X 通道代理值
            maturity_buckets: 期限桶（年）
        
        Returns:
            期限分布 DataFrame
        """
        if maturity_buckets is None:
            maturity_buckets = [0.25, 1.0, 5.0, 10.0, 30.0]
        
        # 简化实现：使用 X 代理值的不同滚动窗口作为期限代理
        # 较短窗口 = 短期压力，较长窗口 = 长期压力
        profiles = {}
        
        for bucket in maturity_buckets:
            # 使用期限对应的滚动窗口（年 → 天）
            window = max(int(bucket * 252), 20)
            profiles[f"{bucket}Y"] = x_proxy.rolling(window=window, min_periods=10).mean()
        
        return pd.DataFrame(profiles)
    
    def compute_all_signatures(
        self,
        channel_pairs: list[tuple[str, str]] = None,
    ) -> SignatureResult:
        """
        计算所有特征量
        
        Args:
            channel_pairs: 通道对列表，默认为 [("M", "D"), ("M", "K"), ("D", "K")]
        
        Returns:
            SignatureResult 包含所有特征量
        """
        if channel_pairs is None:
            channel_pairs = [("M", "D"), ("M", "K"), ("D", "K")]
        
        # 1. 非交换性
        nc_results = {}
        for ch_a, ch_b in channel_pairs:
            nc_results[f"NC_{ch_a}_{ch_b}"] = self.compute_non_commutativity(ch_a, ch_b)
        nc_df = pd.DataFrame(nc_results)
        
        # 2. 平均场差距
        mfg_results = {}
        for channel in ["M", "D", "K", "X"]:
            if channel in self.proxy_data.columns:
                mfg_results[f"MFG_{channel}"] = self.compute_mean_field_gap(channel)
        mfg_df = pd.DataFrame(mfg_results)
        
        # 3. 影子质量期限分布
        if "X" in self.proxy_data.columns:
            shadow_maturity = self.compute_shadow_maturity_profile(self.proxy_data["X"])
        else:
            shadow_maturity = pd.DataFrame()
        
        # 合并非交换性和平均场差距
        nc_mfg = pd.concat([nc_df, mfg_df], axis=1)
        
        return SignatureResult(
            non_commutativity=nc_df.mean(axis=1),
            mean_field_gap=mfg_df.mean(axis=1) if not mfg_df.empty else pd.Series(dtype=float),
            shadow_maturity=shadow_maturity,
            metadata={
                "channel_pairs": channel_pairs,
                "nc_columns": list(nc_df.columns),
                "mfg_columns": list(mfg_df.columns),
            }
        )
    
    def export_for_paper(
        self,
        output_path: str = "",
    ) -> dict[str, pd.DataFrame]:
        """
        导出论文需要的特征量数据
        
        Returns:
            字典包含所有特征量 DataFrame
        """
        signatures = self.compute_all_signatures()
        
        result = {
            "non_commutativity": signatures.non_commutativity.to_frame("NC"),
            "mean_field_gap": signatures.mean_field_gap.to_frame("MFG"),
            "shadow_maturity": signatures.shadow_maturity,
        }
        
        if output_path:
            import os
            os.makedirs(output_path, exist_ok=True)
            for name, df in result.items():
                df.to_parquet(os.path.join(output_path, f"{name}.parquet"))
            print(f"Exported signatures to {output_path}")
        
        return result
