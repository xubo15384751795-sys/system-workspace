"""Phase 1.1: publish-gate symmetry tests.

Verifies that scripts writing to Output/current/ honor the CURRENT_OUTPUT_DIR
candidate redirect (no more "bypass-the-gate direct writes"). A partial_failure
run must leave Output/current/ untouched; only a clean run promotes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestCurrentDirRedirect:
    def test_build_work_brief_honors_candidate_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
        # Re-import so the module-level CURRENT picks up the env.
        import importlib

        from scripts import build_work_brief

        importlib.reload(build_work_brief)
        assert str(build_work_brief.CURRENT) == str(tmp_path), (
            f"build_work_brief.CURRENT must honor CURRENT_OUTPUT_DIR, got {build_work_brief.CURRENT}"
        )

    def test_build_signal_card_honors_candidate_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
        import importlib

        from scripts import build_signal_card

        importlib.reload(build_signal_card)
        assert str(build_signal_card.CURRENT) == str(tmp_path), (
            f"build_signal_card.CURRENT must honor CURRENT_OUTPUT_DIR, got {build_signal_card.CURRENT}"
        )

    def test_no_direct_output_current_hardcode_in_writers(self):
        """The known direct-writer scripts must not hardcode
        ROOT/Output/current anymore - they must use current_dir()."""
        for script in (
            "build_work_brief.py",
            "build_signal_card.py",
            "commands/weekly/build_readme_first.py",
        ):
            src = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            # current_dir() must be imported and used; the old hardcode gone.
            assert "current_dir" in src, f"{script} must import current_dir"
            assert 'OUTPUT_PATH = ROOT / "Output" / "current"' not in src, (
                f"{script} must not hardcode OUTPUT_PATH under Output/current"
            )
            assert 'ROOT / "Output" / "current" / "00_READ_ME_FIRST.md"' not in src, (
                f"{script} must write 00_READ_ME_FIRST.md via current_dir()"
            )

    def test_build_readme_first_honors_candidate_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(sys, "argv", ["build_readme_first.py"])
        # Seed minimal inputs the builder reads from current/.
        (tmp_path / "framework_output.json").write_text("{}", encoding="utf-8")
        (tmp_path / "evidence_grade_report.json").write_text("{}", encoding="utf-8")
        index = ROOT / "Data" / "system_index" / "latest.json"
        if not index.exists():
            import pytest

            pytest.skip("no system index")
        from scripts.commands.weekly import build_readme_first

        build_readme_first.main()
        assert (tmp_path / "00_READ_ME_FIRST.md").exists()
