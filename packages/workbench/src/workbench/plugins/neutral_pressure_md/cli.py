"""Application adapter for running the neutral-pressure model plugin."""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from system_runtime.paths import WorkspacePaths
from verity.runtime.runtime_io import current_dir

from workbench.model_protocol import (
    FileDataAccess,
    MeasurementRequest,
    ModelContext,
    ModelHost,
)
from workbench.measurement import neutral_pressure_measurement as legacy

from .legacy_output import MECHANISM_CARDS, build_legacy_snapshot
from .model import NeutralPressureMdModel
from .state_adapter import NeutralPressureStateAdapter


def evaluate_neutral_pressure(
    *,
    panel_path: Path,
    history_path: Path,
    run_id: str,
    release_id: str,
    input_digest: str | None = None,
):
    model = NeutralPressureMdModel()
    request = MeasurementRequest(
        request_id=run_id,
        input_ref=str(panel_path),
        parameters={"run_id": run_id, "history_output": str(history_path)},
    )
    context = ModelContext(
        data_access=FileDataAccess(),
        metadata={
            "run_id": run_id,
            "release_id": release_id,
            "input_digest": input_digest,
        },
    )
    return ModelHost().evaluate(
        model,
        request,
        context,
        adapter=NeutralPressureStateAdapter(),
    )


def run_cli(argv: Sequence[str] | None = None) -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Build neutral macro-pressure gauges")
    parser.add_argument("--panel", type=Path, default=None)
    parser.add_argument("--current-output", type=Path, default=None)
    parser.add_argument("--history-output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = WorkspacePaths.discover().root
    panel_path = args.panel or root / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
    run_id = os.environ.get("ZCODE_BUNDLE_RUN_ID") or datetime.now(UTC).strftime("neutral_%Y%m%dT%H%M%SZ")
    history_path = args.history_output or root / "Output" / "runs" / run_id / "neutral_pressure" / "pressure_history.parquet"
    output_dir = args.current_output or current_dir()
    release_id = legacy._release_id()
    evaluation = evaluate_neutral_pressure(
        panel_path=panel_path,
        history_path=history_path,
        run_id=run_id,
        release_id=release_id,
    )
    snapshot, history = build_legacy_snapshot(
        evaluation,
        panel_path=panel_path,
        history_path=history_path,
        mechanism_cards=(root / MECHANISM_CARDS),
    )
    snapshot_path, framework_path, history_path = legacy.write_snapshot_files(
        snapshot,
        history,
        output_dir=output_dir,
        history_path=history_path,
    )
    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(f"Neutral pressure snapshot: {snapshot_path}")
    return {
        "snapshot": snapshot,
        "snapshot_path": str(snapshot_path),
        "framework_path": str(framework_path),
        "history_path": str(history_path),
        "model_id": evaluation.result.model_id,
        "adapter_id": evaluation.evidence.adapter_id,
    }


def main() -> None:
    run_cli()


__all__ = ["evaluate_neutral_pressure", "main", "run_cli"]
