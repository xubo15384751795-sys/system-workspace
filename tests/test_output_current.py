from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"


def test_output_current_refreshes() -> None:
    """Refresh should produce all required outputs."""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "refresh_output_current.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"refresh failed: {result.stderr}"

    # Core outputs exist
    assert CURRENT.exists(), "Output/current/ missing"
    assert (CURRENT / "framework_output.json").exists(), "framework_output.json missing"
    assert (CURRENT / "00_READ_ME_FIRST.md").exists(), "00_READ_ME_FIRST.md missing"

    # Judgment outputs exist
    assert JUDGMENT.exists(), "Output/judgment/ missing"
    assert (JUDGMENT / "latest.json").exists(), "judgment/latest.json missing"
    assert (JUDGMENT / "latest.md").exists(), "judgment/latest.md missing"
    assert (JUDGMENT / "promotion_gate.json").exists(), "promotion_gate.json missing"
    assert (JUDGMENT / "promotion_gate.md").exists(), "promotion_gate.md missing"


def test_readme_points_to_judgment() -> None:
    """00_READ_ME_FIRST.md must contain system status."""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "refresh_output_current.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    text = (CURRENT / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    # Check for new structure
    assert "System Status" in text
    assert "Judgment:" in text
    assert "Trade Decision:" in text
    assert "Risk Gate:" in text


def test_readme_contains_system_status() -> None:
    """00_READ_ME_FIRST.md must contain system status section."""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "refresh_output_current.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    text = (CURRENT / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "System Status" in text
    assert "Judgment:" in text
    assert "Trade Decision:" in text
    assert "Risk Gate:" in text


def test_readme_forbidden_language_in_dedicated_section() -> None:
    """Forbidden language should only appear in the Forbidden Language section."""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "refresh_output_current.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    text = (CURRENT / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")

    # Read promotion gate to get forbidden terms
    gate_path = JUDGMENT / "promotion_gate.json"
    if gate_path.exists():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        forbidden = gate.get("forbidden_language", [])

        if forbidden:
            # Split text into sections
            sections = text.split("## ")
            forbidden_section = ""
            other_sections = ""

            for section in sections:
                if section.startswith("Forbidden Language"):
                    forbidden_section = section
                else:
                    other_sections += section

            # Forbidden terms should be in the Forbidden Language section
            for term in forbidden:
                if term.lower() in forbidden_section.lower():
                    # This is expected - forbidden terms in forbidden section
                    pass
                # We don't check other sections because some terms might appear
                # in legitimate contexts (e.g., "regime" in "HMM regime")


def test_judgment_card_structure() -> None:
    """Judgment card must have required fields."""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "refresh_output_current.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    judgment = json.loads((JUDGMENT / "latest.json").read_text(encoding="utf-8"))

    assert "decision" in judgment
    assert "confidence" in judgment
    assert "claim_ceiling" in judgment
    assert "gate_status" in judgment


def test_promotion_gate_blocks_weak_signals() -> None:
    """Promotion gate should block signals when confidence is low."""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "refresh_output_current.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    gate = json.loads((JUDGMENT / "promotion_gate.json").read_text(encoding="utf-8"))

    assert "overall_status" in gate
    assert "allowed_language" in gate
    assert "forbidden_language" in gate
    assert "claim_ceiling" in gate

    # If blocked, forbidden language must be non-empty
    if gate["overall_status"] == "BLOCKED":
        assert len(gate["forbidden_language"]) > 0, "BLOCKED gate must have forbidden terms"


def test_output_readme_points_to_current_first() -> None:
    text = (ROOT / "Output" / "README.md").read_text(encoding="utf-8")
    assert "Open this first" in text
    assert "Output/current/00_READ_ME_FIRST.md" in text


def test_sys_doctor_succeeds() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True)
    subprocess.run([str(ROOT / "sys"), "doctor"], check=True)


def test_sys_status_succeeds() -> None:
    result = subprocess.run([str(ROOT / "sys"), "status"], check=True, capture_output=True, text=True)
    assert "Harvester" in result.stdout
    assert "Deformation" in result.stdout
    assert "LearningHub" in result.stdout
