"""Build change analysis — delta, trend, anomaly layer.

Reads historical judgment, caselab, and framework outputs to compute:
- Daily deltas for sigma vector (M, D, K, X)
- N-day trend (direction, magnitude)
- Anomaly flags (values outside recent norms)
- Judgment/decision state changes
- CaseLab score progression
- Gate status transitions
- Claim ladder progression

Outputs:
    Output/current/change_analysis.json
    Output/current/change_analysis.md
"""
from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from _workspace_imports import add_scripts

add_scripts()

from _runtime_io import ROOT, current_dir, load_json  # noqa: E402

JUDGMENT_DIR = ROOT / "Output" / "judgment"
CASELAB_DIR = ROOT / "Output" / "caselab"
CURRENT_DIR = current_dir()
LOOKBACK_DAYS = 7


def _collect_daily_files(directory: Path, prefix: str = "", suffix: str = ".json") -> list[tuple[str, dict]]:
    """Collect dated files sorted by date."""
    files = []
    for f in sorted(directory.glob(f"*{suffix}")):
        # Extract date from filename (YYYY-MM-DD pattern)
        name = f.stem
        if len(name) >= 10 and name[:4].isdigit() and name[4] == "-":
            date_str = name[:10]
            data = load_json(f)
            if data is not None:
                files.append((date_str, data))
    return files[-LOOKBACK_DAYS:]


def _extract_sigma_vector(fw: dict) -> dict[str, float]:
    """Extract sigma vector from framework_output."""
    sv = fw.get("advanced", {}).get("sigma_vector", {})
    return {
        "M": sv.get("M"),
        "D": sv.get("D"),
        "K": sv.get("K"),
        "X_agg": sv.get("X_agg"),
    }


def _compute_deltas(history: list[tuple[str, dict[str, float | None]]]) -> list[dict]:
    """Compute daily deltas from a time series."""
    deltas = []
    for i in range(1, len(history)):
        date_prev, vals_prev = history[i - 1]
        date_curr, vals_curr = history[i]
        delta = {"date": date_curr, "prev_date": date_prev}
        for key in vals_curr:
            v_prev = vals_prev.get(key)
            v_curr = vals_curr.get(key)
            if v_prev is not None and v_curr is not None:
                delta[key] = {
                    "value": round(v_curr, 4),
                    "prev": round(v_prev, 4),
                    "delta": round(v_curr - v_prev, 4),
                    "delta_pct": round((v_curr - v_prev) / abs(v_prev) * 100, 2) if abs(v_prev) > 1e-10 else None,
                }
            else:
                delta[key] = {"value": v_curr, "prev": v_prev, "delta": None, "delta_pct": None}
        deltas.append(delta)
    return deltas


def _compute_trend(history: list[tuple[str, dict[str, float | None]]], key: str) -> dict:
    """Compute trend direction and magnitude for a single key."""
    values = [(date, vals.get(key)) for date, vals in history if vals.get(key) is not None]
    if len(values) < 2:
        return {"direction": "insufficient_data", "values": len(values)}

    numeric = [v for _, v in values]
    first, last = numeric[0], numeric[-1]
    change = last - first

    # Simple linear trend
    if len(numeric) >= 3:
        # Slope via least squares
        n = len(numeric)
        x_mean = (n - 1) / 2
        y_mean = sum(numeric) / n
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(numeric))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den > 0 else 0
    else:
        slope = change / (len(numeric) - 1)

    # Direction classification
    if abs(change) < 0.05:
        direction = "flat"
    elif change > 0:
        direction = "rising"
    else:
        direction = "falling"

    # Volatility (std dev of daily changes)
    daily_changes = [numeric[i] - numeric[i - 1] for i in range(1, len(numeric))]
    volatility = statistics.stdev(daily_changes) if len(daily_changes) >= 2 else 0

    return {
        "direction": direction,
        "slope": round(slope, 4),
        "total_change": round(change, 4),
        "volatility": round(volatility, 4),
        "values_count": len(values),
        "latest": round(last, 4),
        "earliest": round(first, 4),
        "min": round(min(numeric), 4),
        "max": round(max(numeric), 4),
    }


