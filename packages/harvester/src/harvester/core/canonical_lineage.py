"""Delta + digest storage for canonical observation/chain JSONL.

Short-term stopgap: each release writes only new or revised rows plus a
Merkle digest of the full logical set. Finalize validates the digest chain
instead of rereading multi-gigabyte v1 dumps. Wave 2 replaces this file
store with DuckDB lineage tables.

v1 readers remain valid: each JSONL line is still a
``system.canonical_chain.v1`` record. The v2 envelope describes storage.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "system.canonical_chain.v2"
RECORD_SCHEMA_VERSION = "system.canonical_chain.v1"
LINEAGE_FILENAME_SUFFIX = ".canonical_lineage.v2.json"


class LineageValidationError(ValueError):
    """Raised when a v2 digest chain fails integrity checks."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_observation_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Identity that ignores per-release vintage, snapshot, and capture clocks."""
    return {
        "canonical_series_id": record.get("canonical_series_id"),
        "observed_at": record.get("observed_at"),
        "value": record.get("value"),
        "unit": record.get("unit"),
    }


def upsert_key(record: Mapping[str, Any]) -> tuple[Any, Any]:
    return (record.get("canonical_series_id"), record.get("observed_at"))


def observation_leaf_hash(record: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json(stable_observation_payload(record)).encode("utf-8"))


