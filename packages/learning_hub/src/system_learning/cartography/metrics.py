from __future__ import annotations

from collections import defaultdict

import pandas as pd

from system_learning.cartography.scanner import FileScan


def file_metrics(scans: list[FileScan]) -> pd.DataFrame:
    rows = [
        {
            "path": scan.rel_path,
            "directory": directory_key(scan.rel_path),
            "kind": scan.kind,
            "module": scan.module,
            "lines": scan.lines,
            "loc": scan.loc,
            "classes": scan.classes,
            "functions": scan.functions,
            "imports": len(scan.imports),
            "parse_error": scan.parse_error,
        }
        for scan in scans
    ]
    return pd.DataFrame(rows)


def module_metrics(scans: list[FileScan]) -> pd.DataFrame:
    grouped: dict[str, dict] = defaultdict(lambda: {
        "directory": "",
        "file_count": 0,
        "python_files": 0,
        "config_files": 0,
        "doc_files": 0,
        "total_lines": 0,
        "loc": 0,
        "classes": 0,
        "functions": 0,
        "imports": 0,
        "largest_file_path": "",
        "largest_file_lines": 0,
    })
    for scan in scans:
        directory = directory_key(scan.rel_path)
        row = grouped[directory]
        row["directory"] = directory
        row["file_count"] += 1
        row[f"{scan.kind}_files"] = row.get(f"{scan.kind}_files", 0) + 1
        row["total_lines"] += scan.lines
        row["loc"] += scan.loc
        row["classes"] += scan.classes
        row["functions"] += scan.functions
        row["imports"] += len(scan.imports)
        if scan.lines > row["largest_file_lines"]:
            row["largest_file_lines"] = scan.lines
            row["largest_file_path"] = scan.rel_path
    columns = [
        "directory",
        "file_count",
        "python_files",
        "config_files",
        "doc_files",
        "total_lines",
        "loc",
        "classes",
        "functions",
        "imports",
        "largest_file_path",
        "largest_file_lines",
    ]
    return pd.DataFrame(grouped.values(), columns=columns).sort_values(["loc", "total_lines"], ascending=False).reset_index(drop=True)


def complexity_hotspots(scans: list[FileScan], limit: int = 50) -> pd.DataFrame:
    df = file_metrics(scans)
    if df.empty:
        return df
    df = df[df["kind"] == "python"].copy()
    if df.empty:
        return df
    df["hotspot_score"] = df["loc"] + df["functions"] * 20 + df["classes"] * 30 + df["imports"] * 5
    return df.sort_values("hotspot_score", ascending=False).head(limit).reset_index(drop=True)


def summary_counts(scans: list[FileScan]) -> dict[str, int]:
    return {
        "files": len(scans),
        "python_files": sum(scan.kind == "python" for scan in scans),
        "config_files": sum(scan.kind == "config" for scan in scans),
        "doc_files": sum(scan.kind == "docs" for scan in scans),
        "lines": sum(scan.lines for scan in scans),
        "loc": sum(scan.loc for scan in scans),
        "classes": sum(scan.classes for scan in scans),
        "functions": sum(scan.functions for scan in scans),
        "imports": sum(len(scan.imports) for scan in scans),
    }


def directory_key(rel_path: str) -> str:
    parts = rel_path.split("/")
    if len(parts) <= 1:
        return "."
    return "/".join(parts[:-1])
