"""Workbench current-card renderer — framework-agnostic.

Reads the framework registry, loads each active framework's output, and renders
a unified current risk card. Rendering strategies are driven by each framework's
``framework.yaml`` capability contract — the Workbench no longer hardcodes any
single framework's semantics.

Backward compatibility: the original Structural Deformation Framework extraction
from raw markdown + dashboard JSON is preserved for frameworks that declare a
``raw_output`` section in their contract.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from workbench.paths import workspace_root as _workspace_root
from workbench.freshness import banner_lines, write_model_run_freshness_manifest
from workbench.framework_registry import (
    load_registry,
    active_frameworks,
    resolve_value,
    framework_for_output,
    framework_evidence_requirements,
)

ROOT = _workspace_root()
OUTPUT = ROOT / "Output"
CURRENT = OUTPUT / "current"
DEFORMATION_LATEST = OUTPUT / "deformation_runs" / "latest"
LEARNING_LATEST = OUTPUT / "system_learning" / "latest"

LEARNING_LINKS = {"next_actions.md"}


# -- file helpers ------------------------------------------------------------

def safe_unlink(path: Path) -> None:
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            raise RuntimeError(f"Refusing to remove real directory: {path}")
        path.unlink()


def make_relative_symlink(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    safe_unlink(link)
    relative = os.path.relpath(target, start=link.parent)
    link.symlink_to(relative)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


# -- markdown extraction helpers ---------------------------------------------

def extract_main_signal(summary_md: str, heading: str = "## Main Signal") -> list[str]:
    pattern = rf"^{re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)"
    match = re.search(pattern, summary_md, flags=re.MULTILINE)
    if not match:
        return ["- Main signal not found in latest summary."]
    lines = [line.rstrip() for line in match.group(1).strip().splitlines() if line.strip()]
    return lines or ["- Main signal block is empty."]


def extract_top_actions(queue_md: str, limit: int = 3) -> list[str]:
    actions: list[str] = []
    for raw_line in queue_md.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "---" in line or "Proposed Action" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 10:
            continue
        action = cells[9]
        if action:
            actions.append(action)
        if len(actions) >= limit:
            break
    return actions or ["No proposed next actions found."]


def _field(manifest: dict[str, Any], name: str) -> str:
    value = manifest.get(name)
    if value is None or value == "":
        return "unknown"
    return str(value)


def _signal_payload(main_signal: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in main_signal:
        match = re.match(r"-\s*([^:]+):\s*(.*)", line)
        if match:
            key = match.group(1).strip().lower().replace(" ", "_")
            payload[key] = match.group(2).strip()
    return payload


# -- framework output loading ------------------------------------------------

def _resolve_framework_output_root(fw_entry: dict[str, Any]) -> Path:
    contract = fw_entry.get("contract", {})
    outputs = contract.get("outputs", {})
    fw_output_rel = outputs.get("framework_output")
    run_rel = outputs.get("latest_run")
    if fw_output_rel:
        fw_output_abs = ROOT / fw_output_rel
        if fw_output_abs.is_dir():
            return fw_output_abs
        return fw_output_abs.parent
    if run_rel:
        return ROOT / run_rel
    return DEFORMATION_LATEST


def _empty_framework_output(fw_entry: dict[str, Any]) -> dict[str, Any]:
    contract = fw_entry.get("contract", {})
    return {
        "schema_version": "workbench.framework_output.v1",
        "framework_id": fw_entry["framework_id"],
        "framework_version": contract.get("version", "0.0.0"),
        "run_id": "unknown",
        "as_of": "unknown",
        "status": "missing",
        "basic": {
            "overall": "UNKNOWN",
            "main_pressure": "no output",
            "confidence": "none",
            "summary": "Framework output not available.",
        },
        "advanced": {},
        "artifacts": {},
    }


def _extract_advanced_from_main_signal(
    main_signal: list[str],
    dashboard: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    payload = _signal_payload(main_signal)
    state = ((dashboard.get("snapshot_core") or {}).get("state") or {}) if dashboard else {}

    # SDF-specific fallback mapping: capability_id -> (state_key, default)
    _state_fallbacks = {
        "morphology": ("pattern", "unknown"),
        "sigma": ("sigma_t", None),
        "singular_flag": ("singular_flag", None),
        "singular_regime": ("singular_flag", None),
        "leading_channel": ("leading_channel", "unknown"),
    }

    # Payload key aliases: capability_id → alternative payload keys to try
    _payload_aliases: dict[str, list[str]] = {
        "singular_flag": ["singular_regime"],
        "escalation": ["escalation_flag"],
        "singular_regime": ["singular_flag"],
    }

    advanced: dict[str, Any] = {}
    for cap in contract.get("capabilities", []):
        cap_id = cap["id"]
        value = payload.get(cap_id)
        # Try aliases when direct lookup fails
        if value is None:
            for alias in _payload_aliases.get(cap_id, []):
                value = payload.get(alias)
                if value is not None:
                    break
        if value is None:
            fallback = _state_fallbacks.get(cap_id)
            if fallback:
                state_key, default_val = fallback
                value = state.get(state_key, default_val)
                if value is not None and cap.get("render") == "gauge":
                    value = _format_float(value)
        if value is not None:
            advanced[cap_id] = value

    return advanced


def _resolve_channel_label(channel_value: Any, fw_entry: dict[str, Any]) -> str:
    if channel_value is None or channel_value == "unknown":
        return "unknown"
    sdf_labels = {
        "M": "Anchor mismatch / rates-liquidity pressure",
        "D": "Degrees-of-freedom pressure",
        "K": "Transition-curvature pressure",
        "X": "Shadow-pressure channel",
    }
    return sdf_labels.get(str(channel_value), str(channel_value))


def _compute_basic_from_advanced(
    advanced: dict[str, Any],
    contract: dict[str, Any],
    fw_entry: dict[str, Any],
) -> dict[str, Any]:
    singular = str(advanced.get("singular_regime", advanced.get("singular_flag", "unknown"))).lower()
    escalation = str(advanced.get("escalation", advanced.get("escalation_flag", "unknown"))).lower()
    leading_channel = advanced.get("leading_channel")

    if singular in {"yes", "true"} or escalation in {"yes", "true"}:
        overall = "ALERT"
        summary = "A structural warning condition is active and needs immediate review."
    elif leading_channel not in {None, "", "unknown"}:
        overall = "WATCH"
        summary = "Broad stress is contained, but one or more pressure channels should be inspected."
    else:
        overall = "OK"
        summary = "No major current risk signal is visible in the latest framework output."

    channel_label = _resolve_channel_label(leading_channel, fw_entry)
    main_pressure = channel_label if channel_label and overall != "OK" else "no active pressure channel"

    freshness = _load_freshness_manifest()
    return {
        "overall": overall,
        "main_pressure": main_pressure,
        "confidence": "medium",
        "data_status": freshness.get("model_input_validity") or "usable",
        "summary": summary,
    }


def _extract_from_raw_output(
    fw_entry: dict[str, Any],
    raw_cfg: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = fw_entry.get("contract", {})
    output_root = _resolve_framework_output_root(fw_entry)

    summary_rel = raw_cfg.get("summary_md", "reports/executive_summary.md")
    dashboard_rel = raw_cfg.get("dashboard_json", "reports/dashboard_snapshot.json")
    heading = raw_cfg.get("main_signal_heading", "## Main Signal")

    summary_path = output_root / summary_rel
    dashboard_path = output_root / dashboard_rel

    if not summary_path.exists():
        return _empty_framework_output(fw_entry)

    summary_text = summary_path.read_text(encoding="utf-8")
    main_signal = extract_main_signal(summary_text, heading)

    dashboard: dict[str, Any] = {}
    if dashboard_path.exists():
        dashboard = read_json(dashboard_path)

    advanced = _extract_advanced_from_main_signal(main_signal, dashboard, contract)
    basic = _compute_basic_from_advanced(advanced, contract, fw_entry)

    run_id = "unknown"
    if manifest:
        run_id = _field(manifest, "run_id")

    return {
        "schema_version": "workbench.framework_output.v1",
        "framework_id": fw_entry["framework_id"],
        "framework_version": contract.get("version", "0.0.0"),
        "run_id": run_id,
        "as_of": _field(manifest or {}, "run_date"),
        "status": _field(manifest or {}, "status"),
        "basic": basic,
        "advanced": advanced,
        "artifacts": {},
        "evidence_links": [],
        "next_actions": [],
    }


def _load_framework_output(
    fw_entry: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = fw_entry.get("contract", {})
    raw_cfg = contract.get("raw_output")

    if raw_cfg is None:
        output_root = _resolve_framework_output_root(fw_entry)
        fw_output_path = output_root / "framework_output.json"
        if fw_output_path.exists():
            return read_json(fw_output_path)
        return _empty_framework_output(fw_entry)

    return _extract_from_raw_output(fw_entry, raw_cfg, manifest)


# -- evidence snapshot (multi-framework) -------------------------------------

def _evidence_snapshot(manifest: dict[str, Any]) -> list[dict[str, str]]:
    freshness = _load_freshness_manifest()
    by_series = {item["series_id"]: item for item in freshness.get("indicators", [])}

    def status(series_id: str, default: str = "OK") -> str:
        item = by_series.get(series_id, {})
        fresh = item.get("freshness_status")
        if fresh == "retired_or_unavailable":
            return "RETIRED_OR_UNAVAILABLE"
        if fresh == "missing":
            return "MISSING"
        if fresh == "stale":
            return "STALE"
        if fresh == "acceptable_lag":
            return "ACCEPTABLE_LAG"
        return default

    def note(series_id: str, fallback: str) -> str:
        item = by_series.get(series_id, {})
        return str(item.get("missing_reason") or item.get("retired_reason") or fallback)

    registry = load_registry()
    evidence_map = framework_evidence_requirements(registry)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for series_id, consumers in evidence_map.items():
        if series_id in seen:
            continue
        seen.add(series_id)
        entry = consumers[0]
        consumers_str = ", ".join(c["framework_id"] for c in consumers)
        rows.append({
            "area": entry.get("area", "Unknown"),
            "signal": entry.get("label", series_id),
            "status": status(series_id, "MISSING"),
            "note": note(series_id, f"Required by {consumers_str}"),
        })

    rows.append({
        "area": "Release",
        "signal": _field(manifest, "harvester_release"),
        "status": "USABLE",
        "note": "Admitted Harvester evidence release is linked",
    })

    return rows


# -- freshness helpers -------------------------------------------------------

def _load_freshness_manifest() -> dict[str, Any]:
    path = DEFORMATION_LATEST / "freshness_manifest.json"
    if not path.exists():
        return {}
    return read_json(path)


# -- formatting utilities ----------------------------------------------------

def _format_float(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "unknown"


def _yes_no(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "unknown"
    return str(value)


def _resolve_display_template(template: str, data: dict[str, Any]) -> str:
    result = template
    for key, value in data.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


# -- rendering ---------------------------------------------------------------

def _render_framework_diagnosis_section(
    fw_entry: dict[str, Any],
    fw_output: dict[str, Any],
) -> list[str]:
    contract = fw_entry.get("contract", {})
    display_name = contract.get("display_name", fw_entry["framework_id"])
    basic = fw_output.get("basic", {})
    display_cfg = contract.get("display", {})

    lines: list[str] = []
    lines.append(f"## {display_name}")
    lines.append("")

    lines.append("### Basic Check")
    lines.append(f"- Overall: {basic.get('overall', 'UNKNOWN')}")
    lines.append(f"- Main pressure: {basic.get('main_pressure', 'unknown')}")
    lines.append(f"- Confidence: {basic.get('confidence', 'unknown')}")
    if basic.get("summary"):
        lines.append(f"- Summary: {basic['summary']}")
    lines.append("")

    adv_sections = display_cfg.get("advanced_sections", [])
    if adv_sections:
        lines.append("### Diagnosis")
        for adv_sec in adv_sections:
            title = adv_sec.get("title", "Unknown")
            from_path = adv_sec.get("from", "")
            fmt = adv_sec.get("format", "{value}")
            value = resolve_value(fw_output, from_path, default="unknown")
            if isinstance(value, float):
                try:
                    formatted = fmt.format(value=value)
                except (KeyError, ValueError):
                    formatted = str(value)
            else:
                formatted = fmt.replace("{value}", str(value)) if "{value}" in fmt else str(value)
            lines.append(f"- {title}: {formatted}")
        lines.append("")

    return lines


def render_read_me(manifest: dict[str, Any], main_signal: list[str], top_actions: list[str]) -> str:
    registry = load_registry()
    frameworks = active_frameworks(registry)
    freshness = _load_freshness_manifest()

    sections: list[str] = ["# Current Risk Check", ""]

    # Per-framework sections
    for fw_entry in frameworks:
        fw_output = _load_framework_output(fw_entry, manifest)
        sections.extend(_render_framework_diagnosis_section(fw_entry, fw_output))

    # Data Recency (shared)
    sections.append("## Data Recency")
    if freshness:
        sections.extend(f"- {line}" for line in banner_lines(freshness))
    else:
        sections.append("- Freshness manifest not available.")
    sections.append("")

    # Evidence Snapshot (aggregated)
    evidence_rows = [
        f"| {row['area']} | {row['signal']} | {row['status']} | {row['note']} |"
        for row in _evidence_snapshot(manifest)
    ]
    sections.extend([
        "## Evidence Snapshot",
        "| Area | Signal | Status | Note |",
        "|---|---:|---|---|",
        *evidence_rows,
        "",
    ])

    # What to inspect
    sections.extend([
        "## What To Inspect Next",
        "1. Inspect rate volatility.",
        "2. Check liquidity confirmation.",
        "3. Compare credit spread behavior.",
        "",
    ])

    # Backward-compatible "Framework Diagnosis" for ./sys explain
    if len(frameworks) == 1:
        fw = frameworks[0]
        contract = fw.get("contract", {})
        fw_output = _load_framework_output(fw, manifest)
        display_name = contract.get("display_name", fw["framework_id"])
        sections.append("## Framework Diagnosis")
        sections.append(f"Framework: {display_name}")
        display_cfg = contract.get("display", {})
        for adv_sec in display_cfg.get("advanced_sections", []):
            title = adv_sec.get("title", "Unknown")
            from_path = adv_sec.get("from", "")
            fmt = adv_sec.get("format", "{value}")
            value = resolve_value(fw_output, from_path, default="unknown")
            formatted = fmt.replace("{value}", str(value)) if "{value}" in fmt else str(value)
            sections.append(f"- {title}: {formatted}")
        sections.append("")

    # Open links
    sections.extend([
        "## Open",
        "- Full report: `Output/current/latest_report.html`",
        "- Evidence dashboard: `Output/current/benchmark_evidence_dashboard.md`",
        "- Freshness manifest: `Output/current/freshness_manifest.json`",
        "- Dashboard JSON: `Output/current/latest_dashboard.json`",
        "- Next actions: `Output/current/next_actions.md`",
        "- System health: `Output/system_learning/latest/system_health_report.md`",
        "",
    ])

    # Provenance
    sections.extend([
        "## Provenance",
        "- Run package: `Output/current/latest_run`",
        "- Run manifest: `Output/current/run_manifest.json`",
        f"- Harvester release: `{_field(manifest, 'harvester_release')}`",
        f"- Catalog: `{_field(manifest, 'harvester_catalog_path')}`",
        f"- Run ID: `{_field(manifest, 'run_id')}`",
        "",
    ])

    # Governance
    action_lines = [f"{idx}. {action}" for idx, action in enumerate(top_actions, start=1)]
    sections.extend([
        "## Governance Next Actions",
        *action_lines,
        "",
    ])

    # Commands
    sections.extend([
        "## Deeper Commands",
        "- Basic check: `./sys check`",
        "- Evidence: `./sys evidence`",
        "- Structural explanation: `./sys explain`",
        "- Full report: `./sys open`",
        "- Next actions: `./sys next`",
        "- System health: `./sys doctor`",
        "- List frameworks: `./sys framework list`",
        "",
    ])

    return "\n".join(sections)


# -- model run output --------------------------------------------------------

def _write_model_run(manifest: dict[str, Any], main_signal: list[str]) -> None:
    registry = load_registry()
    frameworks = active_frameworks(registry)
    freshness = _load_freshness_manifest()

    for fw_entry in frameworks:
        contract = fw_entry.get("contract", {})
        fw_output = _load_framework_output(fw_entry, manifest)

        model_run_payload = {
            "schema_version": "workbench.model_run.v1",
            "model_id": fw_entry["framework_id"],
            "producer": contract.get("display_name", fw_entry["framework_id"]),
            "run_id": _field(manifest, "run_id"),
            "run_date": _field(manifest, "run_date"),
            "generated_at": _field(manifest, "generated_at"),
            "status": _field(manifest, "status"),
            "input_bundle": _field(manifest, "harvester_release"),
            "freshness_manifest": "freshness_manifest.json" if freshness else None,
            "model_input_validity": freshness.get("model_input_validity"),
            "artifacts": {
                "status_card": {
                    "path": "00_READ_ME_FIRST.md",
                    "kind": "markdown",
                    "description": "Workbench run cockpit.",
                },
                # Legacy display artifacts REMOVED from Output/current/ (2026-06-17).
                # These now live in Output/deformation_runs/latest/reports/.
                # See governance/architecture_cleanup_decisions.md D5.
                "next_actions": {
                    "path": "next_actions.md",
                    "kind": "markdown",
                    "description": "Governance next actions.",
                },
            },
            "framework_payload": {
                "framework_id": fw_entry["framework_id"],
                "main_signal": _signal_payload(main_signal) if fw_entry["framework_id"] == "structural_deformation" else {},
                "source_manifest_schema": manifest.get("schema_version"),
                "freshness": {
                    "date_semantics": freshness.get("date_semantics"),
                    "gate_result": freshness.get("gate_result"),
                },
            },
        }

        suffix = f"_{fw_entry['framework_id']}" if fw_entry["framework_id"] != "structural_deformation" else ""
        model_run_path = CURRENT / f"model_run{suffix}.json"
        model_run_path.write_text(
            json.dumps(model_run_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        fw_out_payload = copy.deepcopy(fw_output)
        fw_out_payload["schema_version"] = "workbench.framework_output.v1"
        fw_out_payload["evidence_links"] = [
            "Output/current/benchmark_evidence_dashboard.md",
            "Output/current/latest_dashboard.json",
        ]
        fw_out_payload["next_actions"] = [
            "Inspect rate volatility.",
            "Check liquidity confirmation.",
            "Compare credit spread behavior.",
        ]
        fw_out_payload["artifacts"] = {
            "summary": "Output/current/latest_summary.md",
            "report_html": "Output/current/latest_report.html",
            "dashboard_json": "Output/current/latest_dashboard.json",
            "run_manifest": "Output/current/run_manifest.json",
        }

        fw_out_suffix = f"_{fw_entry['framework_id']}.json" if fw_entry["framework_id"] != "structural_deformation" else ".json"
        fw_out_path = CURRENT / f"workbench_framework_output{fw_out_suffix}"
        fw_out_path.write_text(
            json.dumps(fw_out_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )


# -- refresh -----------------------------------------------------------------

def refresh_current() -> None:
    CURRENT.mkdir(parents=True, exist_ok=True)
    manifest_path = DEFORMATION_LATEST / "run_manifest.json"
    summary_path = DEFORMATION_LATEST / "reports" / "executive_summary.md"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing latest run_manifest.json: {manifest_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing latest executive_summary.md: {summary_path}")

    links = {
        "next_actions.md": CURRENT / "NEXT_ACTIONS.md",
    }
    for name, target in links.items():
        link = CURRENT / name
        if target.exists():
            make_relative_symlink(target, link)
        elif name in LEARNING_LINKS:
            safe_unlink(link)
            link.write_text(f"# Missing\n\nSource file not found: `{target}`\n", encoding="utf-8")
        else:
            raise FileNotFoundError(f"Required target missing: {target}")

    manifest = read_json(manifest_path)
    # freshness_manifest symlink REMOVED — freshness is now in status.json.
    manifest = read_json(manifest_path)
    summary_text = summary_path.read_text(encoding="utf-8")
    queue_path = LEARNING_LATEST / "improvement_queue.md"
    queue_text = queue_path.read_text(encoding="utf-8") if queue_path.exists() else ""
    readme = render_read_me(
        manifest=manifest,
        main_signal=extract_main_signal(summary_text),
        top_actions=extract_top_actions(queue_text),
    )
    (CURRENT / "00_READ_ME_FIRST.md").write_text(readme, encoding="utf-8")
    _write_model_run(manifest, extract_main_signal(summary_text))


def main() -> None:
    import warnings

    warnings.warn(
        "refresh_output_current is DEPRECATED. Canonical output path: "
        "scripts/bridge_replay_to_current.py. This path links to the latest "
        "Deformation run, which may be stale (broken SigmaVector persistence). "
        "./sys refresh runs the bridge AFTER this, so bridge output wins.",
        DeprecationWarning,
        stacklevel=2,
    )
    refresh_current()
    print("Done.")
    print("Current output:")
    print("  Output/current/00_READ_ME_FIRST.md")
    print("Latest artifacts:")
    print("  Run package:  Output/current/latest_run")
    print("  Summary:      Output/current/latest_summary.md")
    print("  HTML report:  Output/current/latest_report.html")
    print("  Dashboard:    Output/current/latest_dashboard.json")
    print("  Next actions: Output/current/next_actions.md")
    print("Commands:")
    print("  ./sys check")
    print("  ./sys open")
    print("  ./sys evidence")
    print("  ./sys next")
    print("  ./sys framework list")


if __name__ == "__main__":
    main()
