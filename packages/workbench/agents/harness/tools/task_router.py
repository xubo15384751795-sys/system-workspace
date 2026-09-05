"""task_router — deterministic first-pass routing for System workspace tasks.

The router converts a fuzzy user request into a small, auditable routing
decision. It is intentionally conservative: choose one owning module first,
then name escalation reasons and expert protocols only when the task signals
boundary crossing, protected artifacts, or verification/release risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

SYSTEM_ROOT = _resolve_system_root(WORKBENCH_ROOT)

MODULES_PATH = HARNESS_ROOT / "config" / "modules.md" if (HARNESS_ROOT / "config" / "modules.md").is_file() else WORKBENCH_ROOT / ".opencode" / "modules.md"
CONSTITUTION_PATH = WORKBENCH_ROOT / ".opencode" / "routing_constitution.md"
EXPERT_MAP_PATH = WORKBENCH_ROOT / ".opencode" / "expert_map.yaml"
ROUTING_AUTHORITY_PATH = SYSTEM_ROOT / "governance" / "agent_routing_authority.yaml"


@dataclass(frozen=True)
class ModuleRule:
    module: str
    context_file: str
    primary_paths: list[str]
    keywords: list[str]
    forbidden_first_reads: list[str] = field(default_factory=list)


MODULE_RULES: list[ModuleRule] = [
    ModuleRule(
        module="Workbench",
        context_file="module_contexts/workbench.md",
        primary_paths=["packages/workbench/", "scripts/", "Output/current/"],
        keywords=[
            "sys",
            "dashboard",
            "cockpit",
            "current",
            "evidence view",
            "artifact navigator",
            "report",
            "user-facing",
            "workbench",
            "product",
            "用户",
            "仪表盘",
            "看板",
            "报告",
        ],
        forbidden_first_reads=[
            "packages/framework_v1_archive/src/core/",
            "provider acquisition internals",
        ],
    ),
    ModuleRule(
        module="Deformation v1 Evidence Archive",
        context_file="module_contexts/framework.md",
        primary_paths=["packages/framework_v1_archive/"],
        keywords=[
            "deformation v1",
            "archived falsified",
            "estate settlement",
            "reproduce historical evidence",
        ],
        forbidden_first_reads=[
            "packages/framework_v1_archive/src/core/",
            "packages/framework_v1_archive/src/dynamics/",
            "packages/framework_v1_archive/src/operators/",
            "packages/workbench/src/workbench/",
            "packages/harvester provider code",
        ],
    ),
    ModuleRule(
        module="Harvester",
        context_file="module_contexts/harvester.md",
        primary_paths=[
            "packages/harvester/",
            "Data/harvester/exports/",
        ],
        keywords=[
            "harvester",
            "provider",
            "fred",
            "sec",
            "treasury",
            "openbb",
            "source data",
            "data release",
            "provenance",
            "freshness",
            "checksum",
            "catalog",
            "source registry",
            "数据源",
            "采集",
            "溯源",
            "新鲜度",
            "发布包",
        ],
        forbidden_first_reads=[
            "packages/framework_v1_archive/src/dynamics/",
            "packages/workbench dashboard internals",
        ],
    ),
    ModuleRule(
        module="Protocols",
        context_file="module_contexts/protocols.md",
        primary_paths=["protocols/", "packages/workbench/contracts/workbench/"],
        keywords=[
            "schema",
            "contract",
            "compatibility",
            "field",
            "validation",
            "validator",
            "cross-module exchange",
            "protocol",
            "协议",
            "字段",
            "契约",
            "校验",
        ],
    ),
    ModuleRule(
        module="Data and Output",
        context_file="module_contexts/data-output.md",
        primary_paths=["Data/", "Output/"],
        keywords=[
            "canonical",
            "snapshot",
            "promotion",
            "latest symlink",
            "latest",
            "run artifact",
            "artifact state",
            "Data/system_index",
            "Output/current",
            "规范化",
            "快照",
            "提升",
            "运行产物",
        ],
    ),
    ModuleRule(
        module="Learning Hub",
        context_file="module_contexts/learning-hub.md",
        primary_paths=[
            "packages/learning_hub/",
            "Output/system_learning/",
        ],
        keywords=[
            "learning hub",
            "governance",
            "architecture drift",
            "boundary violation",
            "improvement queue",
            "routing decision",
            "hard case",
            "ledger",
            "治理",
            "学习",
            "改进队列",
            "边界违规",
        ],
    ),
    ModuleRule(
        module="Agent Routing",
        context_file="module_contexts/agent-routing.md",
        primary_paths=[
            "agents/",
            "ROUTING_CONSTITUTION.md",
        ],
        keywords=[
            "agent",
            "routing",
            "route",
            "sparse activation",
            "expert",
            "workflow guard",
            "task routing",
            "context pack",
            "tool registry",
            "permission",
            "policy hook",
            "路由",
            "专家",
            "权限",
            "工作流",
            "工具注册",
        ],
    ),
]


EXPERT_KEYWORDS: dict[str, list[str]] = {
    "research_os_layers": ["cross", "layer", "paper", "wiki", "claim", "report"],
    "proxy_boundary": ["proxy", "sigma", "benchmark", "diagnostic", "no-lookahead"],
    "datahub_implementation": [
        "data access",
        "adapter",
        "manifest",
        "provider",
        "数据源",
        "采集",
        "溯源",
    ],
    "no_lookahead_tests": ["lookahead", "backtest", "historical", "replay", "release timing"],
    "claim_guardian": ["claim", "validation", "early-warning", "outperformance", "portfolio"],
    "paper_claim_calibration": ["paper", "abstract", "caption", "publication"],
    "reference_hygiene": ["citation", "reference", "source", "literature", "pdf"],
    "wiki_maintainer": ["wiki", "mechanism", "variable", "case", "method"],
    "referee_proxy_validity": ["proxy validity", "trace quality", "frequency", "missingness"],
    "referee_benchmark_dominance": ["dominance", "outperformance", "baseline", "incremental"],
    "referee_fatal_objection": ["release", "public", "submission", "overclaim", "circularity"],
    "ui_contract": ["ui", "dashboard", "viewer", "display", "runtime viewer"],
}


MODE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("verify", ["verify", "audit", "validate", "test", "check", "review"]),
    ("verify", ["验证", "审计", "检查", "测试", "复核"]),
    ("implement", ["implement", "fix", "edit", "add", "build", "refactor", "change"]),
    ("implement", ["实现", "修复", "编辑", "新增", "优化", "重构", "改"]),
    ("release", ["release", "finalize", "publish", "promote"]),
    ("release", ["发布", "定稿", "提升", "推广"]),
    ("run", ["run", "execute", "refresh"]),
    ("run", ["运行", "执行", "刷新"]),
    ("fetch", ["fetch", "ingest", "download", "acquire"]),
    ("fetch", ["抓取", "采集", "下载", "摄取"]),
    ("plan", ["plan", "design", "strategy", "roadmap"]),
    ("plan", ["计划", "设计", "策略", "路线图"]),
]


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").split())


def _score_rule(rule: ModuleRule, text: str, artifacts: list[str]) -> tuple[int, list[str]]:
    signals: list[str] = []
    score = 0
    for keyword in rule.keywords:
        if _norm(keyword) in text:
            score += 3
            signals.append(keyword)
    for path in rule.primary_paths:
        path_norm = _norm(path)
        if path_norm.rstrip("/") in text:
            score += 5
            signals.append(path)
    for artifact in artifacts:
        artifact_norm = _norm(artifact)
        if any(_norm(path).rstrip("/") in artifact_norm for path in rule.primary_paths):
            score += 5
            signals.append(artifact)
    return score, signals


def _infer_mode(text: str) -> str:
    for mode, keywords in MODE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return mode
    return "explore"


def _load_expert_protocols() -> dict[str, dict[str, Any]]:
    if not EXPERT_MAP_PATH.is_file():
        return {}
    try:
        raw = yaml.safe_load(EXPERT_MAP_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    protocols = raw.get("expert_protocols", [])
    return {
        item.get("id", ""): item
        for item in protocols
        if isinstance(item, dict) and item.get("id")
    }


def _activate_experts(text: str, modules: list[str]) -> list[dict[str, Any]]:
    protocols = _load_expert_protocols()
    activated: list[dict[str, Any]] = []
    for expert_id, keywords in EXPERT_KEYWORDS.items():
        matches = [keyword for keyword in keywords if keyword in text]
        if matches or (expert_id == "research_os_layers" and len(modules) > 1):
            proto = protocols.get(expert_id, {})
            activated.append(
                {
                    "id": expert_id,
                    "path": proto.get("path", ""),
                    "reason": "matched signals: " + ", ".join(matches)
                    if matches
                    else "task crosses module boundaries",
                    "scope": proto.get("scope", []),
                    "outputs": proto.get("outputs", []),
                }
            )
    return activated


def _load_routing_authority() -> dict[str, Any]:
    if not ROUTING_AUTHORITY_PATH.is_file():
        return {}
    try:
        return yaml.safe_load(ROUTING_AUTHORITY_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def resolve_execution_authority(
    mode: str,
    *,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Resolve whether a routed task may execute a pipeline step."""
    policy = _load_routing_authority()
    mode_map = policy.get("mode_to_tier", {})
    tiers = policy.get("tiers", {})
    tier_name = mode_map.get(mode, policy.get("default_tier", "shadow"))
    tier = tiers.get(tier_name, {})

    may_execute = bool(tier.get("may_execute_pipeline_step"))
    may_dry_run = bool(tier.get("may_dry_run_pipeline_step", True))
    denied = set(tier.get("denied_step_ids", []))
    core_ids = set((policy.get("core_judgment_policy") or {}).get("affected_step_ids", []))

    reasons: list[str] = []
    if step_id:
        if step_id in denied:
            may_execute = False
            reasons.append(f"step '{step_id}' denied for tier '{tier_name}'")
        if step_id in core_ids and tier.get("dry_run_required_unless_mode") != mode:
            if mode != "verify":
                may_execute = False
                reasons.append(f"core-judgment step '{step_id}' requires dry-run or verify mode")

    return {
        "authority_tier": tier_name,
        "recommended_mode": mode,
        "may_execute_pipeline_step": may_execute,
        "may_dry_run_pipeline_step": may_dry_run,
        "governed_tool": "workbench.run_pipeline_step",
        "policy_path": str(ROUTING_AUTHORITY_PATH.relative_to(SYSTEM_ROOT))
        if ROUTING_AUTHORITY_PATH.is_file()
        else "",
        "denied_step_ids": sorted(denied),
        "reasons": reasons,
    }


