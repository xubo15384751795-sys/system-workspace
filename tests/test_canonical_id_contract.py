from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from system_runtime.canonical_ids import (
    CANONICAL_SCHEMA_PATH,
    CanonicalIdError,
    build_chain,
    build_claim,
    build_evidence,
    build_measurement,
    build_observation,
    canonical_id,
    lineage_ids,
    validate_chain,
    validate_observation,
)

ROOT = Path(__file__).resolve().parents[1]


def _chain(*, value: float = 0.42) -> dict:
    observation = build_observation(
        canonical_series_id="FRED:NFCI",
        observed_at="2026-08-14T00:00:00Z",
        vintage_at="2026-08-15T00:00:00Z",
        value=value,
        unit="index",
        source_id="fred:nfci",
        source_snapshot_sha256="a" * 64,
        provenance={"captured_at": "2026-08-15T01:00:00Z", "producer": "test"},
    )
    measurement = build_measurement(
        observation_ids=[observation["observation_id"]],
        measurement_definition="nfci_normalized_level",
        method_version="1",
        value=value,
        unit="zscore",
        confidence=0.95,
        provenance={"captured_at": "2026-08-15T01:00:01Z", "producer": "test"},
    )
    evidence = build_evidence(
        measurement_ids=[measurement["measurement_id"]],
        evidence_role="PRIMARY",
        source_id="fred:nfci",
        release_id="fred-2026-08-15",
        source_snapshot_sha256="a" * 64,
        provenance={"captured_at": "2026-08-15T01:00:02Z", "producer": "test"},
    )
    claim = build_claim(
        claim_text="NFCI is elevated relative to its reference distribution.",
        subject="FRED:NFCI",
        predicate="is_elevated",
        evidence_ids=[evidence["evidence_id"]],
        status="WATCH",
        confidence=0.8,
        provenance={"captured_at": "2026-08-15T01:00:03Z", "producer": "test"},
    )
    return build_chain(observation=observation, measurement=measurement, evidence=evidence, claim=claim)


def test_parity_fixture_is_schema_and_reference_valid() -> None:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "canonical_chain_parity.json").read_text())
    validate_chain(fixture)
    schema = json.loads(CANONICAL_SCHEMA_PATH.read_text())
    assert not list(Draft202012Validator(schema).iter_errors(fixture))
    assert lineage_ids(fixture)["claim_id"] == "clm_098b812fa4635d5320beb77eca394efb"


def _runtime_state_chain(state: dict) -> dict:
    """Build a canonical chain from a runtime-state parity fixture row."""

    captured_at = "2026-08-17T04:00:00Z"
    producer = "canonical_runtime_state_fixture"
    run_id = f"fixture-run-{state['name']}"
    observation_input = state["observation"]
    observation = build_observation(
        canonical_series_id=observation_input["canonical_series_id"],
        observed_at=observation_input["observed_at"],
        vintage_at=observation_input["vintage_at"],
        value=observation_input["value"],
        source_id=observation_input["source_id"],
        status=observation_input["status"],
        provenance={
            "captured_at": captured_at,
            "producer": producer,
            "parser_version": "1",
            "run_id": run_id,
        },
    )
    measurement_input = state["measurement"]
    measurement = build_measurement(
        observation_ids=[observation["observation_id"]],
        measurement_definition=measurement_input["measurement_definition"],
        method_version=measurement_input["method_version"],
        value=measurement_input["value"],
        status=measurement_input["status"],
        derivation=measurement_input["derivation"],
        confidence=measurement_input["confidence"],
        provenance={
            "captured_at": captured_at,
            "producer": producer,
            "parser_version": "1",
            "run_id": run_id,
            "method": measurement_input["derivation"],
        },
    )
    evidence_input = state["evidence"]
    evidence = build_evidence(
        measurement_ids=[measurement["measurement_id"]],
        evidence_role=evidence_input["evidence_role"],
        source_id=observation_input["source_id"],
        release_id=evidence_input["release_id"],
        status=evidence_input["status"],
        provenance={
            "captured_at": captured_at,
            "producer": producer,
            "parser_version": "1",
            "run_id": run_id,
        },
    )
    claim_input = state["claim"]
    claim = build_claim(
        claim_text=claim_input["claim_text"],
        subject=claim_input["subject"],
        predicate=claim_input["predicate"],
        evidence_ids=[evidence["evidence_id"]],
        status=claim_input["status"],
        confidence=claim_input["confidence"],
        provenance={
            "captured_at": captured_at,
            "producer": producer,
            "parser_version": "1",
            "run_id": run_id,
        },
    )
    return build_chain(observation=observation, measurement=measurement, evidence=evidence, claim=claim)


