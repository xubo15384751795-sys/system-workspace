"""Run Feedback Replay v2 — High-Fidelity Historical Replay.

Uses canonical pipeline data instead of raw-price proxies:
- M/D/K/X from Data/ml/channel_series.csv (real pipeline output, 2000-2026)
- sigma_t / pattern / escalation from Data/structural_state.parquet
- CaseLab match scores from Data/structural_lab/nlp/case_library/
- HMM regime derived from sigma_t thresholds
- Claim ladder + promotion gate logic matching real pipeline

This produces judgment cards much closer to what the daily pipeline would
have generated on each historical date.

Output: Output/feedback_samples/replay_runs_v2/{sample_id}.json

Usage:
    python3 scripts/run_feedback_replay_v2.py
    python3 scripts/run_feedback_replay_v2.py --limit 50
    python3 scripts/run_feedback_replay_v2.py --compare-v1
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from _workspace_imports import add_scripts
add_scripts()
from _constants import CASELAB_USABLE_THRESHOLD  # noqa: E402
from _runtime_io import ROOT, ensure_dir, load_json, load_jsonl, utc_now, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MANIFEST_PATH = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"
CHANNEL_SERIES_PATH = ROOT / "Data" / "ml" / "channel_series.csv"
STRUCTURAL_STATE_PATH = ROOT / "Data" / "structural_lab" / "processed" / "state" / "structural_state.parquet"
CASE_LIBRARY_DIR = ROOT / "Data" / "structural_lab" / "nlp" / "case_library"
REPLAY_V1_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
REPLAY_V2_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs_v2"
FIDELITY_REPORT_PATH = ROOT / "Output" / "feedback_samples" / "replay_fidelity_report.md"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_channel_series() -> pd.DataFrame:
    """Load canonical M/D/K/X channel series from pipeline output."""
    df = pd.read_csv(CHANNEL_SERIES_PATH, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    return df


def _load_structural_state() -> pd.DataFrame:
    """Load structural state (sigma_t, pattern, escalation)."""
    df = pd.read_parquet(STRUCTURAL_STATE_PATH)
    if "run_date" in df.columns:
        df["run_date"] = pd.to_datetime(df["run_date"])
        df = df.set_index("run_date").sort_index()
    return df


def _load_case_library() -> list[dict]:
    """Load all CaseLab cases with their variable vectors."""
    cases = []
    for fpath in sorted(CASE_LIBRARY_DIR.glob("*.json")):
        case = load_json(fpath)
        if case:
            case["_file"] = fpath.stem
            cases.append(case)
    return cases


# ---------------------------------------------------------------------------
# CaseLab matching
# ---------------------------------------------------------------------------

def _compute_caselab_match(
    m_val: float | None,
    d_val: float | None,
    k_val: float | None,
    x_val: float | None,
    cases: list[dict],
) -> dict:
    """Compute CaseLab match scores against the case library.

    Uses cosine similarity between current (M,D,K,X) and case variable_vectors.
    The variable_vectors in cases represent ideal pattern strength (0-1).
    We normalize current values to [0,1] range for comparison.
    """
    if m_val is None and d_val is None:
        return {"top_score": None, "top_case": None, "matches": [], "status": "insufficient_data"}

    # Normalize current values to [0,1] using sigmoid-like mapping
    def _norm(v):
        if v is None:
            return 0.5  # neutral
        # Map from roughly [-4, 4] to [0, 1]
        return 1.0 / (1.0 + math.exp(-v))

    current = [_norm(m_val), _norm(d_val), _norm(k_val), _norm(x_val)]

    matches = []
    for case in cases:
        vv = case.get("variable_vector", {})
        case_vec = [vv.get("M", 0.5), vv.get("D", 0.5), vv.get("K", 0.5), vv.get("X", 0.5)]

        # Cosine similarity
        dot = sum(a * b for a, b in zip(current, case_vec))
        norm_a = math.sqrt(sum(a * a for a in current))
        norm_b = math.sqrt(sum(b * b for b in case_vec))
        if norm_a > 0 and norm_b > 0:
            score = dot / (norm_a * norm_b)
        else:
            score = 0.0

        matches.append({
            "case_id": case.get("_file", case.get("case_name", "unknown")),
            "case_name": case.get("case_name", ""),
            "score": round(score, 4),
            "vintage": case.get("vintage", ""),
        })

    matches.sort(key=lambda x: -x["score"])
    top = matches[0] if matches else None

    return {
        "top_score": top["score"] if top else None,
        "top_case": top["case_id"] if top else None,
        "top_case_name": top["case_name"] if top else None,
        "matches": matches[:5],
        "status": "computed",
    }


# ---------------------------------------------------------------------------
# HMM regime derivation
# ---------------------------------------------------------------------------

def _derive_hmm_regime(sigma_t: float | None, pattern: str | None) -> dict:
    """Derive HMM-like regime from sigma_t thresholds.

    Mirrors the real pipeline's 3-state HMM:
    - compression: sigma_t < 0.3
    - volatile: 0.3 <= sigma_t < 0.7
    - crisis: sigma_t >= 0.7
    """
    if sigma_t is None:
        return {
            "current": "unknown",
            "probability": None,
            "stability": "UNKNOWN",
            "state_probs": {},
        }

    if sigma_t < 0.3:
        regime = "compression"
        prob = 1.0 - sigma_t / 0.3 * 0.3  # high confidence
    elif sigma_t < 0.7:
        regime = "volatile"
        prob = 0.5 + (sigma_t - 0.3) / 0.4 * 0.3
    else:
        regime = "crisis"
        prob = 0.6 + min((sigma_t - 0.7) / 0.3, 1.0) * 0.3

    # Stability assessment
    if sigma_t < 0.4:
        stability = "STRONG"
    elif sigma_t < 0.6:
        stability = "ADEQUATE"
    elif sigma_t < 0.8:
        stability = "WEAK"
    else:
        stability = "CRITICAL"

    return {
        "current": regime,
        "probability": round(prob, 4),
        "stability": stability,
        "sigma_t": round(sigma_t, 4),
        "state_probs": {
            "compression": round(max(0, 1 - sigma_t), 4),
            "volatile": round(max(0, 1 - abs(sigma_t - 0.5) * 2), 4),
            "crisis": round(max(0, sigma_t - 0.3), 4),
        },
    }


# ---------------------------------------------------------------------------
# Claim ladder + promotion gate
# ---------------------------------------------------------------------------

def _evaluate_claim_ladder(
    m_val: float | None,
    d_val: float | None,
    k_val: float | None,
    x_val: float | None,
    hmm: dict,
    caselab: dict,
    pattern: str | None,
    escalation: bool | None,
) -> dict:
    """Evaluate claim ladder tier and promotion gate.

    Tier 0: observation — raw measurement only
    Tier 1: mechanism_hypothesis — structural similarity detected
    Tier 2: watch_condition — persistence + mechanism support
    Tier 3: operational — actionable (currently disabled by governance)
    """
    # Determine stress direction
    stress_signals = []
    relief_signals = []

    if m_val is not None:
        if m_val < -1.0:
            stress_signals.append("m_deep_stress")
        elif m_val < -0.5:
            stress_signals.append("m_stress")
        elif m_val > 0.5:
            relief_signals.append("m_relief")

    if d_val is not None:
        if d_val < -0.5:
            stress_signals.append("d_negative")
        elif d_val > 0.5:
            relief_signals.append("d_positive")

    if k_val is not None:
        if k_val > 0.5:
            stress_signals.append("k_curve_stress")
        elif k_val < -0.5:
            relief_signals.append("k_curve_relief")

    if x_val is not None:
        if x_val > 0.7:
            stress_signals.append("x_contagion")

    # CaseLab quality
    cl_score = caselab.get("top_score") or 0
    cl_case = caselab.get("top_case", "")

    # HMM regime
    hmm_regime = hmm.get("current", "unknown")
    hmm_stability = hmm.get("stability", "UNKNOWN")

    # Determine tier
    tier = 0
    label = "observation"
    claim_statement = ""
    promotion_conditions = {}

    if stress_signals and cl_score > 0.5:
        # Strong structural similarity + stress signals
        tier = 2
        label = "watch_condition"
        claim_statement = (
            f"Structural similarity to {cl_case} (score: {cl_score:.3f}). "
            f"M={m_val}, D={d_val}; stress signals: {', '.join(stress_signals)}. "
            f"HMM regime: {hmm_regime}."
        )
        promotion_conditions = {
            "to_tier_3": "Requires operational gate pass (currently disabled by governance freeze)",
        }
    elif stress_signals or (cl_score > 0.45):
        # Some stress signal or moderate CaseLab match
        tier = 1
        label = "mechanism_hypothesis"
        if cl_score > 0.45:
            claim_statement = (
                f"Structural similarity to {cl_case} (score: {cl_score:.3f}). "
                f"M={m_val}, D={d_val}; direction: {'stress' if stress_signals else 'mixed'}. "
                f"This is a mechanism hypothesis, not a directional forecast."
            )
        else:
            claim_statement = (
                f"Cross-asset stress indicators: {', '.join(stress_signals)}. "
                f"M={m_val}, D={d_val}. This is a mechanism hypothesis."
            )
        promotion_conditions = {
            "to_tier_2": f"CaseLab score > 0.5 (currently {cl_score:.3f}) and stress signals persist",
        }
    else:
        tier = 0
        label = "observation"
        claim_statement = f"No strong structural signal. M={m_val}, D={d_val}, K={k_val}, X={x_val}."

    # Decision
    if tier >= 2:
        decision = "WATCH"
        confidence = "medium" if hmm_stability in ("STRONG", "ADEQUATE") else "low"
    elif tier >= 1:
        decision = "RESEARCH_REVIEW"
        confidence = "low"
    else:
        decision = "NO_TRADE"
        confidence = "low"

    # Evidence grade
    channels_available = sum(1 for v in [m_val, d_val, k_val, x_val] if v is not None)
    if channels_available >= 4 and hmm_stability in ("STRONG", "ADEQUATE"):
        evidence_grade = "B"
    elif channels_available >= 3:
        evidence_grade = "C"
    else:
        evidence_grade = "D"

    # Watch conditions
    watch_conditions = []
    if tier >= 1:
        if cl_score > 0.45:
            gap = CASELAB_USABLE_THRESHOLD - cl_score
            watch_conditions.append(
                f"If CaseLab top_score rises above {CASELAB_USABLE_THRESHOLD} (currently {cl_score:.3f}, gap: {gap:.3f}), "
                f"the mechanism analogy becomes usable."
            )
        if m_val is not None and m_val < -0.5:
            watch_conditions.append(
                f"If M deepens below {m_val - 0.5:.2f}, escalate monitoring."
            )
        if hmm_regime == "volatile":
            watch_conditions.append("HMM regime is volatile — monitor for transition to crisis or compression.")

    # Invalidation conditions
    invalidation = []
    if m_val is not None:
        invalidation.append(f"If M reverses sign (currently {m_val:.2f}), the stress hypothesis is invalidated.")
    if k_val is not None and abs(k_val) > 0.3:
        invalidation.append(f"If K curvature normalizes (currently {k_val:.2f}), curve stress resolved.")
    if escalation:
        invalidation.append("Structural escalation flag is active — heightened monitoring required.")

    # Promotion blockers
    blocked_gates = []
    if confidence == "low":
        blocked_gates.append("Confidence is low")
    if label == "observation":
        blocked_gates.append("Claim ceiling is observation — no mechanism hypothesis")
    if hmm_stability == "WEAK":
        blocked_gates.append("HMM stability is WEAK")
    if cl_score < 0.45:
        blocked_gates.append(f"CaseLab match quality below threshold ({cl_score:.3f} < 0.45)")

    promotion_gate_status = "WATCH" if tier >= 2 else ("RESEARCH_REVIEW" if tier >= 1 else "BLOCKED")

    return {
        "decision": decision,
        "confidence": confidence,
        "claim_tier": tier,
        "claim_label": label,
        "claim_statement": claim_statement,
        "mechanism_hypothesis": claim_statement,
        "evidence_grade": evidence_grade,
        "watch_conditions": watch_conditions,
        "invalidation_conditions": invalidation,
        "promotion_conditions": promotion_conditions,
        "promotion_gate_status": promotion_gate_status,
        "blocked_gates": blocked_gates,
        "confidence_reasons": [
            f"{channels_available}/4 proxy channels available",
            f"HMM stability: {hmm_stability}",
            f"CaseLab top score: {cl_score:.3f}",
        ],
        "allowed_language": [
            "measurement", "reading", "observation", "diagnostic",
            "mechanism", "resembles", "structural similarity",
            "historical pattern", "analogy",
        ],
        "forbidden_language": [
            "prediction", "forecast", "signal", "regime call",
            "directional conviction", "position",
        ],
    }


# ---------------------------------------------------------------------------
# Single sample replay v2
# ---------------------------------------------------------------------------

def replay_sample_v2(
    sample: dict,
    channel_series: pd.DataFrame,
    structural_state: pd.DataFrame,
    cases: list[dict],
) -> dict:
    """Run high-fidelity replay for a single sample."""
    as_of = pd.Timestamp(sample["as_of_date"])

    # 1. Get canonical M/D/K/X from channel_series
    cs_row = channel_series.loc[:as_of].tail(1)
    if cs_row.empty:
        m_val = d_val = k_val = x_val = None
    else:
        row = cs_row.iloc[0]
        m_val = _safe_float(row.get("M"))
        d_val = _safe_float(row.get("D"))
        k_val = _safe_float(row.get("K"))
        x_val = _safe_float(row.get("X_agg"))

    # 2. Get structural state
    ss_row = structural_state.loc[:as_of].tail(1) if not structural_state.empty else pd.DataFrame()
    if ss_row.empty:
        sigma_t = None
        pattern = None
        escalation = None
        leading_channel = None
    else:
        row = ss_row.iloc[0]
        sigma_t = _safe_float(row.get("sigma_t"))
        pattern = row.get("pattern")
        escalation = bool(row.get("escalation", False)) if pd.notna(row.get("escalation")) else False
        leading_channel = row.get("leading_channel")

    # 3. CaseLab match
    caselab = _compute_caselab_match(m_val, d_val, k_val, x_val, cases)

    # 4. HMM regime
    hmm = _derive_hmm_regime(sigma_t, pattern)

    # 5. Claim ladder + promotion gate
    judgment = _evaluate_claim_ladder(
        m_val, d_val, k_val, x_val,
        hmm, caselab, pattern, escalation,
    )

    # Build result
    result = {
        "schema_version": "feedback_sample.v2",
        "sample_id": sample["sample_id"],
        "as_of_date": sample["as_of_date"],
        "sample_type": sample["sample_type"],
        "why_selected": sample.get("why_selected", ""),
        "generated_at": utc_now().isoformat(),
        "allowed_lookback": sample.get("allowed_lookback", ""),
        "replay_version": "v2",
        "system_state": {
            "m_value": m_val,
            "d_value": d_val,
            "k_value": k_val,
            "x_value": x_val,
            "sigma_t": sigma_t,
            "pattern": pattern,
            "leading_channel": leading_channel,
            "escalation": escalation,
            "hmm": hmm,
            "caselab": caselab,
        },
        "system_judgment": judgment,
        "conditions": {
            "watch_conditions": judgment.get("watch_conditions", []),
            "invalidation_conditions": judgment.get("invalidation_conditions", []),
        },
        "forward_outcome": sample.get("forward_outcome", {}),
        "review_label": sample.get("review_label", "needs_review"),
    }

    return result


def _safe_float(v) -> float | None:
    """Safely convert to float, returning None for NaN/None."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Comparison: v1 vs v2
