from geometry_catalog_shared import build_geometry_capability_summary, public_geometry_catalog_records


def test_capability_summary_exposes_only_global_baseline_and_admitted_enrichment() -> None:
    catalog = {
        "generated_at": "2026-08-24T00:00:00Z",
        "global_admin_baseline": [
            {"country_code": "BRA", "max_admin_level": 2},
            {"country_code": "AUS", "max_admin_level": 2},
            {"country_code": "FRA", "max_admin_level": 2},
        ],
        "country_profiles": [{"country_code": "AUS", "profile_id": "australia"}],
        "country_family_coverage": [
            {
                "country_code": "AUS",
                "label": "Australia",
                "active_admin_depth": 6,
                "available_family_ids": ["administrative"],
            },
            {
                "country_code": "BRA",
                "label": "Brazil",
                "active_admin_depth": 2,
                "candidate_admin_depth": 4,
                "candidate_admin_status": "blocked",
                "available_family_ids": ["administrative"],
            },
            {
                "country_code": "FRA",
                "label": "France",
                "active_admin_depth": 2,
                "candidate_admin_depth": 4,
                "candidate_admin_status": "preparing",
                "available_family_ids": ["administrative"],
            },
        ],
    }

    summary = build_geometry_capability_summary(catalog)

    assert summary["global_baseline"]["geographic_entity_count"] == 3
    assert summary["global_baseline"]["max_admin_depth"] == 2
    assert summary["enhanced_country_codes"] == ["AUS"]
    assert "candidate_countries" not in summary
    assert "country_programs" not in summary
    assert "same geography tools work" in summary["public_claim"].lower()


def test_additional_reference_family_counts_as_enrichment() -> None:
    summary = build_geometry_capability_summary({
        "global_admin_baseline": [{"country_code": "GBR", "max_admin_level": 2}],
        "country_family_coverage": [{
            "country_code": "GBR",
            "label": "United Kingdom",
            "active_admin_depth": 2,
            "available_family_ids": ["administrative", "place_or_municipality"],
        }],
    })

    assert summary["enhanced_country_codes"] == ["GBR"]
    assert summary["enhanced_countries"][0]["enrichment_reasons"] == ["additional_reference_families"]


def test_country_appears_when_usable_depth_improves_not_when_candidate_is_prepared() -> None:
    baseline = [{"country_code": "FRA", "max_admin_level": 2}]
    prepared = build_geometry_capability_summary({
        "global_admin_baseline": baseline,
        "country_family_coverage": [{
            "country_code": "FRA",
            "label": "France",
            "active_admin_depth": 2,
            "candidate_admin_depth": 4,
            "candidate_admin_status": "prepared_unadmitted",
            "available_family_ids": ["administrative"],
        }],
    })
    admitted = build_geometry_capability_summary({
        "global_admin_baseline": baseline,
        "country_family_coverage": [{
            "country_code": "FRA",
            "label": "France",
            "active_admin_depth": 4,
            "candidate_admin_depth": 5,
            "candidate_admin_status": "preparing",
            "available_family_ids": ["administrative", "place_or_municipality"],
        }],
    })

    assert prepared["enhanced_country_codes"] == []
    assert admitted["enhanced_country_codes"] == ["FRA"]
    assert admitted["enhanced_countries"][0]["active_admin_depth"] == 4
    assert "candidate_admin_depth" not in admitted["enhanced_countries"][0]
    assert "France" in admitted["public_claim"]


def test_public_records_hide_wip_but_keep_admitted_candidate_pass() -> None:
    rows = public_geometry_catalog_records({"geometry_products": [
        {"product_id": "published", "release_state": "published"},
        {"product_id": "admitted", "release_state": "candidate_pass"},
        {"product_id": "wip", "release_state": "candidate_blocked"},
    ]}, "geometry_products")

    assert [item["product_id"] for item in rows] == ["published", "admitted"]


def test_public_country_profile_hides_release_lane_and_unavailable_packages() -> None:
    rows = public_geometry_catalog_records({"country_profiles": [{
        "profile_id": "example",
        "release_status": "candidate_pass",
        "release_id": "example_candidate_r1",
        "graph_release_id": "example_graph_candidate",
        "qa_highlights": ["The adopted local spine passes.", "The graph is local and unpublished."],
        "family_coverage": [{"family_id": "administrative", "state": "graph_admitted", "available": True}],
        "package_recipes": [
            {"package_id": "ready", "download_available": True},
            {"package_id": "wip", "download_available": False},
        ],
    }]}, "country_profiles")

    assert len(rows) == 1
    profile = rows[0]
    assert "release_status" not in profile
    assert "release_id" not in profile
    assert profile["qa_highlights"] == ["The maintained spine passes."]
    assert "state" not in profile["family_coverage"][0]
    assert [item["package_id"] for item in profile["package_recipes"]] == ["ready"]
