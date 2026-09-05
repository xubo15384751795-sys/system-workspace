from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, cast

import numpy as np

from src.core.models import Snapshot, SnapshotCore, SnapshotExtension
from src.interpretation.market_state import interpret_snapshot
from src.research.concept_registry import concept_registry_payload


def export_snapshot_artifacts(
    snapshot: Snapshot,
    output_dir: str,
    export_image: bool = True,
    image_width: int = 1400,
) -> dict[str, str]:
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    base = f"{snapshot.run_date}_{snapshot.run_type}".replace(" ", "_")
    html_path = out_dir / f"{base}.html"
    json_path = out_dir / f"{base}.json"

    payload = snapshot_to_dict(snapshot)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    html_path.write_text(_render_html(payload), encoding="utf-8")

    result = {"json": str(json_path), "html": str(html_path)}
    if export_image:
        image_path = html_to_png(html_path, image_width=image_width)
        if image_path is not None:
            result["png"] = str(image_path)
    return result


def snapshot_to_dict(snapshot: Snapshot) -> dict[str, Any]:
    state_vector = snapshot.state.z_vector
    state_vector_list = state_vector.tolist() if isinstance(state_vector, np.ndarray) else None
    interpretation = interpret_snapshot(snapshot)
    core = snapshot_core_to_dict(snapshot.core())
    extension = snapshot_extension_to_dict(snapshot.extension())
    sigma_vector = _sigma_vector_from_snapshot(snapshot)
    payload = {
        "run_date": snapshot.run_date,
        "run_type": snapshot.run_type,
        "escalation": snapshot.escalation,
        "escalation_reason": snapshot.escalation_reason,
        "snapshot_core": core,
        "snapshot_extension": extension,
        "proxy": {
            "M": snapshot.proxy.M,
            "D": snapshot.proxy.D,
            "K": snapshot.proxy.K,
            "X": snapshot.proxy.X,
            "X_PRE": snapshot.proxy.X_PRE,
            "X_REALIZED": snapshot.proxy.X_REALIZED,
            "directions": dict(snapshot.proxy.directions),
            "available": dict(snapshot.proxy.available),
            "components": dict(snapshot.proxy.components),
        },
        "state": {
            "sigma_t": snapshot.state.sigma_t,
            "SigmaVector": sigma_vector,
            "singular_flag": snapshot.state.singular_flag,
            "structural_singular_time": snapshot.state.structural_singular_time,
            "leading_channel": snapshot.state.leading_channel,
            "pattern": snapshot.state.pattern,
            "anomaly_score": snapshot.state.anomaly_score,
            "z_vector": state_vector_list,
            "reflexivity_flags": dict(snapshot.state.reflexivity_flags),
            "provenance": dict(snapshot.state.provenance),
            "operator_diagnostics": snapshot.state.operator_diagnostics.to_dict() if snapshot.state.operator_diagnostics is not None else {},
            "belief_state": snapshot.state.belief_state.to_dict() if snapshot.state.belief_state is not None else None,
            "primitive_state": snapshot.state.primitive_state.to_dict() if snapshot.state.primitive_state is not None else None,
            "shadow_mass_state": snapshot.state.shadow_mass_state.to_dict() if snapshot.state.shadow_mass_state is not None else None,
            "mean_field_gap": snapshot.state.mean_field_gap.to_dict() if snapshot.state.mean_field_gap is not None else None,
            "structural_diagnostic_state": snapshot.state.diagnostic_state.to_dict() if snapshot.state.diagnostic_state is not None else None,
        },
        "concept_registry": _concept_registry_payload(),
        "narrative": (
            {
                "ai_unicorn": snapshot.narrative.ai_unicorn,
                "clo_cmbs": snapshot.narrative.clo_cmbs,
                "policy": snapshot.narrative.policy,
                "drift_scores": dict(snapshot.narrative.drift_scores),
            }
            if snapshot.narrative is not None
            else None
        ),
        "interpretation": {
            "pattern": interpretation.pattern,
            "leading_channel": interpretation.leading_channel,
            "severity": interpretation.severity,
            "summary": interpretation.summary,
            "channel_notes": interpretation.channel_notes,
            "recommended_actions": interpretation.recommended_actions,
        },
    }
    canonical_lineage = _canonical_snapshot_lineage(snapshot)
    if canonical_lineage is not None:
        payload["canonical_chain"] = canonical_lineage["canonical_chain"]
        payload["canonical_ids"] = canonical_lineage["canonical_ids"]
    return payload


