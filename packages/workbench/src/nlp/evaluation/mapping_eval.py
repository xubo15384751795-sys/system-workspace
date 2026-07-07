from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nlp.evaluation.golden_set import GoldenVariableMapping, read_golden_variable_mappings
from nlp.extraction.schemas import VariableMapping


@dataclass
class MappingEvalReport:
    total_golden: int = 0
    exact_match_rate: float = 0.0
    variable_precision: dict[str, float] = field(default_factory=dict)
    variable_recall: dict[str, float] = field(default_factory=dict)
    variable_f1: dict[str, float] = field(default_factory=dict)
    macro_f1: float = 0.0
    per_mapping_details: list[dict] = field(default_factory=list)
    summary: str = ""


def evaluate_mapping(
    predicted_mappings: list[VariableMapping],
    *,
    source_texts: list[str] | None = None,
    golden_mappings: list[GoldenVariableMapping] | None = None,
    eval_dir: Path | None = None,
) -> MappingEvalReport:
    if golden_mappings is None:
        golden_mappings = read_golden_variable_mappings(eval_dir=eval_dir)

    if not golden_mappings:
        return MappingEvalReport(summary="No golden variable mappings available.")

    report = MappingEvalReport(total_golden=len(golden_mappings))
    golden_by_text: dict[str, GoldenVariableMapping] = {}
    for gm in golden_mappings:
        key = gm.source_text[:120].lower().strip()
        golden_by_text[key] = gm

    pred_by_text: dict[str, VariableMapping] = {}
    for i, pm in enumerate(predicted_mappings):
        text = (source_texts or [""])[i] if source_texts and i < len(source_texts) else ""
        key = text[:120].lower().strip() if text else f"__pred_{i}"
        pred_by_text[key] = pm

    variables = ("S", "A", "L", "V", "P", "tau")
    per_var_tp = {v: 0 for v in variables}
    per_var_fp = {v: 0 for v in variables}
    per_var_fn = {v: 0 for v in variables}
    exact_matches = 0
    matched = 0

    for text_key, golden in golden_by_text.items():
        pred = pred_by_text.get(text_key)
        if pred is None:
            for v in variables:
                per_var_fn[v] += len(golden.expected_variable_mapping.get(v, []))
            report.per_mapping_details.append({
                "mapping_id": golden.mapping_id,
                "matched": False,
                "exact_match": False,
            })
            continue

        matched += 1
        pred_dict = pred.model_dump()
        golden_dict = golden.expected_variable_mapping
        em = all(
            set(pred_dict.get(v, [])) == set(golden_dict.get(v, []))
            for v in variables
        )
        if em:
            exact_matches += 1

        detail: dict = {"mapping_id": golden.mapping_id, "matched": True, "exact_match": em, "per_variable": {}}
        for v in variables:
            p_set = set(pred_dict.get(v, []))
            g_set = set(golden_dict.get(v, []))
            tp = len(p_set & g_set)
            fp = len(p_set - g_set)
            fn = len(g_set - p_set)
            per_var_tp[v] += tp
            per_var_fp[v] += fp
            per_var_fn[v] += fn
            prec = tp / max(1, tp + fp)
            rec = tp / max(1, tp + fn)
            f1 = 2 * prec * rec / max(0.001, prec + rec)
            detail["per_variable"][v] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}
        report.per_mapping_details.append(detail)

    n = max(1, matched)
    report.exact_match_rate = round(exact_matches / n, 4)

    f1_values: list[float] = []
    for v in variables:
        prec = per_var_tp[v] / max(1, per_var_tp[v] + per_var_fp[v])
        rec = per_var_tp[v] / max(1, per_var_tp[v] + per_var_fn[v])
        f1 = 2 * prec * rec / max(0.001, prec + rec)
        report.variable_precision[v] = round(prec, 4)
        report.variable_recall[v] = round(rec, 4)
        report.variable_f1[v] = round(f1, 4)
        f1_values.append(f1)

    report.macro_f1 = round(sum(f1_values) / len(f1_values), 4)
    report.summary = (
        f"Exact match rate={report.exact_match_rate:.3f}, "
        f"Macro F1={report.macro_f1:.3f}, "
        + " ".join(f"{v}={report.variable_f1.get(v, 0):.2f}" for v in variables)
    )
    return report
