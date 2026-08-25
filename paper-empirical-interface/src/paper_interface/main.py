#!/usr/bin/env python3
"""
论文经验接口 - 主入口

用法:
    python -m paper_interface.main --all                    # 生成所有输出
    python -m paper_interface.main --proxies                # 只生成代理数据
    python -m paper_interface.main --signatures             # 只生成特征量
    python -m paper_interface.main --case treasury_2020     # 分析单个案例
    python -m paper_interface.main --figures                # 生成图表
"""

import argparse
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from paper_interface import CaseAnalyzer, FigureGenerator, ProxyComputer, SignatureQuantities

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description="Paper Empirical Interface")
    parser.add_argument("--all", action="store_true", help="Generate all outputs")
    parser.add_argument("--proxies", action="store_true", help="Compute proxies")
    parser.add_argument("--signatures", action="store_true", help="Compute signature quantities")
    parser.add_argument("--case", type=str, help="Analyze specific case (treasury_2020 or svb_2023)")
    parser.add_argument("--figures", action="store_true", help="Generate figures")
    parser.add_argument("--start", type=str, default="2015-01-01", help="Start date")
    parser.add_argument("--end", type=str, default="", help="End date")
    parser.add_argument(
        "--output",
        type=str,
        default=str(_PACKAGE_ROOT / "output"),
        help="Output directory",
    )

    args = parser.parse_args()

    output_dir = Path(args.output)
    data_dir = output_dir / "data"
    figures_dir = output_dir / "figures"

    print("=" * 60)
    print("论文经验接口 (Paper Empirical Interface)")
    print("=" * 60)

    # 初始化
    print("\n[1/4] 初始化...")
    proxy_computer = ProxyComputer(window=260)

    # 检查可用系列
    available = proxy_computer.get_available_series()
    print("\n可用系列:")
    for channel, series in available.items():
        print(f"  {channel}: {series}")

    # 计算代理
    if args.all or args.proxies:
        print("\n[2/4] 计算代理值...")
        proxies = proxy_computer.compute_all_proxies(args.start, args.end)

        # 保存
        data_dir.mkdir(parents=True, exist_ok=True)
        proxies.to_parquet(data_dir / "proxies.parquet")
        proxies.to_csv(data_dir / "proxies.csv")
        print(f"  保存到: {data_dir / 'proxies.parquet'}")
        print(f"  形状: {proxies.shape}")

        if not proxies.empty:
            print(f"  日期范围: {proxies.index[0]} 到 {proxies.index[-1]}")

            # 最新值
            print("\n  最新代理值:")
            for col in proxies.columns:
                val = proxies[col].iloc[-1]
                print(f"    {col}: {val:.4f}")
        else:
            print("  ⚠️ 警告: 代理数据为空，可能日期范围不正确")

    # 计算特征量
    if args.all or args.signatures:
        print("\n[3/4] 计算特征量...")
        proxies = proxy_computer.compute_all_proxies(args.start, args.end)
        signatures = SignatureQuantities(proxies)

        sig_data = signatures.export_for_paper(str(data_dir / "signatures"))
        print(f"  保存到: {data_dir / 'signatures'}")
        for name, df in sig_data.items():
            print(f"    {name}: {df.shape}")

    # 案例分析
    if args.all or args.case:
        print("\n[3.5/4] 案例分析...")
        proxies = proxy_computer.compute_all_proxies(args.start, args.end)
        signatures = SignatureQuantities(proxies)
        case_analyzer = CaseAnalyzer(proxy_computer, signatures)

        cases_to_analyze = [args.case] if args.case else ["treasury_2020", "svb_2023"]

        for case_id in cases_to_analyze:
            print(f"\n  分析案例: {case_id}")
            result = case_analyzer.analyze_case(case_id)
            print(f"    名称: {result.case_name}")
            print(f"    期间: {result.period}")
            print(f"    通道: {result.metadata['channels']}")
            print(f"    压力评分均值: {result.stress_scores.mean():.4f}" if not result.stress_scores.empty else "    压力评分: N/A")

            # 通道分析
            for channel, stats in result.channel_analysis.items():
                print(f"    {channel}: mean={stats['mean']:.4f}, max={stats['max']:.4f}")

            # 导出
            case_analyzer.export_case_for_paper(case_id, str(data_dir / "cases"))

    # 生成图表
    if args.all or args.figures:
        print("\n[4/4] 生成图表...")
        proxies = proxy_computer.compute_all_proxies(args.start, args.end)
        signatures = SignatureQuantities(proxies)

        fig_gen = FigureGenerator(str(figures_dir))

        # 代理时间序列图
        print("  生成代理时间序列图...")
        fig_gen.plot_proxy_time_series(
            proxies,
            highlight_periods=[
                {"start": "2020-03-01", "end": "2020-04-30", "label": "COVID-19"},
                {"start": "2023-03-01", "end": "2023-04-30", "label": "SVB Crisis"},
            ]
        )

        # 案例分析图
        case_analyzer = CaseAnalyzer(proxy_computer, signatures)
        for case_id in ["treasury_2020", "svb_2023"]:
            print(f"  生成案例图: {case_id}...")
            result = case_analyzer.analyze_case(case_id)
            fig_gen.plot_case_study(
                result.case_name,
                result.proxies,
                result.stress_scores,
                result.key_events,
                save_name=case_id,
            )

        # 特征量图
        sig_result = signatures.compute_all_signatures()
        print("  生成特征量图...")
        fig_gen.plot_signature_quantities(
            sig_result.non_commutativity,
            sig_result.mean_field_gap,
        )

        # 影子质量期限分布图
        print("  生成影子质量期限分布图...")
        fig_gen.plot_shadow_maturity_profile(sig_result.shadow_maturity)

        print(f"\n  图表保存到: {figures_dir}")

    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