def _canonical_snapshot_lineage(snapshot: Snapshot) -> dict[str, Any] | None:
    """Build an additive canonical envelope for a framework snapshot.

    The framework snapshot remains a diagnostic/proxy artifact.  Its legacy
    fields are intentionally untouched, and the generated Claim is always
    ``WATCH``.  If the workspace canonical runtime is unavailable (for
    example, when the framework package is installed standalone), the legacy
    export continues to work without inventing a partial envelope.
    """
    try:
        from system_runtime.canonical_ids import (
            build_chain,
            build_claim,
            build_evidence,
            build_measurement,
            build_observation,
            lineage_ids,
        )
    except ImportError:
        return None

    provenance = dict(snapshot.state.provenance or {})
    observed_at = str(snapshot.run_date)
    if len(observed_at) == 10:
        observed_at = f"{observed_at}T00:00:00Z"
    source_id = str(
        provenance.get("source_id")
        or provenance.get("source_release_id")
        or "framework:structural_snapshot"
    )
    source_snapshot_sha256 = provenance.get("source_snapshot_sha256") or provenance.get("snapshot_sha256")
    availability = provenance.get("observation_status")
    if availability not in {
        "AVAILABLE",
        "STALE",
        "DELAYED",
        "MISSING",
        "NOT_APPLICABLE",
        "SOURCE_DOWN",
        "SCHEMA_CHANGED",
        "DISCONTINUED",
        "UNKNOWN",
    }:
        availability = "AVAILABLE" if all(
            bool(snapshot.proxy.available.get(channel, False)) for channel in ("M", "D", "K", "X")
        ) else "MISSING"

    values = {
        channel: _finite_snapshot_value(getattr(snapshot.proxy, channel, None))
        for channel in ("M", "D", "K", "X")
    }
    captured_at = str(provenance.get("generated_at") or provenance.get("captured_at") or observed_at)
    shared_provenance = {
        "captured_at": captured_at,
        "producer": "framework.output_exporter",
        "run_id": f"{snapshot.run_date}_{snapshot.run_type}",
        "source_release_id": provenance.get("source_release_id"),
        "claim_ceiling": "diagnostic_watch_only",
        "statement_kind": "diagnostic_snapshot",
        "promotion_allowed": False,
    }
    observation = build_observation(
        canonical_series_id="FRAMEWORK:STRUCTURAL_SNAPSHOT",
        observed_at=observed_at,
        vintage_at=observed_at,
        value=values,
        unit="bounded_proxy_vector",
        source_id=source_id,
        status=availability,
        source_snapshot_sha256=source_snapshot_sha256,
        provenance=shared_provenance,
    )
    measurement = build_measurement(
        observation_ids=[observation["observation_id"]],
        measurement_definition="framework_structural_snapshot",
        value=values,
        unit="bounded_proxy_vector",
        status=availability,
        derivation="PROXY_DERIVED",
        confidence=None,
        provenance={**shared_provenance, "method": "framework_proxy_snapshot"},
    )
    evidence = build_evidence(
        measurement_ids=[measurement["measurement_id"]],
        evidence_role="DERIVED",
        source_id=source_id,
        release_id=provenance.get("source_release_id"),
        source_snapshot_sha256=source_snapshot_sha256,
        status=availability,
        provenance=shared_provenance,
    )
    claim_status = "STALE" if availability == "STALE" else "INSUFFICIENT_DATA" if availability != "AVAILABLE" else "WATCH"
    claim = build_claim(
        claim_text="Framework structural snapshot is available for bounded diagnostic monitoring.",
        subject="framework_structural_snapshot",
        predicate="supports_diagnostic_monitoring",
        evidence_ids=[evidence["evidence_id"]],
        status=claim_status,
        confidence=None,
        provenance=shared_provenance,
    )
    chain = build_chain(observation=observation, measurement=measurement, evidence=evidence, claim=claim)
    return {"canonical_chain": chain, "canonical_ids": lineage_ids(chain)}


