"""
Migrate European country folders into EUR regional folder.

This script:
1. Creates countries/EUR/ folder
2. Moves all European country folders (DEU, FRA, etc.) into EUR/
3. Consolidates per-country eurostat parquets into EUR/eurostat.parquet
4. Creates single EUR/crosswalk.json
5. Combines geometry files into EUR/geometry.parquet
6. Deletes old per-country crosswalk.json files

Usage:
    python migrate_europe_to_eur.py          # Dry run
    python migrate_europe_to_eur.py --apply  # Apply changes
"""

import json
import shutil
import pandas as pd
from pathlib import Path
import sys

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data")
COUNTRIES_DIR = DATA_DIR / "countries"
EUR_DIR = COUNTRIES_DIR / "EUR"

# European country ISO3 codes
EUROPEAN_COUNTRIES = [
    "ALB", "AUT", "BEL", "BGR", "CHE", "CYP", "CZE", "DEU", "DNK",
    "ESP", "EST", "FIN", "FRA", "GBR", "GRC", "HRV", "HUN", "IRL",
    "ISL", "ITA", "LIE", "LTU", "LUX", "LVA", "MKD", "MLT", "MNE",
    "NLD", "NOR", "POL", "PRT", "ROU", "SRB", "SVK", "SVN", "SWE", "TUR"
]

COUNTRY_NAMES = {
    "ALB": "Albania", "AUT": "Austria", "BEL": "Belgium", "BGR": "Bulgaria",
    "CHE": "Switzerland", "CYP": "Cyprus", "CZE": "Czechia", "DEU": "Germany",
    "DNK": "Denmark", "ESP": "Spain", "EST": "Estonia", "FIN": "Finland",
    "FRA": "France", "GBR": "United Kingdom", "GRC": "Greece", "HRV": "Croatia",
    "HUN": "Hungary", "IRL": "Ireland", "ISL": "Iceland", "ITA": "Italy",
    "LIE": "Liechtenstein", "LTU": "Lithuania", "LUX": "Luxembourg", "LVA": "Latvia",
    "MKD": "North Macedonia", "MLT": "Malta", "MNE": "Montenegro", "NLD": "Netherlands",
    "NOR": "Norway", "POL": "Poland", "PRT": "Portugal", "ROU": "Romania",
    "SRB": "Serbia", "SVK": "Slovakia", "SVN": "Slovenia", "SWE": "Sweden", "TUR": "Turkey"
}


def create_eur_crosswalk():
    """Create consolidated EUR crosswalk.json."""
    return {
        "_description": "Crosswalk documentation for European countries using Eurostat NUTS codes",
        "_purpose": "Documents NUTS code format and GADM compatibility for all EU/EEA countries",
        "source_system": "eurostat_nuts",
        "target_system": "gadm",

        "countries_covered": list(COUNTRY_NAMES.keys()),
        "country_count": len(COUNTRY_NAMES),

        "nuts_format": {
            "_note": "NUTS (Nomenclature of Territorial Units for Statistics) codes",
            "nuts_0": "2-char country code (DE, FR, etc.) - we use ISO3 in loc_id",
            "nuts_1": "3-char region code (DE1, FR1, etc.)",
            "nuts_2": "4-char province code (DE11, FR10, etc.)",
            "nuts_3": "5-char district code (DE111, FR101, etc.)",
            "loc_id_format": "{ISO3}-{NUTS_CODE}",
            "_examples": {
                "germany_nuts_0": "DEU",
                "germany_nuts_1": "DEU-DE1",
                "germany_nuts_2": "DEU-DE11",
                "germany_nuts_3": "DEU-DE111"
            }
        },

        "gadm_compatibility": {
            "_warning": "NUTS codes are NOT directly compatible with GADM codes",
            "_reason": "GADM uses different region naming/numbering schemes per country",
            "_recommendation": "Use EUR/geometry.parquet for European sub-national data, not GADM fallback",
            "level_0": "Compatible (country level - ISO3 codes match)",
            "level_1": "INCOMPATIBLE - NUTS regions differ from GADM admin_1",
            "level_2": "INCOMPATIBLE - NUTS provinces differ from GADM admin_2",
            "level_3": "INCOMPATIBLE - NUTS districts differ from GADM admin_3"
        },

        "notes": {
            "source": "Eurostat Regional Statistics",
            "hierarchy": "NUTS-0 (country) -> NUTS-1 (regions) -> NUTS-2 (provinces) -> NUTS-3 (districts)",
            "fallback": "Do not use GADM fallback for NUTS data - use EUR/geometry.parquet instead",
            "country_specific": "For country-specific non-Eurostat data, use EUR/{ISO3}/ subfolders"
        }
    }


