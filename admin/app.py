"""
County Map - Developer Dashboard
Run with: streamlit run admin/app.py

Manages datasets, metadata, backups, and ETL pipeline.
"""

import streamlit as st
import json
import os
import shutil
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import Supabase client for cloud analytics (optional)
try:
    from supabase_client import get_supabase_client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

# Page config
st.set_page_config(
    page_title="County Map Developer",
    page_icon="",
    layout="wide"
)

# Paths
BASE_DIR = Path(__file__).parent.parent
DATA_PIPELINE_DIR = BASE_DIR / "data_pipeline"
DATA_LOADING_DIR = DATA_PIPELINE_DIR / "data_loading"
DATA_CLEANED_DIR = DATA_PIPELINE_DIR / "data_cleaned"
METADATA_DIR = DATA_PIPELINE_DIR / "metadata"
ULTIMATE_METADATA_FILE = METADATA_DIR / "ultimate_metadata.json"
CONFIG_DIR = BASE_DIR / "config"

# Backup configuration
BACKUP_PATH = Path("D:/data-backups")
BACKUP_CLEANED_DIR = BACKUP_PATH / "data_cleaned"
BACKUP_METADATA_DIR = BACKUP_PATH / "metadata"


def ensure_directories():
    """Ensure all required directories exist"""
    for dir_path in [DATA_LOADING_DIR, DATA_CLEANED_DIR, METADATA_DIR, CONFIG_DIR,
                     BACKUP_PATH, BACKUP_CLEANED_DIR, BACKUP_METADATA_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)


def load_geometry_registry():
    """Load the geometry registry configuration for join suggestions."""
    registry_path = METADATA_DIR / "geometry_registry.json"
    if registry_path.exists():
        with open(registry_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"geometry_files": {}, "data_files": {}}


def get_join_suggestion(df, geo_level):
    """
    Get suggestion for whether data should join an existing dataset.
    Returns dict with action, target file, and reason.
    """
    registry = load_geometry_registry()

    # Map detected level to registry level
    level_mapping = {
        "county": "us_county",
        "state": "us_state",
        "country": "country",
        "city": "city",
        "us_place": "us_place"
    }
    registry_level = level_mapping.get(geo_level, geo_level)

    # Find geometry file for this level
    geometry_file = None
    geometry_config = None
    for geom_file, config in registry.get("geometry_files", {}).items():
        if config.get("level") == registry_level:
            geometry_file = geom_file
            geometry_config = config
            break

    if not geometry_config:
        return {
            "action": "create_new",
            "target_file": None,
            "reason": f"No existing geometry found for level '{geo_level}'",
            "level": geo_level
        }

    # Check if there's an existing data file for this level
    existing_data_files = geometry_config.get("data_files", [])

    if existing_data_files:
        # Get info about existing data file
        existing_file = existing_data_files[0]
        data_info = registry.get("data_files", {}).get(existing_file, {})
        existing_columns = data_info.get("columns", [])

        return {
            "action": "join_existing",
            "target_file": existing_file,
            "geometry_file": geometry_file,
            "existing_columns": existing_columns,
            "reason": f"Data file '{existing_file}' already exists for {geo_level}-level data",
            "level": geo_level,
            "suggestion": f"Consider adding new columns to '{existing_file}' instead of creating a duplicate dataset"
        }
    else:
        return {
            "action": "create_new",
            "target_file": None,
            "geometry_file": geometry_file,
            "reason": f"No existing data file for {geo_level}-level. Will link to {geometry_file}",
            "level": geo_level,
            "suggestion": f"New data file will be created and linked to geometry in '{geometry_file}'"
        }


def load_ultimate_metadata():
    """Load the ultimate metadata file"""
    if ULTIMATE_METADATA_FILE.exists():
        with open(ULTIMATE_METADATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "version": "1.0",
        "last_updated": None,
        "datasets": {},
        "primary_sources": {}
    }


def detect_delimiter(filepath):
    """Detect CSV delimiter"""
    with open(filepath, newline='', encoding='utf-8') as f:
        first_line = f.readline()
        candidates = [',', ';', '\t', '|', ':']
        counts = {d: first_line.count(d) for d in candidates}
        return max(counts, key=counts.get)


def get_loading_folder_status():
    """
    Scan data_loading folder for pending CSV files.
    Returns list of files waiting to be processed.
    """
    ensure_directories()
    pending_files = []

    for csv_file in DATA_LOADING_DIR.glob("*.csv"):
        try:
            size_mb = round(csv_file.stat().st_size / (1024 * 1024), 2)
            pending_files.append({
                "filename": csv_file.name,
                "path": str(csv_file),
                "size_mb": size_mb,
                "modified": datetime.fromtimestamp(csv_file.stat().st_mtime).isoformat()
            })
        except Exception as e:
            pending_files.append({
                "filename": csv_file.name,
                "error": str(e)
            })

    return pending_files


def preview_csv(filepath, nrows=10):
    """
    Preview a CSV file and return info for column management.
    Returns dict with headers, sample data, and detected info.
    """
    try:
        delimiter = detect_delimiter(filepath)
        df = pd.read_csv(filepath, delimiter=delimiter, nrows=nrows)

        # Get full row count without loading entire file
        with open(filepath, 'r', encoding='utf-8') as f:
            row_count = sum(1 for _ in f) - 1  # subtract header

        return {
            "success": True,
            "delimiter": delimiter,
            "columns": df.columns.tolist(),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "sample_data": df.to_dict('records'),
            "row_count": row_count,
            "column_count": len(df.columns)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def scan_csv_source(filepath, sample_size=1000):
    """
    Deep scan a CSV file to analyze quality and suggest improvements.
    Returns dict with suggestions for deletions, renames, and warnings.
    """
    try:
        delimiter = detect_delimiter(filepath)

        # Load sample for analysis (or full file if small)
        df = pd.read_csv(filepath, delimiter=delimiter, nrows=sample_size)

        # Get full row count
        with open(filepath, 'r', encoding='utf-8') as f:
            total_rows = sum(1 for _ in f) - 1

        result = {
            "success": True,
            "total_rows": total_rows,
            "total_columns": len(df.columns),
            "columns_to_delete": [],
            "columns_to_rename": {},
            "warnings": [],
            "quality_score": 100,
            "geographic_level": "unknown",
            "detected_topics": [],
            "column_analysis": {}
        }

        # Standard column aliases (from ultimate_metadata schema)
        standard_aliases = {
            # Geographic identifiers
            "iso_a3": "country_code",
            "iso_code": "country_code",
            "admin country abbr": "country_code",
            "iso 3166-3 area code": "country_code",
            "locationcode": "country_code",
            "iso_a2": "country_code_2",
            "state_abbr": "state_code",
            "state_fips": "state_code",
            "official county code": "county_code",
            "county_fips": "county_code",
            # Geographic names
            "name": "country_name",
            "country": "country_name",
            "admin country name": "country_name",
            "location": "country_name",
            "state name": "state_name",
            "stname": "state_name",
            "official county name": "county_name",
            "ctyname": "county_name",
            "place name": "place_name",
            "city_name": "place_name",
            "full place name": "full_place_name",
            # Coordinates
            "lat": "latitude",
            "label_y": "latitude",
            "lng": "longitude",
            "lon": "longitude",
            "label_x": "longitude",
            # Common data
            "pop_est": "population",
            "pop": "population",
            "land area": "land_area",
            "area_land": "land_area",
            "water area": "water_area",
            "area_water": "water_area",
            "year": "data_year",
        }

        # Columns that are typically useless/redundant
        useless_patterns = [
            "unnamed:", "index", "unnamed", "_id", "objectid",
            "fid", "ogc_fid", "gid"
        ]

        # Analyze each column
        for col in df.columns:
            col_lower = col.lower().strip()
            col_analysis = {
                "original_name": col,
                "dtype": str(df[col].dtype),
                "null_percent": round(df[col].isna().sum() / len(df) * 100, 1),
                "unique_count": df[col].nunique(),
                "suggestion": None,
                "reason": None
            }

            # Check for empty/mostly null columns
            if col_analysis["null_percent"] > 95:
                result["columns_to_delete"].append(col)
                col_analysis["suggestion"] = "DELETE"
                col_analysis["reason"] = f"{col_analysis['null_percent']}% null values"
                result["quality_score"] -= 2

            # Check for useless columns
            elif any(pattern in col_lower for pattern in useless_patterns):
                result["columns_to_delete"].append(col)
                col_analysis["suggestion"] = "DELETE"
                col_analysis["reason"] = "Likely auto-generated index column"

            # Check for single-value columns (no variance)
            elif col_analysis["unique_count"] == 1:
                result["columns_to_delete"].append(col)
                col_analysis["suggestion"] = "DELETE"
                col_analysis["reason"] = "Only one unique value (no variance)"

            # Check for rename suggestions
            elif col_lower in standard_aliases:
                standard_name = standard_aliases[col_lower]
                if col != standard_name:
                    result["columns_to_rename"][col] = standard_name
                    col_analysis["suggestion"] = "RENAME"
                    col_analysis["reason"] = f"Matches standard '{standard_name}'"

            result["column_analysis"][col] = col_analysis

        # Detect geographic level
        columns_lower = [c.lower() for c in df.columns]
        if any("county" in c for c in columns_lower):
            result["geographic_level"] = "county"
        elif any("state" in c or "province" in c for c in columns_lower):
            result["geographic_level"] = "state"
        elif any("country" in c or "nation" in c or "iso" in c for c in columns_lower):
            result["geographic_level"] = "country"
        elif any("city" in c or "place" in c for c in columns_lower):
            result["geographic_level"] = "city"
        elif any("zip" in c or "postal" in c for c in columns_lower):
            result["geographic_level"] = "zip_code"

        # Get join suggestion based on geographic level
        if result["geographic_level"] != "unknown":
            join_suggestion = get_join_suggestion(df, result["geographic_level"])
            result["join_suggestion"] = join_suggestion

            # Note: Join suggestion is displayed prominently in UI, not as a warning

        # Detect topics
        topic_keywords = {
            "economics": ["gdp", "income", "economic", "trade", "export", "import"],
            "environment": ["co2", "emission", "climate", "temperature", "carbon"],
            "health": ["health", "life", "mortality", "disease", "medical"],
            "demographics": ["age", "gender", "census", "race", "ethnicity"],
            "population": ["population", "pop", "people", "resident"],
            "energy": ["energy", "electricity", "power", "oil", "gas", "renewable"],
        }

        all_columns_text = " ".join(columns_lower)
        for topic, keywords in topic_keywords.items():
            if any(kw in all_columns_text for kw in keywords):
                result["detected_topics"].append(topic)

        # Generate warnings
        if result["quality_score"] < 80:
            result["warnings"].append("Low quality score - many columns may need attention")

        if len(result["columns_to_delete"]) > len(df.columns) * 0.3:
            result["warnings"].append(f"Suggesting to delete {len(result['columns_to_delete'])} columns ({round(len(result['columns_to_delete'])/len(df.columns)*100)}%)")

        # Check for duplicate columns
        if len(df.columns) != len(set(col.lower() for col in df.columns)):
            result["warnings"].append("Possible duplicate column names (case-insensitive)")

        # Check for geometry column
        for col in df.columns:
            if df[col].dtype == 'object':
                sample_val = str(df[col].dropna().iloc[0]) if len(df[col].dropna()) > 0 else ""
                if '{"type"' in sample_val and '"coordinates"' in sample_val:
                    result["warnings"].append(f"Column '{col}' appears to contain GeoJSON geometry")
                    break

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_cleaned_datasets():
    """
    Get list of processed datasets in data_cleaned folder.
    Includes metadata if available, file dates, and backup status.
    """
    ensure_directories()
    datasets = []

    for csv_file in DATA_CLEANED_DIR.glob("*.csv"):
        base_name = csv_file.stem
        metadata_file = METADATA_DIR / f"{base_name}_metadata.json"
        backup_file = BACKUP_CLEANED_DIR / csv_file.name

        # Get file timestamps
        file_stat = csv_file.stat()
        created_time = datetime.fromtimestamp(file_stat.st_ctime)
        modified_time = datetime.fromtimestamp(file_stat.st_mtime)

        dataset_info = {
            "filename": csv_file.name,
            "path": str(csv_file),
            "size_mb": round(file_stat.st_size / (1024 * 1024), 2),
            "has_metadata": metadata_file.exists(),
            "date_added": created_time.strftime("%Y-%m-%d %H:%M"),
            "last_modified": modified_time.strftime("%Y-%m-%d %H:%M"),
            "is_backed_up": backup_file.exists()
        }

        # Check if backup is current (compare modification times)
        if backup_file.exists():
            backup_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            dataset_info["backup_date"] = backup_mtime.strftime("%Y-%m-%d %H:%M")
            dataset_info["backup_current"] = backup_mtime >= modified_time
        else:
            dataset_info["backup_date"] = None
            dataset_info["backup_current"] = False

        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    dataset_info["row_count"] = meta.get("row_count", 0)
                    dataset_info["column_count"] = len(meta.get("columns", {}))
                    dataset_info["geographic_level"] = meta.get("geographic_level", "unknown")
                    dataset_info["topic_tags"] = meta.get("topic_tags", [])
                    dataset_info["description"] = meta.get("description", "")
                    dataset_info["llm_summary"] = meta.get("llm_summary", "")
                    dataset_info["year_range"] = meta.get("data_year", {})
            except Exception as e:
                dataset_info["metadata_error"] = str(e)

        datasets.append(dataset_info)

    return datasets


def get_storage_info():
    """Get disk usage info for data directories"""
    result = {
        "loading": {"path": str(DATA_LOADING_DIR), "files": 0, "size_mb": 0},
        "cleaned": {"path": str(DATA_CLEANED_DIR), "files": 0, "size_mb": 0},
        "metadata": {"path": str(METADATA_DIR), "files": 0, "size_mb": 0},
        "backup": {"path": str(BACKUP_PATH), "files": 0, "size_mb": 0}
    }

    for key, dir_path in [("loading", DATA_LOADING_DIR),
                          ("cleaned", DATA_CLEANED_DIR),
                          ("metadata", METADATA_DIR),
                          ("backup", BACKUP_PATH)]:
        if dir_path.exists():
            files = list(dir_path.rglob("*"))  # recursive for backup
            result[key]["files"] = len([f for f in files if f.is_file()])
            result[key]["size_mb"] = round(sum(f.stat().st_size for f in files if f.is_file()) / (1024 * 1024), 2)

    # Get disk space for both drives
    try:
        total, used, free = shutil.disk_usage(BASE_DIR)
        result["disk_c"] = {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1)
        }
    except Exception as e:
        result["disk_c"] = {"error": str(e)}

    try:
        total, used, free = shutil.disk_usage(BACKUP_PATH)
        result["disk_d"] = {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1)
        }
    except Exception as e:
        result["disk_d"] = {"error": str(e)}

    return result


