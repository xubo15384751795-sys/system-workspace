# Replacement Map 落地清单

更新时间：2026-08-25

这份清单是“成熟替代说明”的实施台账，不把源码存在误报成生产切换。每一项分别记录：

- **源码**：实现已经在仓内；
- **聚焦验证**：相关单测或离线演练通过；
- **默认路径**：现行默认入口已经使用它；
- **运行观察**：经过真实调度或双轨窗口；
- **远端验证**：可选；仅在操作者明确要求、且本地 daily 路径已稳定后，再在 `ai-box` 上按仓库规定的 Python 3.13 环境验证。当前默认是本机 `/Users/a1/Verity`。

状态含义：`完成` 表示该层已经有证据；`部分完成` 表示实现存在但仍缺生产级证据；`待办` 表示尚未开始；`阻塞` 表示必须先解决的外部条件。只有“源码 + 聚焦验证 + 默认路径 + 运行观察 + 远端验证”全部完成，才允许从 shadow/pilot 提升为 production authority。

## 总体闸门

- [x] 只替换管道机制；H41、CFTC 及其他 provider 解析器仍是现有业务代码，dlt 仅包适配层。
- [x] 现行默认 daily 入口仍为 Dagster generated-op graph；旧 `scripts/daily_run.py` 仅在显式 legacy 开关下使用。
- [x] `SYSTEM_USE_NATIVE_DAILY_ASSETS` 默认关闭。
- [x] `native_pilot_job` 已注册但 `native_pilot_schedule` 为 `STOPPED`。
- [x] dlt shadow、native asset parity 均明确写入 `promotion_allowed: false`。
- [x] DuckDB canonical 有显式回滚开关 `SYSTEM_DUCKDB_CANONICAL_PANEL=0`。
- [ ] 远端 `ai-box` 测试闭环：SSH 已恢复；replacement focused suites 已远端通过，但 root full 仍保留 4 个环境/证据边界失败，不能称为全仓远端绿色。
- [!] 2026-08-25 历史只读诊断确认 `ai-box` 解析为 `x1538@192.168.124.57:2222`；当时提升权限后的连接返回 `Permission denied (publickey,password,keyboard-interactive)`，随后由用户输入密码恢复，未绕过认证。
- [x] SSH 认证恢复后已按当前工作树同步；`scripts/sync_to_ai_box.sh` 现在显式同步有限的 external-indicators cache、`Data/system_index/latest.json`，并在 Linux 端补齐 lowercase `justfile` 兼容副本，不开放整个 `Data/` 或 `.git`。
- [x] 当前 ai-box Python 3.13 focused evidence：`packages/orchestration`=`176 passed`；`packages/harvester`（含 dlt extra）=`360 passed, 4 warnings`。
- [!] 当前 root `uv run pytest`=`1491 passed, 4 failed, 11 skipped, 82 deselected`；4 个剩余失败均为远端环境/证据边界：3 个测试依赖被同步脚本排除的 `.git`，1 个 restore manifest 声明了本机 `/Users/a1/.../System-DVC-remote` 且在 Linux 不存在。不能将该结果标成 root 全绿。
- [x] 本轮新增 native shadow operator 已补入 `governance/entrypoint_registry.yaml`，entrypoint completeness 聚焦回归通过；未注册脚本不再是当前失败原因。
- [x] 新增 12 个 shadow/DVC operator 已从 root `scripts/` 吸收到 `harvester.operators` / `orchestration.operators`，改用 `python -m` 入口；默认 authority、shadow-only 边界和回滚开关不变。
- [x] root-script redundancy budget 已闭合：全部 root Python `118/118`，public command surface `90/90`；entrypoint registry、package operator import 和预算回归通过。
- [x] 远端验证暴露并修复一个跨平台 dry-run 边界：`scripts/orchestrate.sh --dry-run` 不再被共享 `Output` 的 recovery marker 拦截；真实运行仍保留 `reconcile_generation.py --fail-on-recovery`。ai-box 定向回归 `tests/test_orchestration_default_path.py`=`2 passed`。
- [x] Sentry 实际 DSN 事件回执：`Output/state/health/sentry_event_receipt.json`，event id=`54ccd3fbf40e4dfe8035fd85a68b19c2`，UTC=`2026-08-25T13:41:03.380000+00:00`；回执不包含 DSN。
- [ ] healthchecks.io dead-man 心跳回执及自然 launchd 观察窗口。
- [ ] native full-plan graph 与现行默认 graph 的一周执行、canonical lineage、publication 和 `steps.jsonl` parity。

## 当前替换项证据矩阵

| 替换项 | 仓内实现 | 聚焦验证 | 默认路径 | 真实观察 | 远端/恢复 | 当前结论 |
|---|---|---|---|---|---|---|
| pipeline runner + registry DAG + failure propagation → Dagster native assets/checks | 已完成；71 步 full-plan native graph，含 retry、blocking/non-blocking check | 已完成；结构 parity、retry、`blocked_upstream`、`degraded_by` 聚焦回归 | 未切换；`SYSTEM_USE_NATIVE_DAILY_ASSETS` 默认关闭 | 未完成；只有 preflight、same-inputs 和 stopped pilots | 部分完成；ai-box orchestration `176 passed`，root full 仍有 4 个环境/证据边界失败 | **pilot / shadow** |
| provider 手工采集机制 → dlt source/state/cursor/retry/schema contract | 已完成；CFTC、external-indicators source/operator | 已完成；offline parity、capture manifest、幂等和窗口 gate | 未切换；dlt `promotion_allowed=false` | 部分完成；真实单日 capture 5/5 MATCH，整体仍 PARTIAL，未满一周 | 部分完成；ai-box harvester+dlt `360 passed`，真实 provider 周窗口/proxy 未完成 | **partial shadow** |
| `data_contract.py` 手写断言 → Pandera | 已完成；PASS/WARN/BLOCK 语义保留 | 已完成；warning/blocking 回归 | cross-asset 默认 writer 已接入 | 未完成；无自然 daily 窗口 | 部分完成；ai-box harvester `360 passed`，真实默认 daily 仍待补 | **local default / remote focused pass** |
| 可变 Parquet 面板 → DuckDB canonical + Parquet view | 已完成；PK、`CHECK(close > 0)`、原子写和回滚开关 | 已完成；no-clobber、consumer digest/行数 parity | 已切换；默认 writer 使用 DuckDB | 部分完成；隔离 scratch drill 通过，未完成完整 daily window | 未完成；DVC remote object/restore 未证明 | **local default / recovery blocked** |
| 版本快照 → DVC | 已完成；pointer、verify-only、snapshot/restore helper | 已完成；临时 local remote add/push/pull drill | 未在 daily writer 隐式 push | 未完成；真实 release push 失败已留 typed warning | 阻塞；配置 iCloud remote push exit 255 | **local metadata / remote blocked** |
| `availability.py` vintage/PIT → 受控版本查询 | 已完成；availability 时钟和 latest-vintage selector | 已完成；双 vintage fixture | 仍由现有 availability authority 控制 | 未完成；无真实 release restore replay | 未完成；需 DVC restore | **custom boundary retained** |
| 本地通知/心跳 → Sentry + healthchecks dead-man | 已完成；best-effort adapter、原子本地 heartbeat | 已完成；mock/失败不越权测试 | Sentry 已接通；healthchecks 仍未配置 | 部分完成；Sentry 事件回执已拿到，heartbeat 仍 stale，无自然观察窗口 | Sentry 本机回执完成；healthchecks URL 与 launchd 观察待补 | **integration partial / healthchecks pending** |

当前总状态：**Wave 1–3 的仓内主路径已落地；Wave 4 已进入 opt-in/pilot，尚未达到默认切换条件。**

## Wave 1：低风险契约与可观测性

目标：先把验证、基线和故障信号接上，不改变 provider 业务语义。

