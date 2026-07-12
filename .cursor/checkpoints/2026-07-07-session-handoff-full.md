# Agent Session Handoff: 2026-07-07（完整对话记录与总结）

> **用途**：供后续 Agent 快速恢复上下文，无需重读整段对话。  
> **工作区**：`/Users/a1/System`（Structural Risk Workbench）  
> **对话主题**：安全审查与加固 → 火山方舟 Coding Plan 多工具配置 → 模型上下文上限 → arkcli skill 描述修复

---

## 1. 执行摘要

本次会话共完成 **四块独立工作**：

| # | 主题 | 结果 |
|---|------|------|
| 1 | **项目安全审查** | 未发现远程可利用的高危漏洞；识别 API 无认证、数据完整性校验关闭、Agent 审批未落地等中低风险点 |
| 2 | **安全防护落地** | 实现 Terminal API 绑定/Key 守卫、`hub_lite` 完整性校验、Harness `requires_approval` 强制执行、错误信息脱敏 |
| 3 | **火山方舟 Coding Plan 配置** | 将控制台 12 个 model-name 同步到 OpenCode CLI/Desktop 与 ZCode Desktop |
| 4 | **上下文上限调优** | 按 Coding Plan API `token_limits` 将各模型 context/output 设为支持的最大值 |
| 5 | **ZCode skill 校验修复** | 缩短 3 个 arkcli skill 的 `description`（≤1024 字符） |

**用户未要求 git commit**；仓库内代码改动与 `~/.config`、`~/.zcode`、`~/.agents` 下的用户级配置需分别核对。

---

## 2. 会话时间线与用户意图

```text
用户: 「看看这个项目有什么安全方面的漏洞吗」
  → 全库安全扫描 + security-review 子代理（仅覆盖当时 diff）
  → 输出 Medium/Low 发现与正面安全基线

用户: 「继续吧把这些安全防护做好」
  → 实现 API 认证/绑定守卫、hub_lite 校验、registry 审批门、脱敏、测试

用户: [火山方舟 Coding Plan 控制台截图]
      「配置到 opencodeCLI 和 desktop 和 zcode 的 desktop」
  → 确认 Base URL 与 model-name 正确；写入 opencode.json + zcode config

用户: 「上下文调整成模型支持的最长上下文」
  → 调用 Coding Plan /models API 取 token_limits；更新三处配置

用户: ZCode 报错 description 超过 1024 字符（arkcli-doctor/gen/helper）
  → 缩短 .agents/skills 下三份 SKILL.md 的 frontmatter description

用户: 「把今天对话记录汇总成 md 报告」
  → 本文件
```

---

## 3. 安全审查结论（审查时快照）

### 3.1 总体判断

| 维度 | 评估 |
|------|------|
| 远程攻击面 | 低（本地 CLI + 可选 localhost API） |
| 命令注入 / RCE | 低（无 `shell=True`，无 `exec(open)`） |
| 密钥泄露 | 低（`.gitignore` 覆盖 `.env`；无硬编码生产密钥） |
| 数据完整性 | 中（已修复：`hub_lite` 默认开启 hash/schema 校验） |
| Agent 误操作 / 越权写 | 中（已加强：`requires_approval` + `ask` 阻塞） |

### 3.2 已识别且已修复的问题

| 严重度 | 位置 | 问题 | 修复 |
|--------|------|------|------|
| Medium | `deformation-framework/src/api/app.py` | FastAPI 无认证；非 localhost 暴露风险 | 新增 `security.py`：非 loopback 绑定需 API Key；中间件校验 `X-API-Key` |
| Medium | `app.py` `_build_lite_service` | `validate_hashes/schema=False` | 从 config 读取，默认 `True` |
| Medium | `Workbench/.../registry.py` | `requires_approval` 仅元数据未执行 | 未 `approved=true` 时返回 `APPROVAL REQUIRED` |
| Low | `registry.py` | 策略 `ask` 只记日志仍执行 | `ask` 无批准则阻塞 |
| Low | `registry.py` | 失败返回完整 traceback | 对外仅 `ExceptionType: message`；完整栈写事件 |

### 3.3 审查时已存在的正面措施

