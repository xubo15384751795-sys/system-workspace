from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator
from workbench.judgment.layer import build_judgment
from workbench.measurement.neutral_pressure_measurement import build_snapshot
from workbench.model_protocol import (
    PROTOCOL_VERSION,
    DecisionEvidence,
    MeasurementRequest,
    ModelContext,
    ModelHost,
    ModelManifest,
    ModelResult,
)
from workbench.plugins.neutral_pressure_md import (
    MODEL_MANIFEST,
    NeutralPressureMdModel,
    NeutralPressureStateAdapter,
)
from workbench.plugins.neutral_pressure_md.legacy_output import build_legacy_snapshot

ROOT = Path(__file__).resolve().parents[1]


def _panel() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=220, freq="B")
    series_ids = (
        "DERIVED:CP_TBILL_SPREAD",
        "DERIVED:SOFR_IORB_SPREAD",
        "FRED:NFCICREDIT",
        "FRED:NFCIRISK",
        "CBOE:MOVE",
        "DERIVED:SPX_ROLL_SPREAD",
    )
    rows = []
    for series_index, series_id in enumerate(series_ids):
        for index, date in enumerate(dates):
            rows.append(
                {"date": date, "series_id": series_id, "value": index / 50 + series_index / 10}
            )
    return pd.DataFrame(rows)


class _DataAccess:
    def __init__(self, panel: pd.DataFrame) -> None:
        self.panel = panel

    def read_table(self, input_ref: str) -> pd.DataFrame:
        del input_ref
        return self.panel


class _SecondModel:
    """A paper-shaped model proving the host does not know M/D semantics."""

    manifest = ModelManifest(
        model_id="paper_example",
        model_version="0.1.0",
        protocol_version=PROTOCOL_VERSION,
        input_contract={"type": "fixture"},
        output_contract={"type": "generic_model_result"},
        required_data=("fixture_variable",),
        required_capabilities=(),
        failure_semantics="return unavailable on missing fixture",
        determinism_policy="deterministic",
        reference="fixture://paper-example",
        implementation_digest="0" * 64,
        fixture_version="paper-example.fixture.v1",
    )

    def evaluate(self, request: MeasurementRequest, context: ModelContext) -> ModelResult:
        del request, context
        return ModelResult(
            protocol_version=PROTOCOL_VERSION,
            model_id=self.manifest.model_id,
            model_version=self.manifest.model_version,
            as_of=None,
            available_at=None,
            status="available",
            confidence=0.2,
            state="PAPER_STATE",
            scores={"score_0": 0.4},
            diagnostics={},
            model_payload={"paper_variable": 0.4},
            provenance={"producer": "paper_example"},
            input_digest="1" * 64,
            implementation_digest=self.manifest.implementation_digest,
            authority="DIAGNOSTIC_ONLY",
            claim_ceiling="research_only",
            diagnostic_only=True,
        )


def _evaluation(panel: pd.DataFrame, *, adapter=None):
    return ModelHost().evaluate(
        NeutralPressureMdModel(),
        MeasurementRequest(request_id="protocol-test", input_ref="fixture://panel"),
        ModelContext(
            data_access=_DataAccess(panel),
            metadata={"run_id": "protocol-test", "release_id": "fixture-r1"},
        ),
        adapter=adapter,
    )


def test_manifest_declares_the_generic_protocol_and_real_capability() -> None:
    MODEL_MANIFEST.validate()
    assert MODEL_MANIFEST.model_id == "neutral_pressure_md"
    assert MODEL_MANIFEST.protocol_version == "measurement.model.v1"
    assert MODEL_MANIFEST.required_capabilities == ("data_access",)
    assert len(MODEL_MANIFEST.implementation_digest) == 64
    assert MODEL_MANIFEST.fixture_version


def test_model_result_is_generic_and_host_bounds_authority() -> None:
    evaluation = _evaluation(_panel(), adapter=NeutralPressureStateAdapter())
    result = evaluation.result.to_dict()
    evidence = evaluation.evidence.to_dict()

    assert {"M", "D", "K", "X", "HMM state"}.isdisjoint(result)
    assert {"M", "D", "K", "X", "HMM state"}.isdisjoint(evidence)
    assert result["model_id"] == "neutral_pressure_md"
    assert result["diagnostic_only"] is True
    assert result["authority"] == "DIAGNOSTIC_ONLY"
    assert evidence["adapter_id"] == "neutral_pressure_state"
    assert evidence["research_only"] is False
    assert evidence["diagnostic_only"] is True
    assert set(result["scores"]) == {"score_0", "score_1"}


def test_missing_state_adapter_is_research_only() -> None:
    evaluation = _evaluation(_panel())
    assert evaluation.evidence.adapter_id == "none"
    assert evaluation.evidence.research_only is True
    assert evaluation.evidence.diagnostic_only is True