### 1.1 Pandera 取代手写数据断言

- [x] 在 `packages/harvester/src/harvester/quality/pandera_adapter.py` 定义 cross-asset panel schema。
- [x] 覆盖非空、字段类型、`close > 0`、symbol/date 约束和单调性检查。
- [x] `data_contract.py` 仍保留 PASS/WARN/BLOCK 权威决策；Pandera 作为结构化诊断，不改变现有阻断语义。
- [x] 警告与拦截行为分别有测试，现有契约输出格式继续可消费。
- [x] Great Expectations 不再作为 Python runtime；`configs/great_expectations/expectations/content_freshness_suite.json` 仅保留为历史/契约说明。
- [x] 聚焦验证：`packages/harvester/tests/test_pandera_adapter.py`、`test_data_contract.py`。
- [x] 本轮 harvester Wave 1–3 选定回归：43 passed。
- [x] 项目 Python 3.13 + dlt extra 的完整 Harvester 回归为 355 passed；另用系统 Python 3.14 跑 DuckDB/data-contract/Pandera 选定回归为 22 passed。
- [x] ai-box Python 3.13 + dlt extra Harvester focused 回归 `360 passed`；一次真实默认 daily 报告仍待完成。

退出条件：Pandera 诊断和 `data_contract.py` 的权威 verdict 在远端和默认入口均一致；禁止出现“测试通过但默认入口仍绕过 schema”的情况。

### 1.2 Sentry 与 dead-man heartbeat

- [x] `configs/observability.env.example` 提供 Sentry DSN 和 healthchecks.io URL 的非秘密配置位。
- [x] `system_runtime/observability.py` / `scripts/_notify.py` 保持 best-effort 上报，不让通知故障覆盖真实 pipeline verdict。
- [x] `system_runtime/daily_heartbeat.py` 支持原子本地心跳记录和可选 allowlisted healthchecks ping。
- [x] `tests/test_daily_heartbeat.py` 覆盖本地记录与禁用/失败不越权行为。
- [x] `scripts/audit_launchd_reconciliation.py --no-launchctl` 静态核对通过：7 个预期 LaunchAgent plist 均存在，daily/dead-man 时间表与两个 legacy disabled 标记一致；该结果只证明安装配置，不证明服务正在运行。
- [!] 当前 `--dry-run` dead-man 检查仍为 `ALERT/heartbeat_stale`：最后成功 run 为 `daily_pipeline_20260822_191754_139ced`，年龄约 60.1 小时，超过 26 小时阈值；这不是健康的自然调度证据，也未发送外部通知。
- [x] 读取 mode-600 的运行时 secret file 中的 `SENTRY_DSN`，运行 `python3 -m scripts.test_sentry_event --receipt Output/state/health/sentry_event_receipt.json`；事件回执已成功生成，保存 event id 和 UTC 时间戳。
- [ ] 配置 healthchecks.io（或自托管 URL），让 launchd 真实 daily run 发送 ping。
- [ ] 完成至少一周 dead-man 观察：成功、失败、失联三类均能区分。

当前状态：**源码和聚焦验证完成；Sentry 回执已完成，healthchecks 与自然调度观察仍未完成。**

### 1.3 DVC 基线

- [x] canonical DuckDB 已有 `Data/canonical/panels.duckdb.dvc` 指针。
- [x] `.gitignore` 不再把 DVC pointer 一并忽略。
- [x] `packages/orchestration/orchestration/dvc_promote.py` 与 `orchestration.operators.promote_canonical_panel_dvc` 只允许显式 operator promotion，不在 daily writer 中隐式 push。
- [x] `orchestration.operators.promote_canonical_panel_dvc --verify-only` 已加入；它只读核对 workspace MD5、pointer 和 cloud status，缺 remote object 返回 `BLOCKED`，并可用 `--report` 固化 JSON evidence。
- [x] 当前本地 `dvc status --json --no-updates Data/canonical/panels.duckdb.dvc` 为 clean。
- [x] `packages/orchestration/tests/test_dvc_promote.py` 通过。
- [ ] 在下一次明确的受控提交中纳入 `Data/canonical/panels.duckdb.dvc`；当前工作树混合，本轮不自动 stage/commit。
- [!] `--verify-only` 实际审计：workspace MD5/size 与 pointer 一致，但 18 MB 对象尚不在本机 DVC cache 或已配置 iCloud remote；`dvc status` clean 不能替代 remote-object 存在性证明。
- [x] 当前 DVC verify-only 结果已固化到 `Output/state/health/dvc_canonical_panel_verify.json`：workspace digest/size 均匹配，`remote_verified=false`，状态仍诚实为 `BLOCKED`。
- [!] 受控 promotion 实际尝试仍 fail closed：`orchestration.operators.promote_canonical_panel_dvc` 的 DVC push 返回 exit 255，详细原因为 iCloud remote 目录创建 `Operation not permitted`；升级权限请求因外部数据写入未获批准，未绕过该边界。
- [!] 2026-08-25 finalized provider release 的 DVC 小元数据 push 同样返回 exit 255；本地 release admission 不依赖这个失败被误报为成功，跨设备恢复证据仍保持 `BLOCKED`。
- [x] 隔离 DVC 机制 drill：临时 local remote 完成 `add -> push -> 删除 scratch copy -> pull`，恢复后 MD5=`d6ecc1405cffb050333e6d592ca8a1b7`、size=`18,362,368`；该证据不替代配置中的 iCloud/ai-box remote。
- [ ] 在远端或指定备份设备完成一次 `dvc push`、干净目录 `dvc pull` 和 hash/行数核对。
- [x] 已记录隔离可恢复演练：删除 scratch copy 后由临时 DVC local remote 恢复，未操作真实 current 数据；配置 remote 的跨设备恢复仍待补。

当前状态：**本地基线完成；跨设备恢复证据待补。**

## Wave 2：canonical panel 迁移到 DuckDB

目标：让重复键和坏值在 canonical 存储层被拒绝，同时保留 Parquet 消费兼容面。

### 2.1 写路径与约束

- [x] `packages/harvester/src/harvester/duckdb_panel.py` 建立 `cross_asset_daily_panel` 表。
- [x] 主键为 `(symbol, date)`，重复键由存储层拒绝。
- [x] `CHECK (close > 0)` 在写入层阻断坏值。
- [x] 默认 `duckdb_canonical_panel_enabled()` 为 true；`SYSTEM_DUCKDB_CANONICAL_PANEL=0/false/no/off` 可回滚到旧路径。
- [x] `cross_asset_panel.py` 默认写 DuckDB，旧 Parquet 路径保留为明确回滚分支。
- [x] 写入失败不会覆盖既有 canonical；临时文件和原子替换边界已有测试。
- [x] 兼容 Parquet 导出保持与 legacy consumer 相同的时间戳精度，避免 dtype-sensitive consumer/join 在 DuckDB cutover 后出现伪差异；Wave 2 选定 22 passed（DuckDB/data contract/Pandera）。
- [x] 兼容 Parquet 的 timestamp 精度改为跟随输入/legacy runtime（Python 3.13 的 `us`、Python 3.14 的 `ns`），并用独立 `ns` 副本做契约验证；修复 Python 3.13 full-suite 的 default-path dtype parity 回归。
- [x] 聚焦验证：`packages/harvester/tests/test_duckdb_panel.py`、`test_cross_asset_panel.py`。

### 2.2 消费兼容与实际演练

