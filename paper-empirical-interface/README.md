# Paper Empirical Interface

为论文 "Anchor-Mismatch Dynamics: A Structural Model of Compression Failure and Crisis Regimes" 提供经验接口。

## 隔离原则

本模块是**完全隔离的**：

- ✅ 只读取 Harvester 和 Deformation 的输出
- ✅ 不修改任何现有模块
- ✅ 所有计算在本模块内完成
- ✅ 输出论文需要的图表和数据

## 模块结构

```
paper-empirical-interface/
├── src/paper_interface/
│   ├── __init__.py
│   ├── proxy_computer.py      # 代理篮子计算 (§7.2)
│   ├── signature_quantities.py # 三个特征量 (§7.1)
│   ├── case_analyzer.py       # 案例分析 (§7.3)
│   ├── figure_generator.py    # 图表生成
│   └── main.py                # 主入口
├── output/
│   ├── data/                  # 计算结果数据
│   └── figures/               # 论文图表
└── tests/                     # 测试
```

## 用法

```bash
# 生成所有输出
python -m paper_interface.main --all

# 只生成代理数据
python -m paper_interface.main --proxies

# 只生成特征量
python -m paper_interface.main --signatures

# 分析单个案例
python -m paper_interface.main --case treasury_2020

# 生成图表
python -m paper_interface.main --figures

# 自定义日期范围
python -m paper_interface.main --all --start 2018-01-01 --end 2024-01-01
```

## 论文映射

| 论文章节 | 模块 | 输出 |
|----------|------|------|
| §7.2 Proxy Baskets | `proxy_computer.py` | M/D/K/X 代理值 |
| §7.1 Signature Quantities | `signature_quantities.py` | Δ_t^NC, G_t^mf, m_t(B) |
| §7.3 Case Studies | `case_analyzer.py` | Treasury 2020, SVB 2023 |
| §7.4 Joint Stress Score | `case_analyzer.py` | Σ_t |
| Figures | `figure_generator.py` | PDF/PNG 图表 |

## 数据来源

- **输入**: Harvester benchmark_panel (只读)
- **输出**: 论文图表和数据 (独立目录)

## 依赖

- pandas >= 2.0
- numpy >= 1.24
- matplotlib >= 3.7
- pyarrow >= 12.0

## 安装

```bash
cd /Users/a1/Verity/paper-empirical-interface
pip install -e .
```
