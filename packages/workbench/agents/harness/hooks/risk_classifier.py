"""risk_classifier — classifies a tool invocation into a risk category.

Risk categories (in increasing severity):
  read_only            — no side effects, no data mutation
  code_edit            — modifies source files, config files, or scripts
  data_mutation        — creates or modifies data artifacts
  release_finalization — finalizes a data release (immutable audit point)
  snapshot_publish     — publishes a snapshot for external consumption
  cross_boundary       — one subsystem accesses another's domain
  destructive          — deletes or irreversibly destroys data/artifacts

The classifier inspects the ToolSpec, the input arguments, and the
current agent mode to determine the dominant risk category.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Allow importing both from tools and standalone
try:
    from tools.registry import ToolSpec
except ImportError:
    ToolSpec = object  # type: ignore


RISK_CATEGORIES = [
    "read_only",
    "code_edit",
    "data_mutation",
    "release_finalization",
    "snapshot_publish",
    "cross_boundary",
    "destructive",
]

# Severity order for priority resolution (higher = more severe)
RISK_SEVERITY = {
    "read_only": 1,
    "code_edit": 2,
    "data_mutation": 3,
    "release_finalization": 4,
    "snapshot_publish": 5,
    "cross_boundary": 6,
    "destructive": 7,
}

# Keywords in tool_id that signal specific risk categories
_TOOL_ID_SIGNALS = {
    "release_finalization": ["finalize_release", "publish_release"],
    "snapshot_publish": ["publish_snapshot", "promote_snapshot", "publish"],
    "code_edit": ["edit", "modify", "patch", "create_file"],
    "destructive": ["delete", "destroy", "purge", "drop", "remove_all"],
    "data_mutation": ["run", "ingest", "create", "generate", "write"],
}

# Subsystem boundaries — who owns what
_SUBSYSTEM_DOMAINS = {
    "harvester": ["Data/harvester", "harvester"],
    "deformation": ["Output/deformation_runs", "deformation"],
    "learning_hub": ["Output/system_learning", "learning"],
    "cc_switch": ["cc-switch", "routing"],
}


@dataclass
class RiskClassification:
    """Result of classifying a tool invocation."""
    primary_category: str
    secondary_categories: list[str] = field(default_factory=list)
    is_mutation: bool = False
    is_boundary_crossing: bool = False
    target_subsystems: list[str] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)

    @property
    def max_severity(self) -> int:
        sev = RISK_SEVERITY.get(self.primary_category, 1)
        for cat in self.secondary_categories:
            sev = max(sev, RISK_SEVERITY.get(cat, 1))
        return sev


def classify(tool_spec: Any, input: dict, mode: str) -> RiskClassification:
    """Classify a tool invocation into risk categories.

    Args:
        tool_spec: The ToolSpec (or dict with equivalent fields).
        input:     The input arguments dict passed to the tool.
        mode:      Current agent mode (explore, verify, implement, etc.).

    Returns:
        RiskClassification with primary and secondary categories.
    """
    # Read ToolSpec fields safely (works with both object and dict)
    _get = lambda key, default=None: (
        getattr(tool_spec, key, default) if hasattr(tool_spec, key) else default
    )
    tool_id = _get("id", "") or ""
    subsystem = _get("subsystem", "") or ""
    read_only = _get("read_only", True)
    mutates = _get("mutates_artifacts", False)
    risk_level = _get("risk_level", "low")

    categories: list[str] = []
    flags: dict[str, bool] = {}
    target_subsystems: list[str] = []

    # ── 1. Base classification from ToolSpec ──────────────────────────
    if read_only and not mutates:
        categories.append("read_only")
        flags["is_read_only"] = True
    else:
        flags["is_read_only"] = False
        if mutates:
            categories.append("data_mutation")
            flags["is_mutation"] = True

    # ── 2. Keyword-based signals from tool_id ─────────────────────────
    for cat, kwds in _TOOL_ID_SIGNALS.items():
        if read_only and not mutates and cat in {
            "code_edit",
            "data_mutation",
            "release_finalization",
            "snapshot_publish",
            "destructive",
        }:
            continue
        if any(kw in tool_id for kw in kwds):
            categories.append(cat)
            flags[f"signal_{cat}"] = True

    # ── 3. Input-based signals ────────────────────────────────────────
    input_target = input.get("target", "")
    input_output = input.get("output", "")
    input_run_mode = input.get("run_mode", "")
    input_run_purpose = input.get("run_purpose", "")
    input_run_type = input.get("run_type", "")
    input_release_status = input.get("release_status", "")
    input_action = input.get("action", "")

    # detect targeted subsystem from input paths
    for path_key in ("target", "output", "input_path", "target_path"):
        path_val = input.get(path_key, "")
        if isinstance(path_val, str):
            path_lower = path_val.lower()
            for sys_name, domains in _SUBSYSTEM_DOMAINS.items():
                if any(d.lower() in path_lower for d in domains):
                    if sys_name != subsystem:
                        target_subsystems.append(sys_name)

    # detect cross-boundary: deformation reading harvester
    for path_key in ("target", "input_path", "release_dir", "data_dir"):
        path_val = input.get(path_key, "")
        if isinstance(path_val, str):
            for hint in ["harvester/raw", "harvester/processed", "harvester/corpus"]:
                if hint in path_val and subsystem == "deformation":
                    categories.append("cross_boundary")
                    flags["cross_boundary_def_reads_harvester"] = True
                    target_subsystems.append("harvester")

    # detect learning_hub modifying peer source
    if subsystem == "learning_hub" and input_action in ("edit", "modify", "write", "patch"):
        if any(ts in target_subsystems for ts in ("harvester", "deformation", "cc_switch")):
            categories.append("cross_boundary")
            flags["cross_boundary_learninghub_modifies_peer"] = True

    # detect release finalization
    if input_release_status == "final" or input_action in ("finalize", "finalize_release"):
        categories.append("release_finalization")
        flags["is_finalization"] = True

    # detect snapshot publishing
    if any(kw in tool_id for kw in ("publish",)):
        categories.append("snapshot_publish")
        flags["is_publish"] = True

    # detect simulated fallback
    if input_run_mode == "simulated_fallback":
        flags["is_simulated_fallback"] = True

    # detect benchmark/control
    if input_run_purpose == "benchmark" or input_run_type == "benchmark":
        flags["is_benchmark"] = True

    # detect exploratory
    if input_run_purpose == "exploratory":
        flags["is_exploratory"] = True

    # ── 4. Feature name detection ────────────────────────────────────
    feature_name = input.get("feature_name", "")
    if feature_name:
        flags["feature_name"] = feature_name

    # ── 5. Target output detection ───────────────────────────────────
    target_output = input.get("target_output", "") or input.get("output_target", "")
    if target_output:
        flags["target_output"] = target_output

    # ── 6. Deduplicate and order by severity ──────────────────────────
    unique = list(dict.fromkeys(categories))  # preserve order, remove dups
    if not unique:
        unique = ["read_only"]

    primary = unique[-1] if len(unique) > 1 else unique[0]
    secondary = [c for c in unique if c != primary]

    is_boundary_crossing = "cross_boundary" in unique
    is_mutation = "data_mutation" in unique

    return RiskClassification(
        primary_category=primary,
        secondary_categories=secondary,
        is_mutation=is_mutation,
        is_boundary_crossing=is_boundary_crossing,
        target_subsystems=list(set(target_subsystems)),
        flags=flags,
    )
