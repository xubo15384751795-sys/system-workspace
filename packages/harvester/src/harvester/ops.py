from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from harvester.core.catalog import load_catalog
from harvester.core.exporter import (
    default_exports_root,
    finalize_release,
    list_releases,
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    severity: str = "error"
    detail: str = ""


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def blockers(self) -> list[str]:
        return [c.detail or c.name for c in self.checks if c.severity == "error" and not c.passed]


def next_release_id(exports_root: Path | str | None = None, *, release_date: date | None = None) -> str:
    day = release_date or datetime.now(UTC).date()
    prefix = day.strftime("%Y-%m-%d")
    highest = 0
    for release in list_releases(exports_root or default_exports_root()):
        if not release.startswith(f"{prefix}-r"):
            continue
        try:
            highest = max(highest, int(release.rsplit("-r", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-r{highest + 1}"


def run_preflight(
    *,
    exports_root: Path | str | None = None,
    providers: list[str] | None = None,
) -> PreflightResult:
    root = Path(exports_root) if exports_root is not None else default_exports_root()
    requested = set(providers or [])
    checks: list[PreflightCheck] = []

    checks.append(PreflightCheck(
        "python_version",
        sys.version_info >= (3, 10),
        detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    ))

    for module in ("pandas", "pyarrow", "requests", "jsonschema"):
        checks.append(_import_check(module))

    checks.append(PreflightCheck(
        "exports_root",
        root.exists() and root.is_dir(),
        detail=str(root),
    ))
    checks.append(PreflightCheck(
        "exports_root_writable",
        _is_writable_dir(root),
        detail=str(root),
    ))

    needs_fred = not requested or bool(requested & {"fred", "openbb_fred"})
    checks.append(PreflightCheck(
        "fred_api_key",
        bool(os.environ.get("FRED_API_KEY") or os.environ.get("OPENBB_FRED_API_KEY")),
        severity="error" if needs_fred else "warn",
        detail="required for FRED-backed providers" if needs_fred else "not required for selected provider set",
    ))

    needs_openbb = bool(requested & {"openbb_fred", "openbb_tiingo"}) or not requested
    checks.append(PreflightCheck(
        "openbb_importable",
        _can_import("openbb"),
        severity="warn",
        detail="required only for OpenBB-backed fallback/provider routes" if needs_openbb else "not required",
    ))

    blockers = [c for c in checks if c.severity == "error" and not c.passed]
    return PreflightResult(passed=not blockers, checks=checks)


def run_daily_release(
    *,
    release_id: str = "",
    as_of_date: str = "",
    vintage_date: str = "",
    exports_root: Path | str | None = None,
    providers: list[str] | None = None,
    cache: bool = True,
    include_external: bool = True,
    notes: str = "",
    preflight: bool = True,
) -> dict[str, Any]:
    from harvester.official import stage_complete_release

    root = Path(exports_root) if exports_root is not None else default_exports_root()
    resolved_release_id = release_id or next_release_id(root)
    resolved_as_of = as_of_date or datetime.now(UTC).date().isoformat()
    resolved_vintage = vintage_date or resolved_as_of

    # Phase 2.1: same-day reuse. If the caller did not explicitly request a
    # new release_id, and ``latest`` already points to a finalized release
    # whose as_of_date is today, return ``reused`` without any network calls.
    # This makes the three nightly schedules (21:30/22:30/07:00) idempotent:
    # whichever succeeds first, the others short-circuit - immune to Yahoo
    # rate-limiting from duplicate runs.
    # NOTE: default release_id is "" (not None); empty means "auto-assign".
    if not release_id:
        reused = _check_same_day_reuse(root, resolved_as_of)
        if reused is not None:
            return reused

    if preflight:
        preflight_result = run_preflight(exports_root=root, providers=providers)
        if not preflight_result.passed:
            report = _write_failure_report(
                root,
                resolved_release_id,
                "preflight_failed",
                {"preflight": _preflight_to_dict(preflight_result)},
            )
            return {
                "release_id": resolved_release_id,
                "status": "failed",
                "reason": "preflight_failed",
                "failure_report": str(report),
                "preflight": _preflight_to_dict(preflight_result),
            }

    try:
        staged = stage_complete_release(
            release_id=resolved_release_id,
            as_of_date=resolved_as_of,
            vintage_date=resolved_vintage,
            exports_root=str(root),
            providers=providers,
            cache=cache,
            include_external=include_external,
            notes=notes,
        )
        finalized = finalize_release(resolved_release_id, exports_root=root, dry_run=False)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        # Phase 0.2: catch BaseException (not just Exception) so SystemExit-style
        # failures also leave a failure report. KeyboardInterrupt is re-raised so
        # Ctrl-C still interrupts cleanly.
        report = _write_failure_report(root, resolved_release_id, "release_failed", {"error": repr(exc)})
        return {
            "release_id": resolved_release_id,
            "status": "failed",
            "reason": "release_failed",
            "failure_report": str(report),
            "error": repr(exc),
        }

    return {
        "release_id": resolved_release_id,
        "status": "finalized",
        "release_dir": str(finalized.release_dir),
        "verified_datasets": finalized.verified_datasets,
        "latest_path": str(finalized.latest_path),
        "staged": staged,
    }


def monitor_latest(
    *,
    exports_root: Path | str | None = None,
    max_age_days: int = 3,
) -> dict[str, Any]:
    root = Path(exports_root) if exports_root is not None else default_exports_root()
    latest = root / "latest"
    checks: list[dict[str, Any]] = []

    _monitor_check(checks, "latest_exists", latest.exists() or latest.is_symlink(), str(latest))
    if not (latest.exists() or latest.is_symlink()):
        return _monitor_result(root, "", checks)

    release_dir = latest.resolve()
    release_id = release_dir.name
    _monitor_check(checks, "latest_points_to_directory", release_dir.is_dir(), str(release_dir))
    _monitor_check(checks, "finalized_marker_present", (release_dir / ".finalized").exists(), str(release_dir / ".finalized"))

    catalog: dict[str, Any] | None = None
    try:
        catalog = load_catalog(release_dir)
        _monitor_check(checks, "catalog_valid", True, str(release_dir / "catalog.json"))
    except Exception as exc:
        _monitor_check(checks, "catalog_valid", False, repr(exc))

    if catalog is not None:
        finalized_at = _parse_datetime(catalog.get("finalized_at", ""))
        if finalized_at is not None:
            age_days = (datetime.now(UTC) - finalized_at).total_seconds() / 86400
            _monitor_check(
                checks,
                "latest_fresh",
                age_days <= max_age_days,
                f"age_days={age_days:.2f}, max_age_days={max_age_days}",
                severity="warn",
            )
        _monitor_check(checks, "datasets_present", len(catalog.get("datasets", [])) > 0, f"datasets={len(catalog.get('datasets', []))}")

    try:
        result = finalize_release(release_id, exports_root=root, dry_run=True)
        _monitor_check(checks, "release_integrity_dry_run", True, f"verified_datasets={result.verified_datasets}")
    except Exception as exc:
        _monitor_check(checks, "release_integrity_dry_run", False, repr(exc))

    return _monitor_result(root, release_id, checks)


def _import_check(module: str) -> PreflightCheck:
    return PreflightCheck(f"import_{module}", _can_import(module), detail=module)


def _can_import(module: str) -> bool:
    try:
        __import__(module)
    except Exception:
        return False
    return True


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".harvester_preflight_write_test"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except Exception:
        return False
    return True


def _check_same_day_reuse(exports_root: Path, as_of_date: str) -> dict[str, Any] | None:
    """Phase 2.1: return a ``reused`` result if ``latest`` already points to a
    finalized release for ``as_of_date``, else None.

    A release counts as same-day if its catalog's as_of_date (or release_id
    date prefix) matches today. No network calls are made.
    """
    latest = exports_root / "latest"
    if not (latest.exists() or latest.is_symlink()):
        return None
    try:
        release_dir = latest.resolve()
        catalog_path = release_dir / "catalog.json"
        if not catalog_path.exists():
            return None
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except OSError:
        return None
    # Finalized marker must be present.
    if not (release_dir / ".finalized").exists():
        return None
    # Match on as_of_date in catalog, or on release_id date prefix.
    # Release ids are usually YYYY-MM-DD-rN; older fixtures may use YYYYMMDD-rN.
    cat_as_of = catalog.get("as_of_date") or ""
    release_id = catalog.get("release_id") or release_dir.name
    compact = as_of_date.replace("-", "")
    same_day = (
        (cat_as_of and cat_as_of == as_of_date)
        or release_id.startswith(f"{as_of_date}-r")
        or release_id.startswith(f"{compact}-r")
    )
    if not same_day:
        return None
    return {
        "release_id": release_id,
        "status": "reused",
        "reason": "same_day_finalized_release_exists",
        "release_dir": str(release_dir),
        "as_of_date": as_of_date,
    }


def _write_failure_report(exports_root: Path, release_id: str, reason: str, detail: dict[str, Any]) -> Path:
    """Write a failure report; never raise (Phase 0.2).

    If the report file itself cannot be written, the payload is printed to
    stderr so the failure is still visible (rather than swallowed, which was
    the six-day "why is there no failure report" root cause).
    """
    path = exports_root / ".failures" / f"{release_id}.{reason}.json"
    payload = {
        "release_id": release_id,
        "reason": reason,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **detail,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        # Report-writing failure must not mask the original error. Print to
        # stderr so the operator at least sees the failure payload.
        import sys as _sys

        print(
            f"[harvester] FAILED to write failure report to {path}; payload:\n"
            + json.dumps(payload, indent=2, sort_keys=True),
            file=_sys.stderr,
        )
    return path


def _monitor_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
    *,
    severity: str = "error",
) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail, "severity": severity})


def _monitor_result(root: Path, release_id: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [c["detail"] or c["name"] for c in checks if c["severity"] == "error" and not c["passed"]]
    warnings = [c["detail"] or c["name"] for c in checks if c["severity"] == "warn" and not c["passed"]]
    return {
        "status": "healthy" if not blockers else "unhealthy",
        "exports_root": str(root),
        "release_id": release_id,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
    }


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _preflight_to_dict(result: PreflightResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "blockers": result.blockers,
        "checks": [asdict(check) for check in result.checks],
    }


__all__ = [
    "PreflightCheck",
    "PreflightResult",
    "monitor_latest",
    "next_release_id",
    "run_daily_release",
    "run_preflight",
]
