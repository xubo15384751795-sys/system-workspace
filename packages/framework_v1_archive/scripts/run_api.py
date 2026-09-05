from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

from src.api.app import create_app
from src.api.security import assert_bind_allowed, resolve_api_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Structural Deformation terminal API.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--real-data", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        config_path = ROOT / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    api_key = resolve_api_key(config)
    assert_bind_allowed(args.host, api_key=api_key)

    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install uvicorn to run the terminal API.") from exc

    app = create_app(config_path=str(config_path), use_mock=not args.real_data, api_key=api_key)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