- [x] canonical DuckDB 可导出同结构 Parquet 视图，消费方无需立即改成 DuckDB SQL。
- [x] 离线 drill：源 panel 195,702 行，data contract PASS，Pandera PASS。
- [x] 离线 drill：重复键被拒绝，坏值被阻断，失败不污染既有 canonical。
- [x] 当前 canonical 只读核对：表存在、195,702 行、重复键 0、最小 close 为正。
- [x] 现行默认路径回归测试通过；未修改旧入口的消费语义。
- [x] `harvester.operators.verify_duckdb_default_path` 在隔离 scratch workspace 实跑：默认 writer 输入 170 行，DuckDB 与 Parquet consumer 行数/`symbol,date,close` digest 一致，主键唯一、`close > 0`，坏候选 no-clobber，`workspace_current_touched=false`、`promotion_allowed=false`。
- [ ] 在 `ai-box` 上执行默认 writer + consumer E2E。
- [ ] 在独立 scratch 目录完成 DVC restore 后再跑一次相同 drill。
- [ ] 观察至少一个完整 daily window，确认 Parquet export 与 DuckDB canonical 同源且无 same-day reuse。

当前状态：**默认本地写路径已切 DuckDB，存储层约束和兼容导出已验证；远端、恢复和自然 daily 观察待补。**

回滚：受影响运行显式设置 `SYSTEM_DUCKDB_CANONICAL_PANEL=0`；不得直接删除 DuckDB 文件或用旧 Parquet 覆盖 current。

## 跨 Wave：版本、vintage 与 PIT 边界

这部分不能被“DuckDB 写入成功”替代。当前选择是 DuckDB 负责 canonical 存储、DVC 负责快照 bytes；不同时引入 Delta Lake，也暂不引入 ArcticDB。ArcticDB 的 bitemporal 能力匹配度高，但 BSL 1.1 生产授权边界尚未确认，因此不进入当前生产路径。

- [x] `packages/harvester/src/harvester/core/availability.py` 明确区分 observation、source vintage、published、available、retrieved 五类时钟。
- [x] 未配置 publication calendar 或 `available_at` 时，状态保持 `UNKNOWN` 且 `decision_usable=false`；不能用 retrieval time 伪造 PIT 可用性。
- [x] `configs/source_registry.yaml` 保留带 `vintage_date` 的序列主键语义。
- [x] DuckDB + DVC 的职责边界已写入 Wave 2 decision：DuckDB 不承担 bitemporal 版本魔法，DVC snapshot 不进入 daily writer 隐式 push。
- [x] `availability.py` 新增 `select_latest_vintage_as_of`：只有 `AVAILABLE + decision_usable + available_at <= as_of + source_vintage <= as_of` 的记录可入选；retrieved time 不参与替代。
- [x] 两个 vintage fixture 已验证：旧 as-of 只能看到旧 revision，revision 发布后才可看到新值；未配置 publication availability 的记录不会被选中。
- [ ] 完成 DVC remote push/restore 后，做一次干净 checkout 的 snapshot replay。
- [x] 用至少两个 vintage 的 fixture 验证 availability/PIT 查询不会把 revision 泄漏到旧 as-of 日期。
- [ ] 在上述证据完成前，不宣称 ArcticDB/Delta 已替代 `availability.py`，也不允许 revision-aware 结果进入 core judgment。

## Wave 3：provider 采集机制迁移到 dlt 双轨

目标：引入增量 cursor、状态持久化、退避重试和 schema contract；解析逻辑继续来自现有代码。

### 3.1 通用 dlt source 与契约

- [x] `packages/harvester/src/harvester/ingestion/dlt_series_source.py` 提供标准化外部序列 source/resource。
- [x] 使用日期 cursor 和持久化 dlt pipeline state；重复运行不会重复追加相同窗口。
- [x] dlt shadow load 通过统一 bounded exponential retry helper 执行（默认 3 次，1s/2s backoff），报告记录 initial/idempotence load attempts；最终失败仍 fail-closed。
- [x] 使用主键 `date`，目标表由 dlt 管理。
- [x] schema contract 支持 `evolve`、`freeze`、`discard`；`discard` 映射到当前 dlt 版本的 `discard_value`。
- [x] dlt 运行目录、目标 DuckDB 和报告均可由 operator 指定，测试不写仓库根目录。
- [x] `packages/harvester/src/harvester/ingestion/external_dlt_source.py` 保留 CFTC 解析/归一化逻辑，仅包成 shadow source。
- [x] 聚焦验证：`test_dlt_series_source.py`、`test_external_dlt_source.py`、`test_external_indicators_dlt_shadow.py`。

### 3.2 CFTC 起点

- [x] `harvester.operators.run_cftc_dlt_shadow_parity` 使用离线捕获 payload，不发网络请求。
- [x] CFTC 离线 parity：legacy 1,054 行与 dlt 1,054 行一致，状态 `MATCH`；Python 3.13 + dlt extra operator 复跑仍为 `MATCH`。
- [x] CFTC operator 增加可选真实 dlt DuckDB shadow、capture manifest 和 `--verify-idempotence`；纯 parser parity 默认模式保持不变，capture-backed 模式可产出窗口闸门所需的 execution/state 证据。
- [x] authority 仍为 shadow-only，promotion false。
- [ ] 用真实 daily capture 重复一周，确认新 payload、缺失窗口和 revision 语义都不改变。
- [x] 在 ai-box 执行 dlt extra focused suite：Harvester `360 passed`；真实 provider capture/operator 周窗口仍待完成。

### 3.3 external_indicators 起点