def route_task(task: str, artifacts: list[str] | None = None) -> dict[str, Any]:
    """Route a fuzzy task to the smallest sufficient module and expert set."""
    artifacts = artifacts or []
    text = _norm(" ".join([task, *artifacts]))
    scored: list[dict[str, Any]] = []
    for rule in MODULE_RULES:
        score, signals = _score_rule(rule, text, artifacts)
        if score:
            scored.append({"rule": rule, "score": score, "signals": signals})

    if not scored:
        fallback = next(rule for rule in MODULE_RULES if rule.module == "Workbench")
        scored = [{"rule": fallback, "score": 1, "signals": ["default: user-facing workbench route"]}]

    scored.sort(key=lambda item: item["score"], reverse=True)
    primary: ModuleRule = scored[0]["rule"]
    secondary = [
        {
            "module": item["rule"].module,
            "context_file": item["rule"].context_file,
            "score": item["score"],
            "matched_signals": item["signals"],
        }
        for item in scored[1:]
        if item["score"] >= max(3, scored[0]["score"] // 2)
    ]
    involved_modules = [primary.module] + [item["module"] for item in secondary]

    escalation_reasons: list[str] = []
    if secondary:
        escalation_reasons.append("Task has material signals for more than one module.")
    if any(word in text for word in ["release", "publish", "promote", "claim", "paper"]):
        escalation_reasons.append("Task touches a protected promotion or claim surface.")
    if any(word in text for word in ["schema", "contract", "protocol", "field"]):
        escalation_reasons.append("Protocol or schema compatibility must be checked.")

    requires_record = bool(
        secondary
        or escalation_reasons
        or any(word in text for word in ["release", "publish", "promote", "canonical"])
    )

    activated_experts = _activate_experts(text, involved_modules)
    mode = _infer_mode(text)
    if mode == "release":
        escalation_reasons.append("Release mode requires manual review before finalization.")

    execution_authority = resolve_execution_authority(mode)

    return {
        "task": task,
        "primary_module": primary.module,
        "context_file": primary.context_file,
        "primary_paths": primary.primary_paths,
        "recommended_mode": mode,
        "execution_authority": execution_authority,
        "matched_signals": scored[0]["signals"],
        "secondary_modules": secondary,
        "activated_experts": activated_experts,
        "requires_routing_decision_record": requires_record,
        "routing_record_template": "routing_decision_record.template.yaml"
        if requires_record
        else "",
        "read_first": [primary.context_file],
        "do_not_read_first": primary.forbidden_first_reads,
        "escalation_reasons": escalation_reasons,
        "policy_notes": [
            "Start from the smallest owning module.",
            "Cross source boundaries only with an explicit reason.",
            "Keep execution and verification as separate phases.",
        ],
        "source_documents": [
            str(MODULES_PATH.relative_to(WORKBENCH_ROOT)),
            str(CONSTITUTION_PATH.relative_to(WORKBENCH_ROOT)),
            "tools/task_router.py",
        ],
    }


def route_task_as_dict(task: str, artifacts: list[str] | None = None) -> dict[str, Any]:
    """Compatibility wrapper with an explicit serializable return type."""
    return dict(route_task(task, artifacts))
