"""Test isolation: Qlib paths must be strictly sandboxed."""

# Adjust path to find the benchmark modules
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages" / "workbench" / "src"))

from benchmarks.market_feedback.benchmark_manifest import (
    create_benchmark_manifest,
    validate_manifest_paths,
)
from benchmarks.market_feedback.qlib_job_spec import (
    FORBIDDEN_IN_JOB_SPEC,
    generate_job_spec,
    validate_job_spec_paths,
)

BENCHMARK_ID = "test_2026-05-05_ISOLATION_TEST"


class TestManifestIsolation:
    def test_manifest_paths_are_sandboxed(self):
        manifest = create_benchmark_manifest(
            benchmark_id=BENCHMARK_ID,
            market_data_release="test_release",
            deformation_feature_release="test_deform",
        )
        errors = validate_manifest_paths(manifest)
        assert len(errors) == 0, f"Manifest paths violated isolation: {errors}"

    def test_allowed_read_paths_only_sandbox_input(self):
        manifest = create_benchmark_manifest(
            benchmark_id=BENCHMARK_ID,
            market_data_release="test_release",
            deformation_feature_release="test_deform",
        )
        for path in manifest["allowed_read_paths"]:
            assert "/sandbox_input" in path, f"Read path must be under sandbox_input: {path}"

    def test_allowed_write_paths_only_qlib_dirs(self):
        manifest = create_benchmark_manifest(
            benchmark_id=BENCHMARK_ID,
            market_data_release="test_release",
            deformation_feature_release="test_deform",
        )
        for path in manifest["allowed_write_paths"]:
            assert (
                "/qlib_workspace" in path or "/qlib_output" in path
            ), f"Write path must be qlib_workspace or qlib_output: {path}"

    def test_forbidden_paths_include_critical_dirs(self):
        manifest = create_benchmark_manifest(
            benchmark_id=BENCHMARK_ID,
            market_data_release="test_release",
            deformation_feature_release="test_deform",
        )
        forbidden = manifest["forbidden_paths"]
        assert "Data/" in forbidden
        assert "packages/workbench/src" in forbidden
        assert "Output/deformation_runs" in forbidden
        assert "Output/system_learning" in forbidden


class TestJobSpecIsolation:
    def test_job_spec_paths_are_sandboxed(self):
        spec = generate_job_spec(benchmark_id=BENCHMARK_ID)
        errors = validate_job_spec_paths(spec)
        assert len(errors) == 0, f"Job spec paths violated isolation: {errors}"

    def test_input_dir_is_sandbox_input(self):
        spec = generate_job_spec(benchmark_id=BENCHMARK_ID)
        assert "/sandbox_input" in spec["input_dir"]

    def test_output_dir_is_qlib_output(self):
        spec = generate_job_spec(benchmark_id=BENCHMARK_ID)
        assert "/qlib_output" in spec["output_dir"]

    def test_job_spec_does_not_contain_forbidden_paths(self):
        spec = generate_job_spec(benchmark_id=BENCHMARK_ID)
        path_keys = ["input_dir", "workspace_dir", "output_dir"]
        for key in path_keys:
            value = spec[key]
            for forbidden in FORBIDDEN_IN_JOB_SPEC:
                assert forbidden not in value, (
                    f"Job spec {key}={value!r} contains forbidden {forbidden!r}"
                )

    def test_job_spec_rejects_forbidden_path(self):
        spec = generate_job_spec(benchmark_id=BENCHMARK_ID)
        spec["output_dir"] = "Output/deformation_runs/bad_path"
        errors = validate_job_spec_paths(spec)
        assert len(errors) > 0, "Should reject output_dir pointing to deformation_runs"

    def test_job_spec_has_required_fields(self):
        spec = generate_job_spec(benchmark_id=BENCHMARK_ID)
        assert "job_id" in spec
        assert "benchmark_id" in spec
        assert "input_dir" in spec
        assert "workspace_dir" in spec
        assert "output_dir" in spec
        assert "experiments" in spec
        assert "fail_policy" in spec
        assert spec["read_only_input"] is True
