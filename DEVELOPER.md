# County Map - Developer Guide

Technical documentation for local development, admin dashboard, and data management.

**For system architecture and context**, see [CONTEXT.md](CONTEXT.md).

---

## Local Development Setup

### Prerequisites

- Python 3.12+
- OpenAI API key
- (Optional) Supabase account for cloud logging

### Installation

```bash
# Clone
git clone https://github.com/xyver/county-map.git
cd county-map

# Environment
echo OPENAI_API_KEY=your-key-here > .env

# Optional: Add Supabase for cloud logging
echo SUPABASE_URL=https://your-project.supabase.co >> .env
echo SUPABASE_ANON_KEY=your-key >> .env

# Install dependencies
pip install -r requirements.txt
```

### Running Locally

```bash
# Main server (hot reload enabled)
python -m uvicorn app:app --reload --port 7000

# Or run directly
python app.py

# Admin dashboard (separate terminal)
streamlit run admin/app.py
```

- Main app: http://localhost:7000
- Admin dashboard: http://localhost:8501

---

## Admin Dashboard

Local Streamlit app for data management. **Not deployed to production** - runs locally only.

### Start Dashboard

```bash
streamlit run admin/app.py
```

### Features

**Dataset Management:**
- View all datasets with metadata
- Preview data rows
- Edit metadata
- Delete datasets

**Data Import:**
- Scan `data_loading/` for new CSVs
- Preview file structure and quality
- Configure column mappings
- Run ETL processing

**Aggregate Row Editor:**
- View list of aggregate rows (World, Africa, etc.)
- Add/remove from exclusion list
- These rows are removed during ETL to prevent double-counting

**Backup System:**
- Manual backups to `D:\data-backups` (configurable)
- Backup before destructive operations
- Restore from backup

### Dashboard Pages

| Page | Purpose |
|------|---------|
| Dashboard | Overview, dataset counts, health metrics |
| Datasets | Browse and manage processed datasets |
| Import | Scan and process new CSVs |
| Backups | Backup and restore data |
| Settings | Ultimate metadata, configuration |

---

## Data Management

### Directory Structure

```
data_pipeline/
  data_loading/       # Drop raw CSVs here for processing
  data_cleaned/       # Production data (server reads from here)
  metadata/           # Auto-generated JSON metadata per dataset
    ultimate_metadata.json  # Master index
    owid-co2-data_metadata.json
    ...
  conversions.json    # Region groupings, ISO codes, aliases
```

### Adding New Data

#### Method 1: ETL Pipeline (Recommended)

```bash
# 1. Drop CSV in loading folder
cp your-data.csv data_pipeline/data_loading/

# 2. Run ETL
python data_pipeline/prepare_data.py

# 3. Restart server - auto-discovered!
```

#### Method 2: Admin Dashboard

1. Place CSV in `data_pipeline/data_loading/`
2. Open admin dashboard
3. Go to Import page
4. Click "Scan" to analyze file
5. Review column suggestions
6. Click "Process" to run ETL
7. Dataset appears in data_cleaned/

#### Method 3: Manual (Advanced)

1. Clean CSV manually
2. Create metadata JSON in `data_pipeline/metadata/`
3. Place CSV in `data_pipeline/data_cleaned/`
4. Update `ultimate_metadata.json`
5. Restart server

### CSV Requirements

- UTF-8 encoding (or auto-detected)
- Header row with column names
- Geographic identifier column (country_name, state_name, county_code, etc.)
- Year column for time-series data (optional)
- Any delimiter (comma, tab, semicolon - auto-detected)

### ETL Pipeline Details

The ETL script (`prepare_data.py`) performs:

1. **Encoding Detection** - Auto-detect and handle various encodings
2. **Delimiter Detection** - Comma, tab, semicolon
3. **Column Standardization** - Rename to standard names based on aliases
4. **Geographic Classification** - Detect country/state/county level
5. **Year Detection** - Find year column, determine range
6. **Census Code Translation** - Convert YEAR 1-6 to actual years
7. **Aggregate Row Removal** - Remove World, Africa, etc. totals
8. **Metadata Generation** - Create JSON with column info, keywords
9. **Output** - Clean CSV + metadata to data_cleaned/

### Column Standardization

ETL renames columns based on aliases in ultimate_metadata.json:

| Common Aliases | Standard Name |
|----------------|---------------|
| Location, country, Country | country_name |
| iso_code, ISO_A3 | country_code |
| Year, year | year |
| pop_est, Population | population |
| Latitude, lat | latitude |
| Longitude, lng, lon | longitude |