def consolidate_eurostat_data(apply=False):
    """Consolidate all per-country eurostat parquets into one."""
    all_dfs = []
    files_found = []

    for iso3 in EUROPEAN_COUNTRIES:
        eurostat_dir = COUNTRIES_DIR / iso3 / "eurostat"
        parquet_path = eurostat_dir / f"{iso3}.parquet"

        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
            all_dfs.append(df)
            files_found.append(iso3)
            print(f"    Found {iso3}: {len(df)} rows")

    if not all_dfs:
        print("    No eurostat parquet files found!")
        return None

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"    Combined: {len(combined)} total rows from {len(files_found)} countries")

    if apply:
        output_path = EUR_DIR / "eurostat.parquet"
        combined.to_parquet(output_path, index=False)
        print(f"    Saved to {output_path}")

    return combined


def consolidate_geometry(apply=False):
    """Consolidate all per-country geometry parquets into one."""
    all_dfs = []
    files_found = []

    for iso3 in EUROPEAN_COUNTRIES:
        geom_path = COUNTRIES_DIR / iso3 / "geometry.parquet"

        if geom_path.exists():
            df = pd.read_parquet(geom_path)
            all_dfs.append(df)
            files_found.append(iso3)
            print(f"    Found {iso3}: {len(df)} regions")

    if not all_dfs:
        print("    No geometry parquet files found!")
        return None

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"    Combined: {len(combined)} total regions from {len(files_found)} countries")

    if apply:
        output_path = EUR_DIR / "geometry.parquet"
        combined.to_parquet(output_path, index=False)
        print(f"    Saved to {output_path}")

    return combined


def move_country_folders(apply=False):
    """Move European country folders into EUR/."""
    moved = 0

    for iso3 in EUROPEAN_COUNTRIES:
        src = COUNTRIES_DIR / iso3
        dst = EUR_DIR / iso3

        if not src.exists():
            continue

        if apply:
            # Move the folder
            shutil.move(str(src), str(dst))
            print(f"    Moved {iso3}/ -> EUR/{iso3}/")
        else:
            print(f"    Would move {iso3}/ -> EUR/{iso3}/")

        moved += 1

    return moved


def delete_old_crosswalks(apply=False):
    """Delete per-country crosswalk.json files (now in EUR/)."""
    deleted = 0

    for iso3 in EUROPEAN_COUNTRIES:
        # After move, path is EUR/{iso3}/crosswalk.json
        crosswalk_path = EUR_DIR / iso3 / "crosswalk.json"

        if crosswalk_path.exists():
            if apply:
                crosswalk_path.unlink()
                print(f"    Deleted EUR/{iso3}/crosswalk.json")
            else:
                print(f"    Would delete EUR/{iso3}/crosswalk.json")
            deleted += 1

    return deleted


