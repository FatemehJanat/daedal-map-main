Admin Dashboard Report (admin/app.py)
File: 2730 lines, Streamlit app
Status: Broken (references deleted paths)
Purpose: Developer dashboard for data preparation, ETL, and management
Navigation Pages (10 sections)
Page	Purpose	Status
Dashboard	Overview metrics, dataset summaries, pending imports	Broken
Datasets	View, manage, delete, reprocess existing datasets	Broken
Import	CSV upload, column analysis, ETL processing	Broken
Compare Datasets	Compare new vs existing data for overlap/merge decisions	Broken
Metadata Editor	Edit source info, licensing, descriptions per dataset	Broken
Query Analytics	View user queries/errors from Supabase logs	Works if Supabase configured
Data Quality	Missing geometries, region names, duplicates	Partial
Backups	Backup/restore datasets to secondary location	Broken
LLM Context	View/manage summaries sent to conversation LLM	Broken
Settings	Directory paths, disk usage, ultimate metadata	Broken
Key Features (What It Was Supposed To Do)
1. CSV Import Pipeline (lines 150-760)
Drop CSVs into data_loading/ folder
Auto-detect delimiter, scan columns for quality issues
Suggest column deletions (>95% null, single-value, auto-generated)
Suggest column renames (standardize to country_code, state_name, etc.)
Detect geographic level (country, state, county, city)
Detect topic tags (economics, environment, health, demographics, etc.)
Run ETL via data_pipeline.prepare_data.DataPreparer
2. Dataset Comparison (lines 1334-1684)
Compare new CSV against existing datasets
Calculate data column overlap percentage
Recommendations: REPLACE (>80% overlap), MERGE (>50%), JOIN (shared IDs), SUPPLEMENT, INDEPENDENT
Show which columns are unique vs overlapping
3. Metadata Management (lines 1686-1944)
Edit source name, URL, license, description
License picker with common options (CC-BY, ODbL, etc.)
LLM summary field (sent to chat for context)
Syncs changes to ultimate_metadata.json
4. Data Quality Tools (lines 2099-2400)
Missing geometries: countries without polygon boundaries
Missing regions: unrecognized region names in queries
Name standardization: scan datasets for non-standard country names
Duplicate detection: find rows with duplicate keys
5. Backup System (lines 2402-2490)
Full backup to D:/data-backups
Per-file backup/restore
Track which files need backup
6. LLM Context Manager (lines 2493-2658)
View summaries sent to conversation LLM
Shows priority data terms (gdp, co2, population, etc.)
Regenerate metadata for better summaries
Broken Dependencies

# These paths no longer exist:
DATA_PIPELINE_DIR = BASE_DIR / "data_pipeline"        # DELETED
DATA_LOADING_DIR = DATA_PIPELINE_DIR / "data_loading" # DELETED
DATA_CLEANED_DIR = DATA_PIPELINE_DIR / "data_cleaned" # DELETED
METADATA_DIR = DATA_PIPELINE_DIR / "metadata"         # DELETED
BACKUP_PATH = Path("D:/data-backups")                 # Different from county-map-data

# These imports will fail:
from data_pipeline.prepare_data import DataPreparer   # DELETED
Useful Concepts Worth Preserving
Column analysis logic (lines 202-375) - Detects useless columns, suggests renames
Geographic level detection - county/state/country/city based on column names
Topic detection - economics, environment, health, demographics, population, energy
Dataset comparison algorithm - overlap calculation, merge recommendations
LLM summary generation - priority terms, fallback summary builder
Standard column aliases - mapping nonstandard names to standard schema
Recommendation
Delete the file - it's 2730 lines of broken code. When you need a data prep dashboard:
Start fresh with correct paths to county-map-data/
Extract useful logic (column analysis, comparison) into reusable modules
Build incrementally as needed
The working converters in data_converters/ are more valuable right now.