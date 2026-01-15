"""
Create crosswalk.json files for European countries using Eurostat NUTS codes.

Eurostat uses NUTS (Nomenclature of Territorial Units for Statistics) codes which
differ from GADM codes. This script creates crosswalk documentation files for all
European countries that have eurostat data folders.

NUTS code structure:
- NUTS-0: 2-char country code (DE, FR, etc.) - we use ISO3 in loc_id
- NUTS-1: 3-char region (DE1, DE2, etc.)
- NUTS-2: 4-char province (DE11, DE12, etc.)
- NUTS-3: 5-char district (DE111, DE112, etc.)

GADM vs NUTS:
- GADM uses different admin_1/admin_2 codes specific to each country
- No automatic mapping exists between NUTS and GADM at sub-country levels
- Country geometry files should be preferred over GADM fallback

Usage:
    python create_eurostat_crosswalks.py
"""

import json
from pathlib import Path

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data")
COUNTRIES_DIR = DATA_DIR / "countries"

# European country ISO3 codes that use Eurostat NUTS
EUROPEAN_COUNTRIES = {
    "ALB": "Albania",
    "AUT": "Austria",
    "BEL": "Belgium",
    "BGR": "Bulgaria",
    "CHE": "Switzerland",
    "CYP": "Cyprus",
    "CZE": "Czechia",
    "DEU": "Germany",
    "DNK": "Denmark",
    "ESP": "Spain",
    "EST": "Estonia",
    "FIN": "Finland",
    "FRA": "France",
    "GBR": "United Kingdom",
    "GRC": "Greece",
    "HRV": "Croatia",
    "HUN": "Hungary",
    "IRL": "Ireland",
    "ISL": "Iceland",
    "ITA": "Italy",
    "LIE": "Liechtenstein",
    "LTU": "Lithuania",
    "LUX": "Luxembourg",
    "LVA": "Latvia",
    "MKD": "North Macedonia",
    "MLT": "Malta",
    "MNE": "Montenegro",
    "NLD": "Netherlands",
    "NOR": "Norway",
    "POL": "Poland",
    "PRT": "Portugal",
    "ROU": "Romania",
    "SRB": "Serbia",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "SWE": "Sweden",
    "TUR": "Turkey",
}


def create_crosswalk(iso3: str, country_name: str) -> dict:
    """Create a crosswalk.json structure for a European country."""
    return {
        "_description": f"Crosswalk documentation for {country_name} ({iso3}) Eurostat NUTS codes",
        "_purpose": "Documents NUTS code format and GADM compatibility",
        "source_system": "eurostat_nuts",
        "target_system": "gadm",

        "nuts_format": {
            "_note": f"NUTS codes for {country_name}",
            "country_code": iso3[:2] if len(iso3) == 3 else iso3,
            "nuts_1_length": 3,
            "nuts_2_length": 4,
            "nuts_3_length": 5,
            "_examples": {
                "nuts_0": f"{iso3}",
                "nuts_1": f"{iso3}-{iso3[:2]}1",
                "nuts_2": f"{iso3}-{iso3[:2]}11",
                "nuts_3": f"{iso3}-{iso3[:2]}111"
            }
        },

        "gadm_compatibility": {
            "_warning": "NUTS codes are NOT directly compatible with GADM codes",
            "_reason": "GADM uses different region naming/numbering schemes",
            "_recommendation": f"Use countries/{iso3}/geometry.parquet for {country_name} sub-national data",
            "level_0": "Compatible (country level)",
            "level_1": "INCOMPATIBLE - different region codes",
            "level_2": "INCOMPATIBLE - different region codes",
            "level_3": "INCOMPATIBLE - different region codes"
        },

        "notes": {
            "source": "Eurostat Regional Statistics",
            "hierarchy": "NUTS-0 (country) -> NUTS-1 (regions) -> NUTS-2 (provinces) -> NUTS-3 (districts)",
            "loc_id_format": "{ISO3}-{NUTS_CODE}",
            "fallback": "Do not use GADM fallback for NUTS data - use country geometry instead"
        }
    }


def main():
    print("=" * 60)
    print("Creating Eurostat Crosswalk Files")
    print("=" * 60)

    created = 0
    skipped = 0

    for iso3, name in sorted(EUROPEAN_COUNTRIES.items()):
        country_dir = COUNTRIES_DIR / iso3

        # Check if country folder exists
        if not country_dir.exists():
            print(f"  SKIP: {iso3} - no folder")
            skipped += 1
            continue

        # Check if eurostat data exists
        eurostat_dir = country_dir / "eurostat"
        if not eurostat_dir.exists():
            print(f"  SKIP: {iso3} - no eurostat folder")
            skipped += 1
            continue

        # Create crosswalk
        crosswalk_path = country_dir / "crosswalk.json"
        crosswalk = create_crosswalk(iso3, name)

        # Write file
        with open(crosswalk_path, 'w', encoding='utf-8') as f:
            json.dump(crosswalk, f, indent=2)

        print(f"  CREATED: {crosswalk_path.relative_to(DATA_DIR)}")
        created += 1

    print("\n" + "=" * 60)
    print(f"COMPLETE: Created {created} crosswalk files, skipped {skipped}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