def test_second_model_connects_to_host_without_core_changes() -> None:
    evaluation = ModelHost().evaluate(
        _SecondModel(),
        MeasurementRequest(request_id="paper-test", input_ref="fixture://paper"),
        ModelContext(data_access=_DataAccess(_panel())),
    )
    assert evaluation.result.model_id == "paper_example"
    assert evaluation.evidence.research_only is True
    assert evaluation.evidence.adapter_id == "none"


def test_legacy_projection_preserves_accepted_md_values(tmp_path: Path, monkeypatch) -> None:
    panel_path = tmp_path / "panel.parquet"
    history_path = tmp_path / "history.parquet"
    _panel().to_parquet(panel_path)
    monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "parity-test")
    legacy_snapshot, legacy_history = build_snapshot(panel_path, tmp_path / "legacy-history.parquet")
    evaluation = ModelHost().evaluate(
        NeutralPressureMdModel(),
        MeasurementRequest(request_id="parity-test", input_ref=str(panel_path)),
        ModelContext(
            data_access=__import__("workbench.model_protocol", fromlist=["FileDataAccess"]).FileDataAccess(),
            metadata={"run_id": "parity-test", "release_id": "fixture-r1"},
        ),
        adapter=NeutralPressureStateAdapter(),
    )
    snapshot, history = build_legacy_snapshot(
        evaluation,
        panel_path=panel_path,
        history_path=history_path,
        mechanism_cards=ROOT / "docs" / "measurements" / "macro_pressure_mechanism_cards.md",
    )

    assert snapshot["status"] == "active_partial"
    assert snapshot["decision_evidence"]["model_id"] == "neutral_pressure_md"
    assert snapshot["advanced"]["primary_readout"]["M_anchor_geometry"]["value"] == evaluation.result.scores["score_0"]
    assert snapshot["advanced"]["primary_readout"]["D_path_geometry"]["value"] == evaluation.result.scores["score_1"]
    assert list(history.columns) == ["M", "D"]
    assert snapshot["as_of"] == legacy_snapshot["as_of"]
    assert snapshot["basic"]["main_pressure"] == legacy_snapshot["basic"]["main_pressure"]
    assert snapshot["advanced"]["primary_readout"] == legacy_snapshot["advanced"]["primary_readout"]
    assert snapshot["advanced"]["sigma_vector"]["n_deteriorating"] == legacy_snapshot["advanced"]["sigma_vector"]["n_deteriorating"]
    pd.testing.assert_frame_equal(history, legacy_history)


def test_plugin_result_matches_its_checked_in_schema() -> None:
    evaluation = _evaluation(_panel(), adapter=NeutralPressureStateAdapter())
    schema_path = (
        ROOT
        / "packages"
        / "workbench"
        / "src"
        / "workbench"
        / "plugins"
        / "neutral_pressure_md"
        / "schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(evaluation.result.to_dict()))
    assert errors == [], [error.message for error in errors]


def test_judgment_prefers_generic_decision_evidence_over_compatibility_fields() -> None:
    framework = {
        "schema_version": "workbench.framework_output.v3",
        "framework_id": "macro_pressure_measurement",
        "run_id": "generic-evidence-test",
        "as_of": "2026-09-12T00:00:00+00:00",
        "basic": {
            "overall": "ACTIVE_PARTIAL",
            "quality_status": "FULL_WITH_WARNINGS",
            "main_pressure": "PRESSURE_EASING",
            "confidence": "bounded",
            "summary": "fixture",
        },
        "advanced": {
            "primary_readout": {
                "state": "PRESSURE_BUILDING",
                "M_anchor_geometry": {"value": 9.0},
                "D_path_geometry": {"value": 9.0},
            },
            "channel_confidence": {},
        },
        "decision_evidence": {
            "protocol_version": "measurement.model.v1",
            "model_id": "fixture_model",
            "state": "PRESSURE_EASING",
            "scores": {"score_0": 0.1, "score_1": 0.2},
            "confidence": 0.5,
        },
    }
    card = build_judgment(framework)
    assert card["md_values"] == {"M": 0.1, "D": 0.2}
    assert card["measurement_evidence"]["source"] == "decision_evidence"
    assert card["measurement_evidence"]["state"] == "PRESSURE_EASING"
    assert "0.100" in card["meaning"][1]


def test_model_implementation_has_no_runtime_or_orchestration_imports() -> None:
    path = ROOT / "packages" / "workbench" / "src" / "workbench" / "plugins" / "neutral_pressure_md" / "model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name == "scripts" or name.startswith("scripts.") for name in imported)
    assert not any(name == "orchestration" or name.startswith("orchestration.") for name in imported)
    assert not any(name == "system_runtime" or name.startswith("system_runtime.") for name in imported)


def test_decision_evidence_is_the_only_public_adapter_shape() -> None:
    assert set(DecisionEvidence.__dataclass_fields__) >= {
        "protocol_version",
        "model_id",
        "state",
        "scores",
        "confidence",
        "provenance",
        "authority",
        "claim_ceiling",
        "research_only",
        "diagnostic_only",
    }