- [x] `harvester.operators.run_external_indicators_dlt_shadow` 使用现有 cache，cache-only，不改变 provider cache，不发 HTTP。
- [x] 持久 DuckDB staging 可复用 cursor/state；同一数据库连续运行第二次不新增 load。
- [x] 实际缓存窗口：7 个 series parity `MATCH`（CFTC、CISS、FINRA、3 个 NYFED、OFR）。
- [x] COVAR、SRISK 因现有缓存缺失，明确标为 `MISSING_CACHE`，未伪造成功。
- [x] 总体报告为 `PARTIAL_MATCH`，promotion false。
- [x] durable shadow 运行已写入 `Output/state/health/external_indicators_dlt_shadow.duckdb` / `external_indicators_dlt_shadow_parity.json`；Python 3.13 operator 复跑为 `PARTIAL_MATCH`，7 个可用序列均 `MATCH`，COVAR/SRISK 仍 `MISSING_CACHE`。
- [x] retry helper 接入后的实际 cache-only 复跑仍为 `PARTIAL_MATCH`：7 个可用序列 `MATCH`，initial/idempotence load attempts 均为 1，持久 state 与幂等 load count=7 保持一致；没有把 retry 配置误报成实际重试。
- [x] 新增 `harvester.operators.aggregate_dlt_shadow_window` 作为真实采集窗口闸门：要求支持的 parity schema、全序列 `MATCH`、real provider-capture provenance、UTC 日期一致、稳定 schema/series identity、持久 state 和显式幂等验证；cache-only 报告 fail closed。
- [x] dlt window gate 的 6 个聚焦测试覆盖短窗口、缺 capture/state、缺日、序列漂移、UTC 漂移和重复 capture；仍保持 `promotion_allowed=false`。
- [x] `harvester.operators.run_external_indicators_dlt_shadow` 可选接收已校验的 `provider_capture.v1` manifest，并用 `--verify-idempotence` 实际重复 dlt load；报告显式记录 `state_persisted`、load count 和 `idempotence_verified`，默认 cache-only 行为不变。
- [x] CFTC payload 与 external-indicators cache 均支持 manifest SHA-256 绑定；窗口 gate 只接受 `payload_digest_verified=true`，拒绝无法证明 manifest 与实际 bytes 一致的报告。
- [x] capture manifest 校验覆盖 provider、capture_id、timezone、UTC observation_date 和 schema；Wave 3 operator/manifest/window/provenance 选定回归最新为 43 passed。
- [x] manifest 不再依赖手工伪造：CFTC 单序列和 external-indicators 批量 fresh provider write 成功后，由现有 cache 原子写边界生成 `provider_capture.v1` sidecar，并记录实际 cache bytes 的 SHA-256；cache hit、manual fallback 和 stale fallback 不会产生“新采集”证据。
- [x] `official.py` 逐序列调用 provider 时，同一 UTC 日的 external-indicators sidecar 会合并各 fresh write 的 digest，跨日自动开启新 capture context；两个 dlt operator 在未显式传入 `--capture-manifest` 时会自动发现同目录 sidecar，没有 sidecar 时仍保持 cache-only/fail-closed。provider sidecar、批量/逐序列聚合、CLI 自动发现和原子 writer 的新增回归共 43 passed。
- [x] 真实 provider probe 发现慢速 response body 可能突破单次 read timeout；`OwnedHTTPGateway` 已增加总响应截止时间，避免 external provider 无限拖住 daily runner；Python 3.13 gateway/external-indicator 聚焦回归 37 passed，默认 provider 顺序和解析逻辑不变。
- [x] 当前 `external_indicators_dlt_shadow_parity.json` 经过新 gate 实跑为 `INCOMPLETE/observation_missing_real_capture_or_incremental_evidence`；这确认现有 cache-only shadow 没有被误算成真实窗口。
- [x] 2026-08-25 在隔离临时 cache 取得一条真实 `provider_capture.v1`：OFR、NYFED 3 条、FINRA 共 5 条 fresh payload，digest 全部验证；规范 dlt DuckDB shadow 为 `PARTIAL_MATCH`，5/5 `MATCH`，`idempotence_verified=true`、load count 5→5；CISS/CFTC/COVAR/SRISK 仍明确缺失，未把单日 partial 误算成窗口完成。
- [x] 2026-08-25 完成一次隔离的正式 `stage_complete_release`：release=`2026-08-25-r1`，benchmark=286,402 行、cross-asset=195,735 行，gate=`validated`、`passed=true`、无 blocker；provider warning（benchmark partial、model-input 缺失）保留在 gate report，未被抹平。
- [x] 同一 release 通过 `finalize_release` 全量 integrity 校验（4 个 dataset）；canonical observation/chain JSONL 约 1.7GB 的校验已改为流式逐行读取，避免一次性 `read_text()` 导致进程终止。
- [x] dlt operator 现在拒绝“数据库文件名与 dataset 同名”的危险组合；该组合在 dlt 1.30/DuckDB 上会触发 catalog ambiguity，已加 fail-fast 回归（Wave 3 dlt 聚焦集合 20 passed）。
- [x] COVAR/SRISK 已在 canonical source registry 明确 owner、TTL（180/75 天）和禁止隐式聚合/transport fallback 的策略；合法缓存本身仍缺，故 dlt 仍报告 `MISSING_CACHE`。
- [x] FRED-backed official series 已登记 `fred` / `openbb_fred` provider priority、系列说明、provider-native identity 和 fallback；OpenBB route table 与 `FredProvider` 均有离线 route/provider contract 回归，external-indicators 中的 CISS/OFR/CFTC/NYFED/FINRA/SRISK/COVAR 保持各自官方 transport，不把 OpenBB 当成不适用序列的替代。
- [x] 同一组 OpenBB boundary/provider/prefer-openbb/ops 聚焦回归已用项目 Python 3.13 重跑：45 passed；测试使用 fake client/route contract，不把它记作真实 OpenBB 网络采集。
- [x] 2026-08-25 Python 3.13 对直接 `FredProvider` 做过一次隔离 scratch 读取：`DFF` 返回 26,350 行，`provider=fred`、字段为 `date/value/unit/frequency`，最后观测日为 `2026-08-21`；使用 `cache=False`，未写入仓库、canonical 或 current。
- [x] 已按 lockfile 同步 Python 3.13 的 `sdk` extra：`openbb=4.7.2`、`fredapi=0.5.2` 均可导入，Harvester `openbb_fred` preflight 全部通过。
- [x] 2026-08-25 Python 3.13 真实 OpenBB/FRED scratch probe 已通过：`DFF` 返回 26,350 行、最后观测日 `2026-08-21`，输出 `provider=fred`、`source_engine=openbb`、无 fallback；`cache=False`，未写入仓库、canonical 或 current。
- [x] 2026-08-25 完整 `openbb_fred` route scratch 试跑覆盖 29 条：28 条 PASS，字段均为标准化 `date/value/unit/frequency/source_id/source_series_id/series_id`，provider-native `source_id=fred`；`BAMLC0A0CM` 单条收到 FRED 502，明确记录为 `openbb_error`，未伪造成功。
- [!] 当前 Python 3.13 Treasury 官方 provider scratch probe 对 `debt_to_penny:tot_pub_debt_out_amt` / `daily_treasury_statement:open_today_bal` 均返回 typed `network_error`（outbound endpoint DNS resolution failed）；`cache=false` 且未写仓库，因此正式 release 的两个 model-input warning 仍保持诚实。
- [x] registry acquisition 已补 route-level attempt provenance：记录配置 provider、provider-native source、source engine、source URL、成功/失败和截断错误；fallback 单测验证 OpenBB 失败后 direct FRED 被选中，相关 Python 3.13 回归 30 passed。
- [!] 2026-08-25 在两个独立 `/tmp` 目录尝试 external-indicators 真实 capture；CISS response body 在设定的 10 秒 read budget 内未完成，累计等待后手动终止，未形成合法 sidecar 或 dlt window report，也未写入仓库/当前数据。下一次应在 ai-box 或已验证的 provider proxy 上按 bounded endpoint 逐个重跑。
- [x] 网关总截止时间修复后的单序列 CISS probe 在约 11.9 秒内返回 `BOUNDED_FAILURE/ManualDownloadRequired`，没有继续挂起；这只证明 fail-closed timeout，不构成真实 capture 或 dlt parity。
- [ ] 对 external_indicators 做至少一周双轨窗口；没有稳定 parity 前不得替换旧 provider 路径。
- [ ] 在 ai-box 对 OpenBB/FRED route 集合完成连续窗口实测，并把已验证的 route-level attempt provenance 绑定到真实 capture manifest/dlt 窗口；本机 29 条单日试跑不能替代连续窗口。
- [x] canonical `configs/source_registry.yaml` 已补齐 external indicator 已实现但此前漏登的 `NYFED_PD_TREASURY_LE2Y` / `NYFED_PD_TREASURY_GT11Y` semantic routes；两者明确为 NY Fed partial-maturity primary，不冒充 total Treasury route。

当前状态：**dlt 机制和两个入口的 shadow 证据已落地；external_indicators 仍是部分缓存、shadow-only，未生产切换。**

回滚：不启用 dlt promotion；删除/隔离 shadow staging DB 不影响 legacy cache、canonical 或 current。

## Wave 4：Dagster 原生 assets / checks / retries

目标：逐批替代 `daily_run.py`、pipeline DAG/runner 和 registry 驱动的失败传播；保留 parser 和业务 callable，渐进迁移，不做大爆炸切换。

### 4.1 原生 asset/check pilot

- [x] `packages/orchestration/orchestration/assets/native_batch.py` 将 registry 中明确标记的步骤编译为 Dagster assets。
- [x] `packages/orchestration/orchestration/assets/native_quality.py` 将质量步骤编译为 asset checks。
- [x] registry tags 限定 active、非 core judgment、direct callable；未知 callable/dependency fail closed。
- [x] 每个 native asset 使用 Dagster `RetryPolicy(max_retries=1, delay=5)`。
- [x] `native_batch` 支持显式 native upstream dependency；未知、自依赖、重复依赖均拒绝。
- [x] `registry_block_checks.py` 验证阻断检查会传播 `blocked_upstream`，下游不执行。
- [x] `registry_degrade_checks.py` 验证非阻断质量告警会传播 `degraded/degraded_by`，下游仍可执行。
- [x] `native_pilot_job` 已注册；实际本机 materialization 成功，5 个 native asset/check 路径执行完成。
- [x] native pilot schedule 已注册但默认 `STOPPED`。
- [x] `native_daily_shadow_job` 已注册完整 `CompiledPlan` 的 71 个 native assets；对应 schedule 默认 `STOPPED`，job 使用显式 dry-run，不执行 provider/subprocess。
- [x] full-plan shadow job 测试 materialize 71/71 个 asset，且 `run_step_fn` 若被调用会 fail closed。
- [x] 聚焦验证：native batch/quality/parity、block/degrade、Dagster daily op 与 DVC gate 选定测试本轮 62 passed；其中 native daily 11 passed。

