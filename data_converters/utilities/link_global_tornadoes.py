"""
Apply tornado sequence linking to the global tornadoes dataset.

Links tornadoes that are part of the same storm system based on:
- Time window: 1 hour
- Distance: 10 km (end point of A near start point of B)
"""

import pandas as pd
from pathlib import Path
from math import radians, cos, sin, asin, sqrt


def haversine_km(lon1, lat1, lon2, lat2):
    """Calculate distance in km between two points using haversine formula."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * 6371 * asin(sqrt(a))


def link_tornado_sequences(df, time_window_hours=1, distance_km=10):
    """
    Link tornadoes into sequences (same storm system).

    Algorithm:
    - Tornadoes within time_window_hours of each other are candidates
    - If tornado A's end point is within distance_km of tornado B's start point
      AND B starts after A, they are linked
    - Chains are built by walking forward/backward through links
    - Each sequence gets a unique sequence_id based on the earliest tornado
    """
    print("\nLinking tornado sequences...")

    # All records are tornadoes in this dataset
    tornado_count = len(df)
    print(f"  Total tornadoes: {tornado_count:,}")

    # Initialize/reset sequence columns
    df['sequence_id'] = None
    df['sequence_position'] = None
    df['sequence_count'] = None

    if tornado_count == 0:
        return df

    # Get tornadoes with valid coordinates (need end coords for linking)
    tornadoes = df[df['timestamp'].notna()].copy()
    tornadoes = tornadoes[
        tornadoes['latitude'].notna() &
        tornadoes['longitude'].notna() &
        tornadoes['end_latitude'].notna() &
        tornadoes['end_longitude'].notna()
    ].copy()

    print(f"  Tornadoes with full track data: {len(tornadoes):,}")

    # Show breakdown by country
    if 'country' in df.columns:
        for country in df['country'].unique():
            country_df = df[df['country'] == country]
            with_track = country_df[
                country_df['end_latitude'].notna() &
                country_df['end_longitude'].notna()
            ]
            print(f"    {country}: {len(with_track):,} of {len(country_df):,} ({100*len(with_track)/len(country_df):.1f}%)")

    if len(tornadoes) < 2:
        return df

    # Sort by timestamp
    tornadoes = tornadoes.sort_values('timestamp').reset_index(drop=False)
    tornadoes.rename(columns={'index': 'orig_idx'}, inplace=True)

    # Build links: for each tornado, find what follows it
    links = {}
    time_delta = pd.Timedelta(hours=time_window_hours)

    print(f"  Building link graph (window={time_window_hours}h, distance={distance_km}km)...")

    for i, row_a in tornadoes.iterrows():
        # Only check tornadoes that come after this one (within time window)
        candidates = tornadoes[
            (tornadoes['timestamp'] > row_a['timestamp']) &
            (tornadoes['timestamp'] <= row_a['timestamp'] + time_delta)
        ]

        if len(candidates) == 0:
            continue

        # Check if A's end point is near any candidate's start point
        for j, row_b in candidates.iterrows():
            dist = haversine_km(
                row_a['end_longitude'], row_a['end_latitude'],
                row_b['longitude'], row_b['latitude']
            )

            if dist <= distance_km:
                # A -> B link found
                if row_a['event_id'] not in links:
                    links[row_a['event_id']] = row_b['event_id']
                break  # First match wins (closest in time)

    print(f"  Found {len(links):,} direct links")

    if len(links) == 0:
        return df

    # Build reverse lookup
    reverse_links = {v: k for k, v in links.items()}

    # Build sequences by walking chains
    visited = set()
    sequences = []

    # Create event_id -> row lookup (use first occurrence if duplicates)
    event_lookup = {}
    for idx, row in tornadoes.iterrows():
        eid = row['event_id']
        if eid not in event_lookup:
            event_lookup[eid] = row.to_dict()

    for event_id in tornadoes['event_id']:
        if event_id in visited:
            continue

        # Walk backwards to find sequence start
        current = event_id
        while current in reverse_links:
            current = reverse_links[current]

        # Now walk forward to build full sequence
        sequence = [current]
        visited.add(current)

        while current in links:
            next_id = links[current]
            sequence.append(next_id)
            visited.add(next_id)
            current = next_id

        # Only keep sequences with 2+ tornadoes
        if len(sequence) >= 2:
            seq_id = str(sequence[0])
            sequences.append((seq_id, sequence))

    print(f"  Found {len(sequences):,} sequences with 2+ tornadoes")

    # Count total linked tornadoes
    total_linked = sum(len(s[1]) for s in sequences)
    print(f"  Total linked tornadoes: {total_linked:,}")

    # Apply sequence info to dataframe
    for seq_id, event_ids in sequences:
        seq_count = len(event_ids)
        for position, eid in enumerate(event_ids, 1):
            if eid in event_lookup:
                orig_idx = event_lookup[eid]['orig_idx']
                df.loc[orig_idx, 'sequence_id'] = seq_id
                df.loc[orig_idx, 'sequence_position'] = position
                df.loc[orig_idx, 'sequence_count'] = seq_count

    # Summary
    linked_count = df['sequence_id'].notna().sum()
    print(f"\nTornado sequence linking complete:")
    print(f"  Sequences: {len(sequences):,}")
    print(f"  Linked tornadoes: {linked_count:,} ({linked_count/tornado_count*100:.1f}% of all tornadoes)")

    # Check for cross-border sequences
    if 'country' in df.columns and len(sequences) > 0:
        cross_border = 0
        for seq_id, event_ids in sequences:
            countries = df[df['event_id'].isin(event_ids)]['country'].unique()
            if len(countries) > 1:
                cross_border += 1
        if cross_border > 0:
            print(f"  Cross-border sequences (USA-CAN): {cross_border}")

    # Show example sequences
    if len(sequences) > 0:
        print(f"\n  Example sequences:")
        for seq_id, event_ids in sequences[:3]:
            print(f"    Sequence {seq_id}: {len(event_ids)} tornadoes")

    return df


def main():
    data_path = Path("C:/Users/Bryan/Desktop/county-map-data")
    events_path = data_path / "global" / "tornadoes" / "events.parquet"

    print(f"Loading global tornadoes from {events_path}")
    df = pd.read_parquet(events_path)
    print(f"Loaded {len(df):,} tornadoes")

    # Show current state
    existing_sequences = df['sequence_id'].notna().sum()
    print(f"Tornadoes with existing sequence info: {existing_sequences:,}")

    # Apply linking algorithm
    df = link_tornado_sequences(df, time_window_hours=1, distance_km=10)

    # Save updated dataset
    print(f"\nSaving updated dataset to {events_path}")
    df.to_parquet(events_path, index=False, compression='zstd')

    # Report file size
    size_mb = events_path.stat().st_size / (1024 * 1024)
    print(f"Saved: {size_mb:.2f} MB")

    print("\nDone!")


if __name__ == "__main__":
    main()
