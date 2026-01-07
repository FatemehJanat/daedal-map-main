"""
Download Smithsonian Global Volcanism Program eruption database.

Downloads volcano locations and eruption history from the Smithsonian
Institution's Global Volcanism Program (GVP).

Source: https://volcano.si.edu/
Data: Volcano list, eruption history, VEI ratings

Usage:
    python download_volcano.py
"""

import requests
import json
from pathlib import Path
from datetime import datetime
import sys

# Output directory
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/smithsonian/volcano")

# Smithsonian GVP data sources
# These URLs provide downloadable volcano data
GVP_SOURCES = {
    "volcanoes_excel": {
        "url": "https://volcano.si.edu/database/search_volcano_list.xls",
        "filename": "gvp_volcano_list.xls",
        "description": "Complete volcano list with locations"
    },
    "eruptions_excel": {
        "url": "https://volcano.si.edu/database/search_eruption_list.xls",
        "filename": "gvp_eruption_list.xls",
        "description": "Complete eruption history with VEI"
    }
}

# Alternative: Direct API-style endpoints (JSON)
GVP_API = {
    "base_url": "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows",
    "endpoints": {
        "volcanoes": {
            "params": {
                "service": "WFS",
                "version": "1.0.0",
                "request": "GetFeature",
                "typeName": "GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes",
                "outputFormat": "application/json"
            },
            "filename": "gvp_volcanoes.json",
            "description": "Holocene volcanoes (GeoJSON)"
        },
        "eruptions": {
            "params": {
                "service": "WFS",
                "version": "1.0.0",
                "request": "GetFeature",
                "typeName": "GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions",
                "outputFormat": "application/json"
            },
            "filename": "gvp_eruptions.json",
            "description": "Holocene eruptions (GeoJSON)"
        }
    }
}


def download_file(url, output_path, description, params=None):
    """Download a file from URL."""
    print(f"\nDownloading {description}...")
    print(f"  URL: {url}")

    try:
        response = requests.get(url, params=params, stream=True, timeout=120)
        response.raise_for_status()

        # Get content size
        content_length = response.headers.get('content-length')
        total_size = int(content_length) if content_length else 0

        # Download
        with open(output_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        print(f"  Progress: {downloaded / 1024:.1f} KB / {total_size / 1024:.1f} KB ({pct:.1f}%)", end='\r')

        print()
        actual_size = output_path.stat().st_size
        print(f"  Complete: {actual_size / 1024:.1f} KB")

        return {
            "success": True,
            "file_size_bytes": actual_size
        }

    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def download_geojson(url, params, output_path, description):
    """Download GeoJSON data from WFS service."""
    print(f"\nDownloading {description}...")
    print(f"  URL: {url}")

    try:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()

        # Parse JSON to count features
        data = response.json()
        features = data.get('features', [])
        print(f"  Retrieved: {len(features)} features")

        # Save
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        actual_size = output_path.stat().st_size
        print(f"  Saved: {actual_size / 1024:.1f} KB")

        return {
            "success": True,
            "file_size_bytes": actual_size,
            "feature_count": len(features)
        }

    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    except json.JSONDecodeError as e:
        print(f"  ERROR parsing JSON: {e}")
        return {
            "success": False,
            "error": f"JSON parse error: {e}"
        }


def main():
    """Download all volcano data."""
    print("=" * 70)
    print("Smithsonian Global Volcanism Program Downloader")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Source: https://volcano.si.edu/")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}")

    # Metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Smithsonian Institution Global Volcanism Program",
        "source_url": "https://volcano.si.edu/",
        "citation": "Global Volcanism Program, 2024. [Database] Volcanoes of the World (v. 5.2.0; 2 Oct 2024). Distributed by Smithsonian Institution.",
        "files": {}
    }

    # Try GeoJSON/WFS first (more structured)
    print("\n--- Downloading via WFS Service (GeoJSON) ---")

    for key, config in GVP_API["endpoints"].items():
        output_path = OUTPUT_DIR / config["filename"]
        result = download_geojson(
            GVP_API["base_url"],
            config["params"],
            output_path,
            config["description"]
        )
        metadata["files"][key] = {
            "filename": config["filename"],
            "description": config["description"],
            "format": "GeoJSON",
            **result
        }

    # Also download Excel files as backup
    print("\n--- Downloading Excel Files (backup) ---")

    for key, config in GVP_SOURCES.items():
        output_path = OUTPUT_DIR / config["filename"]
        result = download_file(
            config["url"],
            output_path,
            config["description"]
        )
        metadata["files"][key] = {
            "filename": config["filename"],
            "description": config["description"],
            "format": "Excel",
            **result
        }

    # Save metadata
    metadata_path = OUTPUT_DIR / "volcano_metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved to: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)

    success_count = sum(1 for f in metadata["files"].values() if f.get("success"))
    total_files = len(metadata["files"])
    print(f"Successful: {success_count}/{total_files}")

    for key, info in metadata["files"].items():
        status = "OK" if info.get("success") else "FAILED"
        size = info.get("file_size_bytes", 0) / 1024
        count = info.get("feature_count", "")
        count_str = f" ({count} features)" if count else ""
        print(f"  {key}: {status} - {size:.1f} KB{count_str}")

    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
