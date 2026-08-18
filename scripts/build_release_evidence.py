#!/usr/bin/env python3
"""Validate clean-room distribution contents and emit release evidence.

This is an artifact inventory and exclusion check, not a security proof.  It
binds the observed archives to the source SHA, ``uv.lock``, Python and
platform, and rejects Data/Output/Paper/symlink/secret material before a
release evidence bundle is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import tarfile
import zipfile
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DISTRIBUTIONS = {
    "structural-deformation-system",
    "structural-deformation-research-system",
    "structural-risk-harvester",
    "structural-workbench",
    "system-learning-hub",
    "system-orchestration",
}
ARCHIVE_SUFFIXES = (".whl", ".tar.gz", ".zip")
FORBIDDEN_COMPONENTS = {"Data", "Output", "Paper", ".git", ".dvc"}
_DIST_NAME_RE = re.compile(r"[-_.]+")


class ReleaseEvidenceError(RuntimeError):
    """Raised when an artifact cannot be certified for inventory purposes."""


def _normalise_distribution(name: str) -> str:
    return _DIST_NAME_RE.sub("-", name).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _lock_digest(root: Path) -> str:
    lock = root / "uv.lock"
    if not lock.is_file():
        raise ReleaseEvidenceError(f"missing lockfile: {lock}")
    return _sha256(lock)


def _safe_archive_member(name: str) -> tuple[bool, str | None]:
    normalised = name.replace("\\", "/")
    parts = [part for part in normalised.split("/") if part not in {"", "."}]
    if normalised.startswith("/") or ".." in parts:
        return False, "absolute or parent-traversal member"
    forbidden = sorted(set(parts) & FORBIDDEN_COMPONENTS)
    if forbidden:
        return False, f"forbidden path component(s): {', '.join(forbidden)}"
    if any(part.lower().startswith(".env") for part in parts):
        return False, "environment file member"
    if any(part.lower() == "secrets" or "secret" in part.lower() for part in parts):
        return False, "secret-like member"
    return True, None


def _archive_members(path: Path) -> Iterable[tuple[str, bool]]:
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                # External attributes contain the Unix file mode for wheels
                # produced by setuptools; a symlink has mode 0120000.
                mode = (info.external_attr >> 16) & 0xF000
                yield info.filename, mode == 0xA000
        return
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for info in archive.getmembers():
                yield info.name, info.issym() or info.islnk()
        return
    raise ReleaseEvidenceError(f"unsupported artifact type: {path}")


def _wheel_metadata(path: Path) -> dict[str, Any]:
    if not path.name.endswith(".whl"):
        return {}
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ReleaseEvidenceError(
                f"wheel must contain exactly one dist-info/METADATA: {path.name}"
            )
        message = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
        return _metadata_fields(message)


def _metadata_fields(message: Any) -> dict[str, Any]:
    return {
        "name": message.get("Name"),
        "version": message.get("Version"),
        "requires_dist": message.get_all("Requires-Dist", []),
    }


def _sdist_metadata(path: Path) -> dict[str, Any]:
    """Read the canonical PKG-INFO identity from a source distribution."""
    with tarfile.open(path, "r:gz") as archive:
        metadata = [
            info
            for info in archive.getmembers()
            if not info.isdir() and info.name.replace("\\", "/").rsplit("/", 1)[-1] == "PKG-INFO"
        ]
        if len(metadata) != 1:
            raise ReleaseEvidenceError(
                f"sdist must contain exactly one PKG-INFO: {path.name}"
            )
        handle = archive.extractfile(metadata[0])
        if handle is None:
            raise ReleaseEvidenceError(f"cannot read sdist metadata: {path.name}")
        message = Parser().parsestr(handle.read().decode("utf-8"))
        return _metadata_fields(message)


def inspect_archive(path: Path) -> dict[str, Any]:
    if not path.is_file() or not path.name.endswith(ARCHIVE_SUFFIXES):
        raise ReleaseEvidenceError(f"not a supported distribution archive: {path}")
    if path.is_symlink():
        raise ReleaseEvidenceError(f"distribution artifact must not be a symlink: {path}")
    violations: list[str] = []
    member_count = 0
    symlink_count = 0
    for name, is_symlink in _archive_members(path):
        member_count += 1
        if is_symlink:
            symlink_count += 1
            violations.append(f"{name}: symlink member")
        safe, reason = _safe_archive_member(name)
        if not safe:
            violations.append(f"{name}: {reason}")
    artifact_format = "wheel" if path.name.endswith(".whl") else (
        "sdist" if path.name.endswith(".tar.gz") else "other"
    )
    metadata = (
        _wheel_metadata(path)
        if artifact_format == "wheel"
        else _sdist_metadata(path)
        if artifact_format == "sdist"
        else {}
    )
    expected_name = metadata.get("name")
    if expected_name is None and path.name.endswith(".whl"):
        raise ReleaseEvidenceError(f"wheel metadata has no Name: {path.name}")
    return {
        "file": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "distribution": expected_name,
        "distribution_normalized": _normalise_distribution(expected_name)
        if expected_name
        else None,
        "format": artifact_format,
        "version": metadata.get("version"),
        "requires_dist": metadata.get("requires_dist", []),
        "member_count": member_count,
        "symlink_count": symlink_count,
        "violations": violations,
    }


def _lock_components(root: Path) -> list[dict[str, str]]:
    try:
        import tomllib

        payload = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseEvidenceError(f"cannot parse uv.lock: {exc}") from exc
    components: list[dict[str, str]] = []
    for package in payload.get("package", []):
        if not isinstance(package, dict):
            continue
        name = package.get("name")
        version = package.get("version")
        if isinstance(name, str) and isinstance(version, str):
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": version,
                    "purl": f"pkg:pypi/{_normalise_distribution(name)}@{version}",
                }
            )
    return sorted(components, key=lambda item: (item["name"].lower(), item["version"]))


def _freeze_components(path: Path) -> list[dict[str, str]]:
    """Parse ``uv pip freeze`` output into CycloneDX library components."""
    components: list[dict[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" not in line:
            raise ReleaseEvidenceError(f"unsupported installed freeze line: {raw_line!r}")
        name, version = (part.strip() for part in line.split("==", 1))
        if not name or not version:
            raise ReleaseEvidenceError(f"invalid installed freeze line: {raw_line!r}")
        normalised = _normalise_distribution(name)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{normalised}@{version}",
            }
        )
    if not components:
        raise ReleaseEvidenceError(f"installed freeze is empty: {path}")
    return sorted(components, key=lambda item: (item["name"].lower(), item["version"]))


def _cyclonedx_sbom(
    *,
    manifest: dict[str, Any],
    components: list[dict[str, str]],
    source: str,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    properties = [
        {"name": "commit", "value": manifest["commit"]},
        {"name": "uv_lock_sha256", "value": manifest["lockfile"]["sha256"]},
        {"name": "python", "value": str(manifest.get("python", "unknown"))},
        {"name": "platform", "value": str(manifest.get("platform", "unknown"))},
        {"name": "evidence_boundary", "value": manifest["evidence_boundary"]},
        {"name": "component_source", "value": source},
    ]
    if source_sha256:
        properties.append({"name": "component_source_sha256", "value": source_sha256})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": (
            f"urn:uuid:{manifest['commit']}-{manifest['lockfile']['sha256'][:16]}-{source}"
        ),
        "metadata": {
            "timestamp": manifest["generated_at"],
            "tools": [{"vendor": "System", "name": "build_release_evidence"}],
            "properties": properties,
        },
        "components": components,
    }


def _output_path(root: Path, path: Path) -> Path:
    target = path.expanduser().resolve()
    for forbidden in ((root / "Data").resolve(), (root / "Output").resolve()):
        if target == forbidden or forbidden in target.parents:
            raise ReleaseEvidenceError("release evidence cannot be written under Data/ or Output/")
    return target


def build_evidence(root: Path, artifact_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    archives = sorted(
        path for path in artifact_dir.iterdir() if path.is_file() and path.name.endswith(ARCHIVE_SUFFIXES)
    )
    if not archives:
        raise ReleaseEvidenceError(f"no distribution archives found in {artifact_dir}")
    artifacts = [inspect_archive(path) for path in archives]
    wheel_names = {
        item["distribution_normalized"]
        for item in artifacts
        if item["format"] == "wheel"
    }
    sdist_names = {
        item["distribution_normalized"]
        for item in artifacts
        if item["format"] == "sdist"
    }
    missing_wheels = sorted(EXPECTED_DISTRIBUTIONS - wheel_names)
    unexpected_wheels = sorted(wheel_names - EXPECTED_DISTRIBUTIONS)
    missing_sdists = sorted(EXPECTED_DISTRIBUTIONS - sdist_names)
    unexpected_sdists = sorted(sdist_names - EXPECTED_DISTRIBUTIONS)
    violations = [
        f"{item['file']}: {violation}"
        for item in artifacts
        for violation in item["violations"]
    ]
    if missing_wheels:
        violations.append("missing expected wheels: " + ", ".join(missing_wheels))
    if unexpected_wheels:
        violations.append("unexpected wheels: " + ", ".join(unexpected_wheels))
    if missing_sdists:
        violations.append("missing expected sdists: " + ", ".join(missing_sdists))
    if unexpected_sdists:
        violations.append("unexpected sdists: " + ", ".join(unexpected_sdists))
    manifest: dict[str, Any] = {
        "schema_version": "system.release_manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": _git_sha(root),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "lockfile": {"path": str(root / "uv.lock"), "sha256": _lock_digest(root)},
        "artifact_dir": str(artifact_dir.resolve()),
        "artifacts": artifacts,
        "expected_distributions": sorted(EXPECTED_DISTRIBUTIONS),
        "violations": violations,
        "verdict": "PASS" if not violations else "BLOCK",
        "evidence_boundary": "artifact_inventory_and_exclusion_scan_not_security_proof",
    }
    sbom = _cyclonedx_sbom(
        manifest=manifest,
        components=_lock_components(root),
        source="uv.lock",
    )
    return manifest, sbom


def build_installed_sbom(
    root: Path,
    freeze_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build a second SBOM from the independent environment's freeze output."""
    freeze = freeze_path.resolve()
    if not freeze.is_file():
        raise ReleaseEvidenceError(f"missing installed freeze: {freeze}")
    for forbidden in ((root / "Data").resolve(), (root / "Output").resolve()):
        if freeze == forbidden or forbidden in freeze.parents:
            raise ReleaseEvidenceError("installed freeze cannot be read from Data/ or Output/")
    return _cyclonedx_sbom(
        manifest=manifest,
        components=_freeze_components(freeze),
        source="installed_environment_freeze",
        source_sha256=_sha256(freeze),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--installed-freeze",
        type=Path,
        help="uv pip freeze output from the independent installed environment",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        manifest, sbom = build_evidence(root, args.artifact_dir.resolve())
        installed_sbom = None
        if args.installed_freeze:
            installed_sbom = build_installed_sbom(root, args.installed_freeze, manifest)
        if args.output_dir:
            if installed_sbom is None:
                raise ReleaseEvidenceError(
                    "--output-dir requires --installed-freeze for installed-environment SBOM"
                )
            output = _output_path(root, args.output_dir)
            output.mkdir(parents=True, exist_ok=True)
            manifest["sbom"] = {
                "lock": "sbom.cdx.json",
                "installed_environment": "sbom-installed.cdx.json",
            }
            (output / "release-manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (output / "sbom.cdx.json").write_text(
                json.dumps(sbom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (output / "sbom-installed.cdx.json").write_text(
                json.dumps(installed_sbom, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0 if manifest["verdict"] == "PASS" else 1
    except (OSError, ReleaseEvidenceError) as exc:
        print(f"release evidence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
