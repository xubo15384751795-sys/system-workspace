from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_entrypoint_retries_typed_failure_same_day(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    state = tmp_path / "attempted"
    runner = scripts / "run_dagster_daily.sh"
    runner.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"if [[ ! -f {state} ]]; then touch {state}; exit 3; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_ROOT": str(tmp_path),
            "SYSTEM_DAILY_RETRY_ATTEMPTS": "1",
            "SYSTEM_DAILY_RETRY_DELAY_SECONDS": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_daily_scheduled.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "retry 1/1" in result.stderr


def test_scheduled_entrypoint_does_not_retry_configuration_failure(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = scripts / "run_dagster_daily.sh"
    runner.write_text("#!/usr/bin/env bash\nexit 2\n", encoding="utf-8")
    runner.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_ROOT": str(tmp_path),
            "SYSTEM_DAILY_RETRY_ATTEMPTS": "1",
            "SYSTEM_DAILY_RETRY_DELAY_SECONDS": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_daily_scheduled.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "retry 1/1" not in result.stderr
