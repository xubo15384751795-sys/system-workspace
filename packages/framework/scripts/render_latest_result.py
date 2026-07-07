from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.output.result_renderer import render_latest_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the latest persisted System result.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).expanduser()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"config must be a YAML mapping: {config_path}")

    artifacts = render_latest_result(config)
    print("Rendered latest result:")
    for key in ("run_package", "executive_summary", "artifacts", "latest_html", "latest_json", "latest_png", "index"):
        path = artifacts.get(key)
        if path:
            print(f"  {key}: {path}")
    _refresh_output_current()


def _refresh_output_current() -> None:
    refresh_script = Path("/Users/a1/System/scripts/refresh_output_current.py")
    if not refresh_script.exists():
        print("Run:")
        print("  /Users/a1/System/sys refresh")
        return
    try:
        subprocess.run(["python3", str(refresh_script)], check=True)
    except Exception as exc:
        print(f"Warning: could not refresh Output/current: {exc}")
        print("Try:")
        print("  /Users/a1/System/sys refresh")


if __name__ == "__main__":
    main()
