# County Map - Developer Guide

Technical documentation for local development and data management.

**For system architecture**, see [CONTEXT.md](CONTEXT.md).

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

## Data Folder Structure

The system uses an external data folder (`county-map-data/`) as the contract between build and runtime:

```
county-map-data/                 # External data folder
|
|   Raw data/                    # Original source files
|     gadm36.gpkg                # GADM geometry source (1.9GB)
|     (census CSVs, OWID CSVs, etc.)
|
|   geometry/                    # Location geometries
|     global.csv                 # All countries (admin_0)
|     country_coverage.json      # Drill-down metadata
|     {ISO3}.parquet             # Per-country subdivisions (257 files)
|
|   data/                        # Indicator data by source
|     owid_co2/
|       all_countries.parquet    # Country-level data
|       metadata.json            # Source metadata for LLM
|     who_health/
|       all_countries.parquet
|       metadata.json
|     census_population/
|       USA.parquet              # US-only data
|       metadata.json
|     (etc.)
```

---

## Adding New Data

### Using Data Converters

Each data source has a dedicated converter script in `data_converters/`:

```bash
# Run a converter
python data_converters/convert_owid_co2.py
python data_converters/convert_who_health.py
python data_converters/convert_census_population.py
```

### Available Converters

| Converter | Source | Output |
|-----------|--------|--------|
| convert_owid_co2.py | Our World in Data | owid_co2/ |
| convert_who_health.py | WHO health indicators | who_health/ |
| convert_imf_bop.py | IMF balance of payments | imf_bop/ |
| convert_census_population.py | US Census population | census_population/ |
| convert_census_agesex.py | US Census age/sex | census_agesex/ |
| convert_census_demographics.py | US Census demographics | census_demographics/ |

### Creating a New Converter

1. Place raw data in `county-map-data/Raw data/`
2. Create a new script in `data_converters/`
3. Output parquet files to `county-map-data/data/{source_id}/`
4. Include a `metadata.json` with column descriptions
5. Restart server - new dataset is auto-discovered

See [DATA_PIPELINE.md](DATA_PIPELINE.md) for detailed converter documentation.

---

## Geometry System

Geometry files are built from GADM data using `mapmover/process_gadm.py`:

```bash
python mapmover/process_gadm.py
```

This creates:
- `geometry/global.csv` - All 257 countries
- `geometry/{ISO3}.parquet` - Subdivisions per country
- `geometry/country_coverage.json` - Drill-down metadata

See [GEOMETRY.md](GEOMETRY.md) for the loc_id specification.

---

## Admin Dashboard

Local Streamlit app for data management. **Not deployed to production**.

```bash
streamlit run admin/app.py
```

**Status**: Needs rebuild - paths may be outdated.

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
-- Conversation sessions
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

-- Data quality issues
CREATE TABLE data_quality_issues (
  id SERIAL PRIMARY KEY,
  issue_type TEXT,
  description TEXT,
  entity_name TEXT,
  dataset TEXT,
  query TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_quality_issues ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all" ON conversation_sessions FOR ALL USING (true);
CREATE POLICY "Allow all" ON error_logs FOR ALL USING (true);
CREATE POLICY "Allow all" ON data_quality_issues FOR ALL USING (true);
```

### Test Connection

```bash
python supabase_client.py
```

---

## Debugging

### Enable Debug Logging

```python
# In mapmover/logging_analytics.py or app.py
import logging
logging.getLogger("mapmover").setLevel(logging.DEBUG)
```

### Common Issues

**Dataset not appearing:**
- Check file is in `county-map-data/data/{source_id}/`
- Ensure `metadata.json` exists alongside parquet file
- Restart server (auto-discovery on startup)

**Wrong dataset selected for query:**
- Check keywords in metadata match query terms
- Higher `priority_score` datasets are preferred

**Missing geometry on map:**
- Add alias to name_standardizer.py
- Check loc_id format matches geometry files

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
- `templates/` - Frontend HTML
- `static/` - JS/CSS assets

### What Stays Local

- `admin/` - Dashboard (local only)
- `data_converters/` - Build scripts
- `logs/` - Local logs

---

## Module Reference

### mapmover/ Package

| Module | Purpose |
|--------|---------|
| `__init__.py` | Package exports |
| `chat_handlers.py` | Chat endpoint logic |
| `llm.py` | LLM initialization, prompts, parsing |
| `response_builder.py` | GeoJSON response construction |
| `map_state.py` | Session state management |
| `data_loading.py` | Load data from county-map-data |
| `data_cascade.py` | Parent/child data lookups |
| `geometry_handlers.py` | Geometry endpoints |
| `geometry_enrichment.py` | Adding geometry to responses |
| `geometry_joining.py` | Auto-join, fuzzy matching |
| `meta_queries.py` | "What data?" queries |
| `name_standardizer.py` | loc_id lookups, name matching |
| `constants.py` | State abbreviations, unit multipliers |
| `utils.py` | Normalization, helpers |
| `geography.py` | Regions, coordinates |
| `logging_analytics.py` | Cloud logging |
| `process_gadm.py` | Geometry builder (build tool) |

---

## Quick Commands

```bash
# Start server
python app.py

# Start with hot reload
python -m uvicorn app:app --reload --port 7000

# Run data converter
python data_converters/convert_owid_co2.py

# Rebuild geometry
python mapmover/process_gadm.py

# Admin dashboard
streamlit run admin/app.py

# Test Supabase
python supabase_client.py
```

---

*Last Updated: 2025-12-21*
