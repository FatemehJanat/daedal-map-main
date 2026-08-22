from mapmover.runtime.geometry_inventory import build_depth_index


def test_candidate_product_cannot_raise_active_depth() -> None:
    catalog = {
        "country_family_coverage": [],
        "geometry_products": [{
            "product_group": "admin_spine",
            "scope": "BRA",
            "admin_coverage": {"max_admin_level": 5},
        }],
        "global_admin_baseline": [{
            "country_code": "BRA",
            "max_admin_level": 2,
        }],
    }

    index, _global = build_depth_index(catalog)

    assert index["BRA"]["max_admin_level"] == 2
    assert index["BRA"]["depth_source"] == "shared_bank_baseline"


def test_active_and_candidate_depths_remain_separate() -> None:
    catalog = {
        "country_family_coverage": [{
            "country_code": "GBR",
            "max_admin_level": 2,
            "active_admin_depth": 2,
            "candidate_admin_depth": 3,
            "candidate_admin_status": "blocked_spatial_qa",
            "families": [{
                "family_id": "administrative",
                "max_admin_level": 2,
                "active_admin_depth": 2,
                "candidate_admin_depth": 3,
                "candidate_admin_status": "blocked_spatial_qa",
            }],
        }],
        "global_admin_baseline": [{
            "country_code": "GBR",
            "max_admin_level": 2,
        }],
    }

    index, _global = build_depth_index(catalog)

    assert index["GBR"]["max_admin_level"] == 2
    assert index["GBR"]["candidate_admin_depth"] == 3
    assert index["GBR"]["candidate_admin_status"] == "blocked_spatial_qa"
    assert index["GBR"]["program"]["active_admin_depth"] == 2
    assert index["GBR"]["program"]["candidate_admin_depth"] == 3
