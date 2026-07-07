from __future__ import annotations

import unittest

from src.dynamic.case_pattern_registry import (
    get_known_failure_modes,
    get_recommended_signal_cards,
    list_case_patterns,
    load_case_pattern,
)


class CasePatternRegistryTests(unittest.TestCase):
    def test_list_includes_ldi(self) -> None:
        self.assertIn("ldi_2022", list_case_patterns())

    def test_load_ldi_yaml(self) -> None:
        data = load_case_pattern("ldi_2022")
        self.assertEqual(data.get("case_id"), "ldi_2022")
        self.assertIn("recommended_signal_cards", data)

    def test_getters(self) -> None:
        cards = get_recommended_signal_cards("svb_2023")
        self.assertIn("term_structure_deformation", cards)
        modes = get_known_failure_modes("repo_spike_2019")
        self.assertTrue(all(isinstance(x, str) for x in modes))


if __name__ == "__main__":
    unittest.main()