def _finite_snapshot_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def snapshot_core_to_dict(core: SnapshotCore) -> dict[str, Any]:
    z_vector = core.z_vector.tolist() if isinstance(core.z_vector, np.ndarray) else None
    return {
        "layer": "paper_aligned",
        "run_date": core.run_date,
        "run_type": core.run_type,
        "proxy": {
            "M": core.proxy.M,
            "D": core.proxy.D,
            "K": core.proxy.K,
            "X": core.proxy.X,
            "X_PRE": core.proxy.X_PRE,
            "X_REALIZED": core.proxy.X_REALIZED,
            "directions": dict(core.proxy.directions),
            "available": dict(core.proxy.available),
            "components": dict(core.proxy.components),
        },
        "state": {
            "sigma_t": core.sigma_t,
            "SigmaVector": _sigma_vector_payload(core.evidence),
            "singular_flag": core.singular_flag,
            "structural_singular_time": core.structural_singular_time,
            "leading_channel": core.leading_channel,
            "pattern": core.pattern,
            "z_vector": z_vector,
            "primitive_state": core.primitive_state.to_dict() if core.primitive_state is not None else None,
            "shadow_mass_state": core.shadow_mass_state.to_dict() if core.shadow_mass_state is not None else None,
            "mean_field_gap": core.mean_field_gap.to_dict() if core.mean_field_gap is not None else None,
            "structural_diagnostic_state": core.diagnostic_state.to_dict() if core.diagnostic_state is not None else None,
            "operator_diagnostics": dict(core.operator_diagnostics),
        },
        "evidence": dict(core.evidence),
        "escalation": core.escalation,
        "escalation_reason": core.escalation_reason,
    }


def snapshot_extension_to_dict(extension: SnapshotExtension) -> dict[str, Any]:
    return {
        "layer": extension.layer.value,
        "anomaly_score": extension.anomaly_score,
        "reflexivity_flags": dict(extension.reflexivity_flags),
        "narrative": (
            {
                "ai_unicorn": extension.narrative.ai_unicorn,
                "clo_cmbs": extension.narrative.clo_cmbs,
                "policy": extension.narrative.policy,
                "drift_scores": dict(extension.narrative.drift_scores),
            }
            if extension.narrative is not None
            else None
        ),
        "belief_state": extension.belief_state.to_dict() if extension.belief_state is not None else None,
        "coupling_diagnostics": dict(extension.coupling_diagnostics),
        "operator_advanced_diagnostics": dict(extension.operator_advanced_diagnostics),
        "feature_layers": dict(extension.feature_layers),
    }


def html_to_png(html_path: Path, image_width: int = 1400) -> Path | None:
    output_dir = html_path.parent
    candidate = output_dir / f"{html_path.name}.png"
    cmd = [
        "qlmanage",
        "-t",
        "-s",
        str(image_width),
        "-o",
        str(output_dir),
        str(html_path),
    ]
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    if candidate.exists():
        return candidate
    return None


