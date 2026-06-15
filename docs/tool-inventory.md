# System — 开源工具 & 库清单

> 按 System 线程/模块分类。⭐ = GitHub stars。基于 2026-06-09 搜索。
> **筛选标准**: 与 System 架构匹配、Python 生态、活跃维护、stars > 1000 (学术/细分领域例外)。

---

## 1. ML Signals 线程 (PAPER)

**需求**: regime detection, factor model, graph embeddings

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [hmmlearn/hmmlearn](https://github.com/hmmlearn/hmmlearn) | ⭐ 3,388 | Python | HMM (scikit-learn API) | **直接命中**: K 状态机的 regime detection 核心实现 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | ⭐ 44,187 | Python | AI 量化投资平台 | **已在用** (ExternalTools/qlib_benchmark_runner)。因子模型、特征工程、回测一体化 |
| [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | ⭐ 19,083 | Jupyter | ML 交易教材代码 | 参考实现: 因子模型、特征工程、ML pipeline |
| [unit8co/darts](https://github.com/unit8co/darts) | ⭐ 9,414 | Python | 时间序列预测 & 异常检测 | 统一 API 的 forecasting 框架，支持 ARIMA/Prophet/N-BEATS/Transformer |
| [sktime/sktime](https://github.com/sktime/sktime) | ⭐ 9,798 | Python | 时间序列 ML 统一框架 | 分类、回归、聚类、异常检测——可用于 regime classification |
| [facebook/prophet](https://github.com/facebook/prophet) | ⭐ 20,222 | Python | 时间序列预测 | 结构性断点检测 + 趋势分解，可辅助 M/D 诊断 |
| [Featuretools/featuretools](https://github.com/Featuretools/featuretools) | ~⭐ 7,000 | Python | 自动特征工程 | Deep Feature Synthesis，金融时间序列特征自动化 |
| [pygod-team/pygod](https://github.com/pygod-team/pygod) | ⭐ 1,497 | Python | 图异常检测 | 金融网络中的结构异常——与 graph embeddings 配合 |
| [uber/causalml](https://github.com/uber/causalml) | ⭐ 5,863 | Python | 因果推断 + uplift modeling | 因果关系识别，超越相关性分析 |

---

## 2. Backtest Lens 线程 (PAPER)

**需求**: market feedback, historical replay evaluation

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | ⭐ 7,841 | Python | 向量化回测引擎 | **高契合**: 批量策略回测、参数优化、性能分析 |
| [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) | ⭐ 7,259 | Python | 组合分析 | Sharpe/Sortino/MaxDD 等指标，HTML 报告生成 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | ⭐ 44,187 | Python | AI 量化平台 | 完整回测框架 + 因子评估 |
| [dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | ⭐ 4,262 | Python | 组合优化 | Mean-Variance/Black-Litterman/Risk Parity 等 |
| [goldmansachs/gs-quant](https://github.com/goldmansachs/gs-quant) | ⭐ 10,590 | Python | GS 量化工具包 | 风险分析、定价、组合构建——机构级参考 |
| [google/tf-quant-finance](https://github.com/google/tf-quant-finance) | ⭐ 5,393 | Python | TF 量化金融 | 随机过程、期权定价、收益率曲线——理论验证 |
| [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | ⭐ 4,829 | Python | ML 金融库 | 分数差分、元标签、特征重要性——MLOPT 实践参考 |

---

## 3. NLP Pipeline 线程 (PAPER)

**需求**: event extraction, case similarity, narrative drift

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured) | ⭐ 14,858 | Python | 文档结构化 | PDF/HTML/新闻 → 结构化文本，数据入口 |
| [jina-ai/reader](https://github.com/jina-ai/reader) | ⭐ 11,125 | TypeScript | URL → LLM 友好文本 | 网页抓取 + 清洗，辅助 Harvester |
| [run-llama/llama_index](https://github.com/run-llama/llama_index) | ⭐ 50,013 | Python | 文档 Agent & OCR | RAG pipeline，event extraction 的文档理解层 |
| [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | ⭐ 138,839 | Python | Agent 工程平台 | NLP pipeline 编排、chain-of-thought、tool use |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | ⭐ 17,629 | Python | AI Agent 框架 | 结构化输出、类型安全的 LLM 交互 |

---

## 4. Data Quality & Validation (横切)

**需求**: schema validation, data lineage, provenance

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [great-expectations/great_expectations](https://github.com/great-expectations/great_expectations) | ⭐ 11,549 | Python | 数据质量框架 | **直接命中**: 声明式数据验证，可嵌入 Harvester pipeline |
| [pandera-dev/pandera](https://github.com/pandera-dev/pandera) | ~⭐ 4,000 | Python | DataFrame 验证 | 类型安全的 pandas/polars 验证，轻量级 |
| [pydantic/pydantic](https://github.com/pydantic/pydantic) | ⭐ 27,979 | Python | 数据验证 (type hints) | **已在用**。protocols/*.schema.json 的 Python 实现 |
| [elementary-data/elementary](https://github.com/elementary-data/elementary) | ⭐ 2,356 | TypeScript | dbt 数据可观测性 | 数据血缘、异常检测、freshness 监控 |
| [soda-core/soda-core](https://github.com/soda-core/soda-core) | ~⭐ 2,000 | Python | 数据质量检查 | YAML 定义检查，可嵌入 pipeline |

---

## 5. Workflow & Orchestration (横切)

**需求**: pipeline 编排、调度、监控

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [PrefectHQ/prefect](https://github.com/PrefectHQ/prefect) | ⭐ 22,569 | Python | 数据 pipeline 编排 | 现代化 Luigi 替代，retries/scheduling/observability |
| [dagster-io/dagster](https://github.com/dagster-io/dagster) | ⭐ 15,647 | Python | 数据资产编排 | **概念高度匹配**: data asset-centric (非 task-centric)，适合 System 的 Data→Output 流 |
| [spotify/luigi](https://github.com/spotify/luigi) | ⭐ 18,739 | Python | 批处理 pipeline | 经典，但已显老态 |
| [astral-sh/uv](https://github.com/astral-sh/uv) | ⭐ 86,154 | Rust | 极速包管理 | pip 替代，10-100x 速度提升 |
| [astral-sh/ruff](https://github.com/astral-sh/ruff) | ⭐ 47,871 | Rust | 极速 linter | flake8+isort+pyupgrade 替代，CI 必备 |

---

## 6. Visualization (Workbench)

**需求**: 4 层可视化体系 (TradingView/Plotly/ECharts/Matplotlib)

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [plotly/plotly.py](https://github.com/plotly/plotly.py) | ⭐ 18,591 | Python | 交互式图表 | **已在用**。Workbench 交互层核心 |
| [holoviz/panel](https://github.com/holoviz/panel) | ⭐ 5,693 | Python | 数据探索 & Web 应用 | 可组合的 dashboard，支持 Plotly/Bokeh/Matplotlib |
| [pydantic/logfire](https://github.com/pydantic/logfire) | ⭐ 4,288 | Python | AI 可观测性 | Agent 行为追踪、LLM 调用监控 |

---

## 7. Agent & Observability (Agent Routing + Learning Hub)

**需求**: sparse activation, expert routing, governance memory

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | ⭐ 28,711 | TypeScript | LLM 可观测性 | **直接命中**: trace/cost/quality 监控，Learning Hub 的外部参考 |
| [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | ⭐ 138,839 | Python | Agent 编排 | routing、tool use、memory——但偏重，按需取用 |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | ⭐ 17,629 | Python | 类型安全 Agent | 轻量级替代，Pydantic 原生 |
| [chroma-core/chroma](https://github.com/chroma-core/chroma) | ⭐ 28,293 | Rust | 向量数据库 | 嵌入存储 & 语义搜索——governance memory 的检索层 |
| [semgrep/semgrep](https://github.com/semgrep/semgrep) | ⭐ 15,440 | OCaml | 静态分析 | **已在用** (semgrep_rules/)。代码质量 + 架构边界强制 |

---

## 8. Graph & Network Analysis

**需求**: financial network topology, cross-asset structure

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [networkx/networkx](https://github.com/networkx/networkx) | ⭐ 16,985 | Python | 图分析 | **已在用**。金融网络拓扑、中心性分析、社区检测 |
| [pytorch/pytorch_geometric](https://github.com/pytorch/pytorch_geometric) | ~⭐ 20,000 | Python | 图神经网络 | GNN for financial graphs——ML Signals 的深度学习路径 |
| [pygod-team/pygod](https://github.com/pygod-team/pygod) | ⭐ 1,497 | Python | 图异常检测 | 金融网络中的结构异常 |

---

## 9. Vector DB & Embeddings (语义搜索层)

| 库 | Stars | 语言 | 用途 | 与 System 的契合点 |
|---|---|---|---|---|
| [chroma-core/chroma](https://github.com/chroma-core/chroma) | ⭐ 28,293 | Rust | 嵌入式向量 DB | 轻量、Python 原生，适合本地开发 |
| [qdrant/qdrant](https://github.com/qdrant/qdrant) | ⭐ 31,939 | Rust | 高性能向量 DB | 生产级，filter+search，适合大规模语料 |
| [weaviate/weaviate](https://github.com/weaviate/weaviate) | ⭐ 16,297 | Go | 向量 DB + 对象存储 | 混合搜索 (vector + keyword)，GraphQL API |

---

## 按优先级排序的推荐

### 🔴 P0 — 直接填补 PAPER 线程空白

| 库 | 目标线程 | 理由 |
|---|---|---|
| **hmmlearn** | ML Signals | K 状态机的 regime detection，scikit-learn 兼容 |
| **vectorbt** | Backtest Lens | 向量化回测，比手动实现快 100x |
| **great_expectations** | Data Quality | Harvester 数据验证层，声明式 |
| **darts** | ML Signals | 统一 forecasting API，省去逐个库适配 |
| **quantstats** | Backtest Lens | 组合分析指标，HTML 报告 |

### 🟡 P1 — 增强现有 ACTIVE 线程

| 库 | 目标线程 | 理由 |
|---|---|---|
| **dagster** | Data & Output | data asset-centric 编排，匹配 System 架构 |
| **langfuse** | Learning Hub | LLM trace/cost/quality，agent 可观测性 |
| **Riskfolio-Lib** | Backtest Lens | 组合优化 (MVO/BL/RP) |
| **sktime** | ML Signals | 时间序列分类 (regime classification) |
| **causalml** | ML Signals | 因果推断，超越相关性 |

### 🟢 P2 — 参考 & 长期储备

| 库 | 用途 |
|---|---|
| **stefan-jansen/ml4t** | 教材参考实现 |
| **gs-quant** | 机构级参考架构 |
| **tf-quant-finance** | 理论验证 |
| **mlfinlab** | MLOPT 实践参考 |
| **prophet** | 趋势分解辅助 |
| **pydantic-ai** | 类型安全 Agent 框架 |

---

## 已在用的工具 (确认)

| 库 | 位置 | 用途 |
|---|---|---|
| microsoft/qlib | ExternalTools/qlib_benchmark_runner | 量化基准 |
| networkx | Workbench/src/ | 图分析 |
| plotly | Visualization/ | 交互图表 |
| pydantic | protocols/ | 数据验证 |
| semgrep | semgrep_rules/ | 静态分析 |
| OpenBB | structural-risk-harvester/ | 数据获取 |
| DuckDB | Data/ | 列式存储 |
| JAX | src/ | 数值计算 |
| statsmodels | src/ | VAR/Granger/ADF |

---

## 注意事项

1. **Qlib 已集成** — ExternalTools/qlib_benchmark_runner 存在，遵循 RUN_ISOLATED_BENCHMARK 边界
2. **GluonTS 决策记录** — 2026-05-17-gluonts-probabilistic-forecasting.yaml，需通过 semantic_registry
3. **Legacy DataHub 冻结** — 新 pipeline 走 Harvester → DataHubLite
4. **边界规则** — 任何新工具引入需遵循 MODULES.md 的 module_authority 和 boundary rules
