import pandas as pd

from mapmover.runtime.family_admin_crosswalk import resolve_family_to_admin


def test_identity_crosswalk_without_overlap_metrics_is_supported(tmp_path) -> None:
    crosswalk_path = tmp_path / "identity_crosswalk.parquet"
    pd.DataFrame([{
        "source_family": "ibge_municipality",
        "source_loc_id": "3550308",
        "source_name": "Sao Paulo",
        "target_family": "admin",
        "target_admin_level": "admin_2",
        "target_loc_id": "BRA-EXAMPLE",
        "target_name": "Sao Paulo",
        "is_primary": True,
        "primary_policy": "representative_point",
        "relationship_vintage": "2022",
    }]).to_parquet(crosswalk_path, index=False)

    payload = resolve_family_to_admin(
        "3550308",
        source_family="ibge_municipality",
        target_admin_level="admin_2",
        iso3="BRA",
        crosswalk_path=crosswalk_path,
    )

    assert payload["ok"] is True
    assert payload["primary_match"]["match_loc_id"] == "BRA-EXAMPLE"
    assert payload["primary_match"]["source_area_share"] is None