def _detect_anomalies(history: list[tuple[str, dict[str, float | None]]], key: str) -> dict:
    """Detect if latest value is anomalous (>2σ from recent mean)."""
    values = [vals.get(key) for _, vals in history if vals.get(key) is not None]
    if len(values) < 3:
        return {"anomaly": False, "reason": "insufficient_data"}

    mean = statistics.mean(values[:-1])  # Exclude latest
    std = statistics.stdev(values[:-1]) if len(values[:-1]) >= 2 else 0
    latest = values[-1]

    if std < 1e-10:
        return {"anomaly": False, "reason": "no_variation", "mean": round(mean, 4)}

    z_score = (latest - mean) / std
    is_anomaly = abs(z_score) > 2.0

    return {
        "anomaly": is_anomaly,
        "z_score": round(z_score, 2),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "latest": round(latest, 4),
        "threshold_2sigma": round(mean + 2 * std, 4),
    }


def _analyze_judgment_changes(judgments: list[tuple[str, dict]]) -> list[dict]:
    """Track judgment state changes across days."""
    changes = []
    for i in range(1, len(judgments)):
        date_prev, j_prev = judgments[i - 1]
        date_curr, j_curr = judgments[i]

        change = {"date": date_curr, "prev_date": date_prev, "fields_changed": []}

        # Decision
        d_prev = j_prev.get("decision")
        d_curr = j_curr.get("decision")
        if d_prev != d_curr:
            change["fields_changed"].append({
                "field": "decision",
                "prev": d_prev,
                "curr": d_curr,
                "significance": "high",
            })

        # Confidence
        c_prev = j_prev.get("confidence", {}).get("level")
        c_curr = j_curr.get("confidence", {}).get("level")
        if c_prev != c_curr:
            change["fields_changed"].append({
                "field": "confidence",
                "prev": c_prev,
                "curr": c_curr,
                "significance": "high",
            })

        # Claim ceiling
        cc_prev = j_prev.get("claim_ceiling")
        cc_curr = j_curr.get("claim_ceiling")
        if cc_prev != cc_curr:
            change["fields_changed"].append({
                "field": "claim_ceiling",
                "prev": cc_prev,
                "curr": cc_curr,
                "significance": "medium",
            })

        # Claim tier
        t_prev = j_prev.get("claim_ladder", {}).get("tier")
        t_curr = j_curr.get("claim_ladder", {}).get("tier")
        if t_prev != t_curr:
            change["fields_changed"].append({
                "field": "claim_tier",
                "prev": t_prev,
                "curr": t_curr,
                "significance": "high",
            })

        # Gate status
        for gate in ["hmm_stability", "quality_validation", "k_measurement", "x_measurement"]:
            g_prev = j_prev.get("gate_status", {}).get(gate)
            g_curr = j_curr.get("gate_status", {}).get(gate)
            if g_prev != g_curr:
                change["fields_changed"].append({
                    "field": f"gate.{gate}",
                    "prev": g_prev,
                    "curr": g_curr,
                    "significance": "medium",
                })

        change["total_changed"] = len(change["fields_changed"])
        change["has_high_significance"] = any(
            f["significance"] == "high" for f in change["fields_changed"]
        )
        changes.append(change)

    return changes


def _analyze_caselab_progression(caselabs: list[tuple[str, dict]]) -> list[dict]:
    """Track CaseLab score and mechanism progression."""
    progression = []
    for date, data in caselabs:
        mq = data.get("match_quality", {})
        mc = data.get("mechanism_context", {})
        progression.append({
            "date": date,
            "top_score": mq.get("top_score"),
            "label": mq.get("label"),
            "mechanisms": mc.get("mechanism_types", []),
            "mechanism_count": len(mc.get("mechanism_types", [])),
            "gap_to_usable": mq.get("gap_to_usable"),
        })
    return progression