def _render_html(payload: dict[str, Any]) -> str:
    title = f"Structural Snapshot - {payload['run_date']} ({payload['run_type']})"
    escalation = _human_bool(payload["escalation"])
    reason = payload["escalation_reason"] or "No escalation trigger recorded."
    proxy = payload["proxy"]
    state = payload["state"]
    narrative = payload["narrative"] or {}
    interpretation = payload.get("interpretation", {})
    operator_diag = state.get("operator_diagnostics", {}) or {}
    semantics = proxy.get("semantic_metadata", {}) or {}
    sigma_vector = state.get("SigmaVector", {}) or {}
    concept_registry = payload.get("concept_registry", {}) or {}
    pattern = interpretation.get("pattern") or state.get("pattern") or "-"
    severity = interpretation.get("severity", "-")
    summary = interpretation.get("summary", "No interpretation summary available.")
    operator_count = int(operator_diag.get("operator_count", 0) or 0)
    recommendations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in interpretation.get("recommended_actions", [])
    )
    if not recommendations:
        recommendations = "<li>Continue monitoring baseline structural conditions.</li>"

    proxy_rows = "".join(
        _render_proxy_row(
            channel=channel,
            value=proxy.get(channel),
            direction=proxy.get("directions", {}).get(channel, "UNKNOWN"),
            available=proxy.get("available", {}).get(channel),
        )
        for channel in ("M", "D", "K", "X")
    )
    semantic_rows = "".join(
        _render_semantic_row(channel, semantics.get(channel, {}))
        for channel in ("M", "D", "K", "X_PRE", "X_REALIZED", "Sigma")
    )
    concept_rows = "".join(
        _render_concept_row(concept, concept_registry.get(concept, {}))
        for concept in ("S", "A", "L", "V", "P", "tau")
    )
    run_rows = "".join(
        (
            f"<tr><th>Run date</th><td>{html.escape(str(payload['run_date']))}</td></tr>"
            f"<tr><th>Run type</th><td>{html.escape(str(payload['run_type']))}</td></tr>"
            f"<tr><th>Pattern</th><td>{html.escape(str(pattern))}</td></tr>"
            f"<tr><th>Severity</th><td>{html.escape(str(severity))}</td></tr>"
            f"<tr><th>Escalation</th><td>{html.escape(escalation)}</td></tr>"
            f"<tr><th>Escalation reason</th><td>{html.escape(str(reason))}</td></tr>"
        )
    )
    state_rows = "".join(
        (
            f"<tr><th>Structural pressure (sigma_t)</th><td>{_format_metric(state.get('sigma_t'))}</td></tr>"
            f"<tr><th>Sigma vector</th><td>{html.escape(_sigma_vector_summary(sigma_vector))}</td></tr>"
            f"<tr><th>Singular regime</th><td>{_human_bool(state.get('singular_flag'))}</td></tr>"
            f"<tr><th>Leading channel</th><td>{html.escape(str(state.get('leading_channel') or '-'))}</td></tr>"
            f"<tr><th>Pattern</th><td>{html.escape(str(state.get('pattern') or '-'))}</td></tr>"
            f"<tr><th>Anomaly score</th><td>{_format_metric(state.get('anomaly_score'))}</td></tr>"
        )
    )
    narrative_rows = "".join(
        _render_narrative_row(label, narrative.get(key, "-"), narrative.get("drift_scores", {}).get(key))
        for label, key in (
            ("AI Unicorn", "ai_unicorn"),
            ("CLO / CMBS", "clo_cmbs"),
            ("Policy", "policy"),
        )
    )
    operator_content = _render_operator_section(operator_diag, operator_count)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --ink: #111111;
      --muted: #555555;
      --line: #d8d8d8;
      --soft: #f6f6f6;
    }}
    body {{
      margin: 0;
      padding: 32px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
    }}
    .wrap {{
      max-width: 980px;
      margin: 0 auto;
    }}
    section {{
      margin: 24px 0;
    }}
    h1, h2 {{ margin: 0 0 12px 0; }}
    h1 {{
      font-size: 22px;
      font-weight: 650;
      border-bottom: 2px solid var(--ink);
      padding-bottom: 10px;
    }}
    h2 {{
      font-size: 16px;
      font-weight: 650;
      border-bottom: 1px solid var(--line);
      padding-bottom: 6px;
    }}
    p {{ line-height: 1.55; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
    }}
    th, td {{
      text-align: left;
      padding: 8px 6px;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
      vertical-align: top;
    }}
    th {{
      width: 220px;
      color: var(--muted);
      font-weight: 600;
      background: var(--soft);
    }}
    .matrix th {{
      width: auto;
    }}
    .summary {{
      font-size: 14px;
      line-height: 1.6;
      color: var(--ink);
      margin: 8px 0 0 0;
    }}
    .muted {{
      color: var(--muted);
    }}
    .drift {{
      color: var(--muted);
      font-size: 12px;
      margin-left: 8px;
    }}
    ol {{
      margin: 8px 0 0 18px;
      padding: 0;
    }}
    li {{
      margin: 8px 0;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section>
      <h1>{title}</h1>
      <table>{run_rows}</table>
    </section>

    <section>
      <h2>Proxy Channels</h2>
      <table class="matrix">
        <thead>
          <tr><th>Channel</th><th>Value</th><th>Direction</th><th>Available</th></tr>
        </thead>
        <tbody>{proxy_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Proxy Reduction Warnings</h2>
      <table class="matrix">
        <thead>
          <tr><th>Channel</th><th>Target concept</th><th>Distance</th><th>Status</th><th>Do not interpret as</th></tr>
        </thead>
        <tbody>{semantic_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Concept Implementation Registry</h2>
      <table class="matrix">
        <thead>
          <tr><th>Concept</th><th>Status</th><th>Warning</th></tr>
        </thead>
        <tbody>{concept_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>State</h2>
      <table>{state_rows}</table>
    </section>

    <section>
      <h2>Operator Layer</h2>
      {operator_content}
    </section>

    <section>
      <h2>Interpretation</h2>
      <p class="summary">{html.escape(str(summary))}</p>
      <h2 style="margin-top:18px;">Recommended Actions</h2>
      <ol>{recommendations}</ol>
    </section>

    <section>
      <h2>Narrative</h2>
      <table>{narrative_rows}</table>
    </section>
  </div>
</body>
</html>
"""


def _render_proxy_row(channel: str, value: Any, direction: str, available: Any) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(channel)}</td>"
        f"<td>{_format_metric(value)}</td>"
        f"<td>{html.escape(_direction_label(direction))}</td>"
        f"<td>{_human_bool(available)}</td>"
        "</tr>"
    )


def _render_semantic_row(channel: str, metadata: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(channel)}</td>"
        f"<td>{html.escape(str(metadata.get('target_concept') or '-'))}</td>"
        f"<td>{_format_metric(metadata.get('semantic_distance'), unavailable='-')}</td>"
        f"<td>{html.escape(str(metadata.get('proxy_status') or '-'))}</td>"
        f"<td>{html.escape(', '.join(str(item) for item in metadata.get('do_not_interpret_as', [])[:3]) or '-')}</td>"
        "</tr>"
    )


def _render_concept_row(concept: str, metadata: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(concept)}</td>"
        f"<td>{html.escape(str(metadata.get('status') or '-'))}</td>"
        f"<td>{html.escape(str(metadata.get('warning') or '-'))}</td>"
        "</tr>"
    )


def _render_operator_section(operator_diag: dict[str, Any], operator_count: int) -> str:
    if operator_count <= 0:
        return (
            '<p class="summary muted">No operator activity recorded for this run.</p>'
            '<table><tr><th>Operator count</th><td>0</td></tr></table>'
        )
    rows = "".join(
        [
            f"<tr><th>Operator count</th><td>{operator_count}</td></tr>",
            f"<tr><th>Sequence signature</th><td>{html.escape(str(operator_diag.get('sequence_signature') or 'Not available'))}</td></tr>",
            f"<tr><th>Compression ratio</th><td>{_format_metric(operator_diag.get('compression_ratio'), unavailable='Not available')}</td></tr>",
            f"<tr><th>Non-commutativity score</th><td>{_format_metric(operator_diag.get('non_commutativity_score'), unavailable='Not available')}</td></tr>",
            f"<tr><th>Singular proximity</th><td>{_format_metric(operator_diag.get('singular_proximity'), unavailable='Not available')}</td></tr>",
        ]
    )
    return f"<table>{rows}</table>"


def _render_narrative_row(label: str, value: Any, drift_score: Any) -> str:
    drift = ""
    if drift_score is not None:
        drift = f'<span class="drift">drift {_format_metric(drift_score)}</span>'
    return (
        f"<tr><th>{html.escape(label)}</th>"
        f"<td>{html.escape(str(value or '-'))}{drift}</td></tr>"
    )


def _format_metric(value: Any, unavailable: str = "Not available") -> str:
    if value is None:
        return unavailable
    try:
        number = float(value)
    except Exception:
        return html.escape(str(value))
    if not np.isfinite(number):
        return unavailable
    abs_number = abs(number)
    if abs_number == 0:
        return "0.000"
    if abs_number < 0.001:
        return "&lt;0.001"
    if abs_number < 0.01:
        return f"{number:.4f}"
    return f"{number:.3f}"


def _human_bool(value: Any) -> str:
    if value is None:
        return "Not available"
    return "Yes" if bool(value) else "No"


def _direction_label(direction: str) -> str:
    normalized = str(direction or "UNKNOWN").upper()
    if normalized == "WORSENING":
        return "Worsening"
    if normalized == "IMPROVING":
        return "Improving"
    if normalized == "STABLE":
        return "Stable"
    return "Unknown"


def _direction_tone(direction: str) -> str:
    normalized = str(direction or "UNKNOWN").upper()
    if normalized == "WORSENING":
        return "warn"
    if normalized == "IMPROVING":
        return "good"
    return "calm"


def _sigma_vector_from_snapshot(snapshot: Snapshot) -> dict[str, Any]:
    provenance = dict(snapshot.state.provenance or {})
    return _sigma_vector_payload(provenance)


def _sigma_vector_payload(container: dict[str, Any] | Mapping[str, Any]) -> dict[str, Any]:
    source = dict(container or {})
    if isinstance(source.get("provenance"), dict):
        source = dict(source["provenance"])
    detector = dict(source.get("singular_detector", {}) or {})
    vector = detector.get("sigma_vector")
    if isinstance(vector, dict):
        return vector
    return {
        "M": None,
        "D": None,
        "K": None,
        "X_PRE": None,
        "X_REALIZED": None,
        "operator_penalties": {},
        "dominant_channel": None,
        "cofire_count": 0,
        "reduction_warning": "SigmaVector unavailable for this snapshot; scalar sigma_t remains compatibility output.",
    }


def _sigma_vector_summary(vector: dict[str, Any]) -> str:
    if not vector:
        return "Unavailable"
    return (
        f"dominant={vector.get('dominant_channel') or '-'}, "
        f"cofire={vector.get('cofire_count', 0)}, "
        f"M={_plain_metric(vector.get('M'))}, D={_plain_metric(vector.get('D'))}, "
        f"K={_plain_metric(vector.get('K'))}, X_PRE={_plain_metric(vector.get('X_PRE'))}, "
        f"X_REALIZED={_plain_metric(vector.get('X_REALIZED'))}"
    )


def _plain_metric(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def _concept_registry_payload() -> dict[str, dict[str, Any]]:
    return cast(dict[str, dict[str, Any]], concept_registry_payload())