### 4.2 full-plan native graph

- [x] `packages/orchestration/orchestration/native_daily.py` 将现有 `CompiledPlan.sequence()` 编译为每步骤一个 native asset。
- [x] native daily 已把 runner 返回的 `failed/error/timeout` 结果转为真实 Dagster `RetryRequested`；重试预算耗尽后才把最终失败交给原有 `failure_behavior` 解释器和 `steps.jsonl` callback，避免“声明 RetryPolicy 但失败字典从不重试”。
- [x] 新增 full-plan native asset checks：每个 native asset 都有 `status/failure_behavior/degraded/blocked_by` 检查事件；shadow/default opt-in 仍为 non-blocking，blocking 模式必须由后续双轨窗口显式启用。
- [x] blocking check 语义聚焦验证通过：上游 `failed` 的 blocking check 会让 Dagster 不 materialize `judgment` 与 `trade`，但不改变当前 shadow/default 的 non-blocking 配置。
- [x] 继续复用 `execute_step`、`should_run_step`、`attach_output_lineage`、`STEP_INPUT_ARTIFACTS` 和 record callback；没有复制 H41/CFTC 等业务解析。
- [x] 保留语义 upstream edge，并在共享 Output/current writer 迁移完成前保留 sequence barrier。
- [x] native graph 有显式一重 Dagster retry。
- [x] `runner.py` 只有在 `SYSTEM_USE_NATIVE_DAILY_ASSETS=1/true/yes` 时 dispatch 到 full-plan native graph。
- [x] native graph metadata 明确标为 `authority=shadow_only`，并诚实标注当前仍写 legacy output。
- [x] hermetic success plan 与 direct executor parity 测试通过；blocking failure 的 blocked chain 测试通过。
- [x] 基于真实 `CompiledPlan` 的 no-op 双轨测试通过：native asset graph 与现行 generated-op graph 步骤序列一致，未写业务输出。
- [x] 瞬时 asset 异常的实际 Dagster retry 测试通过：`max_retries=1` 时第一次失败、第二次成功。
- [x] runner-style `status=failed` 的瞬时失败也已验证 Dagster retry：第一次返回失败字典、第二次 success，实际调用次数为 2；native daily 相关回归 18 passed。
- [x] 默认 flag-off 与现行 generated-op default path 回归通过。
- [x] `orchestration.operators.run_native_daily_plan_shadow` 已建立 full-plan 结构 parity 闸门：真实 71 步 `CompiledPlan`、native/generated 两条 Dagster 路径均解析成功，未执行 provider/subprocess，`Output/current` fingerprint 未变化。
- [x] durable 结构 parity 报告：`Output/state/health/native_daily_plan_shadow.json` 为 `MATCH`，71 个 native asset 对应 71 个 non-blocking asset checks，`promotion_allowed=false`，generated job 为 72 个节点（71 步加 summary）。
- [x] 第一批四个非核心 shared `Output/current` writer 已拆出计算/写入边界：`build_data_gaps`、`evidence_grade_report`、`build_artifact_registry`、`change_analysis`；`native_file_boundaries.py` 在显式 `SYSTEM_USE_NATIVE_FILE_BOUNDARIES=1` 时只写 active generation。
- [x] 四个 builder 均保留无参兼容调用；native adapter 只注入 generation-local 输出路径，历史 CaseLab/judgment 输入保持只读，`change_analysis` 对当前 generation judgment 做 overlay。
- [x] 四个边界的隔离写入测试通过；orchestration 全套回归为 130 passed。
- [x] 按 registry 执行顺序补齐 `measurement_quality_report`（order 15）的显式 writer，再补 `signal_card`（23）和 `signal_consensus`（24）；三者与前四个 boundary 合计 7 个 `native_file_boundary=shadow_pilot` adapter。
- [x] 7 个 boundary 均通过 generation-local 隔离写入测试；`signal_card`/`signal_consensus` 保留无参 legacy builder，native adapter 显式注入 current、judgment 和只读输入目录。
- [x] `measurement_quality_report` 增加 `write_report()`，native quality 仍只负责计算/check，file boundary 才负责 candidate current 写入；没有把 native quality shadow 误报为默认 writer。
- [x] 本批相关 root writer/callable 回归 60 passed；orchestration 全套回归 133 passed；ruff 与 `git diff --check` 通过。
- [x] 再补齐 `work_brief`（35.1）、`current_status`（35.2）、`readme_first`（35.5）、`next_actions`（63）的显式 input/output path binding；file-boundary shadow 集合现为 11 个。
- [x] 11 个 boundary 的 generation-local 隔离测试通过；writer chain 回归 72 passed（3 deselected），orchestration 全套回归 137 passed。
- [x] `orchestration.operators.run_native_file_boundary_shadow` 已建立 11 个 current-surface writer 的 same-inputs comparator：native 显式 writer 与 registry `future_callable` legacy writer 分别写入两个临时 generation，比较 JSON/Markdown 输出并忽略生成时间与临时 generation 前缀。
- [x] 2026-08-25 file-boundary same-inputs 实跑为 `MATCH`：11/11 输出一致，`workspace_current_unchanged=true`，`promotion_allowed=false`；`build_artifact_registry` 的默认存在性检查同时改为 generation-aware `current_dir()`，避免读回共享 `Output/current`。
- [x] 追加回归：`packages/orchestration/tests` 全套 149 passed；generation writer inventory 扫描 253 个 active 文件，`direct_live_surface_findings=[]`、`unguarded_latest_pointer_writers=[]`、`syntax_failures=[]`，verdict `PASS`；Python 3.13 复跑仍为 `PASS`。
- [x] `neutral_pressure_measurement`（order 6，core/block_current_readout）与 `quality_validation`（order 10，core/block_promotion）已拆出独立 `native_core_boundaries.py`；计算逻辑不变，显式写入 active generation，结果带 `artifact_status`、`check_passed`、`authority=shadow_only` 和 `promotion_allowed=false`。
- [x] 新增停止状态的 `native_core_pilot_job`：两个核心边界各自编译为 Dagster asset，并附 blocking asset check；失败只会阻断这个 shadow graph，不会改变 `daily_job`、promotion 或默认 current authority。
- [x] 核心边界隔离写入、缺输入 typed error、quality FAIL 检查失败以及 native daily 独立开关测试通过：核心边界 9 tests passed；native daily/file-boundary 相关回归仍通过。
- [x] `orchestration.operators.run_native_core_shadow` 已建立 health-only operator 证据；首次 admitted-panel 运行曾正确记录 `BLOCKED_UPSTREAM`，并保留 `Output/current` 未变化。
- [x] 修复 neutral measurement 的异频 carry-forward 边界：各 gauge 先映射到共享 business-day calendar，再执行 `component_ffill_limit_5`；只允许 gauge 内按声明窗口延续，不允许跨 gauge carry-forward。新增错位末日回归，neutral/core 相关聚焦集合 13 passed。
- [ ] `judgment_layer`、`judgment_promotion_gate`、`trade_decision`、`risk_gate` 输出仍不纳入 core writer batch；它们需要在核心边界双轨和 lineage 证据稳定后再单独迁移。
- [ ] `run_operator_detections` 已 archived，不作为迁移收益；`bridge` 也 archived，不恢复为默认 producer。
- [x] 2026-08-25 full-plan native dry-run 复跑为 `MATCH`：71/71/71，71/71 checks 且 `native_asset_check_blocking=false`，generated job 72（含 summary），`sequence_match=true`、`result_match=true`、`workspace_current_unchanged=true`，`promotion_allowed=false`。
- [x] latest Wave 4 regression：项目 Python 3.13 `.venv` 下 `packages/orchestration/tests` 全套 159 passed；当前 native daily/file-boundary/parity/core/batch/dual-track 选定集合 73 passed，新增 blocking-check 下游不 materialize、目录树隔离、schema/UTC 时间一致性断言通过，ruff 通过。
- [x] 根目录默认入口/compiled-plan/governance 选定回归（Python 3.13）32 passed；这仍是聚焦验证，不替代真实 scheduled daily。
- [x] 2026-08-25 same-inputs native batch 复跑为 `MATCH`：native batch 4 个报告 + native quality `measurement_quality_report` 共 5/5，Dagster materialization 成功，legacy 临时执行 5/5 成功，`input_preparation=per_asset_legacy_generation_snapshot`，`Output/current` fingerprint 未变化，`promotion_allowed=false`；Python 3.13 与系统 Python 3.14 均通过。
- [x] 修复 native batch parity 的隐性输入依赖：`build_artifact_registry` 不再读取未准备的共享 current；每个 native asset 在对应 legacy generation snapshot 上单独 materialize，避免历史 current 文件偶然存在造成假 `MATCH`。
- [ ] 11 个 generation-local file boundary（包括 `signal_card`/`signal_consensus`）尚未进入真实 daily 双轨 execution comparator；本机 same-inputs 报告只覆盖 native batch/quality asset，不等价于一周生产 parity。
- [x] 核心 writer shadow 已建立独立入口 `native_core_pilot_job`，但 job/schedule 保持 `STOPPED`；其 blocking check 证据只证明 native check 语义，不证明默认路径已切换。
- [x] `orchestration.operators.run_native_core_shadow` 将真实运行区分为 `PASS` / `BLOCKED_UPSTREAM` / `FAIL`，并保留 `promotion_allowed=false`；当前报告为 `Output/state/health/native_core_shadow.json`。
- [x] core shadow 报告现持久化 neutral 的 `as_of`、M/D sigma、coverage、逐序列最后观测日和 carry-forward policy；首次 `BLOCKED_UPSTREAM` 可追溯到输入证据，不会被误读成 Dagster 编排故障；修复并 admission 新 release 后当前默认报告已为 `PASS`。
- [x] core shadow 同时计算但不采纳 latest common-sample preview；它仍标为 `diagnostic_only_common_sample`，不会绕过声明的 shared-calendar carry-forward 或伪造 promotion authority。
- [x] `run_native_core_shadow` 的 package CLI 已补齐 `--root` / `--report` / `--help`；`--help` 只解析参数，不 materialize core shadow，避免远端操作误写健康证据。
- [x] 默认 core shadow report 现在显式记录实际 admitted panel 路径和 `harvester_release`；2026-08-25 默认复跑确认路径为 `Data/harvester/exports/2026-08-25-r1/data/benchmark_panel.parquet`，release lineage=`2026-08-25-r1`。
- [x] 修复 `run_native_core_shadow --root <isolated-root>` 的隔离边界：自定义 root 在未显式传 panel 时绑定该 root 的 `latest` panel 并使用该 root 的 health output；只有仓库 ROOT 默认路径才调用 registered stopped job；新增回归通过。
- [x] 2026-08-25 用已通过的 OpenBB/FRED provider 在内存 scratch 刷新 `DCPF3M/DGS3MO/SOFR/IORB/NFCICREDIT` 并重算两个 M derived series：scratch `M` 已恢复到 `2026-08-21`（值 `0.0626`），当时说明 `BLOCKED_UPSTREAM` 来自 admitted panel 未刷新，而不是 neutral 计算逻辑或 native asset 语义失败；未写仓库、canonical 或 current。
- [x] `run_native_core_shadow --benchmark-panel <path>` 已收敛为可复现的 shadow-only requalification 入口：显式 panel 绑定同一 native assets/checks，输出仍落在隔离 health root，默认 admitted panel、`Output/current` 和 promotion authority 不变。
- [x] 2026-08-25 隔离 staged release 上的 native core 复跑：`native_core_pilot_job` materialized 2/2 assets、2/2 blocking checks passed；neutral=`ACTIVE_PARTIAL`、`M=0.1935`、`D=-0.9870`、`as_of=2026-08-25`，quality=`PASS`，`blocked_upstream=false`，`workspace_current_unchanged=true`，`promotion_allowed=false`。
- [x] 该 release 已正式写入 `Data/harvester/exports/2026-08-25-r1` 并 finalize；`latest` 已切换到 `2026-08-25-r1`，随后默认 admitted-panel native shadow 复跑为 `PASS`：2/2 assets、2/2 checks、quality=`PASS`、`business_default_path_changed=false`。这仍是 shadow authority，不是默认 current promotion。
- [x] `judgment_layer`、`judgment_promotion_gate`、`trade_decision`、`risk_gate` 已单独登记为 `native_decision_boundary: shadow_pilot`；只注入输入路径并把四个 writer 重定向到 `Output/state/health/native_decision_shadow`，没有复制 judgment/trade 业务规则，也没有写共享 authority。
- [x] 新增停止状态的 `native_decision_pilot_job` / `native_decision_pilot_schedule`；资产依赖为 `judgment → promotion_gate → trade_decision → risk_gate`，每步都有 blocking artifact check，策略状态（如 `WATCH`、`BLOCKED`、`APPROVED_FOR_RESEARCH`）与执行失败分开记录。
- [x] decision boundary 的路径注入回归通过；promotion gate、trade decision 默认参数保持兼容，risk gate 仍复用原有 `check_decision` / `build_risk_gate_report`。
- [x] 新增 decision pilot 6 个聚焦测试；核心/文件边界回归 26 个测试通过；ruff 通过。
- [x] 2026-08-25 本机真实 stopped shadow 运行 `PASS`：4/4 asset materialized、4/4 blocking checks passed、`shared_surfaces_unchanged=true`、`business_default_path_changed=false`；报告为 `Output/state/health/native_decision_shadow.json`。观测到 promotion `WATCH`、trade `RISK_ON size=0.5`、risk `APPROVED_FOR_RESEARCH`，这些是业务产物状态，不是迁移 promotion。
- [ ] decision shadow 尚未进入默认 core writer batch，也没有完成与旧 callable 的一周 same-inputs/execution parity；在 lineage、publication、`steps.jsonl` 和 failure propagation 窗口稳定前保持 stopped。
- [x] `record_trade_decision`、`paper_portfolio` 已按 registry 顺序单独登记为 `native_adjacent_boundary: shadow_pilot`；前者复用原 ledger entry/upsert，后者复用原 paper portfolio 计算，均在 health generation 中执行。
- [x] 新增停止状态的 `native_adjacent_pilot_job` / `native_adjacent_pilot_schedule`；`record_trade_decision` 使用非 blocking `continue_with_warning` check，`paper_portfolio` 使用 blocking `decision_adjacent_block` check。
- [x] adjacent writer 的 temp-root 隔离测试 6 passed；实际运行中共享 `Output/current`、`Output/trade_ledger`、`Output/system_learning`、`Output/position` 指纹均未变化。
- [x] 2026-08-25 adjacent shadow 首次运行正确暴露 snapshot 绝对路径失效；未伪造通过。确认 Verity 内存在同一 `/Output/...` 相对文件后，只在 shadow snapshot 副本中做存在性验证后的 path rebase，并将原/新路径记录到执行结果。
- [x] path rebase 后真实 stopped adjacent shadow `PASS`：2/2 assets、2/2 checks，`record_trade_decision=APPROVED_FOR_RESEARCH`、`paper_portfolio=RISK_ON`，报告为 `Output/state/health/native_adjacent_shadow.json`；报告持久化 1 条原/新路径映射，`claim_evaluation_status=success`；仍为 `promotion_allowed=false`。
- [x] native/current same-inputs parity 已实际跑通：`judgment_layer`、`judgment_promotion_gate`、`trade_decision`、`risk_gate`、`record_trade_decision`、`paper_portfolio` 共 6/6，JSON 与 Markdown 均 `MATCH`，且 `Output/current`、judgment、trade、ledger、system-learning、position 指纹均未变化；报告为 `Output/state/health/native_decision_parity.json`，仍为 `promotion_allowed=false`。
- [x] parity comparator 已固定真实边界：旧入口显式使用快照 `as_of`，比较器忽略运行时 provenance 时间字段；adjacent generation seed 同时包含历史 ledger/system-learning，`record_trade_decision` 保留 best-effort `claim_evaluator` 副作用；velocity gate 在 native package 入口与旧脚本入口使用同一 fallback。
- [ ] adjacent shadow 尚未与旧 callable 做一周 same-inputs/execution parity；特别是 paper NAV、ledger idempotence、admission/freshness 和 position history 仍需连续窗口证据。
- [ ] 其余非核心 shared Output/current writer 仍需逐个迁移为 file-level asset 或明确 IO boundary；当前 11 个已经完成 shadow boundary，但尚未经过真实 daily 双轨 execution；全部完成前保留 sequence barrier。
- [x] `orchestration.operators.compare_daily_run_parity` 已建立实际双轨证据 comparator：只读消费两次隔离 run bundle，检查 `steps.jsonl`、canonical lineage、release/vintage、input snapshot 与 generation surfaces；缺证据返回 `INCOMPLETE`。
- [x] `PublishTransaction.commit_generation(..., output_root=...)` 已补齐；显式 `daily_run.py --output-root` 不再误写 `ROOT/Output`，默认无参数行为保持不变。
- [x] `orchestration.operators.run_daily_dual_track` 已建立：默认只做隔离 preflight；显式 `--execute` 才按 Dagster 默认入口分别运行 legacy/native，并自动调用只读 comparator；native 轨同时开启第一批 file boundary；promotion 永远为 false。
- [x] `orchestration.operators.aggregate_daily_dual_track_window` 已建立一周窗口闸门：只读聚合 pair report，要求真实执行、全维度 `MATCH`、稳定 release/vintage/plan identity 和连续至少 7 个 UTC 日期；缺日、preflight、缺证据或差异均不放行。
- [x] `run_daily_dual_track --execute` 的 preflight 现在先读取两套 workspace 的 admitted `catalog.json`/benchmark manifest，要求 release、vintage、as-of identity 一致；identity 缺失或漂移时在任何 runner 启动前 fail closed，纯 preflight 模式保持兼容。
- [x] 窗口闸门额外校验 execution report schema 版本，并要求 `observation_date` 与 `observed_at` 的 UTC 日期一致；旧格式或时间漂移报告 fail closed。
- [x] 双轨 operator 强制要求两个不同 workspace root 和 output root，并把 `SYSTEM_GENERATION_MODE=1`、native flag、runner exit、bundle/generation 路径都写进报告；禁止直接使用当前工作区 `Output`。
- [x] 双轨 preflight 进一步拒绝路径树重叠：output root 不能嵌套在任一 workspace root 内，两个 workspace/output 树之间也不能交叉，避免“表面隔离、实际共享生成面”。
- [x] `PublishTransaction.reconcile` / `scripts/reconcile_generation.py` 支持显式 isolated `output_root`；dual-track preflight 对 `recovery_required`、`rollback` 和真实兼容目录 fail closed。
- [x] 2026-08-25 本机双轨 preflight 实跑：返回 `INCOMPLETE/preflight_blocked`，因为两套 isolated workspace 尚未准备；`writes_performed=false`，未触碰共享 `Output`。按 Mac/ai-box 分工，未在本机擅自启动真实 daily pair。
- [x] 同一 preflight 报告经一周窗口聚合器核验为 `INCOMPLETE/observation_missing_real_execution_or_required_parity`，`observation_count=1`、`promotion_allowed=false`；没有把 preflight 当成真实双轨观察。
- [ ] 产生第一对真实隔离 generation 的 native/current run，执行上述 comparator；不能直接对共享 current 做两次写入。
- [ ] 在 ai-box 产生至少连续一周的 pair report，并用窗口闸门比较 execution result、canonical lineage、publication、`steps.jsonl` 和 failure propagation。