def build_change_analysis() -> dict:
    """Build the full change analysis."""
    now = datetime.now(UTC)

    # Collect historical data
    judgments = _collect_daily_files(JUDGMENT_DIR)
    caselabs = _collect_daily_files(CASELAB_DIR)

    # Current framework output
    fw_path = CURRENT_DIR / "framework_output.json"
    fw = load_json(fw_path)
    current_sigma = _extract_sigma_vector(fw) if fw else {}

    # Build sigma vector history from judgment claim statements
    # (extract M/D values from meaning or claim_ladder)
    sigma_history = []
    for date, j in judgments:
        meaning_lines = j.get("meaning", [])
        claim = j.get("claim_ladder", {}).get("claim_statement", "")

        # Extract M and D from meaning lines
        m_val, d_val = None, None
        for line in meaning_lines + [claim]:
            if "M=" in line:
                try:
                    m_str = line.split("M=")[1].split(" and")[0].split(";")[0].split(",")[0]
                    m_val = float(m_str)
                except (ValueError, IndexError):
                    pass
            if "D=" in line:
                try:
                    d_str = line.split("D=")[1].split(";")[0].split(",")[0]
                    d_val = float(d_str)
                except (ValueError, IndexError):
                    pass

        sigma_history.append((date, {"M": m_val, "D": d_val}))

    # Add current values from framework_output
    if current_sigma and fw:
        today = now.strftime("%Y-%m-%d")
        if not sigma_history or sigma_history[-1][0] != today:
            sigma_history.append((today, current_sigma))

    # Compute deltas and trends
    deltas = _compute_deltas(sigma_history) if len(sigma_history) >= 2 else []
    trends = {}
    anomalies = {}
    for key in ["M", "D"]:
        trends[key] = _compute_trend(sigma_history, key)
        anomalies[key] = _detect_anomalies(sigma_history, key)

    # Judgment changes
    judgment_changes = _analyze_judgment_changes(judgments) if len(judgments) >= 2 else []

    # CaseLab progression
    caselab_progression = _analyze_caselab_progression(caselabs)

    # Current state summary
    latest_judgment = judgments[-1][1] if judgments else {}
    latest_caselab = caselabs[-1][1] if caselabs else {}

    current_state = {
        "decision": latest_judgment.get("decision"),
        "confidence": latest_judgment.get("confidence", {}).get("level"),
        "claim_ceiling": latest_judgment.get("claim_ceiling"),
        "claim_tier": latest_judgment.get("claim_ladder", {}).get("tier"),
        "caselab_score": latest_caselab.get("match_quality", {}).get("top_score"),
        "caselab_label": latest_caselab.get("match_quality", {}).get("label"),
        "sigma_vector": current_sigma,
    }

    # Gate transitions
    gate_history = []
    for date, j in judgments:
        gate_history.append((date, j.get("gate_status", {})))

    # Summary statistics
    total_changes_7d = sum(c["total_changed"] for c in judgment_changes)
    high_sig_changes = sum(1 for c in judgment_changes if c["has_high_significance"])

    analysis = {
        "schema_version": "change_analysis.v1",
        "generated_at": now.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "data_points": {
            "judgment_days": len(judgments),
            "caselab_days": len(caselabs),
            "sigma_history_days": len(sigma_history),
        },
        "current_state": current_state,
        "sigma_vector": {
            "current": current_sigma,
            "deltas": deltas,
            "trends": trends,
            "anomalies": anomalies,
        },
        "judgment_changes": judgment_changes,
        "caselab_progression": caselab_progression,
        "summary": {
            "total_field_changes_7d": total_changes_7d,
            "high_significance_changes_7d": high_sig_changes,
            "sigma_trend_M": trends.get("M", {}).get("direction", "unknown"),
            "sigma_trend_D": trends.get("D", {}).get("direction", "unknown"),
            "caselab_score_trend": (
                "improving"
                if len(caselab_progression) >= 2
                and caselab_progression[-1]["top_score"]
                and caselab_progression[-2]["top_score"]
                and caselab_progression[-1]["top_score"] > caselab_progression[-2]["top_score"]
                else "stable"
            ),
            "anomaly_flags": [
                k for k, v in anomalies.items() if v.get("anomaly")
            ],
        },
    }

    return analysis