- `tests/test_security_hardening.py`：禁止 `exec(open(...))`、HTTP 研究文件标记等
- `tests/test_architecture_boundary.py`：模块边界测试通过
- 子进程普遍使用 argv 列表，无 `shell=True`
- `yaml.safe_load`；无 `pickle` 反序列化
- API 默认绑定 `127.0.0.1:8787`
- OpenCode 密钥使用 `{file:...}` 引用，非明文

### 3.4 未在本会话修复的遗留项

- 依赖漏洞扫描（`pip-audit` / Dependabot）未跑
- `tests/test_security_hardening.py::test_no_raw_sys_path_insert_in_scripts` 可能因无关脚本失败（`build_event_replay_factory.py` 等）— 非本次引入
- ZCode `config.json` 内部分 provider API Key 为明文（用户环境风险，未改）

---

## 4. 安全防护实现详情

### 4.1 新增/修改文件（仓库内）

| 文件 | 变更 |
|------|------|
| `deformation-framework/src/api/security.py` | **新建**：`assert_bind_allowed`、`install_api_key_middleware`、`resolve_api_key`、`resolve_harvester_validation` |
| `deformation-framework/src/api/app.py` | 接入中间件；`hub_lite` 使用 config 校验开关 |
| `deformation-framework/scripts/run_api.py` | 启动前绑定检查；传入 `api_key` |
| `deformation-framework/tests/test_api_security.py` | **新建** 12 项测试 |
| `Workbench/agents/harness/tools/registry.py` | `_is_approved`、`_approval_required_result`；`ask`/审批门；异常脱敏 |
| `tests/test_harness_tool_approval.py` | **新建** 5 项测试 |
| `tests/test_security_hardening.py` | 新增 `test_api_security_module_exists` |

### 4.2 Terminal API 使用方式

```bash
export TERMINAL_API_KEY="your-secret"
python3 deformation-framework/scripts/run_api.py --host 0.0.0.0 --port 8787

# 请求（除 /health 外）
curl -H "X-API-Key: your-secret" http://127.0.0.1:8787/runtime
```

- 环境变量：`TERMINAL_API_KEY`（或 config `api.key` / `api.key_env`）
- 默认 `127.0.0.1` 且无 Key：本地开发行为不变
- **禁止**对外暴露时使用 `https://ark.cn-beijing.volces.com/api/v3`（Coding Plan 应使用 `/api/coding/v3`）

### 4.3 Agent Harness 审批约定

工具调用需显式批准时，在 `input` 中传：

```python
run_tool("learning_hub.ingest_events", {"approved": True, "events": []}, mode="run")
```

- `requires_approval=True` 的工具（如 `artifact.promote_snapshot`、`learning_hub.ingest_events`）无 `approved` 会返回 `APPROVAL REQUIRED`
- `snapshot_publish` 类仍受 `permissions.yaml` 的 `require_manual_review` 约束（双重门）

### 4.4 验证命令

```bash
cd /Users/a1/System/deformation-framework && python3 -m pytest tests/test_api_security.py tests/test_api_app.py -q
cd /Users/a1/System && python3 -m pytest tests/test_harness_tool_approval.py tests/test_security_hardening.py -q
```

---

## 5. 火山方舟 Coding Plan 配置

### 5.1 控制台信息（用户截图，已确认正确）

- **套餐**：Coding Plan（生效中）
- **OpenAI 协议 Base URL**：`https://ark.cn-beijing.volces.com/api/coding/v3`
- **Anthropic 协议 Base URL**：`https://ark.cn-beijing.volces.com/api/coding`
- **勿用**：`https://ark.cn-beijing.volces.com/api/v3`（额外计费）

### 5.2 已配置的 12 个 model-name

| model-name | 用途提示 |
|------------|----------|
| `ark-code-latest` | 自动跟随最新代码模型 |
| `doubao-seed-2.0-code` | 豆包代码专用 |
| `doubao-seed-2.0-pro` | 豆包 Pro |
| `doubao-seed-2.0-lite` | 豆包 Lite |
| `doubao-seed-2.0-mini` | 豆包 Mini |
| `glm-5.2` | GLM（reasoning） |
| `kimi-k2.7-code` | Kimi 代码版 |
| `kimi-k2.6` | Kimi |
| `deepseek-v4-pro` | DeepSeek Pro（1M 上下文） |
| `deepseek-v4-flash` | DeepSeek Flash |
| `minimax-m3` | MiniMax M3 |
| `minimax-m2.7` | MiniMax M2.7 |

