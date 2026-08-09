from __future__ import annotations

import json
import unittest
from pathlib import Path

from mapmover.runtime.loc_id_identity_doctrine import evaluate_dual_mode_cases, evaluate_identity_cases

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "loc_id_wind_tunnel_samples.json"


class LocIdWindTunnelSampleTests(unittest.TestCase):
    maxDiff = None

    def test_sample_fixture_emits_diagnostic_categories(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        results = evaluate_identity_cases(cases)
        signals = {result["signal"] for result in results}
        self.assertIn("pass", signals)
        self.assertIn("expected_issue", signals)
        self.assertIn("unexpected_issue", signals)

    def test_sample_fixture_preserves_at_least_one_expected_failure(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        results = evaluate_identity_cases(cases)
        expected_failures = [result for result in results if result["signal"] == "expected_issue"]
        self.assertGreaterEqual(len(expected_failures), 1)

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


if __name__ == "__main__":
    unittest.main()
