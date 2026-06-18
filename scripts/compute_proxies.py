#!/usr/bin/env python3
"""
计算代理值
从 Harvester 的 benchmark_panel 计算 M/D/K/X_PROXY
"""

import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# 代理系列映射
PROXY_MAP = {
    'M_PROXY': {
        'series': [
            {'id': 'FRED:T10Y2Y', 'invert': True, 'weight': 1.0},  # 负号表示反向
            {'id': 'FRED:DFF', 'invert': False, 'weight': 1.0},
        ],
        'description': '锚定错配（收益率曲线+政策利率）'
    },
    'D_PROXY': {
        'series': [
            {'id': 'FRED:BAMLH0A0HYM2', 'invert': True, 'weight': 1.0},  # 高信用利差=差
            {'id': 'FRED:VIXCLS', 'invert': True, 'weight': 1.0},  # 高VIX=差
            {'id': 'H41:discount_window', 'invert': True, 'weight': 1.0},  # 高贴现窗口=差
        ],
        'description': '路径可行性（信用+波动率+流动性）'
    },
    'K_PROXY': {
        'series': [
            {'id': 'FRED:VIXCLS', 'invert': False, 'weight': 1.0},  # 高VIX=高转换变形
            {'id': 'TREASURY:debt_to_penny:tot_pub_debt_out_amt', 'invert': False, 'weight': 1.0},  # 高债务=高压力
            {'id': 'TREASURY:daily_treasury_statement:open_today_bal', 'invert': True, 'weight': 1.0},  # 低现金=高压力
        ],
        'description': '转换变形（波动率+债务+现金）'
    },
    'X_PROXY': {
        'series': [
            {'id': 'H41:primary_credit', 'invert': False, 'weight': 1.0},  # 高贴现窗口=高影子积累
            {'id': 'H41:btfp', 'invert': False, 'weight': 0.5},  # BTFP权重较低
            {'id': 'SEC:0000072971', 'invert': False, 'weight': 0.3},  # SEC数据权重更低
        ],
        'description': '影子积累（紧急信贷工具）'
    }
}

def zscore(series, window=260):
    """滚动 z-score（使用滚动窗口避免前瞻偏差）"""
    if len(series) < 4:
        return np.nan
    # 使用滚动窗口（默认 260 周 ≈ 5 年）
    window_size = min(window, len(series))
    window_data = series.iloc[-window_size:]
    
    # 计算滚动均值和标准差
    mean = window_data.mean()
    std = window_data.std()
    
    if std == 0 or np.isnan(std):
        return 0.0
    
    # 获取最新值
    latest = series.iloc[-1]
    
    # Winsorize: 限制在 ±3 标准差内
    clip_std = 3.0
    lo = mean - clip_std * std
    hi = mean + clip_std * std
    latest_clipped = np.clip(latest, lo, hi)
    
    return (latest_clipped - mean) / std

def compute_proxy_history(pivot_df, proxy_name, config, window=260):
    """计算代理的历史值（使用滚动窗口）"""
    # 获取所有可用系列
    available_series = []
    for series_config in config['series']:
        series_id = series_config['id']
        if series_id in pivot_df.columns:
            available_series.append(series_config)
    
    if not available_series:
        return pd.Series(dtype=float)
    
    # 计算每个系列的滚动 z-score
    scores = []
    for series_config in available_series:
        series_id = series_config['id']
        invert = series_config.get('invert', False)
        weight = series_config.get('weight', 1.0)
        
        series = pivot_df[series_id].dropna()
        if len(series) < 4:
            continue
        
        # 计算滚动 z-score
        rolling_mean = series.rolling(window=window, min_periods=4).mean()
        rolling_std = series.rolling(window=window, min_periods=4).std()
        
        # 避免除零
        rolling_std = rolling_std.replace(0, np.nan)
        
        # 计算 z-score
        z = (series - rolling_mean) / rolling_std
        
        # Winsorize
        z = z.clip(-3, 3)
        
        # 反转（如果需要）
        if invert:
            z = -z
        
        scores.append(z * weight)
    
    if not scores:
        return pd.Series(dtype=float)
    
    # 取平均
    result = pd.concat(scores, axis=1).mean(axis=1)
    return result

def main():
    # 读取数据
    print("读取 Harvester 数据...")
    df = pd.read_parquet(Path(__file__).resolve().parents[1] / 'Data' / 'merged_data' / 'benchmark_panel_with_etfs.parquet')
    
    # 去重
    df = df.drop_duplicates(subset=['date', 'series_id'], keep='last')
    
    # 转换为宽格式
    pivot = df.pivot(index='date', columns='series_id', values='value')
    pivot.index = pd.to_datetime(pivot.index)
    pivot = pivot.sort_index()
    
    # 去除重复的日期索引
    pivot = pivot[~pivot.index.duplicated(keep='last')]
    
    print(f"数据形状: {pivot.shape}")
    print(f"日期范围: {pivot.index[0]} 到 {pivot.index[-1]}")
    
    # 计算每个代理的历史值（使用滚动窗口）
    print("\n=== 计算代理值（滚动窗口 z-score） ===")
    
    # 只计算最近 5 年的数据（避免早期数据不足）
    recent_start = pivot.index[-1] - pd.DateOffset(years=5)
    pivot_recent = pivot.loc[recent_start:]
    
    print(f"计算范围: {pivot_recent.index[0]} 到 {pivot_recent.index[-1]}")
    
    proxy_history = {}
    for proxy_name, config in PROXY_MAP.items():
        history = compute_proxy_history(pivot_recent, proxy_name, config, window=260)
        proxy_history[proxy_name] = history
        
        # 检查哪些系列可用
        available = []
        missing = []
        for series_config in config['series']:
            series_id = series_config['id']
            if series_id in pivot.columns and pivot[series_id].notna().any():
                available.append(series_id)
            else:
                missing.append(series_id)
        
        latest_value = history.iloc[-1] if not history.empty else np.nan
        print(f"\n{proxy_name}: {latest_value:.4f}" if not np.isnan(latest_value) else f"\n{proxy_name}: N/A")
        print(f"  可用: {len(available)}/{len(available)+len(missing)}")
        if missing:
            print(f"  缺失: {missing}")
    
    # 合并为 DataFrame
    proxy_df = pd.DataFrame(proxy_history)
    proxy_df.index.name = 'date'
    
    # 显示最近 10 天
    print("\n=== 最近10天代理值 ===")
    print(proxy_df.tail(10).to_string())
    
    # 保存结果
    output_path = Path(__file__).resolve().parents[1] / 'Data' / 'merged_data' / 'proxy_values_rolling.parquet'
    proxy_df.to_parquet(output_path)
    print(f"\n保存到: {output_path}")
    print(f"行数: {len(proxy_df)}")
    print(f"列: {proxy_df.columns.tolist()}")

if __name__ == '__main__':
    main()