### 5.3 配置文件路径（用户主目录，非 Git 仓库）

| 工具 | 路径 |
|------|------|
| OpenCode CLI + Desktop | `~/.config/opencode/opencode.json` |
| ZCode Desktop | `~/.zcode/v2/config.json` |
| ZCode 运行时模型缓存 | `~/.zcode/v2/bots-model-cache.v2.json` |
| OpenCode API Key | `~/.config/opencode/secrets/volcengine-api-key` |

OpenCode provider 段要点：

```json
{
  "model": "volcengine/ark-code-latest",
  "provider": {
    "volcengine": {
      "name": "火山方舟 Coding Plan",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "apiKey": "{file:/Users/a1/.config/opencode/secrets/volcengine-api-key}"
      }
    }
  }
}
```

ZCode provider id：`volcengine-ark`，`kind: openai`，同一 `baseURL`。

### 5.4 切换模型示例

```bash
# OpenCode
opencode -m volcengine/doubao-seed-2.0-code
# 或 TUI: /connect → 火山方舟 Coding Plan

# ZCode: UI 选择「火山方舟 - Coding Plan」下对应模型
```

---

## 6. 模型上下文与输出上限（当前配置值）

数据来源于 Coding Plan `GET /api/coding/v3/models` 的 `token_limits`（2026-07-07 会话内用用户 Key 拉取）；别名模型在无独立条目时按同系列后端对齐。

| 模型 | context (tokens) | max output (tokens) | 数据来源 |
|------|------------------|---------------------|----------|
| `ark-code-latest` | 262,144 | 131,072 | 对齐 doubao code 后端 |
| `doubao-seed-2.0-code` | 262,144 | 131,072 | API |
| `doubao-seed-2.0-pro` | 262,144 | 131,072 | API |
| `doubao-seed-2.0-lite` | 262,144 | 131,072 | API |
| `doubao-seed-2.0-mini` | 262,144 | 131,072 | API |
| `glm-5.2` | 1,048,576 | 131,072 | API (`glm-5-2-260617`) |
| `kimi-k2.7-code` | 262,144 | 131,072 | Coding Plan 256K 档 |
| `kimi-k2.6` | 262,144 | 131,072 | Coding Plan 256K 档 |
| `deepseek-v4-pro` | 1,048,576 | 393,216 | API |
| `deepseek-v4-flash` | 1,048,576 | 393,216 | API |
| `minimax-m3` | 1,048,576 | 131,072 | 1M 档 agent 模型 |
| `minimax-m2.7` | 262,144 | 131,072 | M2.x 256K 档 |

**选型建议**

- 超长代码库 / 跨文件：`deepseek-v4-pro`、`glm-5.2`、`minimax-m3`
- 日常编码：`doubao-seed-2.0-code` 或 `ark-code-latest`
- 长输出：`deepseek-v4-pro` / `deepseek-v4-flash`（最大输出 393K）

配置变更后：重启 ZCode Desktop；OpenCode 新开会话。

---

## 7. ZCode arkcli Skill 描述修复

### 7.1 问题

ZCode skill 校验要求 frontmatter `description` **≤ 1024 字符**（见 `~/.zcode/skills/skill-creator/scripts/quick_validate.py`）。

| Skill | 原长度 | 修复后 |
|-------|--------|--------|
| `arkcli-doctor` | 1122 | 238 |
| `arkcli-gen` | 1195 | 220 |
| `arkcli-helper` | 1089 | 314 |

### 7.2 修改路径

- `/Users/a1/.agents/skills/arkcli-doctor/SKILL.md`
- `/Users/a1/.agents/skills/arkcli-gen/SKILL.md`
- `/Users/a1/.agents/skills/arkcli-helper/SKILL.md`

**说明**：仅缩短 YAML `description`；正文 SKILL 内容未删。`version` 字段可能触发 validator 的 “Unexpected key” 警告，但非用户报错的 description 超长问题。

**注意**：`~/.claude/skills/` 等路径可能存在同名副本，若 ZCode 仍报错需同步缩短。

---

## 8. 关键代码引用（便于 Agent 定位）

### 8.1 API 安全模块