### Aggregate Row Removal

Data sources often include aggregate rows that would cause double-counting. These are removed during ETL:

```python
AGGREGATE_ROWS = [
    "World", "Africa", "Asia", "Europe", "North America", "South America",
    "High income", "Low income", "Middle income", "Upper middle income",
    "OECD members", "Non-OECD members", "European Union (27)"
]
```

Edit this list in `prepare_data.py` or via admin dashboard.

---

## Regional Groupings

Defined in `data_pipeline/conversions.json`.

### Adding a New Region

```json
{
  "regional_groupings": {
    "Your Region": ["USA", "CAN", "MEX"]
  },
  "region_aliases": {
    "your-region": "Your Region",
    "NAFTA": "Your Region"
  }
}
```

### Supported Regions

**Continents:** Europe, Africa, Americas, Asia, Oceania

**Political Groups:** EU, European Union, G7, G20, NATO, ASEAN, BRICS, Arab League, African Union, Commonwealth

**Sub-regions:** Nordic Countries, Baltic States, Caribbean, Pacific Islands, Gulf Cooperation Council, Maghreb, Benelux, Latin America

---

## Cloud Logging (Supabase)

### Setup

1. Create Supabase project at https://supabase.com
2. Add to `.env`:
   ```bash
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_ANON_KEY=eyJ...
   ```

### Create Tables

Run in Supabase SQL Editor:

```sql
-- Conversation sessions (one row per browser session)
CREATE TABLE conversation_sessions (
  id SERIAL PRIMARY KEY,
  session_id TEXT UNIQUE NOT NULL,
  messages JSONB DEFAULT '[]',
  message_count INT DEFAULT 0,
  datasets_used TEXT[] DEFAULT '{}',
  intents_seen TEXT[] DEFAULT '{}',
  total_results INT DEFAULT 0,
  first_message_at TIMESTAMP WITH TIME ZONE,
  last_message_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Error logs
CREATE TABLE error_logs (
  id SERIAL PRIMARY KEY,
  error_type TEXT,
  error_message TEXT,
  traceback TEXT,
  query TEXT,
  session_id TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Data quality issues (missing geometry, unknown regions)
CREATE TABLE data_quality_issues (
  id SERIAL PRIMARY KEY,
  issue_type TEXT,
  description TEXT,
  entity_name TEXT,
  dataset TEXT,
  query TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Dataset metadata sync
CREATE TABLE dataset_metadata (
  id SERIAL PRIMARY KEY,
  filename TEXT UNIQUE NOT NULL,
  description TEXT,
  source_name TEXT,
  geographic_level TEXT,
  row_count INT,
  topic_tags TEXT[],
  full_metadata JSONB,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_quality_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_metadata ENABLE ROW LEVEL SECURITY;

-- Create policies for public access
CREATE POLICY "Allow all" ON conversation_sessions FOR ALL USING (true);
CREATE POLICY "Allow all" ON error_logs FOR ALL USING (true);
CREATE POLICY "Allow all" ON data_quality_issues FOR ALL USING (true);
CREATE POLICY "Allow all" ON dataset_metadata FOR ALL USING (true);
```

### Test Connection

```bash
python supabase_client.py
```

### What Gets Logged

- **conversation_sessions** - Full chat history per browser tab
- **error_logs** - Exceptions for debugging
- **data_quality_issues** - Missing geometry, unknown regions (for improvement)
- **dataset_metadata** - Synced metadata from all datasets

---

## Backup System

### Default Backup Path

```python
# In admin/app.py
BACKUP_PATH = Path("D:/data-backups")
```

### What Gets Backed Up

- `data_cleaned/*.csv` - All production CSVs
- `metadata/*.json` - All metadata files
- `ultimate_metadata.json` - Master index

### Manual Backup

Via admin dashboard Backups page, or:

```python
import shutil
shutil.copytree("data_pipeline/data_cleaned", "D:/data-backups/data_cleaned")
shutil.copytree("data_pipeline/metadata", "D:/data-backups/metadata")
```

---

## Debugging

### Enable Debug Logging

```python
# In mapmover/logging_analytics.py or app.py
import logging
logging.getLogger("mapmover").setLevel(logging.DEBUG)
```

### Check Local Logs

```bash
# Query logs
cat logs/analytics/queries_YYYYMMDD.jsonl

# Missing geometries
cat logs/analytics/missing_geometries.jsonl
```

### Check Supabase

