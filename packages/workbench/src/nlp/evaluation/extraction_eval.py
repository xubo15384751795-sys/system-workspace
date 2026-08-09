from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nlp.evaluation.golden_set import (
    GoldenEventCard,
    read_golden_event_cards,
)
from nlp.extraction.schemas import StructuralEventCard


@dataclass
class ExtractionEvalReport:
    total_golden: int = 0
    total_predictions: int = 0
    entity_precision: float = 0.0
    entity_recall: float = 0.0
    entity_f1: float = 0.0
    variable_exact_match: float = 0.0
    variable_partial_match: float = 0.0
    quote_coverage: float = 0.0
    field_completion_rate: float = 0.0
    schema_valid_rate: float = 0.0
    per_case_details: list[dict] = field(default_factory=list)
    summary: str = ""


def evaluate_extraction(
    predicted_cards: list[StructuralEventCard],
    *,
    golden_cards: list[GoldenEventCard] | None = None,
    eval_dir: Path | None = None,
) -> ExtractionEvalReport:
    if golden_cards is None:
        golden_cards = read_golden_event_cards(eval_dir=eval_dir)

    if not golden_cards:
        return ExtractionEvalReport(summary="No golden event cards available for evaluation.")

    report = ExtractionEvalReport(total_golden=len(golden_cards))
    report.total_predictions = len(predicted_cards)

    golden_by_quote: dict[str, GoldenEventCard] = {}
    for gc in golden_cards:
        key = gc.source_text_quote[:100].lower()
        golden_by_quote[key] = gc

    pred_by_quote: dict[str, StructuralEventCard] = {}
    for pc in predicted_cards:
        key = pc.source_text_quote[:100].lower()
        pred_by_quote[key] = pc

    total_entity_tp = 0
    total_entity_fp = 0
    total_entity_fn = 0
    total_variable_em = 0
    total_variable_pm = 0
    total_quote_cov = 0
    total_field_completion = 0
    total_schema_valid = 0
    matched_pairs = 0

    for quote_key, golden in golden_by_quote.items():
        pred = pred_by_quote.get(quote_key)
        if pred is None:
            _add_unmatched_detail(report, golden)
            total_entity_fn += len(golden.expected_entities)
            continue

        matched_pairs += 1
        detail = _evaluate_pair(golden, pred)
        report.per_case_details.append(detail)
        total_entity_tp += detail.get("entity_true_positives", 0)
        total_entity_fp += detail.get("entity_false_positives", 0)
        total_entity_fn += detail.get("entity_false_negatives", 0)
        total_variable_em += 1 if detail.get("variable_exact_match") else 0
        total_variable_pm += detail.get("variable_intersection_ratio", 0.0)
        total_quote_cov += detail.get("quote_coverage", 0.0)
        total_field_completion += detail.get("field_completion_ratio", 0.0)
        total_schema_valid += 1 if detail.get("schema_valid") else 0

    n = max(1, matched_pairs)
    report.entity_precision = _safe_div(total_entity_tp, total_entity_tp + total_entity_fp)
    report.entity_recall = _safe_div(total_entity_tp, total_entity_tp + total_entity_fn)
    report.entity_f1 = _safe_div(
        2 * report.entity_precision * report.entity_recall,
        report.entity_precision + report.entity_recall,
    )
    report.variable_exact_match = _safe_div(total_variable_em, n)
    report.variable_partial_match = _safe_div(total_variable_pm, n)
    report.quote_coverage = _safe_div(total_quote_cov, n)
    report.field_completion_rate = _safe_div(total_field_completion, n)
    report.schema_valid_rate = _safe_div(total_schema_valid, n)

    report.summary = (
        f"Evaluated {matched_pairs}/{len(golden_cards)} matched golden pairs. "
        f"Entity F1={report.entity_f1:.3f}, "
        f"Variable EM={report.variable_exact_match:.3f}, "
        f"Variable soft={report.variable_partial_match:.3f}, "
        f"Quote coverage={report.quote_coverage:.3f}, "
        f"Schema valid={report.schema_valid_rate:.3f}"
    )
    return report


def evaluate_extraction_json_legality(
    predicted_cards: list[StructuralEventCard],
) -> dict:
    valid = 0
    invalid = 0
    errors: list[str] = []
    for card in predicted_cards:
        try:
            json_str = card.model_dump_json()
            import json
            json.loads(json_str)
            valid += 1
        except Exception as exc:
            invalid += 1
            errors.append(f"{card.event_id}: {exc}")
    return {
        "total": valid + invalid,
        "valid_json": valid,
        "invalid_json": invalid,
        "json_legality_rate": _safe_div(valid, max(1, valid + invalid)),
        "errors": errors[:20],
    }