路径：`deformation-framework/src/api/security.py`

- `is_loopback_host()` / `assert_bind_allowed()`
- `install_api_key_middleware()` — `/health` 免认证
- `resolve_harvester_validation()` — 默认 `validate_hashes=True`, `validate_schema=True`

### 8.2 Harness 审批门

路径：`Workbench/agents/harness/tools/registry.py`

- `run_tool()` 流程：mode check → policy → **`ask` 无批准则拒** → **`requires_approval` 无批准则拒** → execute
- `_is_approved(input)` 接受 `approved: true` / `"yes"` / `"1"` / `"approved"`

### 8.3 治理策略（未改，但相关）

- `Workbench/agents/harness/policies/permissions.yaml` — 模式矩阵
- `Workbench/agents/harness/policies/boundary_rules.yaml` — 硬拒绝规则
- `tests/test_security_hardening.py` — 安全红线测试

---

## 9. 仓库 Git 状态（报告撰写时）

```text
## main...origin/main
?? .cursor/checkpoints/fix-governance-runtime-debt-worktree-wip.patch
?? audit-reports/governance/governance_health_examination_2026-07-03.md
?? docs/operators/   # 会话开始前即存在未跟踪
```

- `deformation-framework` 子模块在会话初为 `-dirty`；安全相关改动在子模块内，需进入子模块单独 `git status`
- **用户未要求 commit** 安全加固或本 handoff 以外的文档

---

## 10. Checkpoint 字段（机器可读摘要）

```yaml
mission: |
  安全审查与加固；火山方舟 Coding Plan 全工具链模型与上下文配置；
  ZCode arkcli skill description 合规修复；产出本 handoff 文档。

decisions:
  - Terminal API: 非 loopback 必须 TERMINAL_API_KEY；有 Key 时中间件保护除 /health 外所有路由
  - hub_lite: validate_hashes/schema 默认 True，读 config.harvester
  - registry: requires_approval 与 policy ask 必须 approved=true 才执行
  - Coding Plan endpoint 固定 /api/coding/v3，不用 /api/v3
  - 默认模型保持 volcengine/ark-code-latest
  - skill description 缩短至 <1024，正文保留

open_threads:
  - 是否将安全加固改动 commit 到 main / deformation-framework 子模块
  - 是否把 ZCode config 中明文 API Key 迁到密钥文件或环境变量
  - 其他 arkcli skills 若仍超 1024 需同样处理
  - test_no_raw_sys_path_insert_in_scripts 失败项是否清理
  - funding_path_stress.py 实现缺失（import 会失败）— 一致性/可用性，非安全

do_not_touch:
  - 勿将 Coding Plan 请求指向 /api/v3
  - 勿在 handoff 或 commit 中写入用户 API Key 明文
  - 高影响工具 promote_snapshot 除 approved 外仍需 manual_review 流程

next_agent_action:
  - 若用户要继续安全线：跑 pip-audit；修复 sys.path 违规脚本；考虑 ZCode 密钥外置
  - 若用户要继续方舟线：arkcli auth login 后可 plans model-list 校验模型清单
  - 若模型调用失败：对照控制台 model-name 与 API /models 列表微调
  - 读 MODULES.md + module_contexts/ 再改跨模块代码
```

---

## 11. 相关文档与入口

| 资源 | 路径 |
|------|------|
| 模块路由 | `MODULES.md` |
| Agent 宪法 | `ROUTING_CONSTITUTION.md` |
| 工作区 Agent 指南 | `CLAUDE.md` |
| 既有 checkpoint | `.cursor/checkpoints/capability-upgrade-master.md` |
| Operator 文档（未跟踪） | `docs/operators/funding_path_stress.md` |
| OpenCode 全局配置 | `~/.config/opencode/opencode.json` |
| arkcli skills（Agent） | `~/.agents/skills/arkcli-*/SKILL.md` |

---

## 12. 修订历史

| 日期 | 作者 | 说明 |
|------|------|------|
| 2026-07-07 | Cursor Agent | 初版：汇总 2026-07-02～07-07 同线程全部用户请求与实施结果 |

---

*本文件为 Agent 交接文档，不含密钥。涉及 `~/.config`、`~/.zcode`、`~/.agents` 的变更不在 Git 版本控制内，换机或重装需单独备份。*