# ---------------------------------------------------------------------------

def compare_v1_v2(sample_id: str) -> dict | None:
    """Compare v1 and v2 replay outputs for a single sample."""
    v1_path = REPLAY_V1_DIR / f"{sample_id}.json"
    v2_path = REPLAY_V2_DIR / f"{sample_id}.json"

    v1 = load_json(v1_path)
    v2 = load_json(v2_path)

    if not v1 or not v2:
        return None

    j1 = v1.get("system_judgment", {})
    j2 = v2.get("system_judgment", {})
    s1 = v1.get("system_state", {})
    s2 = v2.get("system_state", {})

    # Decision changed?
    decision_changed = j1.get("decision") != j2.get("decision")
    tier_changed = j1.get("claim_tier") != j2.get("claim_tier")
    confidence_changed = j1.get("confidence") != j2.get("confidence")

    return {
        "sample_id": sample_id,
        "as_of_date": v1.get("as_of_date"),
        "sample_type": v1.get("sample_type"),
        "decision_changed": decision_changed,
        "tier_changed": tier_changed,
        "confidence_changed": confidence_changed,
        "v1_decision": j1.get("decision"),
        "v2_decision": j2.get("decision"),
        "v1_tier": j1.get("claim_tier"),
        "v2_tier": j2.get("claim_tier"),
        "v1_confidence": j1.get("confidence"),
        "v2_confidence": j2.get("confidence"),
        "v1_m": s1.get("m_value"),
        "v2_m": s2.get("m_value"),
        "v2_caselab_score": s2.get("caselab", {}).get("top_score"),
        "v2_hmm_regime": s2.get("hmm", {}).get("current"),
        "v2_sigma_t": s2.get("sigma_t"),
    }


