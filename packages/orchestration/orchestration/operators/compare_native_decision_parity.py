#!/usr/bin/env python3
"""Compare native decision/adjacent boundaries with legacy callables.

The comparator runs both sides in separate temporary generations seeded from
the same read-only workspace inputs.  It is an observation tool only: no
shared current, judgment, trade, ledger, position, or publication surface may
change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from orchestration.native_adjacent_boundaries import (
    execute_native_adjacent_boundary,
    _rebase_shadow_snapshot_paths,
)
from orchestration.native_decision_boundaries import execute_native_decision_boundary
from scripts._runtime_io import ROOT

DEFAULT_REPORT = ROOT / "Output" / "health" / "native_decision_parity.json"
_TIMESTAMP = re.compile(
    r"\b20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\b"
)
_STEPS = (
    "judgment_layer",
    "judgment_promotion_gate",
    "trade_decision",
    "risk_gate",
    "record_trade_decision",
    "paper_portfolio",
)
_LEGACY_COMMANDS: dict[str, tuple[str, ...]] = {
    "judgment_layer": ("scripts/judgment_layer.py",),
    "judgment_promotion_gate": ("scripts/judgment_promotion_gate.py",),
    "trade_decision": ("scripts/trade_decision_layer.py",),
    "risk_gate": ("scripts/trade_risk_gate.py",),
    "record_trade_decision": ("scripts/record_trade_decision.py",),
    "paper_portfolio": ("scripts/strategy_lab/paper_portfolio.py", "--no-notify"),
}


def _surface_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return "MISSING"
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _seed_generation(root: Path, generation_root: Path) -> None:
    for name in (
        "current",
        "judgment",
        "trade_decision",
        "quality",
        "position",
        "trade_ledger",
        "system_learning",
    ):
        source = root / "Output" / name
        if source.exists():
            shutil.copytree(
                source.resolve(), generation_root / name, dirs_exist_ok=True
            )
    (generation_root / "current").mkdir(parents=True, exist_ok=True)
    _rebase_shadow_snapshot_paths(
        root=root,
        snapshot_path=generation_root / "current" / "neutral_pressure_snapshot.json",
    )


def _legacy_environment(root: Path, generation_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(root),
            "SYSTEM_ROOT": str(root),
            "SYSTEM_GENERATION_MODE": "1",
            "SYSTEM_GENERATION_DIR": str(generation_root),
            "CURRENT_OUTPUT_DIR": str(generation_root / "current"),
            "DAILY_OUTPUT_ROOT": str(generation_root),
            "SHADOW_OUTPUT_DIR": str(generation_root / "position"),
        }
    )
    pythonpath = [
        str(root),
        str(root / "scripts"),
        str(root / "packages" / "orchestration"),
        str(root / "packages" / "harvester" / "src"),
        str(root / "packages" / "workbench" / "src"),
        str(root / "packages" / "learning_hub" / "src"),
        str(root / "packages" / "framework"),
        str(root / "packages" / "framework" / "src"),
    ]
    existing = [
        part for part in environment.get("PYTHONPATH", "").split(os.pathsep) if part
    ]
    environment["PYTHONPATH"] = os.pathsep.join([*pythonpath, *existing])
    return environment


def _run_legacy_step(
    *, root: Path, generation_root: Path, step_id: str
) -> dict[str, Any]:
    command = [sys.executable, *_LEGACY_COMMANDS[step_id]]
    if step_id in {"judgment_layer", "judgment_promotion_gate", "trade_decision"}:
        snapshot = _load_json(
            generation_root / "current" / "neutral_pressure_snapshot.json"
        )
        as_of = str(snapshot.get("as_of") or "") if isinstance(snapshot, dict) else ""
        date_str = as_of[:10] if len(as_of) >= 10 else ""
        if date_str:
            command.extend(["--date", date_str])
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            env=_legacy_environment(root, generation_root),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "success" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-800:],
        "stderr_tail": (completed.stderr or "")[-1200:],
    }


def _normalize(
    value: Any, *, roots: tuple[Path, ...], drop_keys: frozenset[str]
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(child, roots=roots, drop_keys=drop_keys)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in drop_keys
        }
    if isinstance(value, list):
        return [_normalize(child, roots=roots, drop_keys=drop_keys) for child in value]
    if isinstance(value, str):
        for root in roots:
            value = value.replace(str(root), "<temporary-root>")
        return value
    return value


def _difference_paths(left: Any, right: Any, path: str = "") -> list[str]:
    """Return bounded structural paths for a parity mismatch."""
    if type(left) is not type(right):
        return [path or "$"]
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left or key not in right:
                paths.append(child_path)
            else:
                paths.extend(_difference_paths(left[key], right[key], child_path))
            if len(paths) >= 50:
                return paths[:50]
        return paths
    if isinstance(left, list):
        paths = []
        if len(left) != len(right):
            paths.append(f"{path}.length")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            paths.extend(_difference_paths(left_item, right_item, f"{path}[{index}]"))
            if len(paths) >= 50:
                return paths[:50]
        return paths
    return [] if left == right else [path or "$"]


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[Any] | None:
    if not path.is_file():
        return None
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _canonical_text(path: Path, *, roots: tuple[Path, ...]) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    for root in roots:
        text = text.replace(str(root), "<temporary-root>")
    return _TIMESTAMP.sub("<timestamp>", text)


def _compare_outputs(
    *,
    label: str,
    native_path: Path,
    legacy_path: Path,
    native_root: Path,
    legacy_root: Path,
    jsonl: bool = False,
    drop_keys: frozenset[str] = frozenset(),
    native_md_path: Path | None = None,
    legacy_md_path: Path | None = None,
) -> dict[str, Any]:
    roots = (native_root, legacy_root)
    native_value = _load_jsonl(native_path) if jsonl else _load_json(native_path)
    legacy_value = _load_jsonl(legacy_path) if jsonl else _load_json(legacy_path)
    if native_value is None or legacy_value is None:
        status = "MISSING"
        native_digest = None
        legacy_digest = None
        difference_paths: list[str] = []
    else:
        native_value = _normalize(native_value, roots=roots, drop_keys=drop_keys)
        legacy_value = _normalize(legacy_value, roots=roots, drop_keys=drop_keys)
        status = "MATCH" if native_value == legacy_value else "MISMATCH"
        difference_paths = _difference_paths(native_value, legacy_value)
        native_digest = hashlib.sha256(
            json.dumps(
                native_value, sort_keys=True, ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()
        legacy_digest = hashlib.sha256(
            json.dumps(
                legacy_value, sort_keys=True, ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()
    markdown_label = f"{label}.md"
    native_md = _canonical_text(
        native_md_path or native_path.with_name(native_path.stem + ".md"), roots=roots
    )
    legacy_md = _canonical_text(
        legacy_md_path or legacy_path.with_name(legacy_path.stem + ".md"), roots=roots
    )
    markdown_status = (
        "MATCH" if native_md is not None and native_md == legacy_md else "MISMATCH"
    )
    if native_md is None or legacy_md is None:
        markdown_status = "MISSING"
    return {
        "label": label,
        "status": status,
        "native": str(native_path),
        "legacy": str(legacy_path),
        "native_digest": native_digest,
        "legacy_digest": legacy_digest,
        "difference_paths": difference_paths,
        "markdown": {"label": markdown_label, "status": markdown_status},
    }


def _native_step(
    step_id: str,
    *,
    root: Path,
    native_generation: Path,
    native_decision_root: Path,
    native_adjacent_root: Path,
) -> dict[str, Any]:
    if step_id in {
        "judgment_layer",
        "judgment_promotion_gate",
        "trade_decision",
        "risk_gate",
    }:
        return execute_native_decision_boundary(
            step_id,
            root=root,
            shadow_root=native_decision_root,
            input_root=native_generation,
        )
    return execute_native_adjacent_boundary(
        step_id,
        root=root,
        shadow_root=native_adjacent_root,
        input_root=native_generation,
        decision_shadow_root=native_decision_root,
    )


def run_parity(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    shared_surfaces = {
        name: root / "Output" / name
        for name in (
            "current",
            "judgment",
            "trade_decision",
            "trade_ledger",
            "system_learning",
            "position",
        )
    }
    before = {
        name: _surface_fingerprint(path) for name, path in shared_surfaces.items()
    }
    step_reports: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="native-decision-parity-") as temporary:
        temporary_root = Path(temporary)
        native_generation = temporary_root / "native_generation"
        legacy_generation = temporary_root / "legacy_generation"
        native_decision_root = temporary_root / "native_decision_shadow"
        native_adjacent_root = temporary_root / "native_adjacent_shadow"
        _seed_generation(root, native_generation)
        _seed_generation(root, legacy_generation)

        native_results: dict[str, dict[str, Any]] = {}
        legacy_results: dict[str, dict[str, Any]] = {}
        for step_id in _STEPS:
            native_results[step_id] = _native_step(
                step_id,
                root=root,
                native_generation=native_generation,
                native_decision_root=native_decision_root,
                native_adjacent_root=native_adjacent_root,
            )
            legacy_results[step_id] = _run_legacy_step(
                root=root,
                generation_root=legacy_generation,
                step_id=step_id,
            )
            if (
                native_results[step_id].get("status") != "success"
                or legacy_results[step_id].get("status") != "success"
            ):
                step_reports[step_id] = {
                    "status": "ERROR",
                    "native": native_results[step_id],
                    "legacy": legacy_results[step_id],
                }
                continue

            if step_id == "judgment_layer":
                native_path = native_decision_root / "judgment" / "latest.json"
                legacy_path = legacy_generation / "judgment" / "latest.json"
                outputs = [
                    _compare_outputs(
                        label=step_id,
                        native_path=native_path,
                        legacy_path=legacy_path,
                        native_root=native_decision_root,
                        legacy_root=legacy_generation,
                        drop_keys=frozenset(
                            {
                                "captured_at",
                                "decision_time",
                                "generated_at",
                                "inputs",
                            }
                        ),
                    )
                ]
            elif step_id == "judgment_promotion_gate":
                native_path = native_decision_root / "judgment" / "promotion_gate.json"
                legacy_path = legacy_generation / "judgment" / "promotion_gate.json"
                outputs = [
                    _compare_outputs(
                        label=step_id,
                        native_path=native_path,
                        legacy_path=legacy_path,
                        native_root=native_decision_root,
                        legacy_root=legacy_generation,
                        drop_keys=frozenset(
                            {
                                "captured_at",
                                "decision_time",
                                "generated_at",
                                "inputs",
                            }
                        ),
                    )
                ]
            elif step_id == "trade_decision":
                native_path = native_decision_root / "trade_decision" / "latest.json"
                legacy_path = legacy_generation / "trade_decision" / "latest.json"
                outputs = [
                    _compare_outputs(
                        label=step_id,
                        native_path=native_path,
                        legacy_path=legacy_path,
                        native_root=native_decision_root,
                        legacy_root=legacy_generation,
                        drop_keys=frozenset(
                            {
                                "captured_at",
                                "decision_time",
                                "generated_at",
                                "occurred_at",
                            }
                        ),
                    )
                ]
            elif step_id == "risk_gate":
                native_path = native_decision_root / "trade_decision" / "risk_gate.json"
                legacy_path = legacy_generation / "trade_decision" / "risk_gate.json"
                outputs = [
                    _compare_outputs(
                        label=step_id,
                        native_path=native_path,
                        legacy_path=legacy_path,
                        native_root=native_decision_root,
                        legacy_root=legacy_generation,
                        drop_keys=frozenset(
                            {
                                "captured_at",
                                "decision_time",
                                "generated_at",
                                "occurred_at",
                            }
                        ),
                    )
                ]
            elif step_id == "record_trade_decision":
                native_path = (
                    native_adjacent_root
                    / "generation"
                    / "trade_ledger"
                    / "decisions.jsonl"
                )
                legacy_path = legacy_generation / "trade_ledger" / "decisions.jsonl"
                outputs = [
                    _compare_outputs(
                        label=step_id,
                        native_path=native_path,
                        legacy_path=legacy_path,
                        native_root=native_adjacent_root,
                        legacy_root=legacy_generation,
                        jsonl=True,
                        drop_keys=frozenset(
                            {
                                "added_at",
                                "captured_at",
                                "decision_time",
                                "evaluated_at",
                                "generated_at",
                                "occurred_at",
                                "recorded_at",
                                "updated_at",
                            }
                        ),
                        native_md_path=native_adjacent_root
                        / "generation"
                        / "trade_ledger"
                        / "latest.md",
                        legacy_md_path=legacy_generation / "trade_ledger" / "latest.md",
                    )
                ]
            else:
                native_path = (
                    native_adjacent_root
                    / "generation"
                    / "position"
                    / "paper_portfolio.json"
                )
                legacy_path = legacy_generation / "position" / "paper_portfolio.json"
                outputs = [
                    _compare_outputs(
                        label=step_id,
                        native_path=native_path,
                        legacy_path=legacy_path,
                        native_root=native_adjacent_root,
                        legacy_root=legacy_generation,
                        drop_keys=frozenset(
                            {
                                "captured_at",
                                "decision_time",
                                "evaluated_at",
                                "generated_at",
                                "occurred_at",
                                "recorded_at",
                                "updated_at",
                            }
                        ),
                        native_md_path=native_adjacent_root
                        / "generation"
                        / "position"
                        / "paper_portfolio_latest.md",
                        legacy_md_path=legacy_generation
                        / "position"
                        / "paper_portfolio_latest.md",
                    )
                ]

            statuses = [item["status"] for item in outputs]
            markdown_statuses = [item["markdown"]["status"] for item in outputs]
            status = (
                "MATCH"
                if statuses == ["MATCH"] and markdown_statuses == ["MATCH"]
                else "MISMATCH"
            )
            step_reports[step_id] = {
                "status": status,
                "native": native_results[step_id],
                "legacy": legacy_results[step_id],
                "outputs": outputs,
            }

    after = {name: _surface_fingerprint(path) for name, path in shared_surfaces.items()}
    statuses = [str(item.get("status")) for item in step_reports.values()]
    if before != after:
        overall = "SHARED_SURFACE_WRITE"
    elif any(status == "ERROR" for status in statuses):
        overall = "INCOMPLETE"
    elif statuses and all(status == "MATCH" for status in statuses):
        overall = "MATCH"
    else:
        overall = "MISMATCH"
    return {
        "schema_version": "system.native_decision_parity.v1",
        "status": overall,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "execution_mode": "same_inputs_temporary_generations",
        "selected_steps": list(_STEPS),
        "steps": step_reports,
        "shared_surface_fingerprints_before": before,
        "shared_surface_fingerprints_after": after,
        "shared_surfaces_unchanged": before == after,
        "business_default_path_changed": False,
    }


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    report_path = args.report.expanduser().resolve()
    report = run_parity(root=root)
    _write_json_atomically(report_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