def evaluate_extraction_stability(
    cards_run_1: list[StructuralEventCard],
    cards_run_2: list[StructuralEventCard],
) -> dict:
    """Check that the same input produces consistent outputs across runs."""
    by_event_1 = {c.event_id: c for c in cards_run_1}
    by_event_2 = {c.event_id: c for c in cards_run_2}
    common = set(by_event_1) & set(by_event_2)
    if not common:
        return {"stable_event_ids": 0, "total_common": 0, "stability_rate": 0.0,
                "note": "No common event IDs between runs"}
    stable = 0
    unstable_details: list[dict] = []
    for eid in common:
        c1, c2 = by_event_1[eid], by_event_2[eid]
        vm1 = c1.variable_mapping.model_dump()
        vm2 = c2.variable_mapping.model_dump()
        diffs = {v: vm1.get(v) != vm2.get(v) for v in ("S", "A", "L", "V", "P", "tau")}
        if any(diffs.values()):
            unstable_details.append({"event_id": eid, "diffs": {k: v for k, v in diffs.items() if v}})
        else:
            stable += 1
    return {
        "stable_event_ids": stable,
        "unstable_event_ids": len(common) - stable,
        "total_common": len(common),
        "stability_rate": _safe_div(stable, len(common)),
        "unstable_details": unstable_details[:10],
    }


def _evaluate_pair(golden: GoldenEventCard, pred: StructuralEventCard) -> dict:
    pred_entity_texts = [
        e.get("text", "") if isinstance(e, dict) else getattr(e, "text", "")
        for e in (pred.actors + pred.assets + pred.triggers + pred.anchors)
    ]
    golden_entity_texts = [e.get("text", "") for e in golden.expected_entities]
    pred_set = set(t.lower() for t in pred_entity_texts if t)
    golden_set = set(t.lower() for t in golden_entity_texts if t)
    tp = len(pred_set & golden_set)
    fp = len(pred_set - golden_set)
    fn = len(golden_set - pred_set)

    pred_vars = {v: set(pred.variable_mapping.model_dump().get(v, [])) for v in ("S", "A", "L", "V", "P", "tau")}
    golden_vars = {v: set(golden.expected_variables.get(v, [])) for v in ("S", "A", "L", "V", "P", "tau")}
    em = all(pred_vars[v] == golden_vars[v] for v in ("S", "A", "L", "V", "P", "tau"))
    intersections = [len(pred_vars[v] & golden_vars[v]) / max(1, len(golden_vars[v])) for v in ("S", "A", "L", "V", "P", "tau")]
    var_intersection = sum(intersections) / len(intersections)

    pred_quotes_lower = [q.lower() for q in pred.evidence_quotes]
    golden_quotes_lower = [q.lower() for q in golden.required_quotes]
    quote_cov = sum(1 for gq in golden_quotes_lower if any(gq in pq for pq in pred_quotes_lower)) / max(1, len(golden_quotes_lower))

    fields = [
        bool(pred.triggers), bool(pred.anchors), bool(pred.liquidity_paths),
        bool(pred.visibility_shift), bool(pred.policy_response), bool(pred.market_impact),
        bool(pred.evidence_quotes), bool(pred.actors), bool(pred.assets),
    ]
    field_completion = sum(fields) / len(fields)

    schema_valid = True
    try:
        pred.model_validate(pred.model_dump())
    except Exception:
        schema_valid = False

    return {
        "golden_id": golden.golden_id,
        "event_id": pred.event_id,
        "entity_true_positives": tp,
        "entity_false_positives": fp,
        "entity_false_negatives": fn,
        "variable_exact_match": em,
        "variable_intersection_ratio": round(var_intersection, 4),
        "quote_coverage": round(quote_cov, 4),
        "field_completion_ratio": round(field_completion, 4),
        "schema_valid": schema_valid,
    }


def _add_unmatched_detail(report: ExtractionEvalReport, golden: GoldenEventCard) -> None:
    report.per_case_details.append({
        "golden_id": golden.golden_id,
        "event_id": "NOT_FOUND",
        "entity_true_positives": 0,
        "entity_false_positives": 0,
        "entity_false_negatives": len(golden.expected_entities),
        "variable_exact_match": False,
        "variable_intersection_ratio": 0.0,
        "quote_coverage": 0.0,
        "field_completion_ratio": 0.0,
        "schema_valid": False,
        "note": "No predicted card matched this golden example",
    })


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return round(num / den, 4)