Query tables:
- `conversation_sessions` - Full conversations
- `error_logs` - Exceptions
- `data_quality_issues` - Gaps in data

### Common Issues

**Dataset not appearing:**
- Check file is in `data_cleaned/` not `data_loading/`
- Restart server (auto-discovery on startup)
- Check metadata JSON exists

**Wrong dataset selected for query:**
- Check keywords in metadata match query terms
- Higher `priority_score` datasets are preferred
- Debug by enabling logging and checking LLM response

**Missing geometry on map:**
- Add alias to `COUNTRY_NAME_ALIASES` in mapmover/geometry_enrichment.py
- Check fallback coordinates in data_pipeline/conversions.json
- Check data_quality_issues table for patterns

---

## Deployment

### Railway (Production)

1. Connect GitHub repo to Railway
2. Set environment variables:
   - `OPENAI_API_KEY` (required)
   - `SUPABASE_URL` (optional)
   - `SUPABASE_ANON_KEY` (optional)
3. Deploy (auto-detects Python)

### What Gets Deployed

- `app.py` - FastAPI entry point
- `mapmover/` - Core application package
- `templates/` - Frontend
- `static/` - JS/CSS
- `data_pipeline/data_cleaned/` - Production data
- `data_pipeline/metadata/` - Metadata

### What Stays Local

- `admin/` - Dashboard (local only)
- `data_pipeline/data_loading/` - Raw data staging
- `logs/` - Local logs

---

## File Reference

### Main Application

| File | Purpose |
|------|---------|
| `app.py` | FastAPI entry point, routes, startup |
| `supabase_client.py` | Supabase cloud logging client |

### mapmover/ Package (Core Logic)

| Module | Purpose |
|--------|---------|
| `__init__.py` | Package exports |
| `constants.py` | State abbreviations, unit multipliers |
| `utils.py` | Normalization, unit conversion, helpers |
| `geography.py` | Regions, country codes, coordinates |
| `data_loading.py` | CSV loading, metadata, catalog |
| `meta_queries.py` | "What data?" queries |
| `response_builder.py` | GeoJSON response construction |
| `geometry_enrichment.py` | Adding geometry to data |
| `geometry_joining.py` | Auto-join, fuzzy matching |
| `map_state.py` | Session state, incremental updates |
| `chat_handlers.py` | Chat endpoint logic |
| `geometry_handlers.py` | Geometry endpoint logic |
| `llm.py` | LLM initialization, prompts |
| `logging_analytics.py` | Supabase logging, analytics |

### Other Files

| File | Purpose |
|------|---------|
| `admin/app.py` | Streamlit dashboard |
| `data_pipeline/prepare_data.py` | ETL pipeline |
| `data_pipeline/conversions.json` | Regions, ISO codes |
| `templates/index.html` | Frontend UI |
| `static/mapviewer.js` | MapLibre GL map viewer |

---

## Development Commands

```bash
# Main server (with hot reload)
python -m uvicorn app:app --reload --port 7000

# Or run directly
python app.py

# Admin dashboard
streamlit run admin/app.py

# ETL pipeline
python data_pipeline/prepare_data.py

# Test Supabase connection
python supabase_client.py
```

---

## Project Structure

```
county-map/
  app.py                   # FastAPI entry point
  supabase_client.py       # Supabase client

  mapmover/                # Core application package
    __init__.py            # Package exports
    constants.py           # State abbrevs, unit multipliers
    utils.py               # Normalization, helpers
    geography.py           # Regions, coordinates
    data_loading.py        # CSV loading, catalog
    meta_queries.py        # "What data?" queries
    response_builder.py    # GeoJSON responses
    geometry_enrichment.py # Adding geometry
    geometry_joining.py    # Auto-join, fuzzy matching
    map_state.py           # Session state
    chat_handlers.py       # Chat endpoint logic
    geometry_handlers.py   # Geometry endpoint logic
    llm.py                 # LLM init, prompts
    logging_analytics.py   # Cloud logging

  admin/                   # Local admin dashboard
    app.py                 # Streamlit UI

  data_pipeline/           # Data processing
    prepare_data.py        # Main ETL script
    name_standardizer.py   # ETL helper
    data_cleaned/          # Production data
    data_loading/          # Raw data staging
    metadata/              # Metadata JSONs
    conversions.json       # Regional groupings

  templates/               # Frontend HTML
  static/                  # JS, CSS assets
  archive/                 # Old/unused scripts
```

---

*Last Updated: 2025-12-21*
