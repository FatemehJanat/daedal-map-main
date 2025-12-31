# SDG Data Import Plan

## Source Data

**File**: `county-map-data/Raw data/2025_Q3.2_AllData_Before_20251212.csv`
**Size**: ~2 GB, 3.3M rows
**Structure**: Long format (1 row per observation)

### Key Columns

| Column | Description | Example |
|--------|-------------|---------|
| Goal | SDG goal number (1-17) | 1 |
| Target | Target code | 1.1 |
| Indicator | Indicator code | 1.1.1 |
| SeriesCode | Unique metric ID | SI_POV_DAY1 |
| SeriesDescription | Human-readable name | "Proportion of population below international poverty line (%)" |
| GeoAreaCode | UN M49 numeric code | 840 (USA) |
| GeoAreaName | Country/region name | "United States of America" |
| TimePeriod | Year | 2020 |
| Value | Metric value | 1.2 |
| Units | Unit of measurement | PERCENT |
| ValueType | Float/Integer | Float |
| Age, Sex, Location... | Disaggregation dimensions | ALLAGE, BOTHSEX |

### Data Distribution

| Goal | Rows | Series |
|------|------|--------|
| 1 | 126K | 59 |
| 2 | 223K | 54 |
| 3 | 280K | 43 |
| 4 | 413K | 36 |
| 5 | 43K | 47 |
| 6 | 192K | 59 |
| 7 | 124K | 6 |
| 8 | 452K | 34 |
| 9 | 76K | 24 |
| 10 | 99K | 27 |
| 11 | 67K | 46 |
| 12 | 421K | 58 |
| 13 | 23K | 38 |
| 14 | 56K | 27 |
| 15 | 258K | 35 |
| 16 | 177K | 81 |
| 17 | 284K | 89 |

**Total**: ~783 unique series codes across all goals

---

## Output Structure

17 parquet files, one per SDG goal:

```
county-map-data/data/
  un_sdg_01/
    all_countries.parquet
    metadata.json
    reference.json
  un_sdg_02/
    all_countries.parquet
    metadata.json
    reference.json
  ...
  un_sdg_17/
    all_countries.parquet
    metadata.json
    reference.json
```

### Parquet Schema

| Column | Type | Description |
|--------|------|-------------|
| loc_id | string | ISO3 country code |
| year | int | Year of observation |
| {series_code} | float | Value for each metric (e.g., SI_POV_DAY1) |

**Wide format**: Each series becomes a column. Example:
```
loc_id | year | SI_POV_DAY1 | SI_POV_EMP1 | ...
USA    | 2020 | 1.2         | 0.8         | ...
GBR    | 2020 | 0.5         | 0.3         | ...
```

---

## Country Code Mapping

### Challenge
SDG uses UN M49 numeric codes (e.g., 840 = USA)
Our system uses ISO3 alpha codes (e.g., USA)

### Solution
Build M49 -> ISO3 mapping using:
1. Name matching via NameStandardizer
2. Fallback to pycountry library if installed
3. Manual mapping for edge cases

### Filter Countries Only
SDG includes regions (Africa, World, EU, etc.) that need filtering:
- Keep only M49 codes that map to single countries
- Skip regional aggregates (GeoAreaCode < 100 often indicates regions)
- Skip special entities (Large Marine Ecosystem, FAO Fishing Areas)

---

## Conversion Steps

### Step 1: Build M49 -> ISO3 Mapping

```python
# Extract unique country mappings from CSV
unique_areas = df[['GeoAreaCode', 'GeoAreaName']].drop_duplicates()

# Use NameStandardizer to convert names to ISO3
from mapmover.name_standardizer import NameStandardizer
std = NameStandardizer()

m49_to_iso3 = {}
for _, row in unique_areas.iterrows():
    name = row['GeoAreaName']
    iso3 = std.get_country_code(name)
    if iso3:
        m49_to_iso3[row['GeoAreaCode']] = iso3
```

### Step 2: Filter and Aggregate Data

Many SDG indicators have disaggregation dimensions (Age, Sex, Location).
For initial import, use only "total" aggregations:
- Age = "ALLAGE" or null
- Sex = "BOTHSEX" or null
- Location = "ALLAREA" or null

```python
# Filter to total values only
df_totals = df[
    (df['Age'].isin(['ALLAGE', None, '']) | df['Age'].isna()) &
    (df['Sex'].isin(['BOTHSEX', None, '']) | df['Sex'].isna()) &
    (df['Location'].isin(['ALLAREA', None, '']) | df['Location'].isna())
]
```

### Step 3: Pivot to Wide Format (Per Goal)

