"""Identifier resolution must refuse what it cannot verify.

These cover one class of failure: a tool reporting a confident answer on
evidence it never had. String shape is not identity, agreement between systems
is not ambiguity, and an Overture subtype is not an admin level.
"""
from __future__ import annotations

import unittest

from mapmover.runtime.reference_exchange import (
    GERS_SYSTEM,
    list_reference_systems,
    resolve_gers_division,
    resolve_reference,
    verify_loc_ids,
)
from mapmover.runtime.reference_identification import identify_reference_system


# A real Overture GERS division id and the loc_id the crosswalk assigns it.
USA_GERS_ID = "58cd13ed-fb26-44c3-b791-196cf89a60aa"
USA_GERS_LOC_ID = "USA-G166186276B53580985925186-G252423323B75618764282830"
# Canada resolves the same `county` subtype onto admin_3 census subdivisions.
CAN_GERS_ID = "bdf267a1-4759-45d8-8086-73bf2863edf2"
CAN_GERS_LOC_ID = "CAN-AB-4803-003"
WELL_FORMED_BUT_UNKNOWN = "00000000-0000-0000-0000-000000000000"


class LocIdVerificationTests(unittest.TestCase):
    def test_dash_separated_text_is_not_accepted_as_a_loc_id(self) -> None:
        self.assertEqual(verify_loc_ids(["not-a-real-identifier-at-all"]), set())

    def test_real_loc_id_verifies(self) -> None:
        self.assertEqual(verify_loc_ids(["USA-VA-059"]), {"USA-VA-059"})

    def test_shapeless_family_identity_still_verifies(self) -> None:
        """A polygon is not the only proof an identity exists.

        Canadian economic regions carry no geometry, so a geometry-only check
        would reject a loc_id the reference graph knows perfectly well.
        """
        self.assertEqual(verify_loc_ids(["CAN-ER-01-1010"]), {"CAN-ER-01-1010"})

    def test_identify_refuses_a_foreign_uuid_rather_than_echoing_it(self) -> None:
        payload = identify_reference_system(
            ["not-a-real-identifier-at-all", "XXXX-YYYY-ZZZZ"],
            validation_scope="all_distinct_identifiers",
        )

        self.assertEqual(payload["status"], "unmatched")
        self.assertEqual(payload["candidates"], [])
        self.assertIsNone(payload["recommended_binding"])

    def test_resolve_reference_refuses_an_unknown_loc_id(self) -> None:
        payload = resolve_reference(from_system="loc_id", value="not-a-real-identifier-at-all")

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "loc_id_not_found")
        self.assertIsNone(payload["resolved_loc_id"])

    def test_resolve_reference_still_passes_a_real_loc_id_through(self) -> None:
        payload = resolve_reference(from_system="loc_id", value="USA-VA-059")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolved_loc_id"], "USA-VA-059")


class ConcurringSystemTests(unittest.TestCase):
    def test_systems_naming_the_same_referent_are_not_ambiguous(self) -> None:
        """Two names for one answer is agreement, not a question for the user.

        A five-digit US county code is recognized by both the census GEOID
        adapter and the reference graph's native admin id, and both return
        USA-NY-061. Reporting that as ambiguous asked the caller to choose
        between options that resolve identically.
        """
        payload = identify_reference_system(["36061"], country_scope="USA")

        self.assertEqual(payload["status"], "matched")
        self.assertIn("us_census_geoid", payload["concurring_systems"])
        self.assertGreater(len(payload["concurring_systems"]), 1)

    def test_the_binding_prefers_the_system_carrying_more_evidence(self) -> None:
        """Not the alphabetically first one.

        The census adapter knows the level and vintage; a bare native id knows
        neither, so it is the weaker binding even though it sorts first.
        """
        payload = identify_reference_system(["36061"], country_scope="USA")

        self.assertEqual(payload["recommended_binding"]["system"], "us_census_geoid")