def get_backup_status():
    """
    Get status of dataset backups.
    Compare cleaned datasets vs backed up datasets.
    """
    ensure_directories()

    if not BACKUP_PATH.exists():
        return {
            "configured": False,
            "message": f"Backup path does not exist: {BACKUP_PATH}"
        }

    # Get cleaned files
    cleaned_files = set(f.name for f in DATA_CLEANED_DIR.glob("*.csv"))
    metadata_files = set(f.name for f in METADATA_DIR.glob("*.json"))

    # Get backed up files
    backed_up_csv = set(f.name for f in BACKUP_CLEANED_DIR.glob("*.csv")) if BACKUP_CLEANED_DIR.exists() else set()
    backed_up_meta = set(f.name for f in BACKUP_METADATA_DIR.glob("*.json")) if BACKUP_METADATA_DIR.exists() else set()

    # Check ultimate metadata
    ultimate_backed_up = (BACKUP_METADATA_DIR / "ultimate_metadata.json").exists()

    return {
        "configured": True,
        "path": str(BACKUP_PATH),
        "cleaned_total": len(cleaned_files),
        "cleaned_backed_up": len(cleaned_files & backed_up_csv),
        "cleaned_needs_backup": list(cleaned_files - backed_up_csv),
        "metadata_total": len(metadata_files),
        "metadata_backed_up": len(metadata_files & backed_up_meta),
        "metadata_needs_backup": list(metadata_files - backed_up_meta),
        "ultimate_backed_up": ultimate_backed_up,
        "last_backup": get_last_backup_time()
    }


