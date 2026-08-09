from __future__ import annotations

import json
import unittest
from pathlib import Path

from mapmover.runtime.loc_id_identity_doctrine import (
    DOCTRINE_RULE_KEYS,
    DOCTRINE_PROFILES,
    compare_doctrine_cases,
    compare_doctrine_rules,
    corpus_audit,
    doctrine_manifest,
    doctrine_decisions,
    doctrine_scorecard,
    evaluate_dual_mode_case,
    evaluate_dual_mode_cases,
    evaluate_identity_case,
    evaluate_identity_cases,
    registry_audit,
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
            if result["signal"] in {"known_issue", "unexpected_issue"}
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
        self.assertIn("oracle_failure", signals)
        self.assertTrue(any(result["deltas"] for result in results))
        self.assertTrue(all(result["raw"]["signal"] == "unscored" for result in results))

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

    def test_scorecards_use_the_same_independent_oracle(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        scorecards = {
            doctrine: doctrine_scorecard(cases, doctrine=doctrine)
            for doctrine in DOCTRINE_PROFILES
        }
        assertion_counts = {
            scorecard["declared"]["oracle_assertions"]
            for scorecard in scorecards.values()
        }
        oracle_fingerprints = {
            scorecard["oracle_fingerprint"] for scorecard in scorecards.values()
        }
        doctrine_fingerprints = {
            scorecard["doctrine_fingerprint"] for scorecard in scorecards.values()
        }

        self.assertEqual(len(assertion_counts), 1)
        self.assertEqual(len(oracle_fingerprints), 1)
        self.assertEqual(len(doctrine_fingerprints), len(DOCTRINE_PROFILES))
        self.assertEqual(scorecards["solidified_sibling_layer"]["raw"]["scored_cases"], 0)
        self.assertGreaterEqual(len(doctrine_decisions("solidified_sibling_layer")), 5)

    def test_every_doctrine_exposes_a_complete_executable_manifest(self) -> None:
        for doctrine in DOCTRINE_PROFILES:
            with self.subTest(doctrine=doctrine):
                manifest = doctrine_manifest(doctrine)
                self.assertEqual(set(manifest["rules"]), set(DOCTRINE_RULE_KEYS))
                self.assertTrue(manifest["registry"])
                self.assertTrue(all(entry["rule_id"] for entry in manifest["registry"]))
                self.assertEqual(len(manifest["fingerprint"]), 64)

        differences = compare_doctrine_rules("proposed_changes", "containing_loc_id")
        self.assertEqual(
            [difference["rule"] for difference in differences],
            ["placement_policy"],
        )

    def test_doctrine_specific_expected_answers_are_open_policy_not_oracle(self) -> None:
        result = evaluate_identity_case(
            {
                "case": "relationship policy experiment",
                "id": "NHGIS-XWALK-TRACT-1990-2020",
                "family_id": "relationship",
                "oracle": {
                    "declared": {
                        "status": "provisional",
                        "open_policy_fields": ["role"],
                        "policy_options": {
                            "role": {
                                "baseline": "source_alias",
                                "by_doctrine": {
                                    "solidified_sibling_layer": "relationship_id",
                                },
                            }
                        },
                    }
                },
            },
            doctrine="solidified_sibling_layer",
        )

        self.assertFalse(result["oracle"]["scored"])
        self.assertIn("role", result["oracle"]["open_policy_fields"])
        self.assertEqual(result["role"], "relationship_id")
        self.assertEqual(result["signal"], "unscored")

    def test_raw_mode_is_scored_only_with_an_explicit_raw_oracle(self) -> None:
        case = {
            "case": "raw grid",
            "id": "H3-872830828FFFFFF",
            "family_id": "grid",
            "expected_role": "grid_id",
        }
        unscored = evaluate_dual_mode_case(case)
        self.assertFalse(unscored["raw"]["oracle"]["scored"])

        case["oracle"] = {
            "raw": {
                "status": "verified",
                "role": "grid_id",
                "first_segment_scope": "grid_scope",
            }
        }
        scored = evaluate_dual_mode_case(case)
        self.assertTrue(scored["raw"]["oracle"]["scored"])
        self.assertEqual(scored["raw"]["oracle_assertions_passed"], 2)

    def test_known_issue_is_debt_not_a_required_output(self) -> None:
        case = {
            "case": "known broad fallback defect",
            "id": "NHC-CONE-AL092022-2022092800",
            "expected_role": "event_id",
            "expected_issues": ["role mismatch: expected event_id, got loc_id"],
        }
        present = evaluate_identity_case(case, doctrine="present_system")
        proposed = evaluate_identity_case(case, doctrine="proposed_changes")

        self.assertEqual(present["signal"], "known_issue")
        self.assertTrue(present["ok"])
        self.assertEqual(proposed["signal"], "pass")
        self.assertIn(case["expected_issues"][0], proposed["resolved_known_issues"])

    def test_registry_audit_reports_precedence_collisions(self) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cases = json.load(handle)

        audit = registry_audit(cases, doctrine="solidified_sibling_layer")
        corpus = corpus_audit(cases)
        self.assertEqual(audit["case_count"], len(cases))
        self.assertGreater(audit["overlap_count"], 0)
        self.assertGreater(audit["specific_collision_count"], 0)
        self.assertTrue(audit["unused_namespace_rules"])
        self.assertTrue(corpus["valid"])
        self.assertEqual(corpus["oracle_coverage"]["explicit_declared_cases"], len(cases))
        self.assertEqual(corpus["oracle_coverage"]["raw_scored_cases"], 0)
        self.assertEqual(corpus["legacy_doctrine_override_case_count"], 0)
        self.assertEqual(corpus["legacy_expectation_case_count"], 0)

    def test_corpus_audit_rejects_an_asserted_open_policy_field(self) -> None:
        audit = corpus_audit(
            [
                {
                    "case": "invalid open policy oracle",
                    "id": "TEST-OPEN-1",
                    "oracle": {
                        "declared": {
                            "status": "provisional",
                            "role": "loc_id",
                            "open_policy_fields": ["role"],
                        }
                    },
                }
            ]
        )

        self.assertFalse(audit["valid"])
        self.assertIn("OPEN_POLICY_FIELD_ASSERTED", {error["code"] for error in audit["errors"]})


if __name__ == "__main__":
    unittest.main()
