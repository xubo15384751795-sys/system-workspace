"""
Case Analyzer - 论文 §7.3 案例分析

Case A: March 2020 Treasury market stress
Case B: March 2023 SVB/regional-bank stress
"""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CaseResult:
    """案例分析结果"""
    case_name: str
    period: tuple[str, str]
    proxies: pd.DataFrame
    stress_scores: pd.Series
    key_events: list[dict]
    channel_analysis: dict[str, dict]
    metadata: dict = field(default_factory=dict)


# 案例定义
CASES = {
    "treasury_2020": {
        "name": "Case A: March 2020 Treasury Market Stress",
        "period": ("2020-02-01", "2020-06-30"),
        "channels": ["M", "D", "K"],
        "key_events": [
            {"date": "2020-03-09", "event": "Treasury basis trade unwinds begin"},
            {"date": "2020-03-12", "event": "10Y Treasury yield rises 25bp in one week"},
            {"date": "2020-03-15", "event": "Fed cuts to zero, announces $700B QE"},
            {"date": "2020-03-23", "event": "Fed announces unlimited QE"},
        ],
        "description": "Leveraged Treasury basis trading unwinds, liquidity collapses",
    },
    "svb_2023": {
        "name": "Case B: March 2023 SVB/Regional-Bank Stress",
        "period": ("2023-02-01", "2023-05-31"),
        "channels": ["M", "D", "X"],
        "key_events": [
            {"date": "2023-03-08", "event": "SVB announces $1.8B loss, stock crashes"},
            {"date": "2023-03-10", "event": "FDIC closes SVB ($209B assets)"},
            {"date": "2023-03-12", "event": "Fed announces Bank Term Funding Program"},
            {"date": "2023-03-19", "event": "UBS acquires Credit Suisse"},
        ],
        "description": "Duration mismatch, uninsured deposit runs, shadow banking stress",
    },
}


class CaseAnalyzer:
    """
    论文案例分析

    隔离原则：
    - 只使用 ProxyComputer 和 SignatureQuantities 的输出
    - 不修改任何现有模块
    """

    def __init__(self, proxy_computer, signature_quantities=None):
        """
        Args:
            proxy_computer: ProxyComputer 实例
            signature_quantities: SignatureQuantities 实例（可选）
        """
        self.proxy_computer = proxy_computer
        self.signature_quantities = signature_quantities

    def analyze_case(self, case_id: str) -> CaseResult:
        """
        分析单个案例

        Args:
            case_id: 案例 ID ("treasury_2020" 或 "svb_2023")

        Returns:
            CaseResult
        """
        if case_id not in CASES:
            raise ValueError(f"Unknown case: {case_id}. Must be one of {list(CASES.keys())}")

        case = CASES[case_id]
        start, end = case["period"]

        # 获取代理数据
        proxies = self.proxy_computer.compute_all_proxies(start, end)

        # 计算压力评分（等权平均）
        available_channels = [ch for ch in case["channels"] if ch in proxies.columns]
        if available_channels:
            stress_scores = proxies[available_channels].mean(axis=1)
        else:
            stress_scores = pd.Series(dtype=float)

        # 通道分析
        channel_analysis = {}
        for channel in available_channels:
            series = proxies[channel].dropna()
            if len(series) > 0:
                channel_analysis[channel] = {
                    "mean": float(series.mean()),
                    "std": float(series.std()),
                    "max": float(series.max()),
                    "max_date": str(series.idxmax()),
                    "min": float(series.min()),
                    "min_date": str(series.idxmin()),
                    "current": float(series.iloc[-1]),
                }

        return CaseResult(
            case_name=case["name"],
            period=case["period"],
            proxies=proxies,
            stress_scores=stress_scores,
            key_events=case["key_events"],
            channel_analysis=channel_analysis,
            metadata={
                "case_id": case_id,
                "description": case["description"],
                "channels": available_channels,
            }
        )

    def analyze_all_cases(self) -> dict[str, CaseResult]:
        """分析所有案例"""
        results = {}
        for case_id in CASES:
            results[case_id] = self.analyze_case(case_id)
        return results

    def export_case_for_paper(
        self,
        case_id: str,
        output_path: str = "",
    ) -> dict:
        """
        导出单个案例的论文数据

        Returns:
            字典包含案例数据
        """
        result = self.analyze_case(case_id)

        export = {
            "case_name": result.case_name,
            "period": result.period,
            "proxies": result.proxies,
            "stress_scores": result.stress_scores.to_frame("stress_score"),
            "channel_analysis": pd.DataFrame(result.channel_analysis).T,
            "key_events": pd.DataFrame(result.key_events),
        }

        if output_path:
            import os
            os.makedirs(output_path, exist_ok=True)
            for name, data in export.items():
                if isinstance(data, pd.DataFrame):
                    data.to_parquet(os.path.join(output_path, f"{case_id}_{name}.parquet"))
                elif isinstance(data, list):
                    pd.DataFrame(data).to_csv(os.path.join(output_path, f"{case_id}_{name}.csv"), index=False)
            print(f"Exported case {case_id} to {output_path}")

        return export

    def export_all_cases_for_paper(self, output_path: str = "") -> dict[str, dict]:
        """导出所有案例"""
        results = {}
        for case_id in CASES:
            results[case_id] = self.export_case_for_paper(case_id, output_path)
        return results
