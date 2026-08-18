"""Tests for distribution exclusion and release evidence binding."""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import build_release_evidence as release_evidence
from scripts.build_release_evidence import (
    ReleaseEvidenceError,
    build_installed_sbom,
    inspect_archive,
)


def _wheel(path: Path, *, member: str = "pkg/__init__.py") -> None:
    dist = "demo_pkg-1.0.0.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, "")
        archive.writestr(
            f"{dist}/METADATA",
            "Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.0.0\n",
        )


def _sdist(path: Path, *, name: str = "demo-pkg", version: str = "1.0.0") -> None:
    with tarfile.open(path, "w:gz") as archive:
        metadata = tarfile.TarInfo("demo-pkg-1.0.0/demo_pkg.egg-info/PKG-INFO")
        payload = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
        metadata.size = len(payload)
        import io

        archive.addfile(metadata, io.BytesIO(payload))


def test_safe_wheel_has_no_exclusion_violations(tmp_path: Path) -> None:
    artifact = tmp_path / "demo.whl"
    _wheel(artifact)

    report = inspect_archive(artifact)

    assert report["violations"] == []
    assert report["distribution_normalized"] == "demo-pkg"


def test_data_member_is_blocked(tmp_path: Path) -> None:
    artifact = tmp_path / "demo.whl"
    _wheel(artifact, member="Data/raw.csv")

    report = inspect_archive(artifact)

    assert any("forbidden path component" in item for item in report["violations"])


def test_sdist_identity_is_inspected(tmp_path: Path) -> None:
    artifact = tmp_path / "demo-pkg-1.0.0.tar.gz"
    _sdist(artifact)

    report = inspect_archive(artifact)

    assert report["format"] == "sdist"
    assert report["distribution_normalized"] == "demo-pkg"


def test_distribution_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "demo.whl"
    _wheel(target)
    link = tmp_path / "linked.whl"
    link.symlink_to(target)

    with pytest.raises(ReleaseEvidenceError, match="must not be a symlink"):
        inspect_archive(link)


def test_release_inventory_requires_wheel_and_sdist_for_each_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_evidence, "EXPECTED_DISTRIBUTIONS", {"demo-pkg"})
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _wheel(artifacts / "demo-pkg-1.0.0-py3-none-any.whl")
    _sdist(artifacts / "demo-pkg-1.0.0.tar.gz")

    manifest, _ = release_evidence.build_evidence(tmp_path, artifacts)
    assert manifest["verdict"] == "PASS"

    (artifacts / "demo-pkg-1.0.0.tar.gz").unlink()
    incomplete, _ = release_evidence.build_evidence(tmp_path, artifacts)
    assert incomplete["verdict"] == "BLOCK"
    assert any("missing expected sdists" in item for item in incomplete["violations"])


def test_installed_environment_sbom_is_bound_to_freeze_and_lock(tmp_path: Path) -> None:
    freeze = tmp_path / "installed-freeze.txt"
    freeze.write_text("demo-pkg==1.0.0\njsonschema==4.0.0\n", encoding="utf-8")
    manifest = {
        "commit": "a" * 40,
        "generated_at": "2026-08-12T00:00:00Z",
        "python": "3.13.0",
        "platform": "macOS-test",
        "lockfile": {"sha256": "b" * 64},
        "evidence_boundary": "artifact_inventory_and_exclusion_scan_not_security_proof",
    }

    sbom = build_installed_sbom(tmp_path, freeze, manifest)

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert {item["name"] for item in sbom["components"]} == {"demo-pkg", "jsonschema"}
    properties = {item["name"]: item["value"] for item in sbom["metadata"]["properties"]}
    assert properties["component_source"] == "installed_environment_freeze"
    assert len(properties["component_source_sha256"]) == 64
    assert properties["python"] == "3.13.0"
    assert properties["platform"] == "macOS-test"
