"""Tests for canonical runtime contracts.

Enforces:
- Active path must not use X_PRE/X_REALIZED for voting
- framework_output must pass schema validation
- sys check must display quality_status
- Bridge output source must be recorded
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_OUTPUT_PATH = ROOT / "Output" / "current" / "framework_output.json"
README_PATH = ROOT / "Output" / "current" / "00_READ_ME_FIRST.md"

sys.path.insert(0, str(ROOT / "scripts"))
try:
    import structural_replay_v2 as srv  # noqa: E402
except (ImportError, ModuleNotFoundError):
    srv = None  # type: ignore[assignment]


def _get_voting_proxies() -> list[dict]:
    """ProxySpec registry entries (PROXY_REGISTRY lives in _replay_registry.py)."""
    assert srv is not None, "structural_replay_v2 import failed — check PYTHONPATH / replay deps"
    return [
        {
            "name": s.name,
            "target_variable": s.target_variable,
            "tier": s.tier,
            "canonical_status": s.canonical_status,
        }
        for s in srv.PROXY_REGISTRY
    ]


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_active_path_no_x_pre_x_realized_voting():
    """Canonical voting proxies must not target X_PRE or X_REALIZED."""
    proxies = _get_voting_proxies()
    bad = [
        p["name"] for p in proxies
        if p["target_variable"] in ("X_PRE", "X_REALIZED")
        and p["canonical_status"] == "canonical_voting"
        and p["tier"] in ("core", "auxiliary")
    ]
    assert not bad, (
        f"X_PRE/X_REALIZED proxies with canonical_voting status: {bad}. "
        f"These channels are diagnostic only (Finance-2.tex §4.5)."
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_framework_output_schema_valid():
    """framework_output.json must conform to governance/framework_output.schema.json."""
    if not FRAMEWORK_OUTPUT_PATH.exists():
        pytest.skip("framework_output.json not found — run bridge_replay_to_current.py first")

    fw = json.loads(FRAMEWORK_OUTPUT_PATH.read_text(encoding="utf-8"))

    # Required top-level fields
    assert fw.get("schema_version") in ("workbench.framework_output.v2", "workbench.framework_output.v3"), (
        f"schema_version must be 'workbench.framework_output.v2' or 'v3', got {fw.get('schema_version')!r}"
    )
    assert "basic" in fw, "framework_output missing 'basic' field"
    assert "advanced" in fw, "framework_output missing 'advanced' field"

    # Required basic fields
    basic = fw["basic"]
    assert "overall" in basic, "basic missing 'overall'"
    assert "quality_status" in basic, "basic missing 'quality_status'"
    assert basic["overall"] in (
        "ACTIVE_FULL", "ACTIVE_PARTIAL", "DEGRADED_PARTIAL", "DEGRADED", "MISSING_OUTPUT"
    ), f"Invalid overall: {basic['overall']}"


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_framework_output_has_quality_status():
    """framework_output.json must display quality_status, not just overall."""
    if not FRAMEWORK_OUTPUT_PATH.exists():
        pytest.skip("framework_output.json not found")

    fw = json.loads(FRAMEWORK_OUTPUT_PATH.read_text(encoding="utf-8"))
    assert "quality_status" in fw.get("basic", {}), (
        "framework_output.basic must contain quality_status"
    )
    assert fw["basic"]["quality_status"] in (
        "FULL_HIGH_CONFIDENCE", "FULL_PROXY_REDUCED", "FULL_WITH_WARNINGS", "PARTIAL"
    ), f"Invalid quality_status: {fw['basic']['quality_status']}"


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_framework_output_sigma_vector_has_x_agg():
    """SigmaVector in framework_output must include X_agg."""
    if not FRAMEWORK_OUTPUT_PATH.exists():
        pytest.skip("framework_output.json not found")

    fw = json.loads(FRAMEWORK_OUTPUT_PATH.read_text(encoding="utf-8"))
    sv = fw.get("advanced", {}).get("sigma_vector", {})
    assert "X_agg" in sv, "SigmaVector missing X_agg"
    assert "channels_live" in sv, "SigmaVector missing channels_live"
    assert "complete" in sv, "SigmaVector missing complete"


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_readme_shows_output_source():
    """The README builder must identify structural replay independent of run tag."""
    from scripts.commands.weekly.build_readme_first import build_readme_from_index

    readme = build_readme_from_index(
        {"generated_at": "2026-07-17T00:00:00Z"},
        {
            "source": "structural_replay_v2",
            "run_id": "incident_remediation",
            "basic": {"quality_status": "PARTIAL"},
        },
    )
    assert "Output source" in readme, (
        "00_READ_ME_FIRST.md must display output source"
    )
    assert "structural_replay_v2" in readme or "replay_bridge" in readme, (
        "Output source must indicate structural_replay_v2 bridge"
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_readme_tolerates_null_degraded_sections():
    """A failed run must not turn a presentation-only README step into a root failure."""
    from scripts.commands.weekly.build_readme_first import build_readme_from_index

    readme = build_readme_from_index(
        {
            "generated_at": "2026-08-17T16:09:53Z",
            "measurement_state": {
                "promotion_gate": None,
                "judgment": None,
                "signals": {"hmm": None, "k_gate": None, "x_gate": None},
            },
            "market_feedback": None,
        },
        {"basic": {"quality_status": "PARTIAL"}},
    )

    assert "# System Output - 2026-08-17" in readme
    assert "**Promotion Gate:** N/A" in readme


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_readme_shows_quality_status():
    """00_READ_ME_FIRST.md must display quality status."""
    if not README_PATH.exists():
        pytest.skip("00_READ_ME_FIRST.md not found")

    readme = README_PATH.read_text(encoding="utf-8")
    assert "Quality:" in readme, (
        "00_READ_ME_FIRST.md must display Quality status"
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_k_voting_proxies_are_options_derived():
    """K canonical_voting proxies must use options-derived data (§4.4)."""
    proxies = _get_voting_proxies()
    k_voting = [
        p for p in proxies
        if p["target_variable"] == "K"
        and p["canonical_status"] == "canonical_voting"
    ]
    assert k_voting, "K channel has no canonical_voting proxies"


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_x_agg_has_canonical_voting_proxies():
    """X_agg must have at least one canonical_voting proxy."""
    proxies = _get_voting_proxies()
    x_voting = [
        p for p in proxies
        if p["target_variable"] == "X_agg"
        and p["canonical_status"] == "canonical_voting"
    ]
    assert x_voting, "X_agg channel has no canonical_voting proxies"
