from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.assembly import run_fast_signal_once


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute and persist a DAILY FastSignal surveillance reading.")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--date", default=None, help="Signal date. Defaults to latest local daily FRED observation.")
    parser.add_argument("--no-cross-validate", action="store_true")
    args = parser.parse_args()

    config = _load_config(args.config)
    if args.no_cross_validate:
        config = dict(config)
        config["_skip_fast_cross_validation"] = True
    signal, validation = run_fast_signal_once(config, run_date=args.date)

    print(
        f"FastSignal {signal.date}: "
        f"alert={signal.alert_level}, "
        f"composite={_fmt(signal.composite)}, "
        f"hits={','.join(signal.threshold_hits) or 'none'}"
    )

    if args.no_cross_validate:
        return

    if validation is None:
        print("CrossValidation skipped: no WEEKLY canonical snapshot on or before signal date.")
        return

    print(
        f"CrossValidation {validation.date}: "
        f"verdict={validation.verdict}, "
        f"canonical={validation.canonical_date}, "
        f"confidence_multiplier={validation.confidence_multiplier:.2f}"
    )


def _fmt(value: float | None) -> str:
    return "nan" if value is None else f"{value:.3f}"


if __name__ == "__main__":
    main()
