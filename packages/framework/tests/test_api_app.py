from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.api.app import create_service


def _config(tmpdir: str) -> dict:
    return {
        "project_name": "Structural Deformation Research System",
        "series_ids": ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"],
        "history_start": "2026-01-01",
        "mock_seed": 42,
        "thresholds": {"sigma": 99.0},
        "data": {"root": tmpdir, "version": "api-test"},
        "ode_params": {"dt": 1.0, "horizon": 2},
        "output": {"dir": tmpdir, "export_image": False},
        "event_log": {"path": str(Path(tmpdir) / "event_log.jsonl")},
        "text_log": {"path": str(Path(tmpdir) / "texts.jsonl")},
        "ml": {"enabled": False},
    }


class ApiAppTests(unittest.TestCase):
    def test_create_service_builds_terminal_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = create_service(_config(tmpdir), use_mock=True)

            self.assertEqual(service.health()["status"], "ok")
            self.assertTrue(service.available_series())

    def test_create_app_registers_core_routes_when_fastapi_available(self) -> None:
        try:
            import fastapi  # noqa: F401
        except Exception:
            self.skipTest("fastapi is not installed")

        from src.api.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                "project_name: Structural Deformation Research System\n"
                "series_ids: [M_PROXY, D_PROXY, K_PROXY, X_PROXY]\n"
                "history_start: '2026-01-01'\n"
                "mock_seed: 42\n"
                "thresholds: {sigma: 99.0}\n"
                f"data: {{root: '{tmpdir}', version: api-test}}\n"
                "ode_params: {dt: 1.0, horizon: 2}\n"
                f"output: {{dir: '{tmpdir}', export_image: false}}\n"
                f"event_log: {{path: '{Path(tmpdir) / 'event_log.jsonl'}'}}\n"
                f"text_log: {{path: '{Path(tmpdir) / 'texts.jsonl'}'}}\n"
                "ml: {enabled: false}\n",
                encoding="utf-8",
            )
            app = create_app(config_path=str(config_path), use_mock=True)

            paths = {route.path for route in app.routes}
            self.assertIn("/health", paths)
            self.assertIn("/runtime", paths)
            self.assertIn("/snapshots/run", paths)
            self.assertIn("/hub/presets", paths)
            self.assertIn("/hub/structural", paths)
            self.assertIn("/hub/series", paths)
            self.assertIn("/hub/filings", paths)

    def test_create_app_fails_clearly_without_fastapi(self) -> None:
        from src.api import app as api_app

        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "fastapi":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(RuntimeError):
                api_app.create_app()


if __name__ == "__main__":
    unittest.main()
