from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"


def test_output_current_refreshes() -> None:
    subprocess.run(["python3", str(ROOT / "scripts" / "refresh_output_current.py")], check=True)

    assert CURRENT.exists()
    assert (CURRENT / "00_READ_ME_FIRST.md").exists()
    assert (CURRENT / "latest_run").exists()
    assert (CURRENT / "latest_summary.md").exists()
    assert (CURRENT / "latest_report.html").exists()
    assert (CURRENT / "run_manifest.json").exists()


def test_current_symlinks_resolve() -> None:
    subprocess.run(["python3", str(ROOT / "scripts" / "refresh_output_current.py")], check=True)

    for name in [
        "latest_run",
        "latest_summary.md",
        "latest_report.html",
        "latest_dashboard.json",
        "run_manifest.json",
    ]:
        path = CURRENT / name
        assert path.exists(), f"missing {name}"
        assert path.resolve().exists(), f"broken symlink: {name}"


def test_read_me_first_contains_required_sections() -> None:
    subprocess.run(["python3", str(ROOT / "scripts" / "refresh_output_current.py")], check=True)

    text = (CURRENT / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "Current Risk Check" in text
    assert "Basic Check" in text
    assert "Evidence Snapshot" in text
    assert "Framework Diagnosis" in text
    assert "Governance Next Actions" in text
    assert "Deeper Commands" in text


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
