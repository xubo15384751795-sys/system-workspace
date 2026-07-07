from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.nlp.event_translator import NLPEventTranslator

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
_CASE_LIBRARY = _PROJECT / "Data" / "nlp" / "case_library"
_MAPPING_RULES = _PROJECT / "Data" / "nlp" / "mapping_rules.yaml"


class NLPEventTranslatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.translator = NLPEventTranslator.from_mapping_rules(_MAPPING_RULES)

    # ------------------------------------------------------------------
    # Smoke: translator loads and runs
    # ------------------------------------------------------------------

    def test_empty_input_returns_empty_df(self) -> None:
        result = self.translator.translate([])
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)
        self.assertEqual(
            list(result.columns),
            ["date", "event_type", "channel", "intensity", "actor", "description"],
        )

    def test_translate_empty_dicts_returns_empty_df(self) -> None:
        result = self.translator.translate([{}, {"unrelated": True}])
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)

    # ------------------------------------------------------------------
    # Source A: case_library JSON files
    # ------------------------------------------------------------------

    def test_translates_all_case_library_files(self) -> None:
        case_files = sorted(_CASE_LIBRARY.glob("*.json"))
        self.assertGreaterEqual(len(case_files), 6, "Need at least 6 case files")

        for case_path in case_files:
            with self.subTest(case=case_path.name):
                case = json.loads(case_path.read_text(encoding="utf-8"))
                result = self.translator.translate([case])
                self.assertFalse(
                    result.empty,
                    f"{case_path.name}: translator produced no rows",
                )
                self.assertIn("event_type", result.columns)
                self.assertEqual(result.iloc[0]["date"], case.get("vintage", ""))

    # ------------------------------------------------------------------
    # SVB: deposit_run -> LIQUIDITY_WITHDRAWAL (compression)
    #       policy_intervention -> POLICY_BACKSTOP (recovery)
    # ------------------------------------------------------------------

    def _load_svb_case(self) -> dict:
        return json.loads((_CASE_LIBRARY / "svb_2023.json").read_text(encoding="utf-8"))

    def test_svb_translates_both_patterns(self) -> None:
        case = self._load_svb_case()
        result = self.translator.translate([case])
        self.assertEqual(len(result), 2, "SVB should produce exactly 2 rows")

        event_types = set(result["event_type"])
        self.assertIn("LIQUIDITY_WITHDRAWAL", event_types)
        self.assertIn("POLICY_BACKSTOP", event_types)

    def test_svb_deposit_run_intensity(self) -> None:
        case = self._load_svb_case()
        result = self.translator.translate([case])
        dr_row = result[result["event_type"] == "LIQUIDITY_WITHDRAWAL"].iloc[0]
        # base weight 0.85, tau=0.15 => tau_mult = 1.0 + (1-0.15)*0.5 = 1.425
        # 0.85 * 1.425 = 1.21125, rounded to 3 decimal places
        self.assertAlmostEqual(dr_row["intensity"], 1.211, places=2)
        self.assertEqual(dr_row["date"], "2023-03-10")
        self.assertIn("Silicon Valley Bank", dr_row["actor"])

    def test_svb_policy_recovery_lower_intensity(self) -> None:
        """Recovery operators (P variable present) get reduced intensity."""
        case = self._load_svb_case()
        result = self.translator.translate([case])
        pi_row = result[result["event_type"] == "POLICY_BACKSTOP"].iloc[0]
        # Recovery operator: base * tau_mult * 0.7
        # base 0.70, tau=0.15 (but P channel, not tau variable) => tau_mult=1.0
        # 0.70 * 1.0 * 0.7 = 0.49
        self.assertLess(pi_row["intensity"], 0.7)
        self.assertGreater(pi_row["intensity"], 0.3)

    def test_svb_actor_and_description(self) -> None:
        case = self._load_svb_case()
        result = self.translator.translate([case])
        for _, row in result.iterrows():
            self.assertTrue(row["actor"], "actor should not be empty")
            self.assertTrue(row["description"], "description should not be empty")
            self.assertIn("Silicon Valley Bank", row["description"])

    # ------------------------------------------------------------------
    # Source B: golden_event_card
    # ------------------------------------------------------------------

    def test_event_card_with_expected_variables(self) -> None:
        card = {
            "event_date": "2023-03-10",
            "actor": "SVB",
            "expected_variables": [
                {"signal": "deposit_run", "intensity": 0.80},
            ],
        }
        result = self.translator.translate([card])
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["event_type"], "DEPOSIT_RUN")
        self.assertEqual(result.iloc[0]["intensity"], 0.80)

    def test_event_card_with_expected_triggers(self) -> None:
        card = {
            "vintage": "1998-09-23",
            "actor": "LTCM",
            "expected_triggers": [
                "collateral_spiral",
                {"signal": "liquidation_path_stress", "intensity": 0.90, "channel": "X"},
            ],
        }
        result = self.translator.translate([card])
        self.assertEqual(len(result), 2)
        event_types = set(result["event_type"])
        self.assertIn("MARGIN_CALL", event_types)
        self.assertIn("FORCED_SELLING", event_types)

    # ------------------------------------------------------------------
    # Source C: tagged text (entities / events)
    # ------------------------------------------------------------------

    def test_tagged_entities(self) -> None:
        item = {
            "date": "2024-06-01",
            "entities": [
                {"type": "event", "subtype": "deposit_run", "confidence": 0.75, "name": "Regional Bank X"},
                {"type": "person", "name": "CEO"},
            ],
        }
        result = self.translator.translate([item])
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["event_type"], "DEPOSIT_RUN")

    def test_tagged_events_dict(self) -> None:
        item = {
            "run_date": "2025-01-15",
            "actor": "Unknown",
            "events": [
                {"signal": "liquidity_crisis", "intensity": 0.80, "channel": "D"},
                {"signal": "policy_intervention", "intensity": 0.55, "channel": "P"},
            ],
        }
        result = self.translator.translate([item])
        self.assertEqual(len(result), 2)
        event_types = set(result["event_type"])
        self.assertIn("LIQUIDITY_WITHDRAWAL", event_types)
        self.assertIn("POLICY_BACKSTOP", event_types)

    # ------------------------------------------------------------------
    # Channel inference
    # ------------------------------------------------------------------

    def test_channel_from_variables_list(self) -> None:
        translator = self.translator
        self.assertEqual(translator._primary_channel(["D", "tau"], {}), "D")
        self.assertEqual(translator._primary_channel(["M", "anchor_gap"], {}), "M")
        self.assertEqual(translator._primary_channel(["K", "convexity"], {}), "K")
        self.assertEqual(translator._primary_channel(["X", "shadow"], {}), "X")

    def test_channel_from_vector(self) -> None:
        translator = self.translator
        self.assertEqual(translator._primary_channel([], {"tau": 0.5}), "D")
        self.assertEqual(translator._primary_channel([], {"X": 0.8}), "X")

    def test_channel_default(self) -> None:
        self.assertEqual(self.translator._primary_channel([], {}), "D")

    # ------------------------------------------------------------------
    # Intensity with tau tuning
    # ------------------------------------------------------------------

    def test_intensity_no_tau(self) -> None:
        rule = {"weight": 0.80, "variables": ["D"]}
        self.assertAlmostEqual(self.translator._intensity(rule, {}), 0.80)

    def test_intensity_short_tau_increases(self) -> None:
        """Short tau (fast crisis) increases intensity."""
        rule = {"weight": 0.60, "variables": ["D", "tau"]}
        fast = self.translator._intensity(rule, {"tau": 0.1})
        slow = self.translator._intensity(rule, {"tau": 0.9})
        self.assertGreater(fast, slow)

    def test_intensity_medium_tau_neutral(self) -> None:
        rule = {"weight": 0.60, "variables": ["tau"]}
        # tau=0.5: tau_mult = 1.0 + (1-0.5)*0.5 = 1.25
        # 0.60 * 1.25 = 0.75
        self.assertAlmostEqual(self.translator._intensity(rule, {"tau": 0.5}), 0.75)

    # ------------------------------------------------------------------
    # End-to-end: all 6 real cases produce valid operator names
    # ------------------------------------------------------------------

    def _valid_operator_names(self) -> set[str]:
        from src.operators.operator_registry import build_default_operator_registry
        registry = build_default_operator_registry()
        return {op.name.upper() for op in registry.all()}

    def test_all_case_events_map_to_registered_operators(self) -> None:
        valid_ops = self._valid_operator_names()
        case_files = sorted(_CASE_LIBRARY.glob("*.json"))

        for case_path in case_files:
            with self.subTest(case=case_path.name):
                case = json.loads(case_path.read_text(encoding="utf-8"))
                result = self.translator.translate([case])
                for _, row in result.iterrows():
                    self.assertIn(
                        row["event_type"],
                        valid_ops,
                        f"{case_path.name}: event_type '{row['event_type']}' "
                        f"not in operator registry",
                    )

    def test_all_cases_have_expected_number_of_events(self) -> None:
        expected_counts = {
            "svb_2023.json": 2,
            "ltcm_1998.json": 3,
            "gfc_2008.json": 5,
            "covid_2020.json": 6,
            "archegos_2021.json": 3,
            "uk_gilt_2022.json": 4,
        }
        for case_name, expected in expected_counts.items():
            case_path = _CASE_LIBRARY / case_name
            if not case_path.exists():
                continue
            with self.subTest(case=case_name):
                case = json.loads(case_path.read_text(encoding="utf-8"))
                result = self.translator.translate([case])
                self.assertEqual(
                    len(result),
                    expected,
                    f"{case_name}: expected {expected} rows, got {len(result)}",
                )
