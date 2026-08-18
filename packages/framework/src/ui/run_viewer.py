from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pandas as pd
import streamlit as st

from src.core.runtime_context import RuntimePaths


def _default_run_root() -> Path:
    return cast(Path, RuntimePaths.discover().run_root)


def main(output_root: Path | None = None) -> None:
    if output_root is None:
        output_root = _default_run_root()
    st.set_page_config(page_title="Run Package Viewer", page_icon="SDRS", layout="wide")
    st.title("Run Package Viewer")

    runs = list_runs(output_root)
    if not runs:
        st.info("No run packages found.")
        return

    selected = st.sidebar.selectbox("Run", runs, index=0)
    run_dir = output_root / selected
    package = load_run_package(run_dir)

    render_summary(package)
    render_snapshot_cards(package)

    figures, tables, diagnostics, learning, manifest = st.tabs(
        ["Figures", "Tables", "Diagnostics", "Learning", "Manifest"]
    )
    with figures:
        render_figures(run_dir / "figures")
    with tables:
        render_tables(run_dir / "tables")
    with diagnostics:
        render_files(run_dir / "diagnostics")
    with learning:
        render_files(run_dir / "learning")
    with manifest:
        st.json(manifest)


def list_runs(output_root: Path) -> list[str]:
    if not output_root.exists():
        return []
    return sorted([path.name for path in output_root.iterdir() if path.is_dir()], reverse=True)


def load_run_package(run_dir: Path) -> dict[str, Any]:
    return {
        "run_id": run_dir.name,
        "executive_summary": _read_text(run_dir / "executive_summary.md"),
        "run_manifest": _read_json(run_dir / "run_manifest.json"),
        "artifacts": _read_json(run_dir / "artifacts.json"),
        "snapshot": _read_snapshot_json(run_dir),
        "rejection_flags": _read_json(run_dir / "diagnostics" / "rejection_flags.json"),
    }


def render_summary(package: dict[str, Any]) -> None:
    summary = package.get("executive_summary") or "No executive summary found."
    st.markdown(summary)


def render_snapshot_cards(package: dict[str, Any]) -> None:
    snapshot = package.get("snapshot") or {}
    proxy = snapshot.get("proxy") or {}
    state = snapshot.get("state") or {}
    interpretation = snapshot.get("interpretation") or {}
    rejection_flags = package.get("rejection_flags") or {}

    values = {
        "M": proxy.get("M"),
        "D": proxy.get("D"),
        "K": proxy.get("K"),
        "X": proxy.get("X"),
        "Sigma": state.get("sigma_t"),
        "Morphology": interpretation.get("pattern") or state.get("pattern"),
        "Rejection flags": _compact_flags(rejection_flags),
    }
    columns = st.columns(len(values))
    for column, (label, value) in zip(columns, values.items(), strict=False):
        column.metric(label, _format_value(value))


def render_figures(figures_dir: Path) -> None:
    images = sorted(
        path for path in figures_dir.glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not images:
        st.info("No figures found.")
        return
    for image_path in images:
        st.image(str(image_path), caption=image_path.name, use_container_width=True)


def render_tables(tables_dir: Path) -> None:
    table_paths = sorted(path for path in tables_dir.glob("*") if path.suffix.lower() in {".csv", ".parquet"})
    if not table_paths:
        st.info("No tables found.")
        return
    for table_path in table_paths:
        st.subheader(table_path.name)
        if table_path.suffix.lower() == ".csv":
            st.dataframe(pd.read_csv(table_path), use_container_width=True)
        else:
            st.dataframe(pd.read_parquet(table_path), use_container_width=True)


def render_files(directory: Path) -> None:
    if not directory.exists():
        st.info("No files found.")
        return
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files:
        st.info("No files found.")
        return
    for path in files:
        st.subheader(path.name)
        if path.suffix.lower() == ".json":
            st.json(_read_json(path))
        elif path.suffix.lower() == ".jsonl":
            st.dataframe(pd.DataFrame(_read_jsonl(path)), use_container_width=True)
        elif path.suffix.lower() == ".csv":
            st.dataframe(pd.read_csv(path), use_container_width=True)
        elif path.suffix.lower() in {".md", ".txt", ".log"}:
            st.markdown(_read_text(path) or "")
        else:
            st.caption(str(path))


def _read_snapshot_json(run_dir: Path) -> dict[str, Any]:
    preferred = run_dir / f"{run_dir.name}.json"
    fallback = run_dir / "data" / "snapshot.json"
    for path in (preferred, fallback):
        payload = _read_json(path)
        if payload:
            return payload
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"items": payload}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            rows.append(payload if isinstance(payload, dict) else {"value": payload})
    return rows


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _compact_flags(payload: dict[str, Any]) -> str:
    if not payload:
        return "-"
    active = [str(key) for key, value in payload.items() if bool(value)]
    return ", ".join(active) if active else "clear"


if __name__ == "__main__":
    main()