def _build_markdown(analysis: dict) -> str:
    """Generate human-readable change analysis report."""
    lines = [
        "# Change Analysis",
        "",
        f"**Generated:** {analysis['generated_at']}",
        f"**Lookback:** {analysis['lookback_days']} days",
        f"**Data points:** {analysis['data_points']['judgment_days']} judgment days, "
        f"{analysis['data_points']['caselab_days']} caselab days",
        "",
    ]

    # Current state
    cs = analysis["current_state"]
    lines += [
        "## Current State",
        "",
        f"- **Decision:** {cs.get('decision', 'N/A')}",
        f"- **Confidence:** {cs.get('confidence', 'N/A')}",
        f"- **Claim tier:** {cs.get('claim_tier', 'N/A')} ({cs.get('claim_ceiling', 'N/A')})",
        f"- **CaseLab score:** {cs.get('caselab_score', 'N/A')} ({cs.get('caselab_label', 'N/A')})",
        "",
    ]

    # Sigma vector
    sv = analysis["sigma_vector"]
    lines += ["## Sigma Vector", ""]
    lines.append("| Channel | Current | Trend | Slope | 7d Change | Anomaly |")
    lines.append("|---------|---------|-------|-------|-----------|---------|")
    for ch in ["M", "D"]:
        trend = sv["trends"].get(ch, {})
        anomaly = sv["anomalies"].get(ch, {})
        current = sv["current"].get(ch, "N/A")
        direction = trend.get("direction", "?")
        slope = trend.get("slope", "?")
        total = trend.get("total_change", "?")
        is_anomaly = "⚠️ YES" if anomaly.get("anomaly") else "—"
        lines.append(
            f"| {ch} | {current} | {direction} | {slope} | {total} | {is_anomaly} |"
        )
    lines.append("")

    # Deltas
    if sv["deltas"]:
        lines += ["## Daily Deltas (M/D)", ""]
        lines.append("| Date | M | ΔM | D | ΔD |")
        lines.append("|------|---|----|---|----|")
        for d in sv["deltas"][-5:]:  # Last 5 days
            m = d.get("M", {})
            dd = d.get("D", {})
            lines.append(
                f"| {d['date']} "
                f"| {m.get('value', '?')} | {m.get('delta', '?')} "
                f"| {dd.get('value', '?')} | {dd.get('delta', '?')} |"
            )
        lines.append("")

    # Judgment changes
    if analysis["judgment_changes"]:
        lines += ["## Judgment State Changes", ""]
        for jc in analysis["judgment_changes"]:
            if jc["total_changed"] == 0:
                lines.append(f"- **{jc['date']}:** No changes from {jc['prev_date']}")
            else:
                lines.append(f"- **{jc['date']}:** {jc['total_changed']} field(s) changed from {jc['prev_date']}")
                for fc in jc["fields_changed"]:
                    sig = "🔴" if fc["significance"] == "high" else "🟡"
                    lines.append(f"  - {sig} {fc['field']}: {fc['prev']} → {fc['curr']}")
        lines.append("")

    # CaseLab progression
    if analysis["caselab_progression"]:
        lines += ["## CaseLab Score Progression", ""]
        lines.append("| Date | Score | Label | Mechanisms |")
        lines.append("|------|-------|-------|------------|")
        for cp in analysis["caselab_progression"]:
            score = cp.get("top_score", "?")
            label = cp.get("label", "?")
            mechs = ", ".join(cp.get("mechanisms", [])) or "—"
            lines.append(f"| {cp['date']} | {score} | {label} | {mechs} |")
        lines.append("")

    # Summary
    s = analysis["summary"]
    lines += [
        "## 7-Day Summary",
        "",
        f"- **Total field changes:** {s['total_field_changes_7d']}",
        f"- **High significance changes:** {s['high_significance_changes_7d']}",
        f"- **M trend:** {s['sigma_trend_M']}",
        f"- **D trend:** {s['sigma_trend_D']}",
        f"- **CaseLab trend:** {s['caselab_score_trend']}",
    ]
    if s["anomaly_flags"]:
        lines.append(f"- **⚠️ Anomalies detected:** {', '.join(s['anomaly_flags'])}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    analysis = build_change_analysis()

    # Write JSON
    json_path = CURRENT_DIR / "change_analysis.json"
    json_path.write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Write Markdown
    md_path = CURRENT_DIR / "change_analysis.md"
    md_path.write_text(_build_markdown(analysis), encoding="utf-8")

    print("Change analysis written:")
    print(f"  {json_path}")
    print(f"  {md_path}")

    # Summary
    s = analysis["summary"]
    print("\nSummary:")
    print(f"  M trend: {s['sigma_trend_M']}, D trend: {s['sigma_trend_D']}")
    print(f"  Changes (7d): {s['total_field_changes_7d']} total, {s['high_significance_changes_7d']} high-sig")
    if s["anomaly_flags"]:
        print(f"  ⚠️ Anomalies: {', '.join(s['anomaly_flags'])}")


if __name__ == "__main__":
    main()
