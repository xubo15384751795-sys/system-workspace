"""SSRF boundary tests for /hub/series and the outbound HTTPClient sink.

These tests verify that raw URL fields (``resource``, ``metadata.url``) are
rejected at the HTTP boundary and that ``validate_outbound_url`` blocks
non-HTTPS schemes, loopback/private/link-local IPs, userinfo, and fragments
before any network call is made.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from src.api.security import SSRFBlockedError, validate_outbound_url


class ValidateOutboundUrlTests(unittest.TestCase):
    """Unit tests for the pure validate_outbound_url validator."""

    # -- scheme violations -------------------------------------------------

    def test_rejects_file_scheme(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("file:///etc/passwd")

    def test_rejects_http_scheme(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("http://127.0.0.1/")

    def test_rejects_empty_scheme(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("//evil.com/path")

    def test_rejects_empty_url(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("")

    # -- IP literal violations ---------------------------------------------

    def test_rejects_loopback_ipv4(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://127.0.0.1/")

    def test_rejects_loopback_ipv6(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://[::1]/")

    def test_rejects_link_local(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://169.254.169.254/latest/meta-data/")

    def test_rejects_rfc1918_10(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://10.0.0.1/")

    def test_rejects_rfc1918_192_168(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://192.168.1.1/")

    def test_rejects_rfc1918_172_16(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://172.16.0.1/")

    # -- textual host violations -------------------------------------------

    def test_rejects_localhost(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://localhost/")

    # -- structural violations ---------------------------------------------

    def test_rejects_userinfo(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://user:pass@example.com/")

    def test_rejects_fragment(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            validate_outbound_url("https://example.com/#frag")

    # -- DNS rebinding -----------------------------------------------------

    def test_rejects_dns_rebind_to_private(self) -> None:
        """A public-looking hostname that resolves to a private IP must be blocked."""
        fake_addrinfo = [
            ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("10.0.0.5", 443)),
        ]
        with mock.patch("socket.getaddrinfo", return_value=fake_addrinfo):
            with self.assertRaises(SSRFBlockedError):
                validate_outbound_url("https://evil.example.com/")

    def test_rejects_dns_rebind_to_loopback(self) -> None:
        fake_addrinfo = [
            ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("127.0.0.1", 443)),
        ]
        with mock.patch("socket.getaddrinfo", return_value=fake_addrinfo):
            with self.assertRaises(SSRFBlockedError):
                validate_outbound_url("https://evil.example.com/")

    def test_rejects_dns_rebind_to_link_local(self) -> None:
        fake_addrinfo = [
            ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("169.254.169.254", 443)),
        ]
        with mock.patch("socket.getaddrinfo", return_value=fake_addrinfo):
            with self.assertRaises(SSRFBlockedError):
                validate_outbound_url("https://evil.example.com/")

    # -- positive case -----------------------------------------------------

    def test_accepts_valid_public_https(self) -> None:
        fake_addrinfo = [
            ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("93.184.216.34", 443)),
        ]
        with mock.patch("socket.getaddrinfo", return_value=fake_addrinfo):
            result = validate_outbound_url("https://example.com/data")
        self.assertEqual(result, "https://example.com/data")


class HubSeriesRejectsRawUrlTests(unittest.TestCase):
    """Verify /hub/series (and siblings) reject raw URL fields with 422."""

    def _make_client(self) -> tuple[Any, Any]:
        try:
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("fastapi test client is not installed")

        from src.api.app import create_app

        tmpdir = tempfile.mkdtemp()
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
        return TestClient(app), tmpdir

    def test_rejects_resource_field(self) -> None:
        client, _ = self._make_client()
        resp = client.post(
            "/hub/series",
            json=[{"provider": "cboe", "resource": "http://evil.com"}],
            headers={"X-API-Key": "test-key"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_rejects_metadata_url_field(self) -> None:
        client, _ = self._make_client()
        resp = client.post(
            "/hub/series",
            json=[{"provider": "cboe", "metadata": {"url": "http://evil.com"}}],
            headers={"X-API-Key": "test-key"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_rejects_resource_in_second_request(self) -> None:
        client, _ = self._make_client()
        resp = client.post(
            "/hub/series",
            json=[
                {"provider": "fred", "series_id": "DGS10"},
                {"provider": "cboe", "resource": "http://evil.com"},
            ],
            headers={"X-API-Key": "test-key"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_no_resource_no_422_for_url_rejection(self) -> None:
        """A request without raw URL fields must not 422 for URL reasons.

        It may fail for other reasons (no matching provider), but the
        rejection must not come from the SSRF guard.
        """
        client, _ = self._make_client()
        resp = client.post(
            "/hub/series",
            json=[{"provider": "fred", "series_id": "DGS10"}],
            headers={"X-API-Key": "test-key"},
        )
        # Must not be a 422 from the URL guard.  Other status codes (200,
        # 500, etc.) are acceptable - we only assert the guard didn't fire.
        if resp.status_code == 422:
            self.fail(
                "Request without raw URL fields was rejected with 422 - "
                "the SSRF guard fired incorrectly."
            )
