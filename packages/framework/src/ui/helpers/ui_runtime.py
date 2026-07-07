from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.runtime_context import RuntimePaths
import streamlit as st

from src.runtime.assembly import _load_config, build_system
from src.core.interfaces import SnapshotStoreInterface
from src.core.models import Snapshot
from src.data.paths import resolve_fred_cache_dir
from src.output.output_exporter import snapshot_to_dict


CONFIG_PATH = "config.yaml"
EVENT_COLUMNS = [
    "date",
    "actor",
    "intervention_type",
    "expected_direction",
    "affected_proxy",
    "description",
    "created_at",
]


class EventLogger(ABC):
    @abstractmethod
    def write_event(self, event: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def load_events(self, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        ...


@dataclass
class JsonlEventLogger(EventLogger):
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def write_event(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload["affected_proxy"] = list(payload.get("affected_proxy", []))
        line = json.dumps(payload, ensure_ascii=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def load_events(self, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=EVENT_COLUMNS)

        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload["affected_proxy"] = ",".join(payload.get("affected_proxy", []))
                records.append(payload)

        if not records:
            return pd.DataFrame(columns=EVENT_COLUMNS)

        frame = pd.DataFrame.from_records(records)
        if "date" not in frame.columns:
            return pd.DataFrame(columns=EVENT_COLUMNS)

        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        if start is not None:
            frame = frame[frame["date"] >= pd.to_datetime(start)]
        if end is not None:
            frame = frame[frame["date"] <= pd.to_datetime(end)]

        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        for col in EVENT_COLUMNS:
            if col not in frame.columns:
                frame[col] = ""
        return frame[EVENT_COLUMNS].reset_index(drop=True)


@dataclass
class UIContext:
    config: dict[str, Any]
    pipeline: Any
    snapshot_store: SnapshotStoreInterface
    event_logger: EventLogger
    data_mode: str = "demo"


def get_context() -> UIContext:
    data_mode = str(st.session_state.get("_data_mode", "demo"))
    if "_ui_ctx" in st.session_state and getattr(st.session_state["_ui_ctx"], "data_mode", "demo") == data_mode:
        return st.session_state["_ui_ctx"]

    config = _load_config(CONFIG_PATH)
    pipeline = build_system(config, use_mock=data_mode == "demo")
    snapshot_store = pipeline.snapshot_store

    paths = RuntimePaths.discover()
    event_cfg = config.get("event_log", {})
    event_path = Path(event_cfg.get("path", str(paths.event_log_path))).expanduser()
    event_logger = JsonlEventLogger(path=event_path)

    ctx = UIContext(
        config=config,
        pipeline=pipeline,
        snapshot_store=snapshot_store,
        event_logger=event_logger,
        data_mode=data_mode,
    )
    st.session_state["_ui_ctx"] = ctx
    return ctx


def run_pipeline_once(ctx: UIContext, run_date: str, run_type: str) -> Snapshot:
    produced = ctx.pipeline.run(run_date=run_date, run_type=run_type)
    invalidate_shared_snapshot()
    loaded = ctx.snapshot_store.load(run_date)
    if loaded is not None:
        return loaded
    return produced


def render_workspace_controls(ctx: UIContext, key_prefix: str) -> str:
    with st.sidebar:
        st.subheader("Workspace")
        dashboard_mode = st.radio(
            "Dashboard Mode",
            options=["Paper Dashboard", "Engineering Dashboard", "Exploratory Lab"],
            index=0,
            key=f"{key_prefix}_dashboard_mode",
        )
        st.session_state["_dashboard_mode"] = dashboard_mode
        if dashboard_mode == "Paper Dashboard":
            view_options = [
                "Current Structural State",
                "Structural History",
                "Case Replay",
                "Scenario Lab",
                "Operator Sequence",
                "Public Benchmark",
                "Signal Decomposition",
                "Dual-Track Surveillance",
                "Frontier Research Engine",
                "Claim Guard / Evidence Boundary",
            ]
        elif dashboard_mode == "Engineering Dashboard":
            view_options = ["Evidence & Provenance", "Observability & Miss Taxonomy", "Runtime & Cache"]
        else:
            view_options = ["Exploratory Graph Lab", "ML Extensions", "Advanced Operator Diagnostics", "Snapshot JSON"]
        task_key = f"{key_prefix}_task"
        if st.session_state.get(task_key) not in {None, *view_options}:
            st.session_state.pop(task_key, None)
        task = st.radio(
            "View",
            options=view_options,
            index=0,
            key=task_key,
        )
        mode_label = st.radio(
            "Data Source",
            options=["Demo Mock", "Real APIs"],
            index=0 if ctx.data_mode == "demo" else 1,
            key=f"{key_prefix}_data_source",
            horizontal=True,
        )
        selected_mode = "demo" if mode_label == "Demo Mock" else "real"
        if selected_mode != ctx.data_mode:
            st.session_state["_data_mode"] = selected_mode
            st.session_state.pop("_ui_ctx", None)
            st.rerun()

        _render_time_window_control(ctx, key_prefix)
        _render_run_action(ctx, key_prefix)
    return task


def _render_run_action(ctx: UIContext, key_prefix: str) -> None:
    with st.expander("Run", expanded=True):
        run_date = st.date_input("Run Date", value=date.today(), key=f"{key_prefix}_run_date")
        run_type = st.selectbox("Run Type", options=["WEEKLY", "MONTHLY", "EVENT"], index=0, key=f"{key_prefix}_run_type")
        if st.button("Run Pipeline", key=f"{key_prefix}_run_btn", width="stretch"):
            with st.spinner("Running structural pipeline..."):
                run_pipeline_once(ctx, run_date.strftime("%Y-%m-%d"), run_type)
            st.success("Pipeline run completed.")


def _render_time_window_control(ctx: UIContext, key_prefix: str) -> None:
    snapshots = ctx.snapshot_store.load_range("1900-01-01", "2999-12-31")
    dates = sorted(pd.to_datetime(snap.run_date).date() for snap in snapshots)
    fallback_end = date.today()
    fallback_start = fallback_end - timedelta(days=365)
    data_start = dates[0] if dates else fallback_start
    data_end = dates[-1] if dates else fallback_end
    preset = st.selectbox(
        "Time Window",
        options=["Latest year", "Latest 3 years", "Crisis replay", "All available", "Custom"],
        index=0,
        key=f"{key_prefix}_time_preset",
    )
    if preset == "Latest year":
        start, end = max(data_start, data_end - timedelta(days=365)), data_end
    elif preset == "Latest 3 years":
        start, end = max(data_start, data_end - timedelta(days=365 * 3)), data_end
    elif preset == "Crisis replay":
        start, end = date(2007, 1, 1), date(2009, 6, 30)
    elif preset == "All available":
        start, end = data_start, data_end
    else:
        selected = st.date_input(
            "Custom Range",
            value=(data_start, data_end),
            key=f"{key_prefix}_custom_range",
        )
        if isinstance(selected, tuple) and len(selected) == 2:
            start, end = selected
        else:
            start, end = data_start, data_end
    if start > end:
        start, end = end, start
    st.session_state["_snapshot_start"] = start.strftime("%Y-%m-%d")
    st.session_state["_snapshot_end"] = end.strftime("%Y-%m-%d")
    st.caption(f"{start.isoformat()} to {end.isoformat()}")


def render_run_control(ctx: UIContext, key_prefix: str) -> None:
    _ = render_workspace_controls(ctx, key_prefix)


def render_runtime_status(ctx: UIContext) -> None:
    data_cfg = ctx.config.get("data_sources", {})
    ui_cfg = ctx.config.get("ui", {})
    if not isinstance(data_cfg, dict):
        data_cfg = {}
    if not isinstance(ui_cfg, dict):
        ui_cfg = {}
    with st.sidebar.expander("Runtime Speed", expanded=False):
        st.caption("Startup is lazy; pipeline runs only when requested.")
        rows = [
            ("Lazy UI seed", "on" if not bool(ui_cfg.get("seed_on_start", False)) else "off"),
            ("Composite workers", str(data_cfg.get("composite_max_workers", "default"))),
            ("FRED workers", str(data_cfg.get("fred_max_workers", "default"))),
            ("Proxy incremental cache", "on" if bool(data_cfg.get("proxy_incremental_cache", True)) else "off"),
            ("FRED CSV cache", str(data_cfg.get("fred_cache_dir") or resolve_fred_cache_dir(ctx.config))),
            ("Operator match cache", "on"),
        ]
        for label, value in rows:
            st.write(f"**{label}:** {value}")


def list_snapshots(ctx: UIContext) -> list[Snapshot]:
    ui_cfg = ctx.config.get("ui", {})
    if not isinstance(ui_cfg, dict):
        ui_cfg = {}
    start = str(st.session_state.get("_snapshot_start", ui_cfg.get("snapshot_start", "1900-01-01")))
    end = str(st.session_state.get("_snapshot_end", ui_cfg.get("snapshot_end", "2999-12-31")))
    snapshots = ctx.snapshot_store.load_range(start, end)
    return sorted(snapshots, key=lambda snap: snap.run_date)


def latest_snapshot(ctx: UIContext) -> Snapshot | None:
    snapshots = list_snapshots(ctx)
    return snapshots[-1] if snapshots else None


def get_shared_snapshot(ctx: UIContext) -> Snapshot | None:
    """
    Return the latest snapshot, cached in session_state so all pages share the
    same object without redundant store queries within a single Streamlit run.
    """
    cached = st.session_state.get("_shared_snapshot")
    if cached is not None:
        return cached
    snapshot = latest_snapshot(ctx)
    if snapshot is not None:
        st.session_state["_shared_snapshot"] = snapshot
    return snapshot


def invalidate_shared_snapshot() -> None:
    """Call after running the pipeline so the next page load picks up fresh data."""
    st.session_state.pop("_shared_snapshot", None)


def snapshot_archive_frame(snapshots: list[Snapshot]) -> pd.DataFrame:
    rows = [
        {
            "date": snap.run_date,
            "run_type": snap.run_type,
            "pattern": snap.state.pattern,
            "sigma_t": snap.state.sigma_t,
            "singular_flag": snap.state.singular_flag,
            "escalation": snap.escalation,
        }
        for snap in snapshots
    ]
    if not rows:
        return pd.DataFrame(columns=["date", "run_type", "pattern", "sigma_t", "singular_flag", "escalation"])
    return pd.DataFrame.from_records(rows)


def history_frame(snapshots: list[Snapshot]) -> pd.DataFrame:
    rows = [
        {
            "date": snap.run_date,
            "run_type": snap.run_type,
            "M": snap.proxy.M,
            "D": snap.proxy.D,
            "K": snap.proxy.K,
            "X": snap.proxy.X,
            "sigma_t": snap.state.sigma_t,
            "pattern": snap.state.pattern,
            "singular_flag": snap.state.singular_flag,
            "leading_channel": snap.state.leading_channel,
            "reflexivity_flags": dict(snap.state.reflexivity_flags),
            "escalation": snap.escalation,
        }
        for snap in snapshots
    ]
    if not rows:
        return pd.DataFrame(columns=["date", "run_type", "M", "D", "K", "X", "sigma_t", "pattern", "singular_flag", "leading_channel", "reflexivity_flags", "escalation"])
    frame = pd.DataFrame.from_records(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date").reset_index(drop=True)


def ensure_seed_snapshot(ctx: UIContext) -> None:
    ui_cfg = ctx.config.get("ui", {})
    if not isinstance(ui_cfg, dict):
        ui_cfg = {}
    if not bool(ui_cfg.get("seed_on_start", False)):
        return
    if latest_snapshot(ctx) is not None:
        return
    run_pipeline_once(
        ctx,
        run_date=ctx.config.get("default_run_date", date.today().strftime("%Y-%m-%d")),
        run_type=ctx.config.get("default_run_type", "WEEKLY"),
    )


def snapshot_json(snapshot: Snapshot) -> str:
    payload = snapshot_to_dict(snapshot)
    return json.dumps(payload, indent=2, ensure_ascii=False)
