#!/usr/bin/env python3
"""Unified test runner for the entire System workspace.

Runs tests in each module separately to avoid root pytest pretending
all tests pass when some modules may have import issues.

Usage:
    python scripts/run_all_tests.py           # Run all modules
    python scripts/run_all_tests.py --module workbench  # Run specific module
    python scripts/run_all_tests.py --verbose  # Verbose output
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Module test configurations
MODULES = {
    "root": {
        "path": ROOT,
        "pattern": "tests/",
        "description": "Root governance & integration tests",
    },
    "workbench": {
        "path": ROOT / "Workbench",
        "pattern": "tests/",
        "description": "Workbench user-facing tests",
    },
    "deformation": {
        "path": ROOT / "deformation-framework",
        "pattern": "tests/",
        "description": "Deformation Framework tests",
    },
    "harvester": {
        "path": ROOT / "structural-risk-harvester",
        "pattern": "tests/",
        "description": "Harvester provider tests",
    },
    "learning_hub": {
        "path": ROOT / "system-learning-hub",
        "pattern": "tests/",
        "description": "Learning Hub governance tests",
    },
    "qlib": {
        "path": ROOT / "ExternalTools" / "qlib_benchmark_runner",
        "pattern": "tests/",
        "description": "Qlib benchmark tests",
    },
}


def run_module_tests(module_name: str, config: dict, verbose: bool = False) -> dict:
    """Run tests for a single module."""
    path = config["path"]
    test_path = path / config["pattern"]

    if not test_path.exists():
        return {
            "module": module_name,
            "status": "SKIPPED",
            "reason": f"Test path not found: {test_path}",
            "passed": 0,
            "failed": 0,
            "errors": 0,
        }

    cmd = [sys.executable, "-m", "pytest", str(test_path), "-q", "--tb=short"]
    if verbose:
        cmd.append("-v")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=120,
        )

        # Parse pytest output
        output = result.stdout + result.stderr
        passed = output.count(" passed")
        failed = output.count(" failed")
        errors = output.count(" error")
        skipped = output.count(" skipped")

        # Extract counts from summary line
        for line in output.split("\n"):
            if "passed" in line and "failed" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "passed" and i > 0:
                        try:
                            passed = int(parts[i - 1])
                        except ValueError:
                            pass
                    elif part == "failed" and i > 0:
                        try:
                            failed = int(parts[i - 1])
                        except ValueError:
                            pass
                    elif part == "error" and i > 0:
                        try:
                            errors = int(parts[i - 1])
                        except ValueError:
                            pass

        status = "PASSED" if result.returncode == 0 else "FAILED"

        return {
            "module": module_name,
            "status": status,
            "returncode": result.returncode,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "output": output if verbose else output.split("\n")[-5:],
        }

    except subprocess.TimeoutExpired:
        return {
            "module": module_name,
            "status": "TIMEOUT",
            "reason": "Test execution exceeded 120s timeout",
            "passed": 0,
            "failed": 0,
            "errors": 0,
        }
    except Exception as e:
        return {
            "module": module_name,
            "status": "ERROR",
            "reason": str(e),
            "passed": 0,
            "failed": 0,
            "errors": 0,
        }


def print_report(results: list[dict], verbose: bool = False):
    """Print test results report."""
    print("\n" + "=" * 70)
    print("TEST RUNNER REPORT")
    print("=" * 70)

    total_passed = 0
    total_failed = 0
    total_errors = 0

    for result in results:
        status = result["status"]
        module = result["module"]
        desc = MODULES.get(module, {}).get("description", "")

        icon = {"PASSED": "✓", "FAILED": "✗", "SKIPPED": "○", "TIMEOUT": "⏱", "ERROR": "!"}.get(status, "?")

        print(f"\n{icon} {module}: {status}")
        if desc:
            print(f"  {desc}")

        if status in ("PASSED", "FAILED"):
            print(f"  Passed: {result['passed']}, Failed: {result['failed']}, Errors: {result['errors']}")
            total_passed += result["passed"]
            total_failed += result["failed"]
            total_errors += result["errors"]
        elif status in ("SKIPPED", "TIMEOUT", "ERROR"):
            print(f"  Reason: {result.get('reason', 'unknown')}")

        if verbose and isinstance(result.get("output"), list):
            for line in result["output"]:
                if line.strip():
                    print(f"  {line}")

    print("\n" + "-" * 70)
    print(f"TOTAL: {total_passed} passed, {total_failed} failed, {total_errors} errors")
    print("=" * 70)

    return total_failed == 0 and total_errors == 0


def main():
    parser = argparse.ArgumentParser(description="Run all module tests")
    parser.add_argument("--module", "-m", help="Run specific module only")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--list", "-l", action="store_true", help="List available modules")
    args = parser.parse_args()

    if args.list:
        print("Available modules:")
        for name, config in MODULES.items():
            print(f"  {name}: {config['description']}")
        return

    if args.module:
        if args.module not in MODULES:
            print(f"Unknown module: {args.module}")
            print(f"Available: {', '.join(MODULES.keys())}")
            sys.exit(1)
        modules_to_run = {args.module: MODULES[args.module]}
    else:
        modules_to_run = MODULES

    results = []
    for name, config in modules_to_run.items():
        print(f"\nRunning {name} tests...")
        result = run_module_tests(name, config, verbose=args.verbose)
        results.append(result)

    all_passed = print_report(results, verbose=args.verbose)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
