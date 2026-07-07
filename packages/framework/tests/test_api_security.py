from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.api.security import (
    assert_bind_allowed,
    is_loopback_host,
    resolve_api_key,
    resolve_harvester_validation,
)


class ApiSecurityHelperTests(unittest.TestCase):
    def test_is_loopback_host(self) -> None:
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("localhost"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertFalse(is_loopback_host("0.0.0.0"))

    def test_resolve_api_key_prefers_config(self) -> None:
        with mock.patch.dict("os.environ", {"TERMINAL_API_KEY": "from-env"}, clear=False):
            key = resolve_api_key({"api": {"key": "from-config"}})
        self.assertEqual(key, "from-config")

    def test_assert_bind_allowed_rejects_public_bind_without_key(self) -> None:
        with self.assertRaises(SystemExit):
            assert_bind_allowed("0.0.0.0", api_key="")

    def test_assert_bind_allowed_allows_public_bind_with_key(self) -> None:
        assert_bind_allowed("0.0.0.0", api_key="secret-token")

    def test_resolve_harvester_validation_defaults_secure(self) -> None:
        hashes, schema = resolve_harvester_validation({})
        self.assertTrue(hashes)
        self.assertTrue(schema)

    def test_resolve_harvester_validation_reads_config(self) -> None:
        hashes, schema = resolve_harvester_validation(
            {"harvester": {"validate_hashes": False, "validate_schema": True}}
        )
        self.assertFalse(hashes)
        self.assertTrue(schema)


class ApiSecurityMiddlewareTests(unittest.TestCase):
    def test_create_app_enforces_api_key_on_protected_routes(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("fastapi test client is not installed")

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
            app = create_app(config_path=str(config_path), use_mock=True, api_key="test-key")
            client = TestClient(app)

            health = client.get("/health")
            self.assertEqual(health.status_code, 200)

            denied = client.get("/runtime")
            self.assertEqual(denied.status_code, 401)

            allowed = client.get("/runtime", headers={"X-API-Key": "test-key"})
            self.assertEqual(allowed.status_code, 200)

    def test_build_lite_service_uses_config_validation_flags(self) -> None:
        from src.api.app import _build_lite_service

        with mock.patch("src.data_access.harvester_adapter.HarvesterAdapter") as adapter_cls:
            adapter_cls.return_value = object()
            with mock.patch("src.data.gateway.data_hub_lite.DataHubLite") as lite_cls:
                lite_cls.return_value = object()
                config = {
                    "harvester": {
                        "exports_root": "/tmp/exports",
                        "contract_root": "/tmp/contracts",
                        "validate_hashes": True,
                        "validate_schema": True,
                    }
                }
                service = _build_lite_service(config)
                self.assertIsNotNone(service)
                adapter_cls.assert_called_once()
                kwargs = adapter_cls.call_args.kwargs
                self.assertTrue(kwargs["validate_hashes"])
                self.assertTrue(kwargs["validate_schema"])


class RunApiBindGuardTests(unittest.TestCase):
    def test_run_api_refuses_public_bind_without_api_key(self) -> None:
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("project_name: test\n", encoding="utf-8")
            proc = mock.Mock()
            with mock.patch("uvicorn.run", proc):
                with self.assertRaises(SystemExit):
                    sys.argv = [
                        "run_api.py",
                        "--config",
                        str(config_path),
                        "--host",
                        "0.0.0.0",
                    ]
                    run_api = self._load_run_api(scripts_dir)
                    run_api.main()


    @staticmethod
    def _load_run_api(scripts_dir: Path):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_api", scripts_dir / "run_api.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