```python
for goal_num in range(1, 18):
    goal_df = df_totals[df_totals['Goal'] == goal_num]

    # Add loc_id column
    goal_df['loc_id'] = goal_df['GeoAreaCode'].map(m49_to_iso3)
    goal_df = goal_df[goal_df['loc_id'].notna()]

    # Pivot: rows=loc_id+year, columns=SeriesCode
    pivoted = goal_df.pivot_table(
        index=['loc_id', 'year'],
        columns='SeriesCode',
        values='Value',
        aggfunc='first'
    ).reset_index()

    # Rename columns to lowercase
    pivoted.columns = [c.lower() if c not in ['loc_id', 'year'] else c
                       for c in pivoted.columns]

    # Save
    output_dir = Path('county-map-data/data') / f'un_sdg_{goal_num:02d}'
    output_dir.mkdir(exist_ok=True)
    pivoted.to_parquet(output_dir / 'all_countries.parquet', index=False)
```

### Step 4: Generate metadata.json

```python
def generate_metadata(goal_num: int, df: pd.DataFrame, series_info: dict) -> dict:
    """Generate metadata.json for an SDG goal."""
    return {
        "source_id": f"un_sdg_{goal_num:02d}",
        "source_name": f"UN SDG Goal {goal_num}",
        "source_url": "https://unstats.un.org/sdgs/indicators/database/",
        "license": "Open Data",
        "description": f"SDG Goal {goal_num} indicators from UN Stats Division",
        "category": "development",
        "topic_tags": ["sdg", f"goal{goal_num}", "sustainable development"],
        "keywords": get_goal_keywords(goal_num),
        "last_updated": "2025-12-29",
        "geographic_level": "country",
        "geographic_coverage": {
            "type": "global",
            "countries": df['loc_id'].nunique()
        },
        "temporal_coverage": {
            "start": int(df['year'].min()),
            "end": int(df['year'].max()),
            "frequency": "annual"
        },
        "metrics": build_metrics_dict(series_info)  # From SeriesDescription
    }
```

### Step 5: Generate reference.json

```python
# reference.json contains conceptual context for LLM
# Structure follows optimized_prompting_strategy.md Tier 4
{
    "source_context": "UN Sustainable Development Goals Framework",
    "goal": {
        "number": 1,
        "name": "No Poverty",
        "full_title": "End poverty in all its forms everywhere",
        "description": "Goal 1 calls for an end to poverty...",
        "targets": [
            {"id": "1.1", "text": "Eradicate extreme poverty..."},
            {"id": "1.2", "text": "Reduce poverty by half..."}
        ],
        "key_indicators": ["SI_POV_DAY1", "SI_POV_EMP1"]
    }
}
```

### Step 6: Regenerate Catalog

```bash
python -m mapmover.catalog_builder
```

---

## Shared Indicators

Some series appear in multiple goals (e.g., SI_POV_EMP1 in Goals 1, 8, 10).

**Approach**: Duplicate them in each goal's parquet file.
- Simpler querying (no cross-file joins)
- Slight storage overhead (~10% duplication)
- Each goal is self-contained

---

## Future: API-Based Updates

### UN SDG API Endpoints

Base URL: `https://unstats.un.org/sdgs/UNSDGAPIV5`

**Useful endpoints**:
- `GET /v1/sdg/Goal/Data/{goalCode}` - All data for a goal
- `GET /v1/sdg/Series/DataCSV/{seriesCode}` - CSV for specific series
- `GET /v1/sdg/Series/List` - List all series codes

**Rate limits**: Unknown - test incrementally

### Update Strategy

```python
def update_sdg_data():
    """Incremental update via API."""

    # 1. Check archive for new quarterly release
    # 2. If new version available, download full CSV
    # 3. Re-run full conversion

    # OR for incremental:
    # 1. Get last update date from metadata.json
    # 2. Query API for changes since that date
    # 3. Update relevant parquet files
```

### Quarterly Refresh Workflow

1. Check https://unstats.un.org/sdgs/indicators/database/archive
2. If new version exists (e.g., 2026_Q1):
   - Download full CSV
   - Re-run converter
   - Update catalog
3. Store version in metadata.json for tracking

---

## Implementation Order

1. **M49 Mapping** - Build and validate country code mapping
2. **Single Goal Test** - Convert Goal 1 as prototype
3. **Validate Output** - Check against existing OWID pattern
4. **Full Conversion** - Process all 17 goals
5. **Reference Docs** - Create reference.json for each goal
6. **Catalog Update** - Regenerate catalog
7. **Integration Test** - Test chat discovery ("show me poverty data")

---

## Testing Checklist

- [ ] M49 -> ISO3 mapping covers 190+ countries
- [ ] Goal 1 parquet matches expected schema
- [ ] Year range correct per goal
- [ ] metadata.json validates against schema
- [ ] reference.json provides LLM-readable context
- [ ] Catalog shows all 17 SDG sources
- [ ] Chat can find SDG data by topic keywords
- [ ] Order executor can query SDG data
- [ ] Map displays SDG indicator correctly

---

## Notes

### Memory Considerations
2GB CSV + pivoting = high memory usage
Process one goal at a time to stay within limits

### Column Names
Use lowercase series codes as column names (e.g., `si_pov_day1`)
Matches existing pattern in other converters

### Missing Data
SDG data has many gaps (not all countries have all indicators)
This is expected - empty box model handles gracefully

---

*Last Updated: 2025-12-29*
