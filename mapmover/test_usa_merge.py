"""Test USA merge logic before running full import."""

from process_gadm import *
import sqlite3

# Load US FIPS mapping
us_fips_map = load_us_fips_mapping()

# Connect to GADM
conn = sqlite3.connect(GADM_FILE)

print("Processing USA...")
records = process_country(conn, "USA", us_fips_map)
print(f"  Got {len(records)} records from GADM")

# Create DataFrame
df = pd.DataFrame(records)
df = df.sort_values(["admin_level", "loc_id"])

# Remove placeholder levels
original_count = len(df)
df, removed_levels = remove_placeholder_levels(df)
if removed_levels:
    print(f"  Removed placeholder levels: {removed_levels} ({original_count - len(df)} rows)")

# Merge with existing
output_file = OUTPUT_PATH / "USA.parquet"
if output_file.exists():
    existing_df = pd.read_parquet(output_file)
    print(f"  Existing parquet has {len(existing_df)} rows")
    df, merge_stats = merge_with_existing(df, existing_df)
    print(f"  Merged: {merge_stats['preserved']} preserved, {merge_stats['added']} added, {merge_stats['filled']} filled")
else:
    print("  No existing USA.parquet found - will create new")

# Show level breakdown
print("  Level breakdown after merge:")
for level in sorted(df["admin_level"].unique()):
    level_df = df[df["admin_level"] == level]
    with_geom = level_df["geometry"].notna().sum()
    print(f"    Level {level}: {len(level_df)} rows, {with_geom} with geometry")

# Convert types
df['admin_level'] = df['admin_level'].astype('int8')
if 'has_polygon' in df.columns:
    df['has_polygon'] = df['has_polygon'].astype(bool)

# Save
df.to_parquet(output_file, index=False)
print(f"  Saved to {output_file}")
conn.close()