### 4.3 parity 与切换门槛

- [x] `packages/orchestration/orchestration/native_parity.py` 和 `orchestration.operators.run_native_batch_shadow_parity` 默认只读已有 registry artifacts。
- [x] parity operator 新增显式 `--same-inputs`：在临时 generation 重建 legacy pure reports，不写 `Output/current`。
- [x] parity 工具明确区分 `MATCH`、`MISMATCH`、`LEGACY_MISSING`、`STALE`，只忽略生成时间字段。
- [x] 最近 native pilot parity 报告为 `MISMATCH`：部分 existing `Output/current` artifacts 缺失或内容不一致。
- [x] same-inputs 实际运行：5/5 native pilot reports `MATCH`，Dagster materialization 成功，legacy 临时执行 5/5 成功，`Output/current` fingerprint 未变化。
- [x] durable same-inputs 报告写入 `Output/state/health/native_batch_shadow_parity_same_inputs.json`，状态 `MATCH` 且 `promotion_allowed=false`。
- [x] full-plan dry-run 结构报告写入 `Output/state/health/native_daily_plan_shadow.json`；该报告只证明编排结构和命令解析，不代替实际执行双轨。
- [x] bundle comparator 的三类聚焦 fixture 通过：完整匹配为 `MATCH`，step failure 为 `MISMATCH`，缺 lineage 为 `INCOMPLETE`。
- [x] 因此当前 promotion 仍为 false，不能把 native pilot 抬成默认 authority。
- [x] 已解释既有 current artifact mismatch 的来源（历史 current 缺少部分非核心视图）；重新生成的 same-inputs 报告已恢复 `MATCH`，不把历史缺失伪装成 native 生产证据。
- [ ] parity 连续窗口稳定后，先把一批 registry step 从 generated-op 迁为 native asset。
- [ ] 每批迁移至少观察一周，再迁下一批；每批保留旧 callable/rollback 开关。
- [ ] 所有 registry step 完成后，才删除或收缩 `daily_run.py`、pipeline DAG/runner 的重复编排逻辑。
- [ ] 最后才把 launchd 收缩为只拉起 Dagster daemon，并验证自然调度、心跳、失败通知和恢复。

