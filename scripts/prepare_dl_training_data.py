#!/usr/bin/env python3
"""Freeze Harvester export panels into Data/dl_training/ (read-only copies).

This script never reads Deformation run outputs. It only copies immutable
Harvester artefacts for downstream **manual** labelling workflows.

Usage::

    python3 scripts/prepare_dl_training_data.py --release <release_id>

Environment / layout::

    <system_root>/Data/harvester/exports/<release_id>/evidence_panel.parquet
    -> <system_root>/Data/dl_training/panels/<release_id>/evidence_panel.parquet
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path


def _system_root() -> Path:
    return Path(__file__).resolve().parents[1]


def freeze_panel_for_training(
    release_id: str,
    *,
    harvester_exports: Path | None = None,
    dl_training_root: Path | None = None,
) -> Path:
    root = _system_root()
    exports = harvester_exports or (root / "Data" / "harvester" / "exports")
    src = exports / release_id / "evidence_panel.parquet"
    if not src.exists():
        raise FileNotFoundError(f"Missing harvester panel: {src}")

    dst_root = dl_training_root or (root / "Data" / "dl_training" / "panels")
    dst_dir = dst_root / release_id
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "evidence_panel.parquet"
    shutil.copy2(src, dst)

    prov_path = dst_dir / "copy_provenance.json"
    prov_path.write_text(
        json.dumps(
            {
                "schema_version": "workbench.dl_training_copy.v1",
                "copied_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "release_id": release_id,
                "source_path": str(src),
                "destination_path": str(dst),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dst


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze Harvester panels for DL training.")
    parser.add_argument("--release", required=True, help="Harvester export release id")
    parser.add_argument(
        "--harvester-exports",
        type=Path,
        default=None,
        help="Override path to Data/harvester/exports",
    )
    parser.add_argument(
        "--dl-training-root",
        type=Path,
        default=None,
        help="Override Data/dl_training/panels root",
    )
    args = parser.parse_args()
    path = freeze_panel_for_training(
        args.release,
        harvester_exports=args.harvester_exports,
        dl_training_root=args.dl_training_root,
    )
    print(path)


if __name__ == "__main__":
    main()
