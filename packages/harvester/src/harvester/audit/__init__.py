"""DuckDB-based audit index for finalized Harvester releases.

DuckDB is a read-only projection of the immutable release artifacts.
The source of truth remains exports/<release_id>/catalog.json, manifests,
provenance files, and data files.  The index is fully rebuildable from
those artifacts and holds no original data that cannot be reconstructed.
"""

from harvester.audit.index import (
    AuditIndex,
    build_index,
    diff_releases,
    query_index,
    rebuild_index,
)

__all__ = [
    "AuditIndex",
    "build_index",
    "diff_releases",
    "query_index",
    "rebuild_index",
]
