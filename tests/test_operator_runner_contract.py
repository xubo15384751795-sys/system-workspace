"""The stateful operator suite must never run in the authoring checkout."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import run_operator_tests

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_operator_tests.py"


def test_operator_runner_requires_explicit_authorization() -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--allow-operator-workspace" in result.stderr


def test_direct_operator_pytest_fails_before_stateful_test_runs() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_harvester_bundle_operator.py",
            "-q",
            "-m",
            "operator",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "operator tests require scripts/run_operator_tests.py" in result.stdout


def test_makefile_routes_operator_suite_through_isolated_runner() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "scripts/run_operator_tests.py --allow-operator-workspace" in makefile
    assert "SYSTEM_TEST_OPERATOR_HASH_GUARD=1 $(UV_RUN) python -m pytest" not in makefile


def test_conftest_requires_isolated_operator_environment() -> None:
    source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "SYSTEM_OPERATOR_ISOLATED" in source
    assert "SYSTEM_OPERATOR_WORKSPACE" in source
    assert "operator tests require scripts/run_operator_tests.py" in source


def test_operator_runner_has_bounded_timeout_and_slow_test_evidence() -> None:
    parser = run_operator_tests._parser()
    args = parser.parse_args(["--allow-operator-workspace"])
    assert args.timeout_seconds == run_operator_tests.DEFAULT_TIMEOUT_SECONDS
    command = run_operator_tests._pytest_command(sys.executable, [])
    assert "--durations=25" in command
    assert command[-1] == "--durations=25"

    try:
        run_operator_tests._pytest_command(sys.executable, ["--durations=0"])
    except ValueError as exc:
        assert "--durations=25" in str(exc)
    else:
        raise AssertionError("operator runner must reject duration overrides")


def test_workspace_copy_isolated_from_seed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "tests").mkdir(parents=True)
    (source / "Data").mkdir()
    (source / "Output").mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (source / "Data" / "seed.txt").write_text("seed\n", encoding="utf-8")
    (source / "Output" / "seed.txt").write_text("seed\n", encoding="utf-8")

    modes = run_operator_tests._copy_workspace(source, target)

    assert set(modes) == {"Data", "Output"}
    (target / "Data" / "seed.txt").write_text("changed\n", encoding="utf-8")
    (target / "Output" / "generated.txt").write_text("candidate\n", encoding="utf-8")
    assert (source / "Data" / "seed.txt").read_text(encoding="utf-8") == "seed\n"
    assert not (source / "Output" / "generated.txt").exists()


def test_runner_executes_stateful_test_only_in_copy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "Data").mkdir()
    (source / "Output").mkdir()
    (source / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nmarkers=['operator: stateful']\n",
        encoding="utf-8",
    )
    (source / "Data" / "seed.txt").write_text("seed\n", encoding="utf-8")
    (source / "Output" / "seed.txt").write_text("seed\n", encoding="utf-8")
    (source / "tests" / "test_isolated.py").write_text(
        "import pytest\n"
        "from pathlib import Path\n"
        "pytestmark = pytest.mark.operator\n"
        "def test_write_copy_only():\n"
        "    root = Path(__file__).parents[1]\n"
        "    (root / 'Data' / 'generated.txt').write_text('copy\\n')\n"
        "    (root / 'Output' / 'generated.txt').write_text('copy\\n')\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--allow-operator-workspace",
            "--source-root",
            str(source),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "isolated workspace=" in result.stdout
    assert not (source / "Data" / "generated.txt").exists()
    assert not (source / "Output" / "generated.txt").exists()
