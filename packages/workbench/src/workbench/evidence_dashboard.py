from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Any

import pandas as pd

from workbench.freshness import (
    banner_lines,
    build_release_freshness_manifest,
    series_matches,
    write_release_freshness_manifest,
)

ROOT = _workspace_root()
OUTPUT = ROOT / "Output"
WORKBENCH = OUTPUT / "workbench" / "benchmark_evidence"
CURRENT = OUTPUT / "current"
HARVESTER_LATEST = ROOT / "Data" / "harvester" / "exports" / "latest"

DESIRED_SERIES = [
    "NFCI",
    "VIXCLS",
    "MOVE",
    "STLFSI4",
    "OFR_FSI",
    "BAMLH0A0HYM2",
    "TEDRATE",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_provenance(release: Path) -> list[dict[str, Any]]:
    """Read provenance records from either old (single .jsonl) or new (per-dataset .json) format."""
    legacy = release / "provenance.jsonl"
    if legacy.exists():
        return _read_jsonl(legacy)
    records: list[dict[str, Any]] = []
    for p in sorted((release / "provenance").glob("*.provenance.json")):
        records.append(_read_json(p))
    return records


def _source_lookup(source_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for source in source_registry.get("sources", []) or []:
        for series in source.get("series", []) or []:
            sid = str(series.get("source_series_id") or series.get("series_id") or "")
            if sid:
                out[sid] = series
    return out


def _resolve_catalog_panel(catalog: dict[str, Any], release: Path) -> Path:
    """Resolve benchmark_panel path from catalog, handling both old and new formats."""
    # New format: datasets[].dataset_id == "benchmark_panel"
    for ds in catalog.get("datasets", []) or []:
        if ds.get("dataset_id") == "benchmark_panel":
            return release / ds["data_path"]
    # Old format: files[].role == "benchmark_panel"
    for item in catalog.get("files", []) or []:
        if item.get("role") == "benchmark_panel":
            return release / item["path"]
    raise FileNotFoundError("No benchmark_panel found in Harvester catalog")


def _point_at_or_before(frame: pd.DataFrame, date: pd.Timestamp) -> float | None:
    subset = frame[frame["date"] <= date].dropna(subset=["value"])
    if subset.empty:
        return None
    return float(subset.sort_values("date").iloc[-1]["value"])


def _series_summary(
    panel: pd.DataFrame,
    series_id: str,
    sources: dict[str, dict[str, Any]],
    freshness_by_series: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    freshness = freshness_by_series.get(series_id, {})
    part = panel[series_matches(panel, series_id)].copy()
    if part.empty:
        return {
            "series_id": series_id,
            "status": "missing",
            "freshness_status": freshness.get("freshness_status", "missing"),
            "latest_date": None,
            "observation_date": None,
            "vintage_date": None,
            "evidence_created_at": freshness.get("evidence_created_at"),
            "latest_value": None,
            "unit": None,
            "frequency": None,
            "source_id": None,
            "source_url": None,
            "quality_flag": None,
            "missing_reason": freshness.get("missing_reason"),
            "retired_reason": freshness.get("retired_reason"),
            "change_30d": None,
            "change_90d": None,
            "observations": 0,
            "provider_payload": {},
        }

    part["date"] = pd.to_datetime(part["date"])
    part = part.dropna(subset=["value"]).sort_values("date")
    latest = part.iloc[-1]
    latest_date = pd.Timestamp(latest["date"])
    latest_value = float(latest["value"])
    source_series_id = str(latest.get("source_series_id") or series_id)
    source = sources.get(source_series_id, {})
    value_30d = _point_at_or_before(part, latest_date - pd.Timedelta(days=30))
    value_90d = _point_at_or_before(part, latest_date - pd.Timedelta(days=90))
    return {
        "series_id": series_id,
        "status": freshness.get("freshness_status") if freshness.get("freshness_status") == "retired_or_unavailable" else "available",
        "freshness_status": freshness.get("freshness_status", "fresh"),
        "latest_date": latest_date.date().isoformat(),
        "observation_date": freshness.get("observation_date") or latest_date.date().isoformat(),
        "vintage_date": freshness.get("vintage_date"),
        "evidence_created_at": freshness.get("evidence_created_at"),
        "latest_value": latest_value,
        "unit": str(latest.get("unit") or ""),
        "frequency": str(latest.get("frequency") or ""),
        "source_id": str(latest.get("source_id") or ""),
        "source_url": source.get("url"),
        "quality_flag": str(latest.get("quality_flag") or ""),
        "missing_reason": freshness.get("missing_reason"),
        "retired_reason": freshness.get("retired_reason"),
        "change_30d": latest_value - value_30d if value_30d is not None else None,
        "change_90d": latest_value - value_90d if value_90d is not None else None,
        "observations": int(len(part)),
        "provider_payload": {
            "source_series_id": source_series_id,
            "provider": source.get("provider"),
            "description": source.get("description"),
            "raw_sha256": source.get("raw_sha256"),
        },
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _render_markdown(payload: dict[str, Any]) -> str:
    rows = payload["series"]
    lines = [
        "# Benchmark + Evidence Dashboard",
        "",
        "This is a Workbench tool surface. It shows public evidence and provenance without requiring the Structural Deformation Framework.",
        "",
        "## Provider Release",
        f"- Release: `{payload['provider_release']}`",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Source catalog: `{payload['source_catalog']}`",
        f"- Evidence panel: `{payload['evidence_panel']}`",
        f"- Freshness manifest: `{payload['freshness_manifest']}`",
        "",
        "## Data Recency",
        *[f"- {line}" for line in banner_lines(payload["freshness"])],
        "",
        "## Evidence Coverage",
        "",
        "| Series | Status | Freshness | Observation date | Vintage date | Latest value | Source | Quality | Reason |",
        "|---|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        source = row.get("source_id") or "n/a"
        if row.get("source_url"):
            source = f"[{source}]({row['source_url']})"
        lines.append(
            "| "
            + " | ".join(
                [
                    row["series_id"],
                    row["status"],
                    row.get("freshness_status") or "n/a",
                    _fmt(row.get("observation_date")),
                    _fmt(row.get("vintage_date")),
                    _fmt(row.get("latest_value")),
                    source,
                    _fmt(row.get("quality_flag")),
                    _fmt(row.get("missing_reason") or row.get("retired_reason")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Rule",
            "Benchmarks are evidence and comparison surfaces. They do not define any framework core by default.",
            "",
        ]
    )
    if payload.get("chart_path"):
        lines.extend(["## Chart", "", f"![benchmark evidence]({Path(payload['chart_path']).name})", ""])
    return "\n".join(lines)


def _render_html(payload: dict[str, Any], markdown_path: Path) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{row['series_id']}</td>"
        f"<td>{row['status']}</td>"
        f"<td>{_fmt(row.get('freshness_status'))}</td>"
        f"<td>{_fmt(row.get('observation_date'))}</td>"
        f"<td>{_fmt(row.get('vintage_date'))}</td>"
        f"<td>{_fmt(row.get('latest_value'))}</td>"
        f"<td>{_fmt(row.get('source_id'))}</td>"
        f"<td>{_fmt(row.get('quality_flag'))}</td>"
        f"<td>{_fmt(row.get('missing_reason') or row.get('retired_reason'))}</td>"
        "</tr>"
        for row in payload["series"]
    )
    recency = "".join(f"<li>{line}</li>" for line in banner_lines(payload["freshness"]))
    chart = ""
    if payload.get("chart_path"):
        chart = f'<section><h2>Chart</h2><img src="{Path(payload["chart_path"]).name}" alt="Benchmark evidence chart"></section>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Benchmark + Evidence Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #172026; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #d8dee4; padding: 8px 10px; text-align: left; }}
    th {{ background: #f6f8fa; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #d8dee4; }}
    code {{ background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Benchmark + Evidence Dashboard</h1>
  <p>This Workbench surface shows public evidence and provenance without requiring framework concepts.</p>
  <h2>Provider Release</h2>
  <ul>
    <li>Release: <code>{payload['provider_release']}</code></li>
    <li>Generated at: <code>{payload['generated_at']}</code></li>
    <li>Markdown: <code>{markdown_path.relative_to(ROOT)}</code></li>
    <li>Freshness manifest: <code>{payload['freshness_manifest']}</code></li>
  </ul>
  <h2>Data Recency</h2>
  <ul>{recency}</ul>
  <h2>Evidence Coverage</h2>
  <table>
    <thead><tr><th>Series</th><th>Status</th><th>Freshness</th><th>Observation date</th><th>Vintage date</th><th>Latest value</th><th>Source</th><th>Quality</th><th>Reason</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {chart}
  <h2>Rule</h2>
  <p>Benchmarks are evidence and comparison surfaces. They do not define any framework core by default.</p>
</body>
</html>
"""


def _write_chart(panel: pd.DataFrame, output_path: Path) -> str | None:
    mask = pd.Series(False, index=panel.index)
    for series_id in DESIRED_SERIES:
        mask = mask | series_matches(panel, series_id)
    available = panel[mask].copy()
    if available.empty:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    available["date"] = pd.to_datetime(available["date"])
    recent = available[available["date"] >= available["date"].max() - pd.Timedelta(days=365 * 3)]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for series_id, part in recent.groupby("series_id"):
        part = part.dropna(subset=["value"]).sort_values("date")
        if part.empty:
            continue
        values = part["value"].astype(float)
        std = values.std()
        normalized = values - values.mean() if std == 0 else (values - values.mean()) / std
        ax.plot(part["date"], normalized, linewidth=1.4, label=series_id)
    ax.set_title("Public Benchmark Evidence, normalized")
    ax.set_ylabel("z-score")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return str(output_path.relative_to(ROOT))


def _safe_unlink(path: Path) -> None:
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            raise RuntimeError(f"Refusing to remove real directory: {path}")
        path.unlink()


def _link_current(target: Path, name: str) -> None:
    CURRENT.mkdir(parents=True, exist_ok=True)
    link = CURRENT / name
    _safe_unlink(link)
    link.symlink_to(Path("..") / "workbench" / "benchmark_evidence" / target.name)


def build() -> dict[str, Any]:
    WORKBENCH.mkdir(parents=True, exist_ok=True)
    release = HARVESTER_LATEST.resolve()
    catalog = _read_json(release / "catalog.json")
    source_registry_path = release / "source_registry.json"
    source_registry = _read_json(source_registry_path) if source_registry_path.exists() else {}
    sources = _source_lookup(source_registry)
    panel_path = _resolve_catalog_panel(catalog, release)
    panel = pd.read_parquet(panel_path)
    freshness_manifest = build_release_freshness_manifest(release)
    freshness_manifest_path = WORKBENCH / "freshness_manifest.json"
    freshness_manifest_path.write_text(json.dumps(freshness_manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    freshness_by_series = {item["series_id"]: item for item in freshness_manifest["indicators"]}
    series = [_series_summary(panel, series_id, sources, freshness_by_series) for series_id in DESIRED_SERIES]
    chart_path = _write_chart(panel, WORKBENCH / "benchmark_evidence.png")
    payload = {
        "schema_version": "workbench.evidence_panel.v1",
        "provider_release": release.name,
        "generated_at": _now(),
        "source_catalog": str((release / "catalog.json").relative_to(ROOT)),
        "evidence_panel": str(panel_path.relative_to(ROOT)),
        "provenance": str((release / "provenance.jsonl").relative_to(ROOT)),
        "freshness_manifest": str(freshness_manifest_path.relative_to(ROOT)),
        "freshness": freshness_manifest,
        "chart_path": chart_path,
        "series": series,
        "provider_payload": {
            "catalog": catalog,
            "provenance_records": _read_provenance(release),
        },
    }
    json_path = WORKBENCH / "benchmark_evidence_dashboard.json"
    md_path = WORKBENCH / "benchmark_evidence_dashboard.md"
    html_path = WORKBENCH / "benchmark_evidence_dashboard.html"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    html_path.write_text(_render_html(payload, md_path), encoding="utf-8")
    _link_current(md_path, "benchmark_evidence_dashboard.md")
    _link_current(html_path, "benchmark_evidence_dashboard.html")
    return {"json": json_path, "markdown": md_path, "html": html_path, "chart": chart_path}


def main() -> None:
    paths = build()
    print("Done.")
    print("Benchmark + Evidence Dashboard:")
    print(f"  Markdown: {paths['markdown'].relative_to(ROOT)}")
    print(f"  HTML:     {paths['html'].relative_to(ROOT)}")
    print(f"  JSON:     {paths['json'].relative_to(ROOT)}")
    print("Commands:")
    print("  ./sys evidence")
    print("  ./sys current")


if __name__ == "__main__":
    main()