def get_last_backup_time():
    """Get the most recent backup timestamp"""
    latest = None
    for dir_path in [BACKUP_CLEANED_DIR, BACKUP_METADATA_DIR]:
        if dir_path.exists():
            for f in dir_path.glob("*"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if latest is None or mtime > latest:
                    latest = mtime
    return latest.isoformat() if latest else None


def create_backup():
    """
    Create full backup of all datasets, metadata, and ultimate_metadata.
    Returns dict with results.
    """
    ensure_directories()
    results = {"csv_copied": 0, "meta_copied": 0, "errors": []}

    # Backup cleaned CSVs
    for csv_file in DATA_CLEANED_DIR.glob("*.csv"):
        try:
            dest = BACKUP_CLEANED_DIR / csv_file.name
            shutil.copy2(csv_file, dest)
            results["csv_copied"] += 1
        except Exception as e:
            results["errors"].append(f"CSV {csv_file.name}: {e}")

    # Backup metadata JSONs
    for meta_file in METADATA_DIR.glob("*.json"):
        try:
            dest = BACKUP_METADATA_DIR / meta_file.name
            shutil.copy2(meta_file, dest)
            results["meta_copied"] += 1
        except Exception as e:
            results["errors"].append(f"Meta {meta_file.name}: {e}")

    results["timestamp"] = datetime.now().isoformat()
    return results


def restore_from_backup(filename):
    """
    Restore a specific dataset from backup.
    Restores both CSV and metadata.
    """
    results = {"restored": [], "errors": []}

    # Restore CSV
    backup_csv = BACKUP_CLEANED_DIR / filename
    if backup_csv.exists():
        try:
            dest = DATA_CLEANED_DIR / filename
            shutil.copy2(backup_csv, dest)
            results["restored"].append(filename)
        except Exception as e:
            results["errors"].append(f"CSV: {e}")

    # Restore metadata
    base_name = Path(filename).stem
    backup_meta = BACKUP_METADATA_DIR / f"{base_name}_metadata.json"
    if backup_meta.exists():
        try:
            dest = METADATA_DIR / f"{base_name}_metadata.json"
            shutil.copy2(backup_meta, dest)
            results["restored"].append(f"{base_name}_metadata.json")
        except Exception as e:
            results["errors"].append(f"Metadata: {e}")

    return results


def delete_dataset(filename):
    """
    Delete a dataset and its metadata.
    Returns dict with results.
    """
    results = {"deleted": [], "errors": []}

    # Delete CSV
    csv_path = DATA_CLEANED_DIR / filename
    if csv_path.exists():
        try:
            csv_path.unlink()
            results["deleted"].append(filename)
        except Exception as e:
            results["errors"].append(f"CSV: {e}")

    # Delete metadata
    base_name = Path(filename).stem
    meta_path = METADATA_DIR / f"{base_name}_metadata.json"
    if meta_path.exists():
        try:
            meta_path.unlink()
            results["deleted"].append(f"{base_name}_metadata.json")
        except Exception as e:
            results["errors"].append(f"Metadata: {e}")

    return results


def reprocess_dataset(filename):
    """
    Move dataset back to loading folder for re-processing.
    """
    csv_path = DATA_CLEANED_DIR / filename
    if csv_path.exists():
        dest = DATA_LOADING_DIR / filename
        shutil.move(str(csv_path), str(dest))

        # Also delete old metadata
        base_name = Path(filename).stem
        meta_path = METADATA_DIR / f"{base_name}_metadata.json"
        if meta_path.exists():
            meta_path.unlink()

        return {"success": True, "message": f"Moved {filename} to loading folder"}
    return {"success": False, "message": "File not found"}


def regenerate_metadata_only(filename=None):
    """
    Regenerate metadata for a dataset without moving files.
    If filename is None, regenerate all datasets.

    Returns dict with results.
    """
    try:
        from data_pipeline.prepare_data import DataPreparer
        preparer = DataPreparer()

        results = {"regenerated": [], "errors": []}

        if filename:
            # Single file
            csv_path = DATA_CLEANED_DIR / filename
            if csv_path.exists():
                try:
                    # Load the CSV
                    delimiter = detect_delimiter(str(csv_path))
                    df = pd.read_csv(csv_path, delimiter=delimiter)

                    # Generate new metadata
                    metadata = preparer.generate_metadata(df, filename)

                    # Save metadata
                    base_name = Path(filename).stem
                    metadata_path = METADATA_DIR / f"{base_name}_metadata.json"
                    with open(metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2)

                    # Update ultimate metadata
                    preparer._update_ultimate_with_dataset(filename, metadata)
                    preparer._save_ultimate_metadata()

                    results["regenerated"].append(filename)
                except Exception as e:
                    results["errors"].append(f"{filename}: {e}")
            else:
                results["errors"].append(f"{filename}: File not found")
        else:
            # All files
            for csv_file in DATA_CLEANED_DIR.glob("*.csv"):
                try:
                    delimiter = detect_delimiter(str(csv_file))
                    df = pd.read_csv(csv_file, delimiter=delimiter)

                    metadata = preparer.generate_metadata(df, csv_file.name)

                    base_name = csv_file.stem
                    metadata_path = METADATA_DIR / f"{base_name}_metadata.json"
                    with open(metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2)

                    preparer._update_ultimate_with_dataset(csv_file.name, metadata)
                    results["regenerated"].append(csv_file.name)
                except Exception as e:
                    results["errors"].append(f"{csv_file.name}: {e}")

            # Save ultimate metadata once at the end
            if results["regenerated"]:
                preparer._save_ultimate_metadata()

        return results

    except Exception as e:
        return {"regenerated": [], "errors": [str(e)]}


def run_etl_with_options(filepath, columns_to_delete=None, column_renames=None):
    """
    Run ETL on a single file with optional column modifications.
    """
    try:
        from data_pipeline.prepare_data import DataPreparer

        filepath = Path(filepath)

        # Load the file
        delimiter = detect_delimiter(str(filepath))
        df = pd.read_csv(filepath, delimiter=delimiter)

        # Apply column deletions
        if columns_to_delete:
            df = df.drop(columns=columns_to_delete, errors='ignore')

        # Apply column renames
        if column_renames:
            df = df.rename(columns=column_renames)

        # Save modified file back (overwrite)
        df.to_csv(filepath, index=False)

        # Now run the ETL pipeline
        preparer = DataPreparer()
        result = preparer.process_file(filepath)

        if result:
            # Delete source file from data_loading after successful processing
            try:
                filepath.unlink()
            except Exception:
                pass  # File may already be gone

            # Sync new metadata to Supabase
            if HAS_SUPABASE:
                try:
                    output_filename = filepath.stem + ".csv"
                    metadata = load_dataset_metadata(output_filename)
                    if metadata:
                        supabase_client = get_supabase_client()
                        if supabase_client:
                            supabase_client.sync_metadata(output_filename, metadata)
                except Exception as sync_error:
                    print(f"Supabase sync failed (non-fatal): {sync_error}")

            return {"success": True, "message": f"Processed {filepath.name}"}
        else:
            return {"success": False, "message": "ETL processing failed"}

    except Exception as e:
        return {"success": False, "message": str(e)}


def delete_pending_file(filepath):
    """Delete a file from the data_loading folder without processing."""
    try:
        path = Path(filepath)
        if path.exists():
            path.unlink()
            return {"success": True, "message": f"Deleted {path.name}"}
        return {"success": False, "message": "File not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def load_dataset_metadata(filename):
    """Load metadata for a specific dataset."""
    base_name = Path(filename).stem
    metadata_file = METADATA_DIR / f"{base_name}_metadata.json"
    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_dataset_metadata(filename, metadata):
    """
    Save metadata for a specific dataset.
    Also updates the ultimate_metadata.json file and syncs to Supabase.
    """
    try:
        base_name = Path(filename).stem
        metadata_file = METADATA_DIR / f"{base_name}_metadata.json"

        # Save individual metadata file
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        # Update ultimate metadata
        ultimate = load_ultimate_metadata()
        if filename in ultimate.get("datasets", {}):
            # Update specific fields in ultimate metadata
            ultimate["datasets"][filename]["description"] = metadata.get("description", "")
            ultimate["datasets"][filename]["llm_summary"] = metadata.get("llm_summary", "")
            ultimate["last_updated"] = datetime.now().isoformat()

            with open(ULTIMATE_METADATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(ultimate, f, indent=2)

        # Sync to Supabase if configured
        if HAS_SUPABASE:
            try:
                supabase_client = get_supabase_client()
                if supabase_client:
                    supabase_client.sync_metadata(filename, metadata)
            except Exception as sync_error:
                # Don't fail the whole operation if Supabase sync fails
                print(f"Supabase sync failed (non-fatal): {sync_error}")

        return {"success": True, "message": f"Saved metadata for {filename}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# --- Main Dashboard ---

st.title("County Map Developer Dashboard")
st.markdown("Manage datasets, run ETL pipeline, and configure backups")

# Sidebar navigation
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Datasets", "Import", "Compare Datasets", "Metadata Editor", "Query Analytics", "Data Quality", "Backups", "LLM Context", "Settings"]
)

# --- Dashboard Page ---
if page == "Dashboard":
    st.header("Overview")

    # Load data
    ultimate_meta = load_ultimate_metadata()
    pending_files = get_loading_folder_status()
    cleaned_datasets = get_cleaned_datasets()
    storage = get_storage_info()
    backup_status = get_backup_status()

    # Key metrics
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Active Datasets", len(cleaned_datasets))

    with col2:
        st.metric("Pending Import", len(pending_files))

    with col3:
        total_rows = sum(d.get("row_count", 0) for d in cleaned_datasets)
        st.metric("Total Rows", f"{total_rows:,}")

    with col4:
        st.metric("Storage Used", f"{storage['cleaned']['size_mb']:.1f} MB")

    with col5:
        if backup_status["configured"]:
            needs_backup = len(backup_status.get("cleaned_needs_backup", []))
            if needs_backup == 0:
                st.metric("Backup Status", "Up to date")
            else:
                st.metric("Backup Status", f"{needs_backup} pending")
        else:
            st.metric("Backup Status", "Not configured")

    st.divider()

    # Dataset summary
    st.subheader("Datasets")

    if cleaned_datasets:
        for dataset in cleaned_datasets:
            # Build backup status indicator
            if dataset.get('is_backed_up'):
                if dataset.get('backup_current'):
                    backup_status = "[Backed up]"
                else:
                    backup_status = "[Backup outdated]"
            else:
                backup_status = "[Not backed up]"

            with st.expander(f"{dataset['filename']} - {dataset.get('description', 'No description')}"):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.write(f"**Rows:** {dataset.get('row_count', 'N/A'):,}")
                    st.write(f"**Columns:** {dataset.get('column_count', 'N/A')}")
                with col2:
                    st.write(f"**Level:** {dataset.get('geographic_level', 'N/A')}")
                    st.write(f"**Size:** {dataset['size_mb']} MB")
                with col3:
                    st.write(f"**Added:** {dataset.get('date_added', 'N/A')}")
                    st.write(f"**Updated:** {dataset.get('last_modified', 'N/A')}")
                with col4:
                    st.write(f"**Backup:** {backup_status}")
                    if dataset.get('backup_date'):
                        st.write(f"**Backup Date:** {dataset['backup_date']}")
                    tags = dataset.get('topic_tags', [])
                    if tags:
                        st.write(f"**Topics:** {', '.join(tags)}")
    else:
        st.info("No datasets loaded yet. Go to Import to add CSV files.")

    # Pending imports
    if pending_files:
        st.divider()
        st.subheader("Pending Imports")
        st.warning(f"{len(pending_files)} file(s) waiting in data_loading folder")
        for f in pending_files:
            st.write(f"- {f['filename']} ({f.get('size_mb', '?')} MB)")


# --- Datasets Page ---
elif page == "Datasets":
    st.header("Dataset Management")

    cleaned_datasets = get_cleaned_datasets()

    if not cleaned_datasets:
        st.info("No datasets available. Import some CSV files first.")
    else:
        st.subheader(f"Active Datasets ({len(cleaned_datasets)})")

        for dataset in cleaned_datasets:
            with st.expander(dataset['filename'], expanded=False):
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.write(f"**Description:** {dataset.get('description', 'N/A')}")
                    st.write(f"**Geographic Level:** {dataset.get('geographic_level', 'N/A')}")
                    st.write(f"**Rows:** {dataset.get('row_count', 'N/A'):,}")
                    st.write(f"**Columns:** {dataset.get('column_count', 'N/A')}")

                    tags = dataset.get('topic_tags', [])
                    if tags:
                        st.write(f"**Topics:** {', '.join(tags)}")

                with col2:
                    st.write(f"**Size:** {dataset['size_mb']} MB")
                    st.write(f"**Has Metadata:** {'Yes' if dataset['has_metadata'] else 'No'}")

                st.divider()

                # Action buttons - row 1
                action_col1, action_col2, action_col3 = st.columns(3)

                with action_col1:
                    if st.button("View Sample", key=f"sample_{dataset['filename']}"):
                        st.session_state[f"show_sample_{dataset['filename']}"] = True

                with action_col2:
                    if st.button("View Metadata", key=f"meta_{dataset['filename']}"):
                        st.session_state[f"show_meta_{dataset['filename']}"] = True

                with action_col3:
                    if st.button("Regenerate Metadata", key=f"regen_{dataset['filename']}"):
                        with st.spinner("Regenerating metadata..."):
                            result = regenerate_metadata_only(dataset['filename'])
                            if result["regenerated"]:
                                st.success(f"Regenerated metadata for {dataset['filename']}")
                            if result["errors"]:
                                for err in result["errors"]:
                                    st.error(err)
                            st.rerun()

                # Action buttons - row 2
                action_col4, action_col5, action_col6 = st.columns(3)

                with action_col4:
                    if st.button("Backup", key=f"backup_{dataset['filename']}"):
                        backup_csv = BACKUP_CLEANED_DIR / dataset['filename']
                        shutil.copy2(dataset['path'], backup_csv)
                        base_name = Path(dataset['filename']).stem
                        meta_src = METADATA_DIR / f"{base_name}_metadata.json"
                        if meta_src.exists():
                            shutil.copy2(meta_src, BACKUP_METADATA_DIR / f"{base_name}_metadata.json")
                        st.success(f"Backed up {dataset['filename']}")

                with action_col5:
                    if st.button("Re-process (Full ETL)", key=f"reprocess_{dataset['filename']}"):
                        st.session_state[f"confirm_reprocess_{dataset['filename']}"] = True

                with action_col6:
                    if st.button("Delete", key=f"delete_{dataset['filename']}"):
                        st.session_state[f"confirm_delete_{dataset['filename']}"] = True

                # Show sample data
                if st.session_state.get(f"show_sample_{dataset['filename']}"):
                    st.subheader("Sample Data (first 10 rows)")
                    try:
                        df = pd.read_csv(dataset['path'], nrows=10)
                        st.dataframe(df)
                    except Exception as e:
                        st.error(f"Error loading data: {e}")
                    if st.button("Close", key=f"close_sample_{dataset['filename']}"):
                        st.session_state[f"show_sample_{dataset['filename']}"] = False
                        st.rerun()

                # Show metadata
                if st.session_state.get(f"show_meta_{dataset['filename']}"):
                    st.subheader("Metadata")
                    base_name = Path(dataset['filename']).stem
                    metadata_file = METADATA_DIR / f"{base_name}_metadata.json"
                    if metadata_file.exists():
                        with open(metadata_file, 'r') as f:
                            st.json(json.load(f))
                    if st.button("Close", key=f"close_meta_{dataset['filename']}"):
                        st.session_state[f"show_meta_{dataset['filename']}"] = False
                        st.rerun()

                # Confirm re-process
                if st.session_state.get(f"confirm_reprocess_{dataset['filename']}"):
                    st.warning("This will move the file back to loading folder and delete current metadata.")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Confirm Re-process", key=f"confirm_yes_reprocess_{dataset['filename']}"):
                            result = reprocess_dataset(dataset['filename'])
                            if result["success"]:
                                st.success(result["message"])
                            else:
                                st.error(result["message"])
                            st.session_state[f"confirm_reprocess_{dataset['filename']}"] = False
                            st.rerun()
                    with col2:
                        if st.button("Cancel", key=f"confirm_no_reprocess_{dataset['filename']}"):
                            st.session_state[f"confirm_reprocess_{dataset['filename']}"] = False
                            st.rerun()

                # Confirm delete
                if st.session_state.get(f"confirm_delete_{dataset['filename']}"):
                    st.error("This will permanently delete the dataset and metadata!")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Confirm Delete", key=f"confirm_yes_delete_{dataset['filename']}"):
                            result = delete_dataset(dataset['filename'])
                            if result["deleted"]:
                                st.success(f"Deleted: {', '.join(result['deleted'])}")
                            if result["errors"]:
                                st.error(f"Errors: {', '.join(result['errors'])}")
                            st.session_state[f"confirm_delete_{dataset['filename']}"] = False
                            st.rerun()
                    with col2:
                        if st.button("Cancel", key=f"confirm_no_delete_{dataset['filename']}"):
                            st.session_state[f"confirm_delete_{dataset['filename']}"] = False
                            st.rerun()

                # Export button
                st.download_button(
                    label="Export CSV",
                    data=open(dataset['path'], 'rb').read(),
                    file_name=dataset['filename'],
                    mime="text/csv",
                    key=f"export_{dataset['filename']}"
                )


# --- Import Page ---
elif page == "Import":
    st.header("Import Datasets")

    pending_files = get_loading_folder_status()

    st.markdown(f"""
    **How to import:**
    1. Drop CSV files into: `{DATA_LOADING_DIR}`
    2. Click "Scan" to analyze the file and get suggestions
    3. Review/modify column deletions and renames
    4. Click "Process" to run ETL pipeline
    """)

    st.divider()

    # Pending files
    st.subheader("Pending Files")

    if pending_files:
        for f in pending_files:
            with st.expander(f"{f['filename']} ({f.get('size_mb', '?')} MB)", expanded=False):
                filepath = f['path']

                # Action buttons: Scan and Delete
                col1, col2, col3 = st.columns([1, 1, 2])
                with col1:
                    if st.button("Scan File", key=f"scan_{f['filename']}", type="primary"):
                        with st.spinner("Scanning CSV..."):
                            scan_result = scan_csv_source(filepath)
                            preview_data = preview_csv(filepath)
                            st.session_state[f"scan_data_{f['filename']}"] = scan_result
                            st.session_state[f"preview_data_{f['filename']}"] = preview_data
                            # Pre-populate suggestions
                            if scan_result.get("success"):
                                st.session_state[f"cols_to_delete_{f['filename']}"] = scan_result.get("columns_to_delete", [])
                                st.session_state[f"cols_to_rename_{f['filename']}"] = scan_result.get("columns_to_rename", {})

                with col2:
                    if st.button("Delete File", key=f"delete_pending_{f['filename']}"):
                        st.session_state[f"confirm_delete_pending_{f['filename']}"] = True

                # Confirm delete pending file
                if st.session_state.get(f"confirm_delete_pending_{f['filename']}"):
                    st.warning(f"Delete {f['filename']} without processing?")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button("Yes, Delete", key=f"confirm_yes_pending_{f['filename']}"):
                            result = delete_pending_file(filepath)
                            if result["success"]:
                                st.success(result["message"])
                                # Clear session state for this file
                                for key in list(st.session_state.keys()):
                                    if f['filename'] in key:
                                        del st.session_state[key]
                                st.rerun()
                            else:
                                st.error(result["message"])
                    with confirm_col2:
                        if st.button("Cancel", key=f"confirm_no_pending_{f['filename']}"):
                            st.session_state[f"confirm_delete_pending_{f['filename']}"] = False
                            st.rerun()

                scan_data = st.session_state.get(f"scan_data_{f['filename']}")
                preview_data = st.session_state.get(f"preview_data_{f['filename']}")

                if scan_data and scan_data.get("success"):
                    # Scan results summary
                    st.subheader("Scan Results")

                    # Metrics row
                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        st.metric("Rows", f"{scan_data['total_rows']:,}")
                    with m2:
                        st.metric("Columns", scan_data['total_columns'])
                    with m3:
                        st.metric("Geographic Level", scan_data['geographic_level'].title())
                    with m4:
                        topics = scan_data.get('detected_topics', [])
                        st.metric("Topics", ", ".join(topics) if topics else "General")

                    # Join suggestion alert (prominent display)
                    join_suggestion = scan_data.get("join_suggestion")
                    if join_suggestion and join_suggestion.get("action") == "join_existing":
                        st.info(
                            f"**Data Match Found:** Your data covers **{scan_data['geographic_level']}**-level geography.\n\n"
                            f"An existing data file **{join_suggestion['target_file']}** already contains "
                            f"{scan_data['geographic_level']}-level data with columns: "
                            f"`{', '.join(join_suggestion.get('existing_columns', []))}`.\n\n"
                            f"Consider merging new columns into this file instead of creating a separate dataset."
                        )
                    elif join_suggestion and join_suggestion.get("geometry_file"):
                        st.success(
                            f"**New Data File:** Will be linked to geometry file **{join_suggestion['geometry_file']}**"
                        )

                    # Warnings
                    if scan_data.get("warnings"):
                        for warning in scan_data["warnings"]:
                            st.warning(warning)

                    # Predicted Metadata Preview
                    with st.expander("Preview Predicted Metadata", expanded=False):
                        predicted_meta = {
                            "filename": f['filename'],
                            "row_count": scan_data['total_rows'],
                            "column_count": scan_data['total_columns'],
                            "geographic_level": scan_data['geographic_level'],
                            "topic_tags": scan_data.get('detected_topics', []),
                            "columns_analyzed": {}
                        }
                        # Add column analysis summary
                        col_analysis = scan_data.get("column_analysis", {})
                        for col, info in col_analysis.items():
                            predicted_meta["columns_analyzed"][col] = {
                                "type": info.get("inferred_type", "unknown"),
                                "role": info.get("role", "data"),
                                "null_pct": f"{info.get('null_percentage', 0):.1f}%"
                            }
                        st.json(predicted_meta)

                    st.divider()

                    # Column Configuration with suggestions
                    st.subheader("Column Configuration")

                    columns = preview_data['columns'] if preview_data else []

                    # Initialize session state for this file's column config if not already set
                    if f"cols_to_delete_{f['filename']}" not in st.session_state:
                        st.session_state[f"cols_to_delete_{f['filename']}"] = scan_data.get("columns_to_delete", [])
                    if f"cols_to_rename_{f['filename']}" not in st.session_state:
                        st.session_state[f"cols_to_rename_{f['filename']}"] = scan_data.get("columns_to_rename", {})

                    # Show suggestions summary
                    suggested_deletes = scan_data.get("columns_to_delete", [])
                    suggested_renames = scan_data.get("columns_to_rename", {})

                    if suggested_deletes or suggested_renames:
                        st.info(f"Suggestions: Delete {len(suggested_deletes)} columns, Rename {len(suggested_renames)} columns")

                    # Columns to delete (multiselect) - pre-populated with suggestions
                    cols_to_delete = st.multiselect(
                        "Columns to DELETE:",
                        options=columns,
                        default=st.session_state[f"cols_to_delete_{f['filename']}"],
                        key=f"delete_cols_{f['filename']}",
                        help="Suggested deletions are pre-selected based on scan"
                    )
                    st.session_state[f"cols_to_delete_{f['filename']}"] = cols_to_delete

                    # Show why columns are suggested for deletion
                    if suggested_deletes:
                        with st.expander("Why these deletions?"):
                            for col in suggested_deletes:
                                analysis = scan_data.get("column_analysis", {}).get(col, {})
                                reason = analysis.get("reason", "Unknown reason")
                                st.write(f"- **{col}**: {reason}")

                    st.divider()

                    # Columns to rename - show as table with suggestions
                    st.write("**Column Renames:** (suggested renames pre-filled)")
                    remaining_cols = [c for c in columns if c not in cols_to_delete]

                    rename_dict = {}
                    suggested_rename_keys = set(suggested_renames.keys())

                    # Show suggested renames first
                    if suggested_renames:
                        st.write("*Suggested renames (from standard schema):*")
                        for col in remaining_cols:
                            if col in suggested_rename_keys:
                                suggested_name = suggested_renames.get(col, "")
                                new_name = st.text_input(
                                    f"{col}:",
                                    value=st.session_state[f"cols_to_rename_{f['filename']}"].get(col, suggested_name),
                                    key=f"rename_{f['filename']}_{col}"
                                )
                                if new_name and new_name != col:
                                    rename_dict[col] = new_name

                    # Show other columns (collapsible)
                    other_cols = [c for c in remaining_cols if c not in suggested_rename_keys]
                    if other_cols:
                        with st.expander(f"Other columns ({len(other_cols)})"):
                            for col in other_cols[:30]:  # Limit for UI performance
                                new_name = st.text_input(
                                    f"{col}:",
                                    value=st.session_state[f"cols_to_rename_{f['filename']}"].get(col, ""),
                                    key=f"rename_{f['filename']}_{col}"
                                )
                                if new_name and new_name != col:
                                    rename_dict[col] = new_name

                    st.session_state[f"cols_to_rename_{f['filename']}"] = rename_dict

                    # Show preview of changes
                    st.divider()
                    st.subheader("Changes Summary")

                    change_col1, change_col2 = st.columns(2)
                    with change_col1:
                        if cols_to_delete:
                            st.write(f"**Will delete {len(cols_to_delete)} columns:**")
                            for col in cols_to_delete:
                                st.write(f"  - {col}")
                        else:
                            st.write("*No columns to delete*")

                    with change_col2:
                        if rename_dict:
                            st.write(f"**Will rename {len(rename_dict)} columns:**")
                            for old, new in rename_dict.items():
                                st.write(f"  - {old} -> {new}")
                        else:
                            st.write("*No columns to rename*")

                    # Sample data table
                    st.subheader("Sample Data")
                    sample_df = pd.DataFrame(preview_data['sample_data'])
                    # Apply preview of deletions
                    if cols_to_delete:
                        sample_df = sample_df.drop(columns=cols_to_delete, errors='ignore')
                    if rename_dict:
                        sample_df = sample_df.rename(columns=rename_dict)
                    st.dataframe(sample_df)

                    st.divider()

                    # Process button
                    if st.button("Process This File", key=f"process_{f['filename']}", type="primary"):
                        with st.spinner("Running ETL pipeline..."):
                            result = run_etl_with_options(
                                filepath,
                                columns_to_delete=cols_to_delete if cols_to_delete else None,
                                column_renames=rename_dict if rename_dict else None
                            )
                            if result["success"]:
                                st.success(result["message"])
                                # Clear session state for this file
                                for key in list(st.session_state.keys()):
                                    if f['filename'] in key:
                                        del st.session_state[key]
                                st.rerun()
                            else:
                                st.error(result["message"])

                elif scan_data and not scan_data.get("success"):
                    st.error(f"Error scanning file: {scan_data.get('error')}")

                elif preview_data and not preview_data.get("success"):
                    st.error(f"Error loading preview: {preview_data.get('error')}")

    else:
        st.info(f"No CSV files pending. Drop files into:\n`{DATA_LOADING_DIR}`")

    st.divider()

    # Process all button (no modifications)
    if pending_files:
        st.subheader("Batch Processing")
        st.write("Process all files without modifications:")
        if st.button("Process All Files", type="secondary"):
            with st.spinner("Running ETL pipeline on all files..."):
                try:
                    from data_pipeline.prepare_data import DataPreparer
                    preparer = DataPreparer()
                    successful, failed = preparer.run()
                    st.success(f"Processed {successful} files, {failed} failed")
                    st.rerun()
                except Exception as e:
                    st.error(f"ETL error: {e}")


# --- Compare Datasets Page ---
elif page == "Compare Datasets":
    st.header("Dataset Comparison Tool")
    st.markdown("""
    Compare new datasets against existing datasets using metadata analysis to identify:
    - **Overlapping data columns** - Numeric/data fields that already exist
    - **Unique data columns** - New data that would be added
    - **Geographic compatibility** - Whether datasets can be joined
    - **Topic overlap** - Similar subject areas
    """)

    pending_files = get_loading_folder_status()
    cleaned_datasets = get_cleaned_datasets()

    if not pending_files:
        st.info(f"No files in data_loading folder to compare. Drop CSV files into:\n`{DATA_LOADING_DIR}`")
    elif not cleaned_datasets:
        st.info("No existing datasets to compare against. Import some data first.")
    else:
        st.divider()

        # Select file to compare
        st.subheader("Step 1: Select New File")
        pending_options = [f['filename'] for f in pending_files]
        selected_new = st.selectbox("New file (from data_loading):", pending_options, key="compare_new_file")

        # Check if we have generated metadata for this file
        new_file_metadata_key = f"new_file_metadata_{selected_new}"

        # Step 2: Generate metadata for new file
        st.subheader("Step 2: Generate Metadata for New File")

        if new_file_metadata_key in st.session_state:
            st.success("Metadata generated for new file")
            new_meta = st.session_state[new_file_metadata_key]

            # Show new file summary
            with st.expander("New File Metadata Summary", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**Rows:** {new_meta.get('row_count', 'N/A'):,}")
                    st.write(f"**Columns:** {len(new_meta.get('columns', {}))}")
                with col2:
                    st.write(f"**Geographic Level:** {new_meta.get('geographic_level', 'unknown')}")
                    st.write(f"**Topics:** {', '.join(new_meta.get('topic_tags', []))}")
                with col3:
                    year_info = new_meta.get('data_year', {})
                    if isinstance(year_info, dict) and year_info.get('type') == 'time_series':
                        st.write(f"**Years:** {year_info.get('start')} - {year_info.get('end')}")
                    else:
                        st.write(f"**Year:** {year_info}")

                # Show data columns
                data_cols = [col for col, info in new_meta.get('columns', {}).items()
                            if isinstance(info, dict) and info.get('role') == 'data']
                if data_cols:
                    st.write(f"**Data Columns ({len(data_cols)}):** {', '.join(data_cols[:10])}")
                    if len(data_cols) > 10:
                        st.write(f"*...and {len(data_cols) - 10} more*")
        else:
            st.info("Click 'Generate Metadata' to analyze the new file before comparison")

        if st.button("Generate Metadata", type="secondary"):
            new_file_path = DATA_LOADING_DIR / selected_new

            with st.spinner("Generating metadata for new file..."):
                try:
                    from data_pipeline.prepare_data import DataPreparer
                    preparer = DataPreparer()

                    # Load file and generate metadata
                    delimiter = detect_delimiter(str(new_file_path))
                    df = pd.read_csv(new_file_path, delimiter=delimiter)

                    # Generate metadata using the ETL system
                    new_meta = preparer.generate_metadata(df, selected_new)
                    st.session_state[new_file_metadata_key] = new_meta
                    st.success(f"Generated metadata: {len(new_meta.get('columns', {}))} columns analyzed")
                    st.rerun()

                except Exception as e:
                    st.error(f"Error generating metadata: {e}")

        st.divider()

        # Step 3: Compare
        st.subheader("Step 3: Compare Against Existing Datasets")
        existing_options = ["-- Compare against ALL --"] + [d['filename'] for d in cleaned_datasets]
        selected_existing = st.selectbox("Compare against:", existing_options, key="compare_existing_file")

        compare_disabled = new_file_metadata_key not in st.session_state
        if st.button("Run Comparison", type="primary", disabled=compare_disabled):
            new_meta = st.session_state[new_file_metadata_key]

            with st.spinner("Comparing datasets..."):
                try:
                    # Extract data columns from new file (columns with role='data')
                    new_data_cols = {}
                    new_id_cols = {}
                    for col, info in new_meta.get('columns', {}).items():
                        if not isinstance(info, dict):
                            continue
                        role = info.get('role', '')
                        if role == 'data':
                            new_data_cols[col.lower()] = {'original': col, 'type': info.get('type', ''), 'info': info}
                        elif role in ['identifier', 'geographic']:
                            new_id_cols[col.lower()] = {'original': col, 'type': info.get('type', ''), 'info': info}

                    new_topics = set(new_meta.get('topic_tags', []))
                    new_geo_level = new_meta.get('geographic_level', 'unknown')

                    st.session_state['comparison_results'] = {
                        'new_file': selected_new,
                        'new_meta': new_meta,
                        'new_data_cols': new_data_cols,
                        'new_id_cols': new_id_cols,
                        'new_topics': new_topics,
                        'new_geo_level': new_geo_level,
                        'comparisons': []
                    }

                    # Compare against selected or all datasets
                    datasets_to_compare = []
                    if selected_existing == "-- Compare against ALL --":
                        datasets_to_compare = cleaned_datasets
                    else:
                        datasets_to_compare = [d for d in cleaned_datasets if d['filename'] == selected_existing]

                    for dataset in datasets_to_compare:
                        # Load existing metadata
                        existing_meta = load_dataset_metadata(dataset['filename'])
                        if not existing_meta:
                            continue

                        # Extract data columns from existing file
                        existing_data_cols = {}
                        existing_id_cols = {}
                        for col, info in existing_meta.get('columns', {}).items():
                            if not isinstance(info, dict):
                                continue
                            role = info.get('role', '')
                            if role == 'data':
                                existing_data_cols[col.lower()] = {'original': col, 'type': info.get('type', ''), 'info': info}
                            elif role in ['identifier', 'geographic']:
                                existing_id_cols[col.lower()] = {'original': col, 'type': info.get('type', ''), 'info': info}

                        existing_topics = set(existing_meta.get('topic_tags', []))
                        existing_geo_level = existing_meta.get('geographic_level', 'unknown')

                        # Calculate DATA column overlap (most important)
                        new_data_set = set(new_data_cols.keys())
                        existing_data_set = set(existing_data_cols.keys())

                        data_overlap = new_data_set & existing_data_set
                        data_only_in_new = new_data_set - existing_data_set
                        data_only_in_existing = existing_data_set - new_data_set

                        # Calculate similarity based on data columns
                        if len(new_data_set | existing_data_set) > 0:
                            data_similarity = len(data_overlap) / len(new_data_set | existing_data_set) * 100
                        else:
                            data_similarity = 0

                        # Calculate ID column overlap (for join potential)
                        new_id_set = set(new_id_cols.keys())
                        existing_id_set = set(existing_id_cols.keys())
                        id_overlap = new_id_set & existing_id_set

                        # Topic overlap
                        topic_overlap = new_topics & existing_topics

                        # Geographic compatibility
                        geo_compatible = new_geo_level == existing_geo_level or new_geo_level == 'unknown' or existing_geo_level == 'unknown'

                        comparison = {
                            'existing_file': dataset['filename'],
                            'existing_meta': existing_meta,
                            'existing_data_cols': existing_data_cols,
                            'existing_id_cols': existing_id_cols,
                            'existing_topics': existing_topics,
                            'existing_geo_level': existing_geo_level,
                            'existing_row_count': existing_meta.get('row_count', 0),
                            # Overlap analysis
                            'data_overlap': data_overlap,
                            'data_only_in_new': data_only_in_new,
                            'data_only_in_existing': data_only_in_existing,
                            'data_similarity': data_similarity,
                            'id_overlap': id_overlap,
                            'topic_overlap': topic_overlap,
                            'geo_compatible': geo_compatible
                        }

                        # Determine recommendation based on multiple factors
                        if data_similarity > 80 and geo_compatible:
                            comparison['recommendation'] = 'REPLACE'
                            comparison['recommendation_detail'] = f'High data overlap ({data_similarity:.0f}%). New file likely supersedes existing dataset.'
                        elif data_similarity > 50 and geo_compatible:
                            comparison['recommendation'] = 'MERGE'
                            comparison['recommendation_detail'] = f'Significant overlap ({data_similarity:.0f}%). Consider merging or picking one.'
                        elif len(id_overlap) > 0 and geo_compatible and data_similarity < 30:
                            comparison['recommendation'] = 'JOIN'
                            comparison['recommendation_detail'] = f'Joinable datasets (shared: {", ".join(id_overlap)}). New file adds {len(data_only_in_new)} unique data columns.'
                        elif data_similarity > 10:
                            comparison['recommendation'] = 'SUPPLEMENT'
                            comparison['recommendation_detail'] = f'Some overlap ({data_similarity:.0f}%). New file mostly adds unique data.'
                        else:
                            comparison['recommendation'] = 'INDEPENDENT'
                            comparison['recommendation_detail'] = f'Minimal overlap ({data_similarity:.0f}%). Datasets serve different purposes.'

                        st.session_state['comparison_results']['comparisons'].append(comparison)

                    st.success("Comparison complete!")

                except Exception as e:
                    st.error(f"Error during comparison: {e}")

        # Display results
        if 'comparison_results' in st.session_state:
            results = st.session_state['comparison_results']

            st.divider()
            st.subheader(f"Results for: {results['new_file']}")

            # New file summary
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Data Columns", len(results['new_data_cols']))
            with col2:
                st.metric("ID Columns", len(results['new_id_cols']))
            with col3:
                st.metric("Geographic Level", results['new_geo_level'].title())
            with col4:
                st.metric("Topics", len(results['new_topics']))

            for comp in results['comparisons']:
                rec = comp['recommendation']

                with st.expander(f"[{rec}] vs {comp['existing_file']} - {comp['data_similarity']:.1f}% data overlap", expanded=True):
                    # Metrics row
                    m1, m2, m3, m4, m5 = st.columns(5)
                    with m1:
                        st.metric("Data Overlap", len(comp['data_overlap']))
                    with m2:
                        st.metric("New Data Cols", len(comp['data_only_in_new']))
                    with m3:
                        st.metric("Existing Only", len(comp['data_only_in_existing']))
                    with m4:
                        st.metric("Shared IDs", len(comp['id_overlap']))
                    with m5:
                        geo_status = "Yes" if comp['geo_compatible'] else "No"
                        st.metric("Geo Compatible", geo_status)

                    # Recommendation
                    st.info(f"**Recommendation:** {comp['recommendation_detail']}")

                    # Topic comparison
                    if comp['topic_overlap']:
                        st.write(f"**Shared Topics:** {', '.join(comp['topic_overlap'])}")

                    # Show column details in tabs
                    tab1, tab2, tab3 = st.tabs(["Overlapping Data", "Only in New", "Only in Existing"])

                    with tab1:
                        if comp['data_overlap']:
                            overlap_data = []
                            for col in sorted(comp['data_overlap']):
                                new_info = results['new_data_cols'].get(col, {})
                                exist_info = comp['existing_data_cols'].get(col, {})
                                overlap_data.append({
                                    'Column': new_info.get('original', col),
                                    'Type (New)': new_info.get('type', ''),
                                    'Type (Existing)': exist_info.get('type', '')
                                })
                            st.dataframe(pd.DataFrame(overlap_data), width="stretch")
                        else:
                            st.write("*No overlapping data columns*")

                    with tab2:
                        if comp['data_only_in_new']:
                            new_only_data = []
                            for col in sorted(comp['data_only_in_new']):
                                info = results['new_data_cols'].get(col, {})
                                col_info = info.get('info', {})
                                new_only_data.append({
                                    'Column': info.get('original', col),
                                    'Type': info.get('type', ''),
                                    'Sample': str(col_info.get('sample_values', []))[:50] if col_info.get('sample_values') else ''
                                })
                            st.dataframe(pd.DataFrame(new_only_data), width="stretch")
                        else:
                            st.write("*No unique data columns in new file*")

                    with tab3:
                        if comp['data_only_in_existing']:
                            exist_only_data = []
                            for col in sorted(comp['data_only_in_existing']):
                                info = comp['existing_data_cols'].get(col, {})
                                col_info = info.get('info', {})
                                exist_only_data.append({
                                    'Column': info.get('original', col),
                                    'Type': info.get('type', ''),
                                    'Sample': str(col_info.get('sample_values', []))[:50] if col_info.get('sample_values') else ''
                                })
                            st.dataframe(pd.DataFrame(exist_only_data), width="stretch")
                        else:
                            st.write("*No unique data columns in existing file*")

                    st.divider()

                    # Action buttons based on recommendation
                    action_col1, action_col2, action_col3 = st.columns(3)

                    with action_col1:
                        if rec == 'REPLACE' and st.button(f"Replace {comp['existing_file']}", key=f"replace_{comp['existing_file']}"):
                            st.session_state[f"confirm_replace_{comp['existing_file']}"] = True

                    # Confirm replace dialog
                    if st.session_state.get(f"confirm_replace_{comp['existing_file']}"):
                        st.warning(f"This will delete {comp['existing_file']} and its metadata. Then go to Import to process {results['new_file']}.")
                        confirm_c1, confirm_c2 = st.columns(2)
                        with confirm_c1:
                            if st.button("Confirm Replace", key=f"confirm_yes_replace_{comp['existing_file']}"):
                                delete_result = delete_dataset(comp['existing_file'])
                                if delete_result['deleted']:
                                    st.success(f"Deleted {comp['existing_file']}")
                                    st.session_state[f"confirm_replace_{comp['existing_file']}"] = False
                                    st.session_state.pop('comparison_results', None)
                                    st.info(f"Now go to Import page to process {results['new_file']}")
                                    st.rerun()
                                else:
                                    st.error(f"Error deleting: {delete_result['errors']}")
                        with confirm_c2:
                            if st.button("Cancel", key=f"confirm_no_replace_{comp['existing_file']}"):
                                st.session_state[f"confirm_replace_{comp['existing_file']}"] = False
                                st.rerun()

            # Clear results button
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Clear Results"):
                    st.session_state.pop('comparison_results', None)
                    st.rerun()
            with col2:
                if st.button("Clear Metadata Cache"):
                    # Clear the generated metadata for the new file
                    if new_file_metadata_key in st.session_state:
                        del st.session_state[new_file_metadata_key]
                    st.session_state.pop('comparison_results', None)
                    st.rerun()


# --- Metadata Editor Page ---
elif page == "Metadata Editor":
    st.header("Metadata Editor")
    st.markdown("""
    Edit source information, licensing, and descriptions for your datasets.
    Changes are saved to individual metadata files and synced to ultimate_metadata.json.
    """)

    cleaned_datasets = get_cleaned_datasets()

    # License options (common data licenses)
    LICENSE_OPTIONS = [
        "Unknown",
        "CC0 (Public Domain)",
        "CC-BY 4.0",
        "CC-BY-SA 4.0",
        "CC-BY-NC 4.0",
        "CC-BY-NC-SA 4.0",
        "Open Government License",
        "Open Data Commons (ODC-BY)",
        "Open Database License (ODbL)",
        "MIT License",
        "Apache 2.0",
        "GPL v3",
        "Custom/Other"
    ]

    if not cleaned_datasets:
        st.info("No datasets available. Import some CSV files first.")
    else:
        # Summary metrics
        total_datasets = len(cleaned_datasets)
        sources_filled = sum(1 for d in cleaned_datasets if d.get("has_metadata"))

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Datasets", total_datasets)
        with col2:
            st.metric("With Metadata", sources_filled)
        with col3:
            # Count datasets with source info filled
            sources_known = 0
            for d in cleaned_datasets:
                meta = load_dataset_metadata(d['filename'])
                if meta and meta.get("source_name") and meta.get("source_name") != "Unknown":
                    sources_known += 1
            st.metric("Sources Documented", f"{sources_known}/{total_datasets}")

        st.divider()

        # Dataset selector
        st.subheader("Select Dataset to Edit")

        dataset_options = [d['filename'] for d in cleaned_datasets]
        selected_dataset = st.selectbox(
            "Dataset:",
            options=dataset_options,
            key="metadata_editor_dataset"
        )

        if selected_dataset:
            metadata = load_dataset_metadata(selected_dataset)

            if metadata:
                st.divider()
                st.subheader(f"Editing: {selected_dataset}")

                # Show current read-only info
                with st.expander("Dataset Info (read-only)", expanded=False):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Rows:** {metadata.get('row_count', 'N/A'):,}")
                        st.write(f"**Geographic Level:** {metadata.get('geographic_level', 'N/A')}")
                    with col2:
                        year_info = metadata.get('data_year', {})
                        if isinstance(year_info, dict):
                            if year_info.get('type') == 'time_series':
                                st.write(f"**Years:** {year_info.get('start')} - {year_info.get('end')}")
                            else:
                                st.write(f"**Year:** {year_info}")
                        else:
                            st.write(f"**Year:** {year_info}")
                        st.write(f"**Topics:** {', '.join(metadata.get('topic_tags', []))}")

                st.divider()

                # Editable fields
                st.subheader("Source Information")

                # Use form for clean submission
                with st.form(key=f"metadata_form_{selected_dataset}"):

                    # Source Name
                    source_name = st.text_input(
                        "Source Name",
                        value=metadata.get("source_name", "Unknown"),
                        placeholder="e.g., Our World in Data, US Census Bureau, WHO",
                        help="The organization or entity that publishes this data"
                    )

                    # Source URL
                    source_url = st.text_input(
                        "Source URL",
                        value=metadata.get("source_url", ""),
                        placeholder="https://example.org/data",
                        help="Link to the original data source or download page"
                    )

                    st.divider()
                    st.subheader("Licensing")

                    # License selection
                    current_license = metadata.get("license", "Unknown")
                    if current_license not in LICENSE_OPTIONS:
                        license_index = LICENSE_OPTIONS.index("Custom/Other")
                    else:
                        license_index = LICENSE_OPTIONS.index(current_license)

                    license_type = st.selectbox(
                        "License Type",
                        options=LICENSE_OPTIONS,
                        index=license_index,
                        help="Select the license under which this data is published"
                    )

                    # Custom license field (shown if Custom/Other selected)
                    custom_license = ""
                    if license_type == "Custom/Other":
                        custom_license = st.text_input(
                            "Custom License Name",
                            value=current_license if current_license not in LICENSE_OPTIONS else "",
                            placeholder="e.g., Creative Commons Attribution 3.0 IGO"
                        )

                    # License URL
                    license_url = st.text_input(
                        "License URL",
                        value=metadata.get("license_url", ""),
                        placeholder="https://creativecommons.org/licenses/by/4.0/",
                        help="Link to the full license text"
                    )

                    # License verified checkbox
                    license_verified = st.checkbox(
                        "License Verified",
                        value=metadata.get("license_verified", False),
                        help="Check if you have verified the license information is correct"
                    )

                    st.divider()
                    st.subheader("Description & Notes")

                    # Description
                    description = st.text_area(
                        "Description",
                        value=metadata.get("description", ""),
                        placeholder="Brief description of what this dataset contains...",
                        height=100,
                        help="Human-readable description of the dataset"
                    )

                    # LLM Summary (what gets sent to the chat LLM)
                    llm_summary = st.text_area(
                        "LLM Summary",
                        value=metadata.get("llm_summary", ""),
                        placeholder="Concise summary for the LLM to understand available data...",
                        height=80,
                        help="This summary is sent to the conversation LLM to help it understand available data"
                    )

                    # Notes (internal notes not shown to users)
                    notes = st.text_area(
                        "Internal Notes",
                        value=metadata.get("notes", ""),
                        placeholder="Any internal notes about this dataset (data quality issues, update schedule, etc.)",
                        height=80,
                        help="Internal notes - not shown to end users"
                    )

                    st.divider()

                    # Submit button
                    submitted = st.form_submit_button("Save Changes", type="primary")

                    if submitted:
                        # Update metadata with new values
                        metadata["source_name"] = source_name
                        metadata["source_url"] = source_url

                        # Handle license
                        if license_type == "Custom/Other" and custom_license:
                            metadata["license"] = custom_license
                        else:
                            metadata["license"] = license_type

                        metadata["license_url"] = license_url
                        metadata["license_verified"] = license_verified
                        metadata["description"] = description
                        metadata["llm_summary"] = llm_summary
                        metadata["notes"] = notes

                        # Save
                        result = save_dataset_metadata(selected_dataset, metadata)

                        if result["success"]:
                            st.success(f"Saved metadata for {selected_dataset}")
                            st.rerun()
                        else:
                            st.error(f"Error saving: {result['message']}")

                # Quick actions outside form
                st.divider()
                st.subheader("Quick Actions")

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("View Raw JSON"):
                        st.json(metadata)

                with col2:
                    if st.button("Regenerate Auto-Fields"):
                        with st.spinner("Regenerating..."):
                            regen_result = regenerate_metadata_only(selected_dataset)
                            if regen_result["regenerated"]:
                                st.success("Regenerated auto-detected fields (preserved source/license info)")
                                st.rerun()
                            else:
                                st.error(f"Error: {regen_result['errors']}")

            else:
                st.warning(f"No metadata found for {selected_dataset}. Run ETL or regenerate metadata first.")

        st.divider()

        # Bulk status overview
        st.subheader("All Datasets - Source Status")

        status_data = []
        for d in cleaned_datasets:
            meta = load_dataset_metadata(d['filename'])
            if meta:
                source_status = "OK" if meta.get("source_name") and meta.get("source_name") != "Unknown" else "Missing"
                license_status = "OK" if meta.get("license") and meta.get("license") != "Unknown" else "Missing"
                verified = "Yes" if meta.get("license_verified") else "No"
            else:
                source_status = "No metadata"
                license_status = "No metadata"
                verified = "-"

            status_data.append({
                "Dataset": d['filename'],
                "Source": source_status,
                "License": license_status,
                "Verified": verified
            })

        status_df = pd.DataFrame(status_data)
        st.dataframe(status_df, width="stretch")


# --- Query Analytics Page ---
elif page == "Query Analytics":
    st.header("Query Analytics")
    st.markdown("View user queries and errors from Supabase cloud logging")

    if not HAS_SUPABASE:
        st.error("Supabase package not installed. Install with: `pip install supabase`")
    else:
        # Try to connect to Supabase
        supabase_client = get_supabase_client()

        if supabase_client is None:
            st.warning("""
            **Supabase not configured.**

            Add these environment variables to your `.env` file:
            ```
            SUPABASE_URL=https://your-project-id.supabase.co
            SUPABASE_ANON_KEY=your_anon_key_here
            ```

            See DEVELOPER.md for full setup instructions.
            """)
        else:
            # Connection status
            status = supabase_client.test_connection()

            if not status["connected"]:
                st.error(f"Failed to connect to Supabase: {status.get('error', 'Unknown error')}")
            else:
                # Show connection info
                st.success(f"Connected to Supabase")

                # Overview stats
                stats = supabase_client.get_query_stats()

                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("Total Queries", stats.get("total_queries", 0))

                with col2:
                    st.metric("Errors", stats.get("error_count", 0))

                with col3:
                    error_rate = stats.get("error_rate", 0)
                    st.metric("Error Rate", f"{error_rate:.1f}%")

                with col4:
                    # Get table counts
                    table_info = status.get("tables", {})
                    session_count = table_info.get("conversation_sessions", {}).get("count", 0)
                    st.metric("Sessions", session_count)

                st.divider()

                # Tabs for different views
                tab1, tab2, tab3 = st.tabs(["Recent Sessions", "Error Logs", "Top Interests"])

                with tab1:
                    st.subheader("Recent Conversation Sessions")

                    # Filter options
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("")  # Placeholder for future filters
                    with col2:
                        limit = st.selectbox("Show", [25, 50, 100, 200], index=0)

                    # Fetch sessions from conversation_sessions table
                    sessions = supabase_client.get_recent_sessions(limit=limit)

                    if not sessions:
                        st.info("No sessions logged yet. Sessions will appear here after users interact with the map.")
                    else:
                        # Format for display
                        session_data = []
                        for session in sessions:
                            # Get messages array and extract useful info
                            messages = session.get("messages", [])
                            query_count = len([m for m in messages if m.get("role") == "user"])
                            last_query = ""
                            for m in reversed(messages):
                                if m.get("role") == "user":
                                    last_query = m.get("content", "")[:60]
                                    if len(m.get("content", "")) > 60:
                                        last_query += "..."
                                    break

                            session_data.append({
                                "Updated": session.get("updated_at", "")[:19].replace("T", " "),
                                "Session ID": session.get("session_id", "")[:20] + "...",
                                "Messages": len(messages),
                                "Queries": query_count,
                                "Last Query": last_query,
                                "Results": session.get("total_results", 0)
                            })

                        df = pd.DataFrame(session_data)
                        st.dataframe(df, width="stretch", hide_index=True)

                        # Export option
                        if st.button("Export to CSV"):
                            csv = df.to_csv(index=False)
                            st.download_button(
                                "Download CSV",
                                csv,
                                file_name=f"sessions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )

                with tab2:
                    st.subheader("Error Logs")

                    error_logs = supabase_client.get_error_logs(limit=50)

                    if not error_logs:
                        st.info("No errors logged. This is good!")
                    else:
                        for i, error in enumerate(error_logs):
                            with st.expander(f"{error.get('error_type', 'Error')} - {error.get('created_at', '')[:19]}"):
                                st.write(f"**Query:** {error.get('query', 'N/A')}")
                                st.write(f"**Error:** {error.get('error_message', 'N/A')}")
                                if error.get("traceback"):
                                    st.code(error.get("traceback"), language="python")

                with tab3:
                    st.subheader("Popular Topics")

                    top_interests = stats.get("top_interests", [])

                    if not top_interests:
                        st.info("No topics tracked yet.")
                    else:
                        # Create bar chart data
                        interest_df = pd.DataFrame(top_interests, columns=["Interest", "Count"])
                        st.bar_chart(interest_df.set_index("Interest"))

                        st.dataframe(interest_df, width="stretch", hide_index=True)

                st.divider()

                # Raw table info
                with st.expander("Database Status"):
                    st.write("**Table Information:**")
                    for table, info in status.get("tables", {}).items():
                        if info.get("exists"):
                            st.write(f"- {table}: {info.get('count', 0)} rows")
                        else:
                            st.write(f"- {table}: NOT FOUND - {info.get('error', 'unknown')}")


# --- Data Quality Page ---
elif page == "Data Quality":
    st.header("Data Quality")
    st.markdown("Identify and fix data issues: missing geometries, name mismatches, and duplicates")

    # Load conversions.json for reference data
    CONVERSIONS_FILE = DATA_PIPELINE_DIR / "conversions.json"
    conversions_data = {}
    if CONVERSIONS_FILE.exists():
        with open(CONVERSIONS_FILE, 'r', encoding='utf-8') as f:
            conversions_data = json.load(f)

    # Tabs for different quality checks
    tab1, tab2, tab3, tab4 = st.tabs(["Missing Geometries", "Missing Regions", "Name Standardization", "Duplicate Detection"])

    # --- Tab 1: Missing Geometries ---
    with tab1:
        st.subheader("Countries Missing Map Boundaries")
        st.markdown("""
        These countries appear in datasets but don't have polygon geometry in Countries.csv.
        They display as points (dots) instead of filled regions.
        """)

        # Try to load from Supabase
        missing_from_supabase = []
        if HAS_SUPABASE:
            try:
                client = get_supabase_client()
                if client:
                    missing_from_supabase = client.get_missing_geometries(limit=100)
            except Exception as e:
                st.warning(f"Could not load from Supabase: {e}")

        # Also show from conversions.json
        limited_geo = conversions_data.get("limited_geometry_countries", {})

        col1, col2 = st.columns(2)

        with col1:
            st.write("**From Supabase (recent queries)**")
            if missing_from_supabase:
                missing_df = pd.DataFrame(missing_from_supabase)
                # Show relevant columns (new schema uses 'name' instead of 'country_name')
                display_cols = ["name", "dataset", "region", "occurrence_count", "created_at"]
                display_cols = [c for c in display_cols if c in missing_df.columns]
                if display_cols:
                    st.dataframe(missing_df[display_cols], width="stretch")
                else:
                    st.dataframe(missing_df, width="stretch")
            else:
                st.info("No missing geometries logged yet, or Supabase not configured.")

        with col2:
            st.write("**Known Limited Geometry (conversions.json)**")

            # Show categories
            unexpected = limited_geo.get("missing_geometry_unexpected", {}).get("countries", [])
            microstates = limited_geo.get("microstates", {}).get("countries", [])
            islands = limited_geo.get("small_island_nations", {}).get("countries", [])

            iso_codes = conversions_data.get("iso_country_codes", {})

            if unexpected:
                st.write("**Unexpected Missing (should fix):**")
                for code in unexpected:
                    name = iso_codes.get(code, code)
                    st.write(f"- {name} ({code})")

            if microstates:
                st.write("**Microstates (expected - too small):**")
                st.write(", ".join([iso_codes.get(c, c) for c in microstates]))

            if islands:
                st.write("**Small Island Nations (expected):**")
                st.write(", ".join([iso_codes.get(c, c) for c in islands[:10]]) + f"... ({len(islands)} total)")

        st.divider()

        # Tool to add new missing geometry to conversions.json
        st.subheader("Add to Known Limited Geometry")
        with st.form("add_limited_geo"):
            new_country = st.text_input("Country Name or ISO Code")
            category = st.selectbox("Category", ["missing_geometry_unexpected", "microstates", "small_island_nations"])
            submitted = st.form_submit_button("Add to conversions.json")

            if submitted and new_country:
                st.info(f"Would add '{new_country}' to '{category}' category. (Manual edit required for now)")
                st.code(f'Edit: {CONVERSIONS_FILE}')

    # --- Tab 2: Missing Regions ---
    with tab2:
        st.subheader("Unrecognized Region Names")
        st.markdown("""
        These region names were used in queries but not found in `conversions.json`.
        Add them to `region_aliases` or `regional_groupings` to enable region-based filtering.
        """)

        # Load missing regions from Supabase
        missing_regions = []
        if HAS_SUPABASE:
            try:
                client = get_supabase_client()
                if client:
                    missing_regions = client.get_missing_regions(limit=100)
            except Exception as e:
                st.warning(f"Could not load from Supabase: {e}")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**Missing Regions (from queries)**")
            if missing_regions:
                regions_df = pd.DataFrame(missing_regions)
                display_cols = ["name", "first_query", "dataset", "occurrence_count", "created_at"]
                display_cols = [c for c in display_cols if c in regions_df.columns]
                if display_cols:
                    st.dataframe(regions_df[display_cols], width="stretch")
                else:
                    st.dataframe(regions_df, width="stretch")
            else:
                st.info("No missing regions logged yet.")

        with col2:
            st.write("**Known Region Aliases (conversions.json)**")
            region_aliases = conversions_data.get("region_aliases", {})
            if region_aliases:
                alias_list = [{"Alias": k, "Maps To": v} for k, v in sorted(region_aliases.items())]
                st.dataframe(pd.DataFrame(alias_list), width="stretch", height=300)

            st.divider()
            st.write("**Regional Groupings:**")
            groupings = conversions_data.get("regional_groupings", {})
            grouping_names = list(groupings.keys())
            st.write(", ".join(grouping_names[:15]) + (f"... ({len(grouping_names)} total)" if len(grouping_names) > 15 else ""))

        st.divider()

        # Tool to add new region alias
        st.subheader("Add Region Alias")
        with st.form("add_region_alias"):
            new_alias = st.text_input("New Alias (e.g., 'Asian')")
            maps_to = st.selectbox("Maps To", ["-- Select --"] + list(groupings.keys()))
            submitted_alias = st.form_submit_button("Add Alias")

            if submitted_alias and new_alias and maps_to != "-- Select --":
                st.info(f"Would add alias: '{new_alias}' -> '{maps_to}'. (Manual edit required)")
                st.code(f'Edit region_aliases in: {CONVERSIONS_FILE}')

    # --- Tab 3: Name Standardization ---
    with tab3:
        st.subheader("Country Name Standardization")
        st.markdown("""
        Compare country names in datasets against the standard names in `conversions.json`.
        Helps identify naming inconsistencies that cause geometry lookup failures.
        """)

        # Get standard country names
        standard_names = set(conversions_data.get("iso_country_codes", {}).values())
        standard_names_lower = {n.lower(): n for n in standard_names}

        # Get existing country name aliases from mapmover.py
        st.write("**Current COUNTRY_NAME_ALIASES (in mapmover.py):**")
        known_aliases = {
            'cape verde': 'cabo verde',
            'central african republic': 'central african rep.',
            'democratic republic of congo': 'dem. rep. congo',
            'democratic republic of the congo': 'dem. rep. congo',
            'dr congo': 'dem. rep. congo',
            'drc': 'dem. rep. congo',
            'equatorial guinea': 'eq. guinea',
            'south sudan': 's. sudan',
            'ivory coast': "cote d'ivoire",
            'czechia': 'czech rep.',
            'czech republic': 'czech rep.',
            'south korea': 'korea',
            'republic of korea': 'korea',
            'bosnia and herzegovina': 'bosnia and herz.',
            'united states': 'united states of america',
            'usa': 'united states of america',
            'uk': 'united kingdom',
            'britain': 'united kingdom',
        }
        alias_df = pd.DataFrame([{"Dataset Name": k, "Maps To": v} for k, v in known_aliases.items()])
        st.dataframe(alias_df, width="stretch", height=200)

        st.divider()

        # Scan a dataset for unknown names
        st.subheader("Scan Dataset for Unknown Country Names")

        cleaned_datasets = get_cleaned_datasets()
        dataset_names = [d["filename"] for d in cleaned_datasets if "filename" in d]

        selected_dataset = st.selectbox("Select Dataset to Scan", ["-- Select --"] + dataset_names)

        if selected_dataset != "-- Select --":
            dataset_path = DATA_CLEANED_DIR / selected_dataset
            if dataset_path.exists():
                try:
                    # Load dataset
                    delimiter = detect_delimiter(dataset_path)
                    df = pd.read_csv(dataset_path, delimiter=delimiter, nrows=5000)

                    # Find country column
                    country_cols = [c for c in df.columns if any(x in c.lower() for x in ['country', 'location', 'name'])]

                    if country_cols:
                        col_to_check = st.selectbox("Column to check", country_cols)

                        if st.button("Scan for Non-Standard Names"):
                            unique_names = df[col_to_check].dropna().unique()

                            unknown_names = []
                            matched_names = []

                            for name in unique_names:
                                name_lower = str(name).lower().strip()
                                # Check if it's a standard name or known alias
                                if name_lower in standard_names_lower:
                                    matched_names.append(name)
                                elif name_lower in known_aliases:
                                    matched_names.append(f"{name} -> {known_aliases[name_lower]}")
                                else:
                                    unknown_names.append(name)

                            st.write(f"**Results:** {len(matched_names)} matched, {len(unknown_names)} unknown")

                            if unknown_names:
                                st.warning(f"Found {len(unknown_names)} names not in standard list:")
                                unknown_df = pd.DataFrame({"Unknown Name": unknown_names[:50]})
                                st.dataframe(unknown_df, width="stretch")

                                st.info("Add aliases to COUNTRY_NAME_ALIASES in mapmover.py or standardize in conversions.json")
                            else:
                                st.success("All names matched!")
                    else:
                        st.warning("No country/location column found in this dataset")

                except Exception as e:
                    st.error(f"Error scanning dataset: {e}")

    # --- Tab 4: Duplicate Detection ---
    with tab4:
        st.subheader("Duplicate Detection")
        st.markdown("""
        Find duplicate rows in datasets that might cause multiple features per country.
        Common issue: multiple rows per country/year when only one is expected.
        """)

        cleaned_datasets = get_cleaned_datasets()
        dataset_names = [d["filename"] for d in cleaned_datasets if "filename" in d]

        selected_dataset_dup = st.selectbox("Select Dataset", ["-- Select --"] + dataset_names, key="dup_dataset")

        if selected_dataset_dup != "-- Select --":
            dataset_path = DATA_CLEANED_DIR / selected_dataset_dup
            if dataset_path.exists():
                try:
                    delimiter = detect_delimiter(dataset_path)
                    df = pd.read_csv(dataset_path, delimiter=delimiter)

                    st.write(f"**Total rows:** {len(df)}")

                    # Find potential key columns
                    key_candidates = [c for c in df.columns if any(x in c.lower()
                                     for x in ['country', 'location', 'name', 'year', 'date', 'code'])]

                    if key_candidates:
                        selected_keys = st.multiselect("Select columns that should be unique together",
                                                       key_candidates,
                                                       default=key_candidates[:2] if len(key_candidates) >= 2 else key_candidates)

                        if selected_keys and st.button("Find Duplicates"):
                            # Find duplicates
                            duplicates = df[df.duplicated(subset=selected_keys, keep=False)]

                            if len(duplicates) > 0:
                                st.warning(f"Found {len(duplicates)} rows with duplicate keys")

                                # Show duplicate groups
                                dup_counts = df.groupby(selected_keys).size().reset_index(name='count')
                                dup_counts = dup_counts[dup_counts['count'] > 1].sort_values('count', ascending=False)

                                st.write("**Most duplicated combinations:**")
                                st.dataframe(dup_counts.head(20), width="stretch")

                                # Option to deduplicate
                                st.divider()
                                st.write("**Deduplication Options:**")
                                keep_option = st.radio("Keep which row?", ["first", "last"])

                                if st.button("Preview Deduplication"):
                                    deduped = df.drop_duplicates(subset=selected_keys, keep=keep_option)
                                    st.write(f"Would reduce from {len(df)} to {len(deduped)} rows")
                            else:
                                st.success("No duplicates found for selected columns!")
                    else:
                        st.info("No obvious key columns found. Select columns manually.")

                except Exception as e:
                    st.error(f"Error analyzing dataset: {e}")


# --- Backups Page ---
elif page == "Backups":
    st.header("Dataset Backups")

    backup_status = get_backup_status()

    if not backup_status["configured"]:
        st.error(backup_status["message"])
    else:
        st.write(f"**Backup Location:** `{backup_status['path']}`")

        # Backup status metrics
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "CSVs Backed Up",
                f"{backup_status['cleaned_backed_up']} / {backup_status['cleaned_total']}"
            )

        with col2:
            st.metric(
                "Metadata Backed Up",
                f"{backup_status['metadata_backed_up']} / {backup_status['metadata_total']}"
            )

        with col3:
            st.metric(
                "Ultimate Metadata",
                "Yes" if backup_status['ultimate_backed_up'] else "No"
            )

        if backup_status['last_backup']:
            st.write(f"**Last Backup:** {backup_status['last_backup']}")

        st.divider()

        # Files needing backup
        needs_backup_csv = backup_status.get("cleaned_needs_backup", [])
        needs_backup_meta = backup_status.get("metadata_needs_backup", [])

        if needs_backup_csv or needs_backup_meta:
            st.warning(f"{len(needs_backup_csv)} CSV files and {len(needs_backup_meta)} metadata files need backup")

            if needs_backup_csv:
                st.write("**CSVs needing backup:**")
                for f in needs_backup_csv:
                    st.write(f"  - {f}")

        # Backup actions
        st.subheader("Actions")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Create Full Backup", type="primary"):
                with st.spinner("Creating backup..."):
                    result = create_backup()
                    st.success(f"Backup complete: {result['csv_copied']} CSVs, {result['meta_copied']} metadata files")
                    if result['errors']:
                        st.warning(f"Errors: {', '.join(result['errors'])}")
                    st.rerun()

        with col2:
            if st.button("Refresh Status"):
                st.rerun()

        st.divider()

        # Restore section
        st.subheader("Restore from Backup")

        backed_up_files = list(BACKUP_CLEANED_DIR.glob("*.csv")) if BACKUP_CLEANED_DIR.exists() else []

        if backed_up_files:
            selected_restore = st.selectbox(
                "Select file to restore:",
                options=[f.name for f in backed_up_files]
            )

            if st.button("Restore Selected"):
                result = restore_from_backup(selected_restore)
                if result["restored"]:
                    st.success(f"Restored: {', '.join(result['restored'])}")
                if result["errors"]:
                    st.error(f"Errors: {', '.join(result['errors'])}")
                st.rerun()
        else:
            st.info("No backups available to restore.")


# --- LLM Context Page ---
elif page == "LLM Context":
    st.header("LLM Context Manager")
    st.markdown("""
    View and manage the dataset summaries that are sent to the conversation LLM.
    The LLM uses these summaries to answer questions about available data.
    """)

    cleaned_datasets = get_cleaned_datasets()

    # Priority terms used by both ETL and mapmover.py
    priority_data_terms = {'gdp', 'co2', 'emission', 'population', 'income', 'health',
                          'mortality', 'energy', 'temperature', 'methane', 'trade'}
    skip_patterns = ['year', 'rank', 'latitude', 'longitude', 'lat', 'lng', 'lon',
                    'code', 'id', 'fips', 'index']

    st.subheader("Current Dataset Summaries")
    st.markdown("These are the summaries sent to the conversation LLM:")

    all_summaries = []

    for dataset in cleaned_datasets:
        base_name = Path(dataset['filename']).stem
        metadata_file = METADATA_DIR / f"{base_name}_metadata.json"

        if not metadata_file.exists():
            continue

        with open(metadata_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        filename = meta.get("filename", dataset['filename'])
        level = meta.get("geographic_level", "")
        llm_summary = meta.get("llm_summary", "")

        # Get year info
        data_year = meta.get("data_year", {})
        year_str = ""
        if isinstance(data_year, dict) and data_year.get("type") == "time_series":
            year_str = f"Years: {data_year.get('start')}-{data_year.get('end')}"
        elif isinstance(data_year, str) and data_year not in ["Unknown", ""]:
            year_str = f"Year: {data_year}"

        # Build fallback summary if no llm_summary
        if llm_summary and len(llm_summary) > 20:
            current_summary = f"{filename}: {llm_summary}"
        else:
            # Build from metadata (same logic as mapmover.py)
            columns_info = meta.get("columns", {})
            priority_cols = []
            other_cols = []

            for col, info in columns_info.items():
                if not isinstance(info, dict):
                    continue
                role = info.get("role", "")
                col_type = info.get("type", "")
                col_lower = col.lower()

                if role != "data" or col_type != "float":
                    continue
                if any(skip in col_lower for skip in skip_patterns):
                    continue

                if any(term in col_lower for term in priority_data_terms):
                    if 'per_capita' in col_lower or 'per capita' in col_lower:
                        priority_cols.append(col)
                    else:
                        priority_cols.insert(0, col)
                else:
                    other_cols.append(col)

            key_cols = (priority_cols + other_cols)[:6]
            cols_str = ", ".join(key_cols) if key_cols else ""

            summary_parts = [f"{filename} ({level} level)"]
            if year_str:
                summary_parts.append(year_str)
            if cols_str:
                summary_parts.append(f"Data: {cols_str}")

            current_summary = " | ".join(summary_parts)

        all_summaries.append({
            "filename": filename,
            "level": level,
            "has_llm_summary": bool(llm_summary and len(llm_summary) > 20),
            "summary": current_summary,
            "year_str": year_str,
            "topics": meta.get("topic_tags", [])
        })

    # Display summaries in a clear format
    for s in all_summaries:
        status_icon = "[OK]" if s["has_llm_summary"] else "[FALLBACK]"
        with st.expander(f"{status_icon} {s['filename']}", expanded=False):
            st.write(f"**Current Summary:**")
            st.code(f"- {s['summary']}")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**Level:** {s['level']}")
            with col2:
                st.write(f"**{s['year_str']}**" if s['year_str'] else "No year info")
            with col3:
                st.write(f"**Topics:** {', '.join(s['topics'])}" if s['topics'] else "No topics")

            st.write(f"**Has pre-generated LLM summary:** {'Yes' if s['has_llm_summary'] else 'No (using fallback)'}")

    st.divider()

    # Preview what gets sent to LLM
    st.subheader("Full LLM Context Preview")
    st.markdown("This is the exact text that gets sent to the conversation LLM:")

    datasets_text = "\n".join([f"- {s['summary']}" for s in all_summaries[:6]])
    st.code(datasets_text, language=None)

    st.divider()

    # Regenerate summaries
    st.subheader("Regenerate Metadata")
    st.markdown("""
    Regenerate metadata (including `llm_summary`) for datasets.
    This updates metadata in place without moving files.
    """)

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Regenerate All Metadata", type="primary"):
            with st.spinner("Regenerating metadata for all datasets..."):
                result = regenerate_metadata_only()
                if result["regenerated"]:
                    st.success(f"Regenerated metadata for {len(result['regenerated'])} datasets")
                if result["errors"]:
                    for err in result["errors"]:
                        st.error(err)
                st.rerun()

    with col2:
        # Single dataset regeneration
        dataset_names = [s["filename"] for s in all_summaries]
        selected_dataset = st.selectbox("Or select single dataset:", ["-- Select --"] + dataset_names)

    with col3:
        if selected_dataset and selected_dataset != "-- Select --":
            if st.button("Regenerate Selected"):
                with st.spinner(f"Regenerating metadata for {selected_dataset}..."):
                    result = regenerate_metadata_only(selected_dataset)
                    if result["regenerated"]:
                        st.success(f"Regenerated metadata for {selected_dataset}")
                    if result["errors"]:
                        for err in result["errors"]:
                            st.error(err)
                    st.rerun()

    st.divider()

    # Manual edit hint
    st.info(f"""
    **Manual Editing:** You can also directly edit metadata files at:
    `{METADATA_DIR}`

    Each dataset has a `*_metadata.json` file with an `llm_summary` field you can customize.
    """)


# --- Settings Page ---
elif page == "Settings":
    st.header("Settings")

    st.subheader("Directory Paths")
    storage = get_storage_info()

    st.write(f"**Base Directory:** `{BASE_DIR}`")
    st.write(f"**Data Loading:** `{DATA_LOADING_DIR}` ({storage['loading']['files']} files, {storage['loading']['size_mb']} MB)")
    st.write(f"**Data Cleaned:** `{DATA_CLEANED_DIR}` ({storage['cleaned']['files']} files, {storage['cleaned']['size_mb']} MB)")
    st.write(f"**Metadata:** `{METADATA_DIR}` ({storage['metadata']['files']} files, {storage['metadata']['size_mb']} MB)")
    st.write(f"**Backup Path:** `{BACKUP_PATH}` ({storage['backup']['files']} files, {storage['backup']['size_mb']} MB)")

    st.divider()

    st.subheader("Disk Usage")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**C: Drive (Data)**")
        if "error" not in storage.get("disk_c", {}):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Total", f"{storage['disk_c']['total_gb']} GB")
            with c2:
                st.metric("Used", f"{storage['disk_c']['used_gb']} GB")
            with c3:
                st.metric("Free", f"{storage['disk_c']['free_gb']} GB")

    with col2:
        st.write("**D: Drive (Backups)**")
        if "error" not in storage.get("disk_d", {}):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Total", f"{storage['disk_d']['total_gb']} GB")
            with c2:
                st.metric("Used", f"{storage['disk_d']['used_gb']} GB")
            with c3:
                st.metric("Free", f"{storage['disk_d']['free_gb']} GB")
        else:
            st.warning(f"Could not read D: drive - {storage['disk_d'].get('error', 'unknown error')}")

    st.divider()

    st.subheader("Ultimate Metadata")
    ultimate = load_ultimate_metadata()
    st.write(f"**Version:** {ultimate.get('version', 'N/A')}")
    st.write(f"**Last Updated:** {ultimate.get('last_updated', 'Never')}")
    st.write(f"**Datasets Registered:** {len(ultimate.get('datasets', {}))}")

    if st.button("View Full Ultimate Metadata"):
        st.json(ultimate)

    st.divider()

    # Cloud Sync Placeholder
    st.subheader("Cloud Sync (Future)")
    st.info("""
    **Cloud sync is planned for a future release.**

    Current strategy: Datasets are small enough to store in GitHub.

    Future options being considered:
    - Supabase (Postgres + REST API)
    - Cloudflare R2 (S3-compatible storage)
    - Direct GitHub integration

    For now, use the local backup system (D:/data-backups).
    """)
