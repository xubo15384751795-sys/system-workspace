#!/usr/bin/env python3
"""
补充 Harvester 缺失数据
从 Data Hub 读取 HYG/LQD/TLT 数据，合并到 Harvester benchmark_panel
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os
import shutil

def merge_data_hub_to_harvester():
    """将 Data Hub 的数据合并到 Harvester"""
    
    # 路径
    data_hub_path = '/Users/a1/Data/latest/combined_panel.parquet'
    harvester_path = '/Users/a1/System/Data/harvester/exports/latest/data/benchmark_panel.parquet'
    
    # 读取数据
    print("读取 Data Hub 数据...")
    data_hub = pd.read_parquet(data_hub_path)
    
    print("读取 Harvester 数据...")
    harvester = pd.read_parquet(harvester_path)
    
    # 需要补充的系列
    missing_series = ['HYG', 'LQD', 'TLT']
    
    # 转换 Data Hub 数据为 Harvester 格式
    new_rows = []
    vintage_date = datetime.now().strftime('%Y-%m-%d')
    
    for series_id in missing_series:
        if series_id not in data_hub.columns:
            print(f"  {series_id}: 未在 Data Hub 中找到")
            continue
        
        series = data_hub[series_id].dropna()
        if series.empty:
            print(f"  {series_id}: 无数据")
            continue
        
        for date, value in series.items():
            new_rows.append({
                'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                'series_id': f'YFINANCE:{series_id}',
                'source_id': 'yfinance',
                'source_series_id': series_id,
                'value': float(value),
                'unit': 'usd',
                'frequency': 'daily',
                'vintage_date': vintage_date,
                'quality_flag': 'observed',
            })
        
        print(f"  {series_id}: 补充 {len(series)} 行数据")
    
    if not new_rows:
        print("没有需要补充的数据")
        return
    
    # 创建新的 DataFrame
    new_df = pd.DataFrame(new_rows)
    
    # 合并
    print(f"\n合并数据...")
    merged = pd.concat([harvester, new_df], ignore_index=True)
    
    # 按日期排序
    merged['date'] = pd.to_datetime(merged['date'])
    merged = merged.sort_values(['series_id', 'date'])
    
    # 备份原文件（如果不存在）
    backup_dir = '/Users/a1/System/Data/merged_data'
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, 'benchmark_panel_backup.parquet')
    if not os.path.exists(backup_path):
        shutil.copy2(harvester_path, backup_path)
        print(f"备份原文件到: {backup_path}")
    else:
        print(f"备份文件已存在: {backup_path}")
    
    # 保存合并后的数据
    output_path = os.path.join(backup_dir, 'benchmark_panel_merged.parquet')
    merged.to_parquet(output_path, index=False)
    print(f"保存合并后的数据到: {output_path}")
    
    # 验证
    print(f"\n验证:")
    print(f"  原始系列数: {len(harvester['series_id'].unique())}")
    print(f"  合并后系列数: {len(merged['series_id'].unique())}")
    print(f"  新增系列: {[f'YFINANCE:{s}' for s in missing_series]}")
    
    # 检查缺失的系列
    print(f"\n检查代理所需系列:")
    required = ['FRED:T10Y2Y', 'FRED:DFF', 'FRED:BAMLH0A0HYM2', 'FRED:VIXCLS', 
                'H41:primary_credit', 'H41:btfp', 'YFINANCE:HYG', 'YFINANCE:LQD', 'YFINANCE:TLT']
    
    for series in required:
        status = '✅' if series in merged['series_id'].values else '❌'
        print(f"  {status} {series}")

if __name__ == '__main__':
    merge_data_hub_to_harvester()
