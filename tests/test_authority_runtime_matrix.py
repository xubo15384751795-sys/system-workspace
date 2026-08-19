"""Regression checks for the Stage A authority/runtime contract map."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "architecture" / "authority_runtime_matrix.md"


def test_authority_runtime_matrix_names_one_owner_per_runtime_fact() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    required = (
        "one fact → one runtime authority",
        "system_runtime.run_outcome.RunOutcome",
        "system_runtime.publish_admission.PublishAdmission",
        "system_runtime.publish_transaction.PublishTransaction",
        "protocols/canonical_chain.schema.json",
        "scripts/freshness_validator.py",
        "SYS-15",
        "SYS-7",
        "SYS-19",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"authority/runtime matrix lost required contract markers: {missing}"


def test_authority_runtime_matrix_matches_python_313_contract() -> None:
    matrix = MATRIX.read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    uv_lock = (ROOT / "uv.lock").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.13,<3.14"' in pyproject
    assert python_version == "3.13"
    assert 'requires-python = "==3.13.*"' in uv_lock
    assert "Python 3.13 is the only supported active-workspace runtime" in matrix
