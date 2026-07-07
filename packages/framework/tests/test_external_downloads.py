from __future__ import annotations

import unittest

from src._legacy.data.external_downloads import (
    CISS,
    KNOWN_INDICATORS,
    _parse_ciss_csv,
    _parse_covar_csv,
    _parse_srisk_csv,
    fetch_external_indicator,
    write_template_csv,
)


class ExternalDownloadParserTests(unittest.TestCase):
    def test_parse_ciss_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Structural Risk Harvester"):
            _parse_ciss_csv("TIME_PERIOD,OBS_VALUE\n2024-01-01,0.10\n")

    def test_parse_srisk_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Structural Risk Harvester"):
            _parse_srisk_csv("Date,SRISK\n2024-01-01,1.0\n")

    def test_parse_covar_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Structural Risk Harvester"):
            _parse_covar_csv("Date,DeltaCoVaR\n2024-01-01,-0.5\n")

    def test_known_indicators_have_metadata(self) -> None:
        for ind in KNOWN_INDICATORS:
            self.assertEqual(ind.publisher_url, "moved-to-harvester")
            self.assertIn("Harvester", ind.instructions)


class ExternalDownloadFlowTests(unittest.TestCase):
    def test_fetch_external_indicator_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Structural Risk Harvester"):
            fetch_external_indicator(CISS)

    def test_template_writer_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Structural Risk Harvester"):
            write_template_csv("CISS")


if __name__ == "__main__":
    unittest.main()
