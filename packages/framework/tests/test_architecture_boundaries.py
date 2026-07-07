from __future__ import annotations

import ast
from pathlib import Path
import unittest

from src.core.feature_taxonomy import FeatureLayer, feature_keys_for_layer
from src.core.models import (
    MeanFieldGapState,
    ProxyReading,
    ShadowMassState,
    Snapshot,
    StructuralPrimitiveState,
    StructuralState,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


SUBSYSTEM_PATHS = {
    "datahub": ("src/data/gateway", "src/data/adapters", "src/data/contracts.py"),
    "proxy": ("src/derivation/proxy_builder.py", "src/data/gateway/bridge.py"),
    "singular_detector": ("src/derivation/singular_detector.py",),
    "primitive_state": ("src/derivation/structural_layers.py",),
    "operator_algebra": ("src/operators",),
    "graph": ("src/derivation/graph_engine.py", "src/core/representation/graph_repr.py", "src/core/metrics/graph_features.py"),
    "belief_state": ("src/derivation/belief_builder.py",),
    "shadow_mass": ("src/derivation/structural_layers.py",),
    "mean_field_gap": ("src/derivation/structural_layers.py",),
    "abm_scenario_lab": ("src/simulation",),
    "ode_engine": ("src/dynamics",),
    "ml_layer": ("src/ml",),
    "data_quality_manifest": ("src/data/quality",),
}


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_subsystem_import_graph_stays_sparse(self) -> None:
        path_to_subsystem = _path_to_subsystem()
        coupling = {name: set() for name in SUBSYSTEM_PATHS}
        for file_path, source_subsystem in path_to_subsystem.items():
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for module in _imported_modules(tree):
                target = _module_to_path(module)
                if target is None:
                    continue
                target_subsystem = path_to_subsystem.get(target)
                if target_subsystem and target_subsystem != source_subsystem:
                    coupling[source_subsystem].add(target_subsystem)

        average = sum(len(deps) for deps in coupling.values()) / len(coupling)
        self.assertLessEqual(average, 3.0, coupling)
        self.assertTrue(all(len(deps) <= 5 for deps in coupling.values()), coupling)

    def test_config_is_not_monolithic(self) -> None:
        config_lines = (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8").splitlines()

        self.assertLess(len(config_lines), 400)

    def test_snapshot_core_projection_excludes_exploratory_fields(self) -> None:
        snapshot = _minimal_snapshot()
        core = snapshot.core()
        extension = snapshot.extension()

        self.assertEqual(core.proxy.M, 0.1)
        self.assertEqual(core.sigma_t, 0.7)
        self.assertIsNotNone(core.primitive_state)
        self.assertIsNotNone(core.shadow_mass_state)
        self.assertIsNotNone(core.mean_field_gap)
        self.assertEqual(extension.anomaly_score, -0.2)
        self.assertEqual(dict(extension.reflexivity_flags), {"credit": True})

    def test_feature_taxonomy_has_all_required_layers(self) -> None:
        self.assertIn("proxy_aggregation", feature_keys_for_layer(FeatureLayer.PAPER))
        self.assertIn("data_quality_manifest", feature_keys_for_layer(FeatureLayer.ENGINEERING))
        self.assertIn("ml_anomaly", feature_keys_for_layer(FeatureLayer.EXPLORATORY))
        self.assertIn("path_rank_witness", feature_keys_for_layer(FeatureLayer.EXPLORATORY))


def _path_to_subsystem() -> dict[Path, str]:
    result: dict[Path, str] = {}
    for subsystem, entries in SUBSYSTEM_PATHS.items():
        for entry in entries:
            path = PROJECT_ROOT / entry
            if path.is_file():
                result[path] = subsystem
            elif path.exists():
                for file_path in path.rglob("*.py"):
                    result[file_path] = subsystem
    return result


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _module_to_path(module: str) -> Path | None:
    if not module.startswith("src."):
        return None
    file_path = PROJECT_ROOT / Path(*module.split(".")).with_suffix(".py")
    if file_path.exists():
        return file_path
    init_path = PROJECT_ROOT / Path(*module.split(".")) / "__init__.py"
    if init_path.exists():
        return init_path
    return None


def _minimal_snapshot() -> Snapshot:
    proxy = ProxyReading(
        run_date="2026-04-25",
        M=0.1,
        D=0.2,
        K=0.3,
        X=0.4,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.1, "D": 0.2, "K": 0.3, "X": 0.4},
    )
    state = StructuralState(
        run_date="2026-04-25",
        z_vector=None,
        sigma_t=0.7,
        singular_flag=False,
        leading_channel="M",
        pattern="STABLE_LOCAL",
        anomaly_score=-0.2,
        reflexivity_flags={"credit": True},
        provenance={},
        primitive_state=StructuralPrimitiveState(
            subject=0.1,
            anchor=0.0,
            liquidation_feasibility=0.6,
            verifiability_density=0.5,
            positional_power=0.2,
            latency=0.1,
        ),
        shadow_mass_state=ShadowMassState(
            aggregate_mass=0.4,
            forced_realization_pressure=0.2,
            buckets=(),
        ),
        mean_field_gap=MeanFieldGapState(
            actual_shadow_mass=0.4,
            benchmark_shadow_mass=0.3,
            gap=0.1,
            normalized_gap=0.25,
        ),
    )
    return Snapshot(
        run_date="2026-04-25",
        run_type="WEEKLY",
        proxy=proxy,
        state=state,
        narrative=None,
        escalation=False,
        escalation_reason=None,
    )


if __name__ == "__main__":
    unittest.main()