def generate_fidelity_report(comparisons: list[dict]) -> str:
    """Generate replay_fidelity_report.md."""
    total = len(comparisons)
    decision_changes = [c for c in comparisons if c["decision_changed"]]
    tier_changes = [c for c in comparisons if c["tier_changed"]]
    confidence_changes = [c for c in comparisons if c["confidence_changed"]]

    # Decision change breakdown
    dec_change_breakdown = {}
    for c in decision_changes:
        key = f"{c['v1_decision']} → {c['v2_decision']}"
        dec_change_breakdown[key] = dec_change_breakdown.get(key, 0) + 1

    # Tier change breakdown
    tier_change_breakdown = {}
    for c in tier_changes:
        key = f"Tier {c['v1_tier']} → Tier {c['v2_tier']}"
        tier_change_breakdown[key] = tier_change_breakdown.get(key, 0) + 1

    lines = [
        "# Replay Fidelity Report: v1 vs v2",
        "",
        f"**Generated:** {utc_now().isoformat()}",
        f"**Total samples compared:** {total}",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Count | Pct |",
        f"|--------|------:|----:|",
        f"| Decision changed | {len(decision_changes)} | {len(decision_changes)/total:.1%} |",
        f"| Tier changed | {len(tier_changes)} | {len(tier_changes)/total:.1%} |",
        f"| Confidence changed | {len(confidence_changes)} | {len(confidence_changes)/total:.1%} |",
        "",
        "## Decision Changes",
        "",
        "| Transition | Count |",
        "|------------|------:|",
    ]
    for key, count in sorted(dec_change_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {key} | {count} |")

    lines += [
        "",
        "## Tier Changes",
        "",
        "| Transition | Count |",
        "|------------|------:|",
    ]
    for key, count in sorted(tier_change_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {key} | {count} |")

    # Most changed cases
    lines += [
        "",
        "## Cases with Decision + Tier Changes (highest fidelity impact)",
        "",
        "| Date | Type | v1 Decision | v2 Decision | v1 Tier | v2 Tier | CaseLab Score | HMM |",
        "|------|------|-------------|-------------|--------:|--------:|--------------:|-----|",
    ]
    both_changed = [c for c in comparisons if c["decision_changed"] and c["tier_changed"]]
    for c in sorted(both_changed, key=lambda x: x.get("as_of_date", "")):
        cl = c.get("v2_caselab_score")
        cl_str = f"{cl:.3f}" if cl is not None else "N/A"
        hmm = c.get("v2_hmm_regime", "N/A")
        lines.append(
            f"| {c['as_of_date']} | {c['sample_type']} | "
            f"{c['v1_decision']} | {c['v2_decision']} | "
            f"{c['v1_tier']} | {c['v2_tier']} | {cl_str} | {hmm} |"
        )

    # Tier upgrade/downgrade analysis
    upgrades = [c for c in tier_changes if (c["v2_tier"] or 0) > (c["v1_tier"] or 0)]
    downgrades = [c for c in tier_changes if (c["v2_tier"] or 0) < (c["v1_tier"] or 0)]

    lines += [
        "",
        "## Analysis",
        "",
        f"- **Tier upgrades:** {len(upgrades)} (v2 is more sensitive to structural signals)",
        f"- **Tier downgrades:** {len(downgrades)} (v2 is more conservative)",
        f"- **Net tier change:** {len(upgrades) - len(downgrades):+d}",
        "",
    ]

    if len(upgrades) > len(downgrades):
        lines.append(
            "v2 replay detects more structural signals than v1 because it uses canonical "
            "M/D/K/X values and CaseLab matching instead of raw-price proxies. "
            "This means more dates get classified as RESEARCH_REVIEW or WATCH."
        )
    elif len(downgrades) > len(upgrades):
        lines.append(
            "v2 replay is more conservative than v1. This could mean the raw-price proxies "
            "were over-sensitive, or that the canonical pipeline has stricter gates."
        )
    else:
        lines.append("v1 and v2 produce similar tier distributions.")

    lines += [
        "",
        "---",
        "",
        "*Auto-generated by run_feedback_replay_v2.py. "
        "Review the changed cases to determine if v2 is more faithful to real pipeline behavior.*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_batch(limit: int | None = None, compare: bool = False) -> int:
    """Run v2 replay for all samples."""
    manifest = load_jsonl(MANIFEST_PATH)
    if not manifest:
        print(f"[ERROR] No manifest at {MANIFEST_PATH}")
        return 1

    print(f"[INFO] Manifest: {len(manifest)} entries")

    # Skip real_judgment entries (they already have real pipeline output)
    replay_entries = [e for e in manifest if e.get("sample_type") != "real_judgment"]
    if limit:
        replay_entries = replay_entries[:limit]
    print(f"[INFO] Will replay {len(replay_entries)} entries (skipping real_judgment)")

    # Load canonical data
    print("[INFO] Loading canonical pipeline data...")
    channel_series = _load_channel_series()
    structural_state = _load_structural_state()
    cases = _load_case_library()
    print(f"[INFO] Channel series: {len(channel_series)} rows, "
          f"Structural state: {len(structural_state)} rows, Cases: {len(cases)}")

    ensure_dir(REPLAY_V2_DIR)

    # Run replays
    completed = 0
    errors = 0

    for i, sample in enumerate(replay_entries):
        sid = sample.get("sample_id", f"unknown_{i}")
        out_path = REPLAY_V2_DIR / f"{sid}.json"

        try:
            result = replay_sample_v2(sample, channel_series, structural_state, cases)
            write_json(out_path, result)
            completed += 1

            if completed % 100 == 0:
                print(f"  [{completed}/{len(replay_entries)}] processed")

        except Exception as e:
            print(f"  [ERROR] {sid}: {e}")
            errors += 1

    print(f"\n[DONE] v2 replay: {completed} completed, {errors} errors")
    print(f"       Outputs in: {REPLAY_V2_DIR}")

    # Compare v1 vs v2 if requested
    if compare:
        print("\n[INFO] Comparing v1 vs v2...")
        comparisons = []
        for sample in replay_entries:
            sid = sample.get("sample_id")
            if sid:
                comp = compare_v1_v2(sid)
                if comp:
                    comparisons.append(comp)

        if comparisons:
            report = generate_fidelity_report(comparisons)
            ensure_dir(FIDELITY_REPORT_PATH.parent)
            FIDELITY_REPORT_PATH.write_text(report, encoding="utf-8")
            print(f"[OK] Fidelity report: {FIDELITY_REPORT_PATH}")

            # Print summary
            dec_changes = sum(1 for c in comparisons if c["decision_changed"])
            tier_changes = sum(1 for c in comparisons if c["tier_changed"])
            print(f"     Decision changes: {dec_changes}/{len(comparisons)}")
            print(f"     Tier changes: {tier_changes}/{len(comparisons)}")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run feedback replay v2 with canonical pipeline data"
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit entries")
    parser.add_argument(
        "--compare-v1", action="store_true",
        help="Compare v1 vs v2 outputs and generate fidelity report"
    )
    args = parser.parse_args()
    run_batch(limit=args.limit, compare=args.compare_v1)


if __name__ == "__main__":
    main()