def test_runtime_state_parity_fixture_covers_safe_boundaries() -> None:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "canonical_runtime_states.json").read_text())
    assert fixture["schema_version"] == "system.canonical_runtime_parity.v1"
    assert fixture["fixture_only"] is True
    assert {state["category"] for state in fixture["states"]} == {
        "Healthy",
        "Provider Failure",
        "Stale / Carry-forward",
        "Schema Drift",
    }
    assert len(fixture["states"]) == 5

    schema = json.loads(CANONICAL_SCHEMA_PATH.read_text())
    for state in fixture["states"]:
        chain = _runtime_state_chain(state)
        validate_chain(chain)
        assert not list(Draft202012Validator(schema).iter_errors(chain))
        assert lineage_ids(chain) == {
            "schema_version": "system.canonical_chain.v1",
            **state["expected_lineage"],
        }

        runtime = state["runtime"]
        observation_status = chain["observation"]["status"]
        claim_status = chain["claim"]["status"]
        attempts = state["provider_attempts"]
        assert attempts and all(item["provider_attempt_id"].startswith("att_") for item in attempts)
        assert all(item["outcome"] in {"success", "failed"} for item in attempts)

        if state["name"] == "healthy":
            assert runtime == {
                "operational_state": "FRESH_READY",
                "execution_status": "SUCCESS",
                "admission_verdict": "PASS",
                "publish_status": "COMMITTED",
                "decision_ready": True,
                "claim_ceiling": "SUPPORTED",
                "current_pointer": "generation-healthy",
            }
            assert observation_status == "AVAILABLE"
            assert claim_status == "SUPPORTED"
            assert attempts[0]["outcome"] == "success"
        else:
            assert runtime["admission_verdict"] == "BLOCK"
            assert runtime["publish_status"] == "NOT_PUBLISHED"
            assert runtime["decision_ready"] is False
            assert runtime["current_pointer"] == "generation-healthy"
            assert runtime["claim_ceiling"] == "WATCH"
            assert attempts[0]["outcome"] == "failed"
            assert observation_status in {"SOURCE_DOWN", "STALE", "SCHEMA_CHANGED"}
            assert claim_status in {"STALE", "INSUFFICIENT_DATA", "UNOBSERVABLE"}

        if state["name"] == "stale_within_grace":
            assert runtime["operational_state"] == "COMPLETED_DEGRADED"
            assert claim_status == "STALE"
        if state["name"] == "stale_expired":
            assert runtime["operational_state"] == "COMPLETED_BLOCKED"
            assert claim_status == "INSUFFICIENT_DATA"
        if state["name"] == "schema_drift":
            assert observation_status == "SCHEMA_CHANGED"
            assert claim_status == "UNOBSERVABLE"
            assert attempts[0]["reason"] == "schema_changed"
            assert attempts[0]["retryable"] is False


def test_runtime_state_parity_fixture_is_not_scheduled_evidence() -> None:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "canonical_runtime_states.json").read_text())
    assert fixture["fixture_only"] is True
    assert fixture["contract_scope"] == "contract_replay_only"
    assert all("scheduled_evidence" not in state for state in fixture["states"])
    assert all(state["runtime"]["current_pointer"] == "generation-healthy" for state in fixture["states"])


def test_ids_are_deterministic_and_identity_order_independent() -> None:
    first = _chain()
    second = _chain()
    assert first == second
    assert canonical_id("observation", {"b": 2, "a": 1}) == canonical_id("observation", {"a": 1, "b": 2})

    changed = _chain(value=0.43)
    assert changed["observation"]["observation_id"] != first["observation"]["observation_id"]
    assert changed["measurement"]["measurement_id"] != first["measurement"]["measurement_id"]
    # Claim identity is the proposition, not the current evidence vintage.
    assert changed["claim"]["claim_id"] == first["claim"]["claim_id"]


def test_cross_object_links_are_enforced() -> None:
    chain = _chain()
    chain["claim"]["evidence_ids"] = []
    with pytest.raises(CanonicalIdError, match="claim does not reference its evidence"):
        validate_chain(chain)


def test_id_tampering_is_rejected_even_when_shape_is_valid() -> None:
    chain = _chain()
    chain["observation"]["observation_id"] = "obs_00000000000000000000000000000000"
    with pytest.raises(CanonicalIdError, match="observation ID does not match"):
        validate_chain(chain)


def test_missingness_and_non_finite_values_are_explicit() -> None:
    observation = build_observation(
        canonical_series_id="demo:series",
        observed_at="2026-08-17",
        value=None,
        source_id="demo",
        status="SOURCE_DOWN",
        provenance={"captured_at": "2026-08-17T00:00:00Z", "producer": "test"},
    )
    assert observation["status"] == "SOURCE_DOWN"
    with pytest.raises(CanonicalIdError, match="NaN"):
        build_observation(
            canonical_series_id="demo:series",
            observed_at="2026-08-17",
            value=float("nan"),
            source_id="demo",
        )


def test_standalone_observation_validator_matches_sidecar_contract() -> None:
    observation = build_observation(
        canonical_series_id="ETF:SPY:close",
        observed_at="2026-08-17",
        vintage_at="2026-08-17",
        value=100.0,
        source_id="yfinance",
        source_snapshot_sha256="b" * 64,
        provenance={"captured_at": "2026-08-17T00:00:00Z", "producer": "test"},
    )
    validate_observation(observation)
    observation["observation_id"] = "obs_" + "0" * 32
    with pytest.raises(CanonicalIdError, match="observation ID does not match"):
        validate_observation(observation)


def test_workbench_nlp_evidence_id_is_content_stable_across_path_moves(tmp_path: Path) -> None:
    from workbench.nlp import _chunks_for_path

    first_path = tmp_path / "old" / "latest_summary.md"
    second_path = tmp_path / "new" / "latest_summary.md"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_text("# Evidence\n\nA stable excerpt.\n", encoding="utf-8")
    second_path.write_text(first_path.read_text(encoding="utf-8"), encoding="utf-8")
    first = _chunks_for_path(first_path, release_id="release-1", max_chars=1000)
    second = _chunks_for_path(second_path, release_id="release-1", max_chars=1000)
    assert first[0].evidence_id == second[0].evidence_id
    assert first[0].evidence_id.startswith("evd_")
    from workbench.nlp import _citation

    citation = _citation(first[0], excerpt_limit=100)
    assert citation["evidence_kind"] == "RETRIEVAL_CITATION"
    assert citation["canonical_evidence"] is False
    assert citation["promotion_allowed"] is False
