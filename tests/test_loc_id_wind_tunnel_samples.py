from __future__ import annotations

import json
import unittest
from pathlib import Path

from mapmover.runtime.loc_id_identity_doctrine import (
    DOCTRINE_PROFILES,
    compare_doctrine_cases,
    doctrine_decisions,
    evaluate_dual_mode_cases,
    evaluate_identity_cases,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "loc_id_wind_tunnel_samples.json"


class LocIdWindTunnelSampleTests(unittest.TestCase):
    maxDiff = None

    def test_sample_fixture_emits_diagnostic_categories(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        results = evaluate_identity_cases(cases)
        signals = {result["signal"] for result in results}
        self.assertIn("pass", signals)
        self.assertIn("unexpected_issue", signals)

    def test_sample_fixture_preserves_at_least_one_design_finding(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        results = evaluate_identity_cases(cases)
        findings = [
            result
            for result in results
            if result["signal"] in {"expected_issue", "unexpected_issue", "missing_expected_issue"}
        ]
        self.assertGreaterEqual(len(findings), 1)

    def test_unexpected_failures_are_report_findings_not_suite_failures(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        results = evaluate_identity_cases(cases)
        unexpected = [result for result in results if result["signal"] == "unexpected_issue"]
        self.assertGreaterEqual(len(unexpected), 1)
        self.assertTrue(all(result["unexpected_issues"] for result in unexpected))

    def test_dual_mode_reports_raw_declared_deltas(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        results = evaluate_dual_mode_cases(cases)
        signals = {result["signal"] for result in results}
        self.assertIn("raw_declared_delta", signals)
        self.assertIn("needs_policy_decision", signals)
        self.assertTrue(any(result["deltas"] for result in results))

    def test_doctrine_profiles_produce_comparison_deltas(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        by_doctrine = {
            doctrine: evaluate_dual_mode_cases(cases, doctrine=doctrine)
            for doctrine in DOCTRINE_PROFILES
        }
        compared = compare_doctrine_cases(cases, left="present_system", right="proposed_changes")
        self.assertTrue(by_doctrine)
        self.assertTrue(all(len(results) == len(cases) for results in by_doctrine.values()))
        self.assertEqual(len(compared), len(cases))
        self.assertTrue(any(result["deltas"] for result in compared))

    def test_every_doctrine_runs_against_the_same_fixture_corpus(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        case_names = [case["case"] for case in cases]
        for doctrine in DOCTRINE_PROFILES:
            with self.subTest(doctrine=doctrine):
                results = evaluate_dual_mode_cases(cases, doctrine=doctrine)
                self.assertEqual([result["case"] for result in results], case_names)

    def test_containing_loc_id_profile_adds_placement_deltas(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        compared = compare_doctrine_cases(cases, left="proposed_changes", right="containing_loc_id")
        joined_deltas = "\n".join(delta for result in compared for delta in result["deltas"])
        self.assertIn("placement_semantics", joined_deltas)

    def test_solidified_sibling_layer_records_decisions_and_improves_passes(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        containing = evaluate_dual_mode_cases(cases, doctrine="containing_loc_id")
        solidified = evaluate_dual_mode_cases(cases, doctrine="solidified_sibling_layer")
        containing_passes = sum(result["signal"] == "pass" for result in containing)
        solidified_passes = sum(result["signal"] == "pass" for result in solidified)

        self.assertGreater(solidified_passes, containing_passes)
        self.assertGreaterEqual(len(doctrine_decisions("solidified_sibling_layer")), 5)


if __name__ == "__main__":
    unittest.main()