def delete_old_eurostat_folders(apply=False):
    """Delete per-country eurostat folders after consolidation."""
    deleted = 0

    for iso3 in EUROPEAN_COUNTRIES:
        eurostat_dir = EUR_DIR / iso3 / "eurostat"

        if eurostat_dir.exists():
            if apply:
                shutil.rmtree(str(eurostat_dir))
                print(f"    Deleted EUR/{iso3}/eurostat/")
            else:
                print(f"    Would delete EUR/{iso3}/eurostat/")
            deleted += 1

    return deleted


def delete_old_geometry_files(apply=False):
    """Delete per-country geometry.parquet files after consolidation."""
    deleted = 0

    for iso3 in EUROPEAN_COUNTRIES:
        geom_path = EUR_DIR / iso3 / "geometry.parquet"

        if geom_path.exists():
            if apply:
                geom_path.unlink()
                print(f"    Deleted EUR/{iso3}/geometry.parquet")
            else:
                print(f"    Would delete EUR/{iso3}/geometry.parquet")
            deleted += 1

    return deleted


def main():
    apply = '--apply' in sys.argv

    print("=" * 60)
    print("Migrate European Countries to EUR Folder")
    print("=" * 60)

    if apply:
        print("\nMode: APPLY (changes will be made)")
    else:
        print("\nMode: DRY RUN (preview only, use --apply to execute)")

    # Step 1: Create EUR folder
    print("\n--- Step 1: Create EUR folder ---")
    if apply:
        EUR_DIR.mkdir(parents=True, exist_ok=True)
        print(f"    Created {EUR_DIR}")
    else:
        print(f"    Would create {EUR_DIR}")

    # Step 2: Consolidate eurostat data BEFORE moving folders
    print("\n--- Step 2: Consolidate Eurostat data ---")
    if apply:
        EUR_DIR.mkdir(parents=True, exist_ok=True)
    consolidate_eurostat_data(apply=apply)

    # Step 3: Consolidate geometry BEFORE moving folders
    print("\n--- Step 3: Consolidate geometry ---")
    consolidate_geometry(apply=apply)

    # Step 4: Move country folders into EUR
    print("\n--- Step 4: Move country folders into EUR ---")
    moved = move_country_folders(apply=apply)
    print(f"    Total: {moved} folders")

    # Step 5: Create EUR crosswalk
    print("\n--- Step 5: Create EUR/crosswalk.json ---")
    if apply:
        crosswalk = create_eur_crosswalk()
        crosswalk_path = EUR_DIR / "crosswalk.json"
        with open(crosswalk_path, 'w', encoding='utf-8') as f:
            json.dump(crosswalk, f, indent=2)
        print(f"    Created {crosswalk_path}")
    else:
        print(f"    Would create EUR/crosswalk.json")

    # Step 6: Delete old per-country crosswalks
    print("\n--- Step 6: Delete old per-country crosswalks ---")
    deleted_crosswalks = delete_old_crosswalks(apply=apply)
    print(f"    Total: {deleted_crosswalks} files")

    # Step 7: Delete old per-country eurostat folders
    print("\n--- Step 7: Delete old per-country eurostat folders ---")
    deleted_eurostat = delete_old_eurostat_folders(apply=apply)
    print(f"    Total: {deleted_eurostat} folders")

    # Step 8: Delete old per-country geometry files
    print("\n--- Step 8: Delete old per-country geometry files ---")
    deleted_geom = delete_old_geometry_files(apply=apply)
    print(f"    Total: {deleted_geom} files")

    print("\n" + "=" * 60)
    if apply:
        print("COMPLETE!")
        print("\nNew structure:")
        print("  countries/EUR/")
        print("    eurostat.parquet      # Combined Eurostat data")
        print("    geometry.parquet      # Combined NUTS geometry")
        print("    crosswalk.json        # Single crosswalk file")
        print("    DEU/                  # Empty, for future German-specific data")
        print("    FRA/                  # Empty, for future French-specific data")
        print("    ...")
    else:
        print("DRY RUN COMPLETE")
        print("\nRun with --apply to execute:")
        print("  python migrate_europe_to_eur.py --apply")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