def chain_leaf_hash(
    record: Mapping[str, Any],
    *,
    measurement_definition: str = "",
    predicate: str = "",
) -> str:
    observation = record.get("observation") if isinstance(record.get("observation"), Mapping) else record
    measurement = record.get("measurement") if isinstance(record.get("measurement"), Mapping) else {}
    claim = record.get("claim") if isinstance(record.get("claim"), Mapping) else {}
    payload = {
        "observation": stable_observation_payload(observation if isinstance(observation, Mapping) else {}),
        "measurement_definition": measurement_definition or measurement.get("measurement_definition"),
        "predicate": predicate or claim.get("predicate"),
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def merkle_root(leaf_hashes: Sequence[str]) -> str:
    nodes = [bytes.fromhex(item) for item in leaf_hashes]
    if not nodes:
        return _sha256_bytes(b"")
    while len(nodes) > 1:
        if len(nodes) % 2 == 1:
            nodes.append(nodes[-1])
        nodes = [
            hashlib.sha256(nodes[index] + nodes[index + 1]).digest()
            for index in range(0, len(nodes), 2)
        ]
    return nodes[0].hex()


def unique_by_upsert(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    merged: dict[tuple[Any, Any], Mapping[str, Any]] = {}
    for record in records:
        observation = record.get("observation") if isinstance(record.get("observation"), Mapping) else record
        merged[upsert_key(observation if isinstance(observation, Mapping) else record)] = record
    return [merged[key] for key in sorted(merged)]


def merkle_from_records(
    records: Sequence[Mapping[str, Any]],
    *,
    kind: str = "observation",
    measurement_definition: str = "",
    predicate: str = "",
) -> str:
    hasher = observation_leaf_hash if kind == "observation" else (
        lambda record: chain_leaf_hash(
            record,
            measurement_definition=measurement_definition,
            predicate=predicate,
        )
    )
    leaves = sorted(hasher(record) for record in unique_by_upsert(records))
    return merkle_root(leaves)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    path.write_text(payload, encoding="utf-8")
    return sha256_file(path)


def lineage_relpath(dataset_id: str) -> str:
    return f"provenance/{dataset_id}{LINEAGE_FILENAME_SUFFIX}"


def lineage_path(release_dir: Path, dataset_id: str) -> Path:
    return release_dir / "provenance" / f"{dataset_id}{LINEAGE_FILENAME_SUFFIX}"


def _release_sort_key(name: str) -> tuple[str, int]:
    date_part, sep, rev = name.rpartition("-r")
    if not sep:
        return (name, 0)
    try:
        return (date_part, int(rev))
    except ValueError:
        return (name, 0)


def find_previous_release_dir(
    exports_root: Path | str | None,
    release_id: str,
    dataset_id: str,
) -> Path | None:
    if exports_root is None:
        return None
    root = Path(exports_root)
    if not root.is_dir():
        return None
    latest = root / "latest"
    if latest.exists() or latest.is_symlink():
        try:
            resolved = latest.resolve()
            jsonl = resolved / "provenance" / f"{dataset_id}.canonical_observations.jsonl"
            if resolved.name != release_id and jsonl.is_file():
                return resolved
        except OSError:
            pass
    candidates: list[Path] = []
    for path in root.iterdir():
        if not path.is_dir() or path.name in {release_id, "latest"} or path.name.startswith("."):
            continue
        jsonl = path / "provenance" / f"{dataset_id}.canonical_observations.jsonl"
        if jsonl.is_file():
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda item: _release_sort_key(item.name))


def load_lineage(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    return payload


def _index_from_records(records: Iterable[Mapping[str, Any]]) -> dict[tuple[Any, Any], str]:
    index: dict[tuple[Any, Any], str] = {}
    for record in records:
        index[upsert_key(record)] = observation_leaf_hash(record)
    return index


def previous_observation_index(previous_dir: Path, dataset_id: str) -> dict[tuple[Any, Any], str]:
    rebuilt = rebuild_observations(previous_dir, dataset_id)
    return _index_from_records(rebuilt)


def select_delta(
    observations: Sequence[Mapping[str, Any]],
    previous_index: Mapping[tuple[Any, Any], str] | None,
) -> list[Mapping[str, Any]]:
    if not previous_index:
        return list(observations)
    delta: list[Mapping[str, Any]] = []
    for record in observations:
        key = upsert_key(record)
        digest = observation_leaf_hash(record)
        if previous_index.get(key) != digest:
            delta.append(record)
    return delta


def rebuild_observations(release_dir: Path, dataset_id: str) -> list[dict[str, Any]]:
    """Reconstruct the full logical observation set from a v1 dump or v2 delta chain."""
    lineage = load_lineage(lineage_path(release_dir, dataset_id))
    jsonl = release_dir / "provenance" / f"{dataset_id}.canonical_observations.jsonl"
    if lineage is None or str(lineage.get("storage_mode") or "") == "full":
        return list(iter_jsonl(jsonl))
    previous_id = lineage.get("previous_release_id")
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    if previous_id:
        previous_dir = release_dir.parent / str(previous_id)
        if previous_dir.is_dir():
            for record in rebuild_observations(previous_dir, dataset_id):
                merged[upsert_key(record)] = record
    for record in iter_jsonl(jsonl):
        merged[upsert_key(record)] = record
    for tombstone in lineage.get("tombstones") or []:
        if isinstance(tombstone, Mapping):
            merged.pop((tombstone.get("canonical_series_id"), tombstone.get("observed_at")), None)
    return [merged[key] for key in sorted(merged)]


def rebuild_chains(release_dir: Path, dataset_id: str) -> list[dict[str, Any]]:
    lineage = load_lineage(lineage_path(release_dir, dataset_id))
    jsonl = release_dir / "provenance" / f"{dataset_id}.canonical_chains.jsonl"
    if lineage is None or str(lineage.get("storage_mode") or "") == "full":
        return list(iter_jsonl(jsonl))
    previous_id = lineage.get("previous_release_id")
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    if previous_id:
        previous_dir = release_dir.parent / str(previous_id)
        if previous_dir.is_dir():
            for record in rebuild_chains(previous_dir, dataset_id):
                observation = record.get("observation") if isinstance(record.get("observation"), Mapping) else {}
                merged[upsert_key(observation)] = record
    for record in iter_jsonl(jsonl):
        observation = record.get("observation") if isinstance(record.get("observation"), Mapping) else {}
        merged[upsert_key(observation)] = record
    for tombstone in lineage.get("tombstones") or []:
        if isinstance(tombstone, Mapping):
            merged.pop((tombstone.get("canonical_series_id"), tombstone.get("observed_at")), None)
    return [merged[key] for key in sorted(merged)]


@dataclass(frozen=True)
class LineageWrite:
    lineage: dict[str, Any]
    observation_relpath: str
    chain_relpath: str
    delta_observations: list[Mapping[str, Any]]
    provenance_fields: dict[str, Any]


def write_canonical_lineage(
    *,
    release_dir: Path,
    dataset_id: str,
    release_id: str,
    observations: Sequence[Mapping[str, Any]],
    chains: Sequence[Mapping[str, Any]] | None = None,
    chain_builder: Callable[[Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]] | None = None,
    exports_root: Path | str | None = None,
    measurement_definition: str = "",
    predicate: str = "",
) -> LineageWrite:
    previous_dir = find_previous_release_dir(exports_root or release_dir.parent, release_id, dataset_id)
    previous_id = previous_dir.name if previous_dir is not None else None
    previous_index = previous_observation_index(previous_dir, dataset_id) if previous_dir is not None else {}
    previous_obs_root = ""
    previous_chain_root = ""
    if previous_dir is not None:
        previous_lineage = load_lineage(lineage_path(previous_dir, dataset_id))
        if previous_lineage:
            previous_obs_root = str((previous_lineage.get("observations") or {}).get("merkle_root") or "")
            previous_chain_root = str((previous_lineage.get("chains") or {}).get("merkle_root") or "")
        else:
            previous_obs = list(iter_jsonl(previous_dir / "provenance" / f"{dataset_id}.canonical_observations.jsonl"))
            previous_chains = list(iter_jsonl(previous_dir / "provenance" / f"{dataset_id}.canonical_chains.jsonl"))
            previous_obs_root = merkle_from_records(previous_obs, kind="observation")
            previous_chain_root = merkle_from_records(
                previous_chains,
                kind="chain",
                measurement_definition=measurement_definition,
                predicate=predicate,
            )
    delta_observations = select_delta(observations, previous_index)
    storage_mode = "delta" if previous_dir is not None else "full"
    if storage_mode == "full":
        delta_observations = list(observations)
    if chain_builder is not None:
        delta_chains = list(chain_builder(delta_observations))
    else:
        delta_keys = {upsert_key(record) for record in delta_observations}
        delta_chains = [
            record
            for record in (chains or [])
            if upsert_key(record.get("observation") if isinstance(record.get("observation"), Mapping) else {})
            in delta_keys
        ]

    observation_relpath = f"provenance/{dataset_id}.canonical_observations.jsonl"
    chain_relpath = f"provenance/{dataset_id}.canonical_chains.jsonl"
    obs_sha = write_jsonl(release_dir / observation_relpath, delta_observations)
    chain_sha = write_jsonl(release_dir / chain_relpath, delta_chains)
    logical_observations = unique_by_upsert(observations)
    current_keys = {upsert_key(record) for record in logical_observations}
    tombstones = [
        {"canonical_series_id": key[0], "observed_at": key[1]}
        for key in sorted(set(previous_index) - current_keys)
        if key[0] is not None and key[1] is not None
    ]
    obs_root = merkle_from_records(logical_observations, kind="observation")
    chain_root = merkle_root(
        sorted(
            chain_leaf_hash(
                record,
                measurement_definition=measurement_definition,
                predicate=predicate,
            )
            for record in logical_observations
        )
    )
    lineage: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "release_id": release_id,
        "storage_mode": storage_mode,
        "wave2_successor": "duckdb_lineage_tables",
        "observations": {
            "path": observation_relpath,
            "mode": storage_mode,
            "delta_count": len(delta_observations),
            "full_count": len(logical_observations),
            "sha256": obs_sha,
            "merkle_root": obs_root,
        },
        "chains": {
            "path": chain_relpath,
            "mode": storage_mode,
            "delta_count": len(delta_chains),
            "full_count": len(logical_observations),
            "sha256": chain_sha,
            "merkle_root": chain_root,
        },
    }
    if previous_id:
        lineage["previous_release_id"] = previous_id
    if previous_obs_root:
        lineage["previous_observation_merkle_root"] = previous_obs_root
    if previous_chain_root:
        lineage["previous_chain_merkle_root"] = previous_chain_root
    if tombstones:
        lineage["tombstones"] = tombstones
    target = lineage_path(release_dir, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    provenance_fields = {
        "canonical_observation_path": observation_relpath,
        "canonical_observation_count": len(logical_observations),
        "canonical_chain_path": chain_relpath,
        "canonical_chain_count": len(logical_observations),
        "canonical_schema_version": SCHEMA_VERSION,
        "canonical_lineage_path": lineage_relpath(dataset_id),
        "previous_release_id": previous_id,
        "canonical_observation_delta_count": len(delta_observations),
        "canonical_chain_delta_count": len(delta_chains),
        "canonical_observation_merkle_root": obs_root,
        "canonical_chain_merkle_root": chain_root,
    }
    return LineageWrite(
        lineage=lineage,
        observation_relpath=observation_relpath,
        chain_relpath=chain_relpath,
        delta_observations=list(delta_observations),
        provenance_fields=provenance_fields,
    )


def validate_digest_chain(
    release_dir: Path,
    dataset_id: str,
    provenance: Mapping[str, Any],
    *,
    validate_observation: Callable[[Mapping[str, Any]], None] | None = None,
    validate_chain: Callable[[Mapping[str, Any]], None] | None = None,
) -> None:
    """Validate v2 digest + delta. Does not reread a reconstructed full set."""
    relpath = provenance.get("canonical_lineage_path")
    if not relpath:
        raise LineageValidationError(f"canonical lineage path missing for {dataset_id}")
    payload = load_lineage(release_dir / str(relpath))
    if payload is None:
        raise LineageValidationError(f"canonical lineage missing for {dataset_id}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LineageValidationError(f"canonical lineage schema mismatch for {dataset_id}")
    for section_name, validator in (
        ("observations", validate_observation),
        ("chains", validate_chain),
    ):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            raise LineageValidationError(f"canonical lineage {section_name} missing for {dataset_id}")
        path = release_dir / str(section["path"])
        if not path.is_file():
            raise LineageValidationError(f"canonical {section_name} sidecar missing for {dataset_id}: {path}")
        actual_sha = sha256_file(path)
        if actual_sha != section.get("sha256"):
            raise LineageValidationError(f"canonical {section_name} sha256 mismatch for {dataset_id}")
        actual_count = 0
        for record in iter_jsonl(path):
            if validator is not None:
                validator(record)
            actual_count += 1
        if actual_count != int(section.get("delta_count") or 0):
            raise LineageValidationError(
                f"canonical {section_name} delta count mismatch for {dataset_id}: "
                f"declared={section.get('delta_count')}, actual={actual_count}"
            )
        merkle = str(section.get("merkle_root") or "")
        if len(merkle) != 64:
            raise LineageValidationError(f"canonical {section_name} merkle_root invalid for {dataset_id}")
    previous_id = payload.get("previous_release_id")
    if previous_id:
        previous_dir = release_dir.parent / str(previous_id)
        if not previous_dir.is_dir():
            raise LineageValidationError(f"previous_release_id not found for {dataset_id}: {previous_id}")
        previous_lineage = load_lineage(lineage_path(previous_dir, dataset_id))
        if previous_lineage is not None:
            prev_obs = (previous_lineage.get("observations") or {}).get("merkle_root")
            if prev_obs and prev_obs != payload.get("previous_observation_merkle_root"):
                raise LineageValidationError(
                    f"observation digest chain break for {dataset_id}: {previous_id}"
                )
            prev_chain = (previous_lineage.get("chains") or {}).get("merkle_root")
            if prev_chain and prev_chain != payload.get("previous_chain_merkle_root"):
                raise LineageValidationError(
                    f"chain digest chain break for {dataset_id}: {previous_id}"
                )
        else:
            previous_jsonl = previous_dir / "provenance" / f"{dataset_id}.canonical_observations.jsonl"
            if not previous_jsonl.is_file():
                raise LineageValidationError(
                    f"previous v1 observation sidecar missing for {dataset_id}: {previous_id}"
                )
    declared_full = provenance.get("canonical_observation_count")
    actual_full = (payload.get("observations") or {}).get("full_count")
    if declared_full is not None and int(declared_full) != int(actual_full or 0):
        raise LineageValidationError(
            f"canonical observation full count mismatch for {dataset_id}"
        )


def verify_rebuild_matches_digest(release_dir: Path, dataset_id: str) -> dict[str, Any]:
    lineage = load_lineage(lineage_path(release_dir, dataset_id))
    observations = rebuild_observations(release_dir, dataset_id)
    chains = rebuild_chains(release_dir, dataset_id)
    obs_root = merkle_from_records(observations, kind="observation")
    chain_root = merkle_from_records(chains, kind="chain")
    expected_obs = (lineage or {}).get("observations", {}).get("merkle_root") if lineage else obs_root
    expected_chain = (lineage or {}).get("chains", {}).get("merkle_root") if lineage else chain_root
    if lineage is None:
        expected_obs = obs_root
        expected_chain = chain_root
    return {
        "dataset_id": dataset_id,
        "release_id": release_dir.name,
        "schema_version": (lineage or {}).get("schema_version") or RECORD_SCHEMA_VERSION,
        "observation_count": len(observations),
        "chain_count": len(chains),
        "observation_merkle_root": obs_root,
        "chain_merkle_root": chain_root,
        "observation_digest_match": obs_root == expected_obs,
        "chain_digest_match": chain_root == expected_chain,
    }


__all__ = [
    "LINEAGE_FILENAME_SUFFIX",
    "LineageValidationError",
    "LineageWrite",
    "RECORD_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "chain_leaf_hash",
    "find_previous_release_dir",
    "iter_jsonl",
    "lineage_path",
    "lineage_relpath",
    "load_lineage",
    "merkle_from_records",
    "merkle_root",
    "observation_leaf_hash",
    "previous_observation_index",
    "rebuild_chains",
    "rebuild_observations",
    "select_delta",
    "sha256_file",
    "unique_by_upsert",
    "stable_observation_payload",
    "upsert_key",
    "validate_digest_chain",
    "verify_rebuild_matches_digest",
    "write_canonical_lineage",
    "write_jsonl",
]