切换条件（必须全部满足）：

- [ ] native 与当前入口相同输入、相同 release/vintage、相同 canonical lineage。
- [ ] `failure_behavior`、retry 次数、`blocked_upstream`、`degraded_by` 结果一致。
- [ ] `steps.jsonl`、publication/current writer 和消费方报告无 divergence。
- [ ] 一周 native/current 双轨无未解释差异。
- [ ] `ai-box` 远端验证通过。
- [ ] 明确 rollback：关闭 native flag 即回到 generated-op graph；切换本身不删除旧路径。

## 可复现验证命令

本机聚焦回归：

```bash
cd /Users/a1/Verity/packages/orchestration
uv run python -m pytest tests/test_native_daily.py tests/test_native_batch.py tests/test_native_quality.py tests/test_native_parity.py tests/test_dagster_daily_op.py tests/test_registry_shadow.py tests/test_registry_quality_checks.py tests/test_registry_block_checks.py tests/test_registry_degrade_checks.py -q

cd /Users/a1/Verity
uv run python -m pytest tests/test_dagster_compiled_plan.py tests/test_orchestration_default_path.py tests/test_repository_governance.py tests/test_daily_pipeline_contract.py -q

cd /Users/a1/Verity/packages/harvester
uv run python -m pytest tests/test_external_indicators_dlt_shadow.py tests/test_dlt_series_source.py tests/test_duckdb_panel.py tests/test_data_contract.py tests/test_external_dlt_source.py -q

# full-plan native/generated structural parity; no provider/subprocess execution
cd /Users/a1/Verity
DAGSTER_LOG_LEVEL=WARNING uv run python -m orchestration.operators.run_native_daily_plan_shadow \
  --report Output/state/health/native_daily_plan_shadow.json

# stopped judgment -> promotion -> trade -> risk asset/check pilot;
# shadow-only outputs and shared-surface fingerprints
DAGSTER_LOG_LEVEL=WARNING uv run python -m orchestration.operators.run_native_decision_shadow \
  --report Output/state/health/native_decision_shadow.json

# stopped record-trade / paper-position pilot; generation-local state only
DAGSTER_LOG_LEVEL=WARNING uv run python -m orchestration.operators.run_native_adjacent_shadow \
  --report Output/state/health/native_adjacent_shadow.json

# six-step decision + adjacent same-inputs parity; temporary generations only
DAGSTER_LOG_LEVEL=WARNING uv run python -m orchestration.operators.compare_native_decision_parity \
  --report Output/state/health/native_decision_parity.json

# eleven generation-local current-surface writers vs legacy future_callable;
# temporary generations only, no provider/network and no Output/current write
env PYTHONPATH=.:packages/orchestration:packages/harvester/src:packages/workbench/src \
  python3 -m orchestration.operators.run_native_file_boundary_shadow \
  --report Output/state/health/native_file_boundary_shadow.json

# core-boundary shadow; remains health-only and promotion=false
python3 -m orchestration.operators.run_native_core_shadow \
  --report Output/state/health/native_core_shadow.json

# explicit fresh-panel requalification; panel must come from a verified
# provider release/scratch, and the output remains isolated from current
python3 -m orchestration.operators.run_native_core_shadow \
  --benchmark-panel /path/to/fresh-benchmark-panel.parquet \
  --root /path/to/shadow-workspace \
  --report /path/to/native_core_refresh_shadow.json

# isolated Wave 2 default writer -> Parquet consumer -> DuckDB/no-clobber evidence
python3 -m harvester.operators.verify_duckdb_default_path \
  --input-panel Data/harvester/panels/cross_asset_daily_panel.parquet \
  --workspace-root /private/tmp/verity-duckdb-default-evidence \
  --report Output/state/health/duckdb_default_path_evidence.json

# vintage/PIT selector: package cwd avoids the root/package conftest collision
cd /Users/a1/Verity/packages/harvester
uv run python -m pytest tests/test_data_reliability_contract.py -q

# real provider-capture dlt window; cache-only reports intentionally fail closed
cd /Users/a1/Verity
uv run --project packages/harvester --extra dlt python -m harvester.operators.run_cftc_dlt_shadow_parity \
  --database /path/to/cftc-shadow.duckdb \
  --capture-manifest /path/to/cftc-provider-capture-2026-08-25.json \
  --verify-idempotence \
  --output /path/to/dlt-2026-08-25.json

uv run --project packages/harvester --extra dlt python -m harvester.operators.run_external_indicators_dlt_shadow \
  --capture-manifest /path/to/provider-capture-2026-08-25.json \
  --verify-idempotence \
  --report /path/to/dlt-2026-08-25.json

uv run python -m harvester.operators.aggregate_dlt_shadow_window \
  --observation-report /path/to/dlt-2026-08-19.json \
  --observation-report /path/to/dlt-2026-08-20.json \
  --observation-report /path/to/dlt-2026-08-21.json \
  --observation-report /path/to/dlt-2026-08-22.json \
  --observation-report /path/to/dlt-2026-08-23.json \
  --observation-report /path/to/dlt-2026-08-24.json \
  --observation-report /path/to/dlt-2026-08-25.json \
  --report Output/state/health/dlt_shadow_window.json

# compare two already-completed isolated native/current bundles (read-only)
cd /Users/a1/Verity
uv run python -m orchestration.operators.compare_daily_run_parity \
  --legacy-run /path/to/current/run \
  --native-run /path/to/native/run \
  --report Output/state/health/native_current_dual_run_parity.json

# first real isolated pair: default is preflight-only; add --execute only on ai-box
uv run python -m orchestration.operators.run_daily_dual_track \
  --legacy-workspace-root /path/to/verity-legacy \
  --native-workspace-root /path/to/verity-native \
  --legacy-output-root /path/to/dual-track/legacy/Output \
  --native-output-root /path/to/dual-track/native/Output \
  --report Output/state/health/native_current_dual_track_execution.json
# after reviewing the preflight report, repeat with --execute on ai-box

# after at least one real report per consecutive UTC day, aggregate the window
uv run python -m orchestration.operators.aggregate_daily_dual_track_window \
  --observation-report /path/to/reports/dual-2026-08-19.json \
  --observation-report /path/to/reports/dual-2026-08-20.json \
  --observation-report /path/to/reports/dual-2026-08-21.json \
  --observation-report /path/to/reports/dual-2026-08-22.json \
  --observation-report /path/to/reports/dual-2026-08-23.json \
  --observation-report /path/to/reports/dual-2026-08-24.json \
  --observation-report /path/to/reports/dual-2026-08-25.json \
  --report Output/state/health/native_current_dual_track_window.json
```