class GersResolutionTests(unittest.TestCase):
    def test_gers_division_resolves_to_a_loc_id(self) -> None:
        payload = resolve_gers_division(USA_GERS_ID)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolved_loc_id"], USA_GERS_LOC_ID)
        self.assertEqual(payload["match_type"], "exact_identifier_crosswalk")
        self.assertEqual(payload["relationship_type"], "equivalence")

    def test_identity_and_geometry_confidence_stay_separate(self) -> None:
        """A blended score would call an unambiguous match doubtful.

        Our spine carries territorial water and the Overture side is filtered to
        land, so a coastal unit reads low on area agreement while remaining the
        same county.
        """
        payload = resolve_gers_division(USA_GERS_ID)

        self.assertEqual(payload["identity_confidence"], "high")
        self.assertLess(payload["geometry_confidence"], 0.98)

    def test_the_same_subtype_resolves_to_different_levels_per_country(self) -> None:
        """The reason admin_level is an output and never an input.

        Overture's subtype is an OpenStreetMap tagging convention. Canada tags
        `county` onto units that match our admin_3 census subdivisions while the
        USA's land on admin_2, so no fixed subtype-to-level join exists.
        """
        usa = resolve_gers_division(USA_GERS_ID)
        canada = resolve_gers_division(CAN_GERS_ID)

        self.assertEqual(usa["overture_subtype"], canada["overture_subtype"])
        self.assertEqual(usa["admin_level"], 2)
        self.assertEqual(canada["admin_level"], 3)
        self.assertEqual(canada["resolved_loc_id"], CAN_GERS_LOC_ID)
        self.assertEqual(canada["spine_vintage"], "can_authority_spine")

    def test_requested_admin_level_cannot_steer_the_result(self) -> None:
        """Canada would return nothing at the caller's default admin_2."""
        payload = resolve_reference(
            from_system="gers", value=CAN_GERS_ID, target_admin_level="admin_2"
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["admin_level"], 3)

    def test_secondary_overlaps_are_visible_but_make_no_identity_claim(self) -> None:
        payload = resolve_gers_division(USA_GERS_ID)

        self.assertTrue(payload["overlaps"])
        for overlap in payload["overlaps"]:
            self.assertFalse(overlap["is_primary"])
            self.assertEqual(overlap["relationship_type"], "overlaps")

    def test_a_well_formed_unknown_id_is_refused(self) -> None:
        payload = resolve_gers_division(WELL_FORMED_BUT_UNKNOWN)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "gers_division_not_found")

    def test_common_aliases_reach_the_crosswalk(self) -> None:
        for alias in ("gers", "overture", "overture_gers", "overture_division"):
            with self.subTest(alias=alias):
                payload = resolve_reference(from_system=alias, value=USA_GERS_ID)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["resolved_loc_id"], USA_GERS_LOC_ID)

    def test_identify_routes_a_column_of_gers_ids(self) -> None:
        payload = identify_reference_system(
            [USA_GERS_ID, CAN_GERS_ID], validation_scope="all_distinct_identifiers"
        )

        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["recommended_binding"]["system"], GERS_SYSTEM)

    def test_identify_reports_partial_when_only_some_ids_are_known(self) -> None:
        payload = identify_reference_system(
            [USA_GERS_ID, WELL_FORMED_BUT_UNKNOWN],
            validation_scope="all_distinct_identifiers",
        )

        self.assertEqual(payload["status"], "partial_match")

    def test_discovery_lists_gers_without_advertising_an_admin_join(self) -> None:
        entry = next(
            item for item in list_reference_systems()["systems"]
            if item["system"] == GERS_SYSTEM
        )

        self.assertTrue(entry["exchangeable"])
        self.assertEqual(entry["role"], "exact_identifier_system")
        self.assertEqual(entry["exchange_via"], "exact_identifier_crosswalk")
        self.assertNotIn("target_admin_level", entry)
        self.assertIn("not a join key", entry["level_note"])

    def test_discovery_reports_the_observed_level_mix(self) -> None:
        """One subtype spanning three of our levels is the evidence itself."""
        entry = next(
            item for item in list_reference_systems()["systems"]
            if item["system"] == GERS_SYSTEM
        )
        county_levels = {
            key for key in entry["subtype_admin_level_rows"] if key.startswith("county_")
        }

        self.assertGreater(len(county_levels), 1)


if __name__ == "__main__":
    unittest.main()
