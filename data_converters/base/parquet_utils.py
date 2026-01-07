"""
Shared parquet utilities for data converters.

Includes:
- Standardized parquet saving
- Schema helpers
- Compression settings
"""
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path


# =============================================================================
# Standard Parquet Saving
# =============================================================================

def save_parquet(df, output_path, schema=None, compression='snappy', description=None):
    """Save DataFrame to parquet with standard settings.

    Args:
        df: pandas DataFrame to save
        output_path: Path for output file
        schema: Optional pyarrow schema (inferred if not provided)
        compression: Compression codec (default 'snappy')
        description: Description for logging (default: filename)

    Returns:
        File size in MB
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    desc = description or output_path.name
    print(f"  Saving {desc}...")

    if schema:
        table = pa.Table.from_pandas(df, schema=schema)
    else:
        table = pa.Table.from_pandas(df, preserve_index=False)

    pq.write_table(table, output_path, compression=compression)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"    Saved: {output_path}")
    print(f"    Size: {size_mb:.2f} MB, {len(df):,} rows")

    return size_mb


# =============================================================================
# Common Schema Definitions
# =============================================================================

def events_schema(
    time_col='event_date',
    include_radius=True,
    include_depth=False,
    extra_fields=None
):
    """Create standard schema for events.parquet.

    Args:
        time_col: Name of timestamp column
        include_radius: Include felt_radius_km and damage_radius_km
        include_depth: Include depth_km column
        extra_fields: List of (name, type) tuples for additional fields

    Returns:
        pyarrow.Schema
    """
    fields = [
        ('event_id', pa.string()),
        ('loc_id', pa.string()),
        (time_col, pa.timestamp('us', tz='UTC')),
        ('year', pa.int32()),
        ('lat', pa.float32()),
        ('lon', pa.float32()),
        ('magnitude', pa.float32()),
    ]

    if include_depth:
        fields.append(('depth_km', pa.float32()))

    if include_radius:
        fields.append(('felt_radius_km', pa.float32()))
        fields.append(('damage_radius_km', pa.float32()))

    fields.extend([
        ('place', pa.string()),
    ])

    if extra_fields:
        fields.extend(extra_fields)

    return pa.schema(fields)


def aggregates_schema(
    count_col='event_count',
    include_magnitude_stats=True,
    extra_fields=None
):
    """Create standard schema for aggregates parquet.

    Args:
        count_col: Name of count column
        include_magnitude_stats: Include max/mean/median magnitude
        extra_fields: List of (name, type) tuples for additional fields

    Returns:
        pyarrow.Schema
    """
    fields = [
        ('loc_id', pa.string()),
        ('year', pa.int32()),
        (count_col, pa.int32()),
    ]

    if include_magnitude_stats:
        fields.extend([
            ('max_magnitude', pa.float32()),
            ('mean_magnitude', pa.float32()),
            ('median_magnitude', pa.float32()),
        ])

    if extra_fields:
        fields.extend(extra_fields)

    return pa.schema(fields)


# =============================================================================
# Output Path Helpers
# =============================================================================

def get_output_paths(country, source_id, base_dir="C:/Users/Bryan/Desktop/county-map-data"):
    """Get standard output paths for a converter.

    Args:
        country: Country code ('USA', 'CAN', 'AUS', 'GLOBAL')
        source_id: Source identifier
        base_dir: Base data directory

    Returns:
        dict with paths: {
            'dir': output directory,
            'events': events.parquet path,
            'aggregates': {COUNTRY}.parquet path,
            'metadata': metadata.json path
        }
    """
    base = Path(base_dir)

    if country == 'GLOBAL':
        output_dir = base / "global" / source_id
        agg_name = "all_countries.parquet"
    else:
        output_dir = base / "countries" / country / source_id
        agg_name = f"{country}.parquet"

    return {
        'dir': output_dir,
        'events': output_dir / "events.parquet",
        'aggregates': output_dir / agg_name,
        'metadata': output_dir / "metadata.json",
    }