本地默认验证（按 `AGENTS.md`）：

```bash
cd /Users/a1/Verity
uv run pytest
# 或: make test
```

远端验证仅在操作者明确要求、且本地 daily 路径已稳定后使用：

```bash
cd /Users/a1/Verity
./scripts/sync_to_ai_box.sh && ssh ai-box 'export PATH="$HOME/.local/bin:$PATH"; cd ~/Verity && uv run pytest'
```

## 当前下一步顺序

1. 默认在本机跑 focused / dry-run；不要把 `ai-box` 当成下一步必做。等本地 daily 路径稳定能跑之后，再按需做远端验证。若以后需要 root 全绿，另建带 Git 元数据的 clean checkout/CI，不能把 source-sync 树的 Git 依赖失败算作替换失败。
2. 配置 healthchecks URL，让 launchd 真实 daily run 发送 ping；Sentry 已有真实事件回执，随后开始一周 heartbeat 观察。
3. 完成 DVC scratch restore/push 验证，固定 DuckDB canonical 的跨设备恢复证据。
4. 补齐 external_indicators 缺失缓存，开始 dlt 一周双轨窗口；CFTC 继续作为已 MATCH 的基准。
5. 保持 `2026-08-25-r1` admitted release 的默认 core shadow `PASS`，下一步转入一周 native/current 隔离双轨；不把 shadow PASS 当作 current promotion。
6. 用刚完成的 bundle comparator 接入第一对隔离 output root 的实际 native/current run；file-boundary same-inputs 已 `MATCH`，剩下的是完整 daily 的 execution/lineage/publication parity。
7. 只有实际 parity、heartbeat、远端验证和一周观察都通过，才提交下一批 native asset 默认切换决策。

相关决策记录：

- `governance/routing_decisions/2026-08-25-replacement-map-wave1-4-batch.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave2-duckdb-dvc.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave3-series-shadow.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-native-daily-assets-01.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-native-parity.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-native-full-plan-shadow.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-cross-wave-pit.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-dual-run-comparator.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-dual-track-operator.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-dual-track-window.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-file-boundary-01.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-file-boundary-02.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-file-boundary-03.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-file-boundary-04.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-core-boundary-01.yaml`
- `governance/routing_decisions/2026-08-25-replacement-map-wave4-file-boundary-parity.yaml`
