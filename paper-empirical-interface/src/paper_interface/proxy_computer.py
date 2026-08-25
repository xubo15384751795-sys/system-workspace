"""
Proxy Computer - 计算论文 §7 定义的代理篮子

只读取 Harvester 输出，不修改任何现有模块
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PANEL = (
    _WORKSPACE_ROOT
    / "Data"
    / "harvester"
    / "exports"
    / "latest"
    / "data"
    / "benchmark_panel.parquet"
)


@dataclass
class ProxyConfig:
    """代理配置"""
    series_ids: list[str]
    weights: list[float]
    invert: list[bool]
    description: str


# 论文 §7.2 定义的代理篮子
PROXY_BASKETS = {
    "M": ProxyConfig(
        series_ids=["FRED:T10Y2Y", "FRED:DFF"],
        weights=[1.0, 1.0],
        invert=[True, False],
        description="Anchor mismatch (funding gap, curve shape)"
    ),
    "D": ProxyConfig(
        series_ids=["FRED:BAMLH0A0HYM2", "FRED:VIXCLS", "H41:discount_window"],
        weights=[1.0, 1.0, 1.0],
        invert=[True, True, True],
        description="Path feasibility (depth, hedge breadth, funding access)"
    ),
    "K": ProxyConfig(
        series_ids=["FRED:VIXCLS", "CBOE:SKEW", "CBOE:VVIX"],
        weights=[1.0, 0.5, 0.5],
        invert=[False, False, False],
        description="Transition deformation (IV distortion, jump intensity)"
    ),
    "X": ProxyConfig(
        series_ids=["H41:primary_credit", "H41:btfp", "SEC:0000072971"],
        weights=[1.0, 0.5, 0.3],
        invert=[False, False, False],
        description="Shadow accumulation (emergency credit facilities)"
    ),
}


class ProxyComputer:
    """
    计算论文定义的代理篮子

    隔离原则：
    - 只读取 Harvester 的 benchmark_panel
    - 不修改任何现有模块
    - 输出标准化的代理值
    """

    def __init__(
        self,
        data_path: str | Path = _DEFAULT_PANEL,
        window: int = 260,
    ):
        self.data_path = Path(data_path)
        self.window = window
        self._series_cache: dict[str, pd.Series] = {}

    def _get_series(self, series_id: str) -> pd.Series:
        """获取单个系列的时间序列（带缓存）"""
        if series_id not in self._series_cache:
            df = pd.read_parquet(
                self.data_path,
                filters=[("series_id", "==", series_id)],
                columns=["date", "value"],
            )
            if df.empty:
                self._series_cache[series_id] = pd.Series(dtype=float)
            else:
                df["date"] = pd.to_datetime(df["date"])
                series = df.set_index("date")["value"].sort_index()
                series = series[~series.index.duplicated(keep="last")]
                self._series_cache[series_id] = series.dropna()
        return self._series_cache[series_id]

    def compute_proxy(self, channel: str, start: str = "", end: str = "") -> pd.Series:
        """计算单个通道的代理值"""
        if channel not in PROXY_BASKETS:
            raise ValueError(f"Unknown channel: {channel}")

        config = PROXY_BASKETS[channel]

        scores = []
        for series_id, weight, invert in zip(config.series_ids, config.weights, config.invert):
            series = self._get_series(series_id)
            if len(series) < 4:
                continue

            # 过滤日期范围
            if start:
                series = series.loc[start:]
            if end:
                series = series.loc[:end]

            if len(series) < 4:
                continue

            # 滚动 z-score
            rolling_mean = series.rolling(window=self.window, min_periods=4).mean()
            rolling_std = series.rolling(window=self.window, min_periods=4).std()
            rolling_std = rolling_std.replace(0, np.nan)

            z = (series - rolling_mean) / rolling_std
            z = z.clip(-3, 3)

            if invert:
                z = -z

            scores.append(z * weight)

        if not scores:
            return pd.Series(dtype=float)

        result = pd.concat(scores, axis=1).mean(axis=1).dropna()

        if start:
            result = result.loc[start:]
        if end:
            result = result.loc[:end]

        return result

    def compute_all_proxies(self, start: str = "", end: str = "") -> pd.DataFrame:
        """计算所有通道的代理值"""
        results = {}
        for channel in PROXY_BASKETS:
            results[channel] = self.compute_proxy(channel, start, end)

        df = pd.DataFrame(results)
        if not df.empty:
            df = df.dropna(how="all")

        return df

    def get_available_series(self) -> dict[str, list[str]]:
        """获取每个通道可用的系列"""
        available = {}
        for channel, config in PROXY_BASKETS.items():
            channel_available = []
            for series_id in config.series_ids:
                series = self._get_series(series_id)
                if len(series) > 0:
                    channel_available.append(series_id)
            available[channel] = channel_available
        return available

    def export_for_paper(
        self,
        start: str = "2015-01-01",
        end: str = "",
        output_path: str | Path = "",
    ) -> pd.DataFrame:
        """导出论文需要的代理数据"""
        proxies = self.compute_all_proxies(start, end)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            proxies.to_parquet(output_path)
            print(f"Exported proxies to {output_path}")

        return proxies
