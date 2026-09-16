"""Build a Lake County ACS 2023 5-year tract demographics layer joined to 2020 tract boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
TRACTS_PATH = BASE_DIR / "static" / "data" / "fema_nri_v1_20_lake_county_tracts.geojson"
OUTPUT_PATH = BASE_DIR / "static" / "data" / "lake_county_acs2023_tract_demographics.geojson"
ACS_TABLE_URL = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData"

VARIABLES = [
    "NAME",
    "B01003_001E",  # total population
    "B11001_001E",  # total households
    "B02001_002E",  # white alone
    "B02001_003E",  # black or african american alone
    "B02001_005E",  # asian alone
    "B03003_003E",  # hispanic or latino
    "B01001_020E",  # male 75 to 79
    "B01001_021E",  # male 80 to 84
    "B01001_022E",  # male 85+
    "B01001_023E",  # female 75 to 79
    "B01001_024E",  # female 80 to 84
    "B01001_025E",  # female 85+
    "B19055_002E",  # households with supplement security income
    "B25044_003E",  # owner occupied households with no vehicle
    "B25044_010E",  # renter occupied households with no vehicle
    "B17017_001E",  # total households for poverty status
    "B17017_002E",  # households below poverty line
    "B18101_001E",  # civilian noninstitutionalized population for disability status
    "B18101_004E", "B18101_007E", "B18101_010E", "B18101_013E", "B18101_016E", "B18101_019E",
    "B18101_023E", "B18101_026E", "B18101_029E", "B18101_032E", "B18101_035E", "B18101_038E",
]


def as_int(raw):
    if raw is None or raw == "":
        return 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def percent(num: float, denom: float) -> float:
    if denom in (None, 0):
        return 0.0
    return round((float(num) / float(denom)) * 100.0, 4)


def fetch_acs_tracts() -> dict[str, dict[str, int | str]]:
    table_names = sorted({variable[:6] for variable in VARIABLES if variable[:1] == "B"})
    tables: dict[str, dict[str, dict[str, str]]] = {}
    for table_name in table_names:
        url = f"{ACS_TABLE_URL}/acsdt5y2023-{table_name.lower()}.dat"
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        rows = response.text.splitlines()
        if len(rows) < 2:
            raise RuntimeError(f"ACS table returned no rows: {table_name}")
        header = rows[0].split("|")
        table_rows = {}
        for row in rows[1:]:
            values = row.split("|")
            if not values or not values[0].startswith("1400000US06033"):
                continue
            table_rows[values[0][9:]] = {
                header[index]: values[index]
                for index in range(min(len(header), len(values)))
            }
        tables[table_name] = table_rows

    tract_geoids = set(tables["B01003"])
    data = {}
    for geoid in tract_geoids:
        record = {**tables["B01003"][geoid], **tables["B11001"][geoid], **tables["B02001"][geoid],
                  **tables["B03003"][geoid], **tables["B01001"][geoid], **tables["B19055"][geoid],
                  **tables["B25044"][geoid], **tables["B17017"][geoid], **tables["B18101"][geoid]}
        disabled_pop = sum(as_int(record.get(f"B18101_E{i:03d}")) for i in (4, 7, 10, 13, 16, 19, 23, 26, 29, 32, 35, 38))
        data[geoid] = {
            "total_population": as_int(record.get("B01003_E001")),
            "total_households": as_int(record.get("B11001_E001")),
            "white_pop": as_int(record.get("B02001_E002")),
            "black_pop": as_int(record.get("B02001_E003")),
            "asian_pop": as_int(record.get("B02001_E005")),
            "hispanic_pop": as_int(record.get("B03003_E003")),
            "age_75_plus_pop": sum(as_int(record.get(f"B01001_E{i:03d}")) for i in range(20, 26)),
            "ssi_households": as_int(record.get("B19055_E002")),
            "no_car_households": as_int(record.get("B25044_E003")) + as_int(record.get("B25044_E010")),
            "poverty_households": as_int(record.get("B17017_E002")),
            "poverty_household_total": as_int(record.get("B17017_E001")),
            "disabled_pop": disabled_pop,
            "disability_population_total": as_int(record.get("B18101_E001")),
        }
    return data


def build_layer() -> dict:
    with open(TRACTS_PATH, "r", encoding="utf-8") as fh:
        tracts = json.load(fh)

    acs = fetch_acs_tracts()
    joined_features = []
    unmatched = []

    for feature in tracts.get("features", []):
        props = feature.get("properties", {})
        tract_geoid = str(props.get("GEOID") or props.get("TRACTFIPS") or "").strip()
        if not tract_geoid:
            tract_geoid = str(props.get("STCOFIPS") or "") + str(props.get("TRACT") or "")
        lookup_key = tract_geoid.replace("-", "")
        if len(lookup_key) == 11 and lookup_key.startswith("06033"):
            lookup_key = lookup_key[5:]  # keep tract-only if the source already includes state+county
        record = acs.get(lookup_key) or acs.get(tract_geoid)
        if record is None:
            unmatched.append(tract_geoid)
            continue

        total_population = record["total_population"]
        total_households = record["total_households"]
        white_pop = record["white_pop"]
        black_pop = record["black_pop"]
        asian_pop = record["asian_pop"]
        hispanic_pop = record["hispanic_pop"]
        age_75_plus_pop = record["age_75_plus_pop"]
        ssi_households = record["ssi_households"]
        no_car_households = record["no_car_households"]
        poverty_households = record["poverty_households"]
        poverty_household_total = record["poverty_household_total"] or total_households
        disabled_pop = record["disabled_pop"]
        disability_population_total = record["disability_population_total"]

        merged = dict(props)
        merged.update(
            {
                "acs_2023_year": 2023,
                "acs_2023_boundary_source": "US Census TIGER/Line 2020 tract boundaries",
                "acs_2023_source": "U.S. Census Bureau ACS 5-Year estimates (2023)",
                "total_population": total_population,
                "total_households": total_households,
                "white_pop": white_pop,
                "white_share_pct": percent(white_pop, total_population),
                "black_pop": black_pop,
                "black_share_pct": percent(black_pop, total_population),
                "asian_pop": asian_pop,
                "asian_share_pct": percent(asian_pop, total_population),
                "hispanic_pop": hispanic_pop,
                "hispanic_share_pct": percent(hispanic_pop, total_population),
                "age_75_plus_pop": age_75_plus_pop,
                "age_75_plus_share_pct": percent(age_75_plus_pop, total_population),
                "ssi_households": ssi_households,
                "ssi_household_share_pct": percent(ssi_households, total_households),
                "no_car_households": no_car_households,
                "no_car_household_share_pct": percent(no_car_households, total_households),
                "poverty_households": poverty_households,
                "poverty_household_share_pct": percent(poverty_households, poverty_household_total),
                "disabled_pop": disabled_pop,
                "disabled_pop_share_pct": percent(disabled_pop, disability_population_total),
                "disabled_measure_label": "People with a disability; ACS does not publish a direct household-level measure in this table",
                "tract_geoid": tract_geoid,
            }
        )
        feature["properties"] = merged
        joined_features.append(feature)

    output = {"type": "FeatureCollection", "features": joined_features}
    print(f"Joined {len(joined_features)} / {len(tracts.get('features', []))} tracts")
    if unmatched:
        print("Unmatched tract GEOIDs:", unmatched)
    return output


def main() -> None:
    output = build_layer()
    OUTPUT_PATH.write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
