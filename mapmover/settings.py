"""
Settings Management for County Map

Handles storage and retrieval of application settings,
particularly the external backup folder path for large data files.
"""

import json
from pathlib import Path

# Settings file location (in project root)
SETTINGS_FILE = Path(__file__).parent.parent / "settings.json"

# Default settings
DEFAULT_SETTINGS = {
    "backup_path": ""
}

# Expected folder structure within backup path
BACKUP_FOLDERS = ["geometry", "data", "metadata"]


def load_settings() -> dict:
    """
    Load settings from settings.json file.
    Returns default settings if file doesn't exist.
    """
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # Merge with defaults to ensure all keys exist
                return {**DEFAULT_SETTINGS, **settings}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load settings: {e}")

    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> bool:
    """
    Save settings to settings.json file.
    Returns True on success, False on failure.
    """
    try:
        # Merge with existing settings
        current = load_settings()
        current.update(settings)

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(current, f, indent=2)
        return True
    except IOError as e:
        print(f"Error saving settings: {e}")
        return False


def get_backup_path() -> str:
    """Get the configured backup path."""
    settings = load_settings()
    return settings.get("backup_path", "")


def set_backup_path(path: str) -> bool:
    """Set the backup path."""
    return save_settings({"backup_path": path})


def check_backup_folders(backup_path: str) -> dict:
    """
    Check which folders exist in the backup path.
    Returns dict mapping folder name to existence boolean.
    """
    if not backup_path:
        return {}

    base_path = Path(backup_path)
    result = {}

    for folder in BACKUP_FOLDERS:
        folder_path = base_path / folder
        result[folder] = folder_path.exists()

    return result


def init_backup_folders(backup_path: str) -> list:
    """
    Create the backup folder structure.
    Returns list of created folder names.
    """
    if not backup_path:
        raise ValueError("Backup path is required")

    base_path = Path(backup_path)
    created = []

    # Create base path if it doesn't exist
    base_path.mkdir(parents=True, exist_ok=True)

    # Create subfolders
    for folder in BACKUP_FOLDERS:
        folder_path = base_path / folder
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)
            created.append(folder)

        # Create README in each folder
        readme_path = folder_path / "README.txt"
        if not readme_path.exists():
            readme_content = get_folder_readme(folder)
            readme_path.write_text(readme_content, encoding='utf-8')

    return created if created else BACKUP_FOLDERS


def get_folder_readme(folder_name: str) -> str:
    """Get README content for a backup folder."""
    readmes = {
        "geometry": """Geometry Folder
===============

This folder stores geographic boundary files (GeoJSON, Shapefiles).

Recommended structure:
  admin_0/          -- Country boundaries
  admin_1/          -- State/province boundaries
  admin_2/          -- County/district boundaries
  admin_3/          -- City/municipality boundaries

Sources:
  - GADM (gadm.org)
  - Natural Earth (naturalearthdata.com)
  - geoBoundaries (geoboundaries.org)
  - US Census TIGER/Line
""",
        "data": """Data Folder
===========

This folder stores indicator datasets (Parquet, CSV).

Recommended structure:
  [indicator_name]/
    admin_0/
      all_countries_all_years.parquet
    admin_1/
      usa_all_years.parquet
      fra_all_years.parquet

Examples:
  gdp/admin_0/all_countries_all_years.parquet
  population/admin_1/usa_all_years.parquet
  poverty/admin_0/all_countries_all_years.parquet

Sources:
  - World Bank Open Data
  - UN SDG Database
  - OECD.Stat
  - OWID
""",
        "metadata": """Metadata Folder
===============

This folder stores catalog and index files.

Key files:
  catalog.json              -- Master catalog of all datasets
  catalog_embeddings.npy    -- Vector embeddings for semantic search

The catalog.json contains:
  - Dataset paths and descriptions
  - Geographic and temporal coverage
  - Tags and keywords for search
  - SDG alignment information
"""
    }
    return readmes.get(folder_name, f"{folder_name} folder for county-map data")


def get_settings_with_status() -> dict:
    """
    Get settings along with folder existence status.
    Used by the /settings endpoint.
    """
    settings = load_settings()
    backup_path = settings.get("backup_path", "")

    result = {
        "backup_path": backup_path,
        "folders_exist": check_backup_folders(backup_path) if backup_path else {}
    }

    return result
