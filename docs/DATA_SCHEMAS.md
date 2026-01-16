# Data Schemas

This document defines the data formats used by county-map. Follow these schemas when creating your own data converters.

---

## Core Concepts

### Location ID (loc_id)

Every location has a unique `loc_id` that identifies it across all datasets:

```
{country}[-{admin1}[-{admin2}[-{admin3}...]]]
```

| Level | Example | Description |
|-------|---------|-------------|
| Country | `USA` | ISO 3166-1 alpha-3 |
| State/Province | `USA-CA` | Country + admin1 code |
| County/District | `USA-CA-6037` | Country + admin1 + admin2 |

**Key rules:**
- Country codes are ISO 3166-1 alpha-3 (uppercase): `USA`, `GBR`, `DEU`
- US FIPS codes have NO leading zeros: `USA-CA-6037` not `USA-CA-06037`
- Canada uses 2-letter province codes: `CAN-BC`, `CAN-ON`

### Universal Join Key

All data joins on `(loc_id, year)`. This enables:
- Merging any datasets together
- Time slider functionality
- Location hierarchy queries

---

## Indicator Data Schema

For aggregate statistics (population, GDP, risk scores, etc.):

```
| loc_id      | year | metric1 | metric2 | metric3 |
|-------------|------|---------|---------|---------|
| USA         | 2020 | 5000    | 15.2    | 800     |
| USA-CA      | 2020 | 400     | 10.1    | 50      |
| USA-CA-6037 | 2020 | 25      | 8.5     | 12      |
```

**Required columns:**
- `loc_id` - Location identifier (string)
- `year` - Integer year

**Do NOT include:**
- Redundant location columns (state, county, name, FIPS)
- These are derivable from loc_id or geometry lookup

**File format:** Parquet, stored as `{source}/aggregates.parquet`

---

## Event Data Schema

For individual events (earthquakes, hurricanes, wildfires):

```
| event_id | timestamp           | latitude | longitude | magnitude | loc_id  |
|----------|---------------------|----------|-----------|-----------|---------|
| eq_001   | 2024-01-15T08:30:00 | 34.05    | -118.24   | 5.2       | USA-CA  |
| eq_002   | 2024-01-16T12:45:00 | 35.68    | -121.89   | 4.1       | USA-CA  |
```

**Required columns:**
- `event_id` - Unique event identifier (string)
- `timestamp` - ISO 8601 datetime
- `latitude`, `longitude` - Decimal degrees (WGS84)

**Common optional columns:**
- `magnitude` - Event magnitude/intensity
- `loc_id` - Resolved location (for filtering)
- `name` - Event name (hurricanes, named storms)
- `status` - Current status (active, historical)

**File format:** Parquet, stored as `{source}/events.parquet`

---

## Geometry Files

Geometry is stored separately and joined via `loc_id`:

```
geometry/{ISO3}.parquet
```

**Schema:**
| Column | Type | Description |
|--------|------|-------------|
| loc_id | string | Location identifier |
| name | string | Display name |
| admin_level | int | 0=country, 1=state, 2=county |
| parent_id | string | Parent loc_id |
| geometry | WKB | Polygon/MultiPolygon |
| centroid_lat | float | Center latitude |
| centroid_lon | float | Center longitude |

---

## Data Storage Location

The app uses a configurable **backup folder** for storing large data files. This keeps your git repository small.

### Configuring via Admin Settings

In the app, go to **Admin > Settings > Data Storage** to configure:

```
Backup Folder Path: C:\Users\Bryan\Desktop\global map\county-map-data
```

The app will create/use this structure:
```
[backup_path]/
    geometry/   -- Admin boundaries (GADM, Natural Earth)
    data/       -- Indicator datasets (parquet/CSV)
    metadata/   -- Catalog and index files
```

### Manual Configuration

Edit `settings.json` in the app root:
```json
{
  "backup_path": "C:\\path\\to\\county-map-data"
}
```

---

## Folder Structure

Data is organized by scope and source:

```
county-map-data/
    catalog.json              # Master index of all sources

    global/                   # Global scope datasets
        earthquakes/
            events.parquet
            metadata.json
        tsunamis/
            events.parquet

    countries/                # Country-specific datasets
        USA/
            index.json        # Country catalog
            fema_nri/
                aggregates.parquet
                metadata.json
        CAN/
            ...

    geometry/                 # Geometry files
        USA.parquet
        CAN.parquet
        global.csv
```

---

## Metadata Schema

Each dataset has a `metadata.json`:

```json
{
    "source_id": "usgs_earthquakes",
    "source_name": "USGS Earthquake Catalog",
    "source_url": "https://earthquake.usgs.gov/",
    "license": "Public Domain",
    "description": "Global earthquake events from USGS",
    "category": "hazard",
    "update_frequency": "real-time",
    "temporal_coverage": {
        "start_year": 1900,
        "end_year": 2024
    },
    "spatial_coverage": {
        "scope": "global"
    },
    "columns": [
        {"name": "magnitude", "type": "float", "description": "Richter magnitude"}
    ]
}
```

---

## Creating a Converter

See the [examples/](../examples/) folder for sample converters. The basic pattern:

```python
import pandas as pd
from pathlib import Path

# 1. Load raw data
df = pd.read_csv("raw_data.csv")

# 2. Transform to schema
df = df.rename(columns={"location_code": "loc_id", "date": "year"})
df["loc_id"] = df["loc_id"].apply(normalize_loc_id)
df["year"] = pd.to_datetime(df["year"]).dt.year

# 3. Keep only required columns
df = df[["loc_id", "year", "metric1", "metric2"]]

# 4. Save as parquet
output_path = Path("county-map-data/countries/USA/my_source/aggregates.parquet")
output_path.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(output_path, index=False)
```

---

## Country-Specific Formats

### United States (USA)

| Level | Format | Example |
|-------|--------|---------|
| State | `USA-{ST}` | `USA-CA` |
| County | `USA-{ST}-{FIPS}` | `USA-CA-6037` |
| ZCTA | `USA-{ST}-Z{ZIP5}` | `USA-CA-Z90210` |

**Note:** County FIPS codes have NO leading zeros.

### Canada (CAN)

| Level | Format | Example |
|-------|--------|---------|
| Province | `CAN-{PR}` | `CAN-BC` |
| Census Division | `CAN-{PR}-{CDUID}` | `CAN-BC-5915` |

### Europe (EUR)

| Level | Format | Example |
|-------|--------|---------|
| Country | `{ISO3}` | `DEU`, `FRA` |
| NUTS 1 | `{ISO3}-{NUTS1}` | `DEU-DE1` |
| NUTS 2 | `{ISO3}-{NUTS1}-{NUTS2}` | `DEU-DE1-DE11` |
| NUTS 3 | `{ISO3}-{NUTS1}-{NUTS2}-{NUTS3}` | `DEU-DE1-DE11-DE111` |

### Australia (AUS)

| Level | Format | Example |
|-------|--------|---------|
| State | `AUS-{ST}` | `AUS-NSW` |
| LGA | `AUS-{ST}-{LGACODE}` | `AUS-NSW-10050` |

---

*For source attribution, see [public reference.md](public%20reference.md)*
