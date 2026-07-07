from __future__ import annotations

import pandas as pd

from system_learning.cartography.scanner import FileScan


def dependency_edges(scans: list[FileScan]) -> pd.DataFrame:
    local_modules = {scan.module for scan in scans if scan.kind == "python" and scan.module}
    rows = []
    for scan in scans:
        if scan.kind != "python":
            continue
        for imported in scan.imports:
            target = resolve_local_import(imported, local_modules)
            if target:
                rows.append(
                    {
                        "source_path": scan.rel_path,
                        "source_module": scan.module,
                        "target_module": target,
                        "raw_import": imported,
                    }
                )
    return pd.DataFrame(rows, columns=["source_path", "source_module", "target_module", "raw_import"])


def resolve_local_import(raw_import: str, local_modules: set[str]) -> str:
    if raw_import.startswith("."):
        return ""
    candidates = [module for module in local_modules if raw_import == module or raw_import.startswith(f"{module}.") or module.startswith(f"{raw_import}.")]
    if not candidates:
        return ""
    return sorted(candidates, key=len)[0]
