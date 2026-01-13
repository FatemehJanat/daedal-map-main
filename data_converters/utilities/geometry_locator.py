"""
Geometry Locator - Assign loc_ids to geographic features based on their extent.

This utility analyzes polygon geometries (fire perimeters, flood extents, etc.)
and determines the appropriate loc_id based on which administrative boundaries
they intersect, following the sibling layer rules from GEOMETRY.md.

Sibling Rules:
- Feature within 1 county -> child of that county
- Feature crosses counties in 1 state -> sibling at state level (level 2)
- Feature crosses states in 1 country -> sibling at country level (level 1)
- Feature crosses countries -> global entity (level 0)

Optimizations:
- R-tree spatial indexing for fast candidate lookup
- Bounding box pre-filtering
- Hierarchical pruning (country -> state -> county)
- Multiprocessing for batch processing
- Centroid-first for small features
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import numpy as np

# Try to import spatial libraries
try:
    from shapely.geometry import shape, Point, box
    from shapely.ops import unary_union
    from shapely import wkb
    from rtree import index as rtree_index
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False
    print("Warning: shapely or rtree not available. Install with: pip install shapely rtree")

try:
    import pyarrow.parquet as pq
    import pandas as pd
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False
    print("Warning: pyarrow not available. Install with: pip install pyarrow")


import time
import multiprocessing as mp
from functools import partial

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Incremental save interval
SAVE_INTERVAL = 1000

# Global locator for multiprocessing workers
_worker_locator = None


def _init_worker(geometry_dir: str, event_type: str):
    """Initialize locator in worker process."""
    global _worker_locator
    _worker_locator = GeometryLocator(geometry_dir, event_type)


def _locate_fire_worker(fire_data: Dict) -> Dict:
    """
    Worker function to locate a single fire.
    Uses global _worker_locator initialized by _init_worker.
    Returns dict with location results (picklable).
    """
    global _worker_locator

    try:
        result = _worker_locator.locate(
            fire_data.get('perimeter', ''),
            str(fire_data.get('event_id', '')),
            fire_data.get('latitude'),
            fire_data.get('longitude')
        )
        return {
            'event_id': fire_data.get('event_id'),
            'loc_id': result.loc_id,
            'parent_loc_id': result.parent_loc_id,
            'sibling_level': result.admin_level,
            'iso3': result.country_iso3,
            'loc_confidence': result.confidence
        }
    except Exception as e:
        return {
            'event_id': fire_data.get('event_id'),
            'loc_id': f"FIRE-{fire_data.get('event_id', '')}",
            'parent_loc_id': '',
            'sibling_level': 0,
            'iso3': '',
            'loc_confidence': 0.0
        }


@dataclass
class LocationResult:
    """Result of locating a geometry within admin boundaries."""
    loc_id: str              # The assigned loc_id (e.g., "CAN-BC-FIRE-12345")
    parent_loc_id: str       # Parent location (e.g., "CAN-BC")
    admin_level: int         # Level where this becomes a sibling (1, 2, or 3)
    intersected: List[str]   # All loc_ids the geometry intersects
    country_iso3: str        # Country code
    confidence: float        # 0-1, how confident we are in the assignment


class BoundaryIndex:
    """
    Spatial index for administrative boundaries.
    Uses R-tree for fast bounding box queries.
    """

    def __init__(self, geometry_dir: str):
        """
        Initialize the boundary index.

        Args:
            geometry_dir: Path to geometry directory (e.g., county-map-data/geometry/)
        """
        if not SPATIAL_AVAILABLE:
            raise ImportError("shapely and rtree required for BoundaryIndex")
        if not PYARROW_AVAILABLE:
            raise ImportError("pyarrow required for BoundaryIndex")

        self.geometry_dir = Path(geometry_dir)
        self.country_index = None  # R-tree for countries
        self.country_bounds = {}   # iso3 -> (minx, miny, maxx, maxy)
        self.country_geoms = {}    # iso3 -> shapely geometry
        self._country_caches = {}  # iso3 -> loaded admin boundaries

        self._build_country_index()

    def _build_country_index(self):
        """Build spatial index for country-level boundaries."""
        logger.info("Building country spatial index...")

        # Load global.csv for country boundaries
        global_csv = self.geometry_dir / "global.csv"
        if not global_csv.exists():
            raise FileNotFoundError(f"global.csv not found at {global_csv}")

        df = pd.read_csv(global_csv)

        # Create R-tree index
        self.country_index = rtree_index.Index()

        for idx, row in df.iterrows():
            iso3 = row.get('loc_id') or row.get('iso_a3') or row.get('ISO_A3')
            if not iso3 or pd.isna(iso3):
                continue

            geom_str = row.get('geometry')
            if not geom_str or pd.isna(geom_str):
                continue

            try:
                geom = shape(json.loads(geom_str))
                bounds = geom.bounds  # (minx, miny, maxx, maxy)

                self.country_bounds[iso3] = bounds
                self.country_geoms[iso3] = geom
                self.country_index.insert(idx, bounds, obj=iso3)
            except Exception as e:
                logger.warning(f"Failed to parse geometry for {iso3}: {e}")

        logger.info(f"Indexed {len(self.country_geoms)} countries")

    def _load_country_boundaries(self, iso3: str) -> Optional[Dict]:
        """
        Load admin boundaries for a specific country with R-tree indexes.

        Returns dict with:
            - 'df': the DataFrame with parsed geometries
            - 'rtree_1': R-tree index for admin level 1 (states)
            - 'rtree_2': R-tree index for admin level 2 (counties)
        """
        if iso3 in self._country_caches:
            return self._country_caches[iso3]

        parquet_path = self.geometry_dir / f"{iso3}.parquet"
        if not parquet_path.exists():
            logger.warning(f"No parquet file for {iso3}")
            return None

        try:
            df = pd.read_parquet(parquet_path)

            # Parse geometries if they're strings
            if 'geometry' in df.columns and len(df) > 0:
                sample = df['geometry'].iloc[0]
                if isinstance(sample, str):
                    df['_geom'] = df['geometry'].apply(
                        lambda g: shape(json.loads(g)) if g and not pd.isna(g) else None
                    )
                    df['_bounds'] = df['_geom'].apply(
                        lambda g: g.bounds if g else None
                    )

            # Build R-tree indexes for each admin level
            cache_entry = {'df': df, 'rtrees': {}}

            for admin_level in [1, 2, 3]:
                level_df = df[df['admin_level'] == admin_level]
                if len(level_df) == 0:
                    continue

                # Create R-tree for this level
                rtree = rtree_index.Index()
                for idx, row in level_df.iterrows():
                    bounds = row.get('_bounds')
                    if bounds is not None:
                        # Store the DataFrame index as the object
                        rtree.insert(idx, bounds, obj=idx)

                cache_entry['rtrees'][admin_level] = rtree

            self._country_caches[iso3] = cache_entry
            return cache_entry
        except Exception as e:
            logger.error(f"Failed to load {iso3}.parquet: {e}")
            return None

    def find_containing_countries(self, geom) -> List[str]:
        """
        Find which countries a geometry intersects.

        Args:
            geom: Shapely geometry (Polygon/MultiPolygon)

        Returns:
            List of ISO3 country codes
        """
        bounds = geom.bounds
        candidates = list(self.country_index.intersection(bounds, objects=True))

        intersecting = []
        for item in candidates:
            iso3 = item.object
            country_geom = self.country_geoms.get(iso3)
            if country_geom and geom.intersects(country_geom):
                intersecting.append(iso3)

        return intersecting

    def find_containing_admin_units(
        self,
        geom,
        iso3: str,
        admin_level: int
    ) -> List[Dict]:
        """
        Find which admin units at a given level a geometry intersects.
        Uses R-tree spatial index for O(log n) candidate lookup.

        Args:
            geom: Shapely geometry
            iso3: Country code
            admin_level: Admin level to check (1=state, 2=county)

        Returns:
            List of dicts with loc_id, name, etc.
        """
        cache = self._load_country_boundaries(iso3)
        if cache is None:
            return []

        df = cache['df']
        rtrees = cache['rtrees']

        # Check if we have an R-tree for this level
        if admin_level not in rtrees:
            # No R-tree means no data at this level
            return []

        rtree = rtrees[admin_level]
        bounds = geom.bounds

        # R-tree query for candidates - O(log n) instead of O(n)
        candidates = list(rtree.intersection(bounds, objects=True))

        if not candidates:
            return []

        intersecting = []
        for item in candidates:
            df_idx = item.object  # DataFrame index stored as object
            row = df.loc[df_idx]

            # Detailed intersection check
            row_geom = row.get('_geom')
            if row_geom and geom.intersects(row_geom):
                intersecting.append({
                    'loc_id': row['loc_id'],
                    'name': row.get('name', ''),
                    'parent_id': row.get('parent_id', ''),
                    'admin_level': admin_level
                })

        return intersecting

    def clear_country_cache(self, iso3: str = None):
        """
        Clear cached country boundaries to free memory.

        Args:
            iso3: Specific country to clear, or None to clear all
        """
        if iso3:
            if iso3 in self._country_caches:
                del self._country_caches[iso3]
        else:
            self._country_caches.clear()

    def point_to_country(self, lon: float, lat: float) -> Optional[str]:
        """
        Fast lookup: which country contains this point?
        Uses R-tree bbox first, then precise check.

        Args:
            lon: Longitude
            lat: Latitude

        Returns:
            ISO3 country code or None
        """
        from shapely.geometry import Point
        point = Point(lon, lat)

        # R-tree bbox query
        candidates = list(self.country_index.intersection((lon, lat, lon, lat), objects=True))

        for item in candidates:
            iso3 = item.object
            country_geom = self.country_geoms.get(iso3)
            if country_geom and country_geom.contains(point):
                return iso3

        return None

    def points_to_countries_vectorized(self, lons: np.ndarray, lats: np.ndarray) -> List[Optional[str]]:
        """
        Vectorized lookup: which country contains each point?
        Much faster than calling point_to_country in a loop.

        Args:
            lons: Array of longitudes
            lats: Array of latitudes

        Returns:
            List of ISO3 country codes (or None for ocean/unknown)
        """
        import numpy as np
        from shapely.geometry import Point
        from shapely.prepared import prep

        n_points = len(lons)
        results = [None] * n_points

        # Prepare geometries for faster contains checks
        prepared_geoms = {iso3: prep(geom) for iso3, geom in self.country_geoms.items()}

        # Group points by their R-tree bbox candidates
        # This reduces redundant geometry checks
        country_candidates = {}  # iso3 -> list of point indices

        for i in range(n_points):
            lon, lat = lons[i], lats[i]
            candidates = list(self.country_index.intersection((lon, lat, lon, lat), objects=True))

            for item in candidates:
                iso3 = item.object
                if iso3 not in country_candidates:
                    country_candidates[iso3] = []
                country_candidates[iso3].append(i)

        # Process country by country (more cache-friendly)
        for iso3, point_indices in country_candidates.items():
            prepared_geom = prepared_geoms.get(iso3)
            if not prepared_geom:
                continue

            for i in point_indices:
                # Skip if already assigned
                if results[i] is not None:
                    continue

                point = Point(lons[i], lats[i])
                if prepared_geom.contains(point):
                    results[i] = iso3

        return results

    def get_cache_size(self) -> int:
        """Return number of countries currently cached."""
        return len(self._country_caches)

    def get_neighboring_countries(self, iso3: str) -> List[str]:
        """
        Get countries that share a border with the given country.
        Uses R-tree for fast candidate lookup, then precise intersection check.

        Args:
            iso3: Country code

        Returns:
            List of neighboring country codes
        """
        if iso3 not in self.country_geoms:
            return []

        country_geom = self.country_geoms[iso3]
        bounds = country_geom.bounds

        # R-tree query for candidates
        candidates = list(self.country_index.intersection(bounds, objects=True))

        neighbors = []
        for item in candidates:
            neighbor_iso3 = item.object
            if neighbor_iso3 == iso3:
                continue

            neighbor_geom = self.country_geoms.get(neighbor_iso3)
            if neighbor_geom and country_geom.touches(neighbor_geom) or country_geom.intersects(neighbor_geom):
                neighbors.append(neighbor_iso3)

        return neighbors

    def build_adjacency_graph(self) -> Dict[str, List[str]]:
        """
        Build a graph of which countries neighbor each other.
        Computed once, then cached.

        Returns:
            Dict mapping iso3 -> list of neighboring iso3 codes
        """
        if hasattr(self, '_adjacency_graph'):
            return self._adjacency_graph

        logger.info("Building country adjacency graph...")
        adjacency = {}

        for iso3 in self.country_geoms.keys():
            adjacency[iso3] = self.get_neighboring_countries(iso3)

        self._adjacency_graph = adjacency
        total_edges = sum(len(v) for v in adjacency.values()) // 2
        logger.info(f"Adjacency graph: {len(adjacency)} countries, {total_edges} borders")

        return adjacency


def get_dfs_country_order(
    countries_with_fires: List[str],
    fire_counts: Dict[str, int],
    adjacency: Dict[str, List[str]]
) -> List[str]:
    """
    Get DFS traversal order for countries, starting with biggest.

    Strategy:
    1. Start with country that has most fires
    2. DFS to neighbors (prioritizing neighbors with more fires)
    3. When branch exhausted, pop to next biggest unvisited country
    4. Repeat until all countries visited

    This keeps neighboring countries processed together, so their
    geometries stay cached for cross-border fire checks.

    Args:
        countries_with_fires: List of country codes that have fires
        fire_counts: Dict of iso3 -> fire count
        adjacency: Dict of iso3 -> list of neighboring iso3

    Returns:
        Ordered list of country codes for processing
    """
    # Filter to only countries with fires
    countries_set = set(countries_with_fires)
    visited = set()
    order = []

    # Sort by fire count descending for picking start points
    sorted_by_fires = sorted(
        [c for c in countries_with_fires if c is not None],
        key=lambda x: fire_counts.get(x, 0),
        reverse=True
    )

    def dfs(iso3):
        if iso3 in visited or iso3 not in countries_set:
            return
        visited.add(iso3)
        order.append(iso3)

        # Get neighbors that have fires, sorted by fire count (biggest first)
        neighbors = adjacency.get(iso3, [])
        neighbors_with_fires = [n for n in neighbors if n in countries_set and n not in visited]
        neighbors_with_fires.sort(key=lambda x: fire_counts.get(x, 0), reverse=True)

        for neighbor in neighbors_with_fires:
            dfs(neighbor)

    # Start DFS from each unvisited country (biggest first)
    for start_country in sorted_by_fires:
        if start_country not in visited:
            dfs(start_country)

    # Add None/ocean fires at the end if present
    if None in countries_set:
        order.append(None)

    return order


class GeometryLocator:
    """
    Main class for assigning loc_ids to geographic features.
    """

    def __init__(self, geometry_dir: str, event_type: str = "FIRE"):
        """
        Initialize the geometry locator.

        Args:
            geometry_dir: Path to geometry directory
            event_type: Type of event (FIRE, FLOOD, etc.) for loc_id generation
        """
        self.boundary_index = BoundaryIndex(geometry_dir)
        self.event_type = event_type.upper()

    def clear_country_cache(self, iso3: str = None):
        """Clear cached country boundaries to free memory."""
        self.boundary_index.clear_country_cache(iso3)

    def point_to_country(self, lon: float, lat: float) -> Optional[str]:
        """Fast lookup: which country contains this point?"""
        return self.boundary_index.point_to_country(lon, lat)

    def get_cache_size(self) -> int:
        """Return number of countries currently cached."""
        return self.boundary_index.get_cache_size()

    def points_to_countries_vectorized(self, lons: np.ndarray, lats: np.ndarray) -> List[Optional[str]]:
        """Vectorized lookup: which country contains each point?"""
        return self.boundary_index.points_to_countries_vectorized(lons, lats)

    def build_adjacency_graph(self) -> Dict[str, List[str]]:
        """Build country adjacency graph for DFS traversal."""
        return self.boundary_index.build_adjacency_graph()

    def locate(
        self,
        geom_geojson: str,
        event_id: str,
        centroid_lat: float = None,
        centroid_lon: float = None
    ) -> LocationResult:
        """
        Determine the loc_id for a geometry based on admin boundaries.

        Args:
            geom_geojson: GeoJSON string of the geometry
            event_id: Unique event identifier
            centroid_lat: Optional centroid latitude (for optimization)
            centroid_lon: Optional centroid longitude (for optimization)

        Returns:
            LocationResult with assigned loc_id and metadata
        """
        try:
            geom = shape(json.loads(geom_geojson))
        except Exception as e:
            logger.error(f"Failed to parse geometry for {event_id}: {e}")
            return LocationResult(
                loc_id=f"{self.event_type}-{event_id}",
                parent_loc_id="",
                admin_level=0,
                intersected=[],
                country_iso3="",
                confidence=0.0
            )

        # Find containing countries
        countries = self.boundary_index.find_containing_countries(geom)

        if len(countries) == 0:
            # No country found - might be ocean or data issue
            # Try centroid if provided
            if centroid_lat is not None and centroid_lon is not None:
                point = Point(centroid_lon, centroid_lat)
                countries = self.boundary_index.find_containing_countries(point.buffer(0.1))

            if len(countries) == 0:
                return LocationResult(
                    loc_id=f"{self.event_type}-{event_id}",
                    parent_loc_id="",
                    admin_level=0,
                    intersected=[],
                    country_iso3="",
                    confidence=0.3
                )

        if len(countries) > 1:
            # Crosses country borders - global entity
            return LocationResult(
                loc_id=f"{self.event_type}-{event_id}",
                parent_loc_id="",
                admin_level=0,
                intersected=countries,
                country_iso3=countries[0],  # Primary country
                confidence=0.9
            )

        # Single country - drill down
        iso3 = countries[0]

        # Check state level (admin_level 1)
        states = self.boundary_index.find_containing_admin_units(geom, iso3, 1)

        if len(states) == 0:
            # No state data - use country level
            return LocationResult(
                loc_id=f"{iso3}-{self.event_type}-{event_id}",
                parent_loc_id=iso3,
                admin_level=1,
                intersected=[iso3],
                country_iso3=iso3,
                confidence=0.7
            )

        if len(states) > 1:
            # Crosses state borders - country-level sibling
            return LocationResult(
                loc_id=f"{iso3}-{self.event_type}-{event_id}",
                parent_loc_id=iso3,
                admin_level=1,
                intersected=[s['loc_id'] for s in states],
                country_iso3=iso3,
                confidence=0.9
            )

        # Single state - drill to county level
        state_loc_id = states[0]['loc_id']

        # Check county level (admin_level 2)
        counties = self.boundary_index.find_containing_admin_units(geom, iso3, 2)

        # Filter to counties within this state
        state_counties = [c for c in counties if c['loc_id'].startswith(state_loc_id)]

        if len(state_counties) == 0:
            # No county data - use state level
            return LocationResult(
                loc_id=f"{state_loc_id}-{self.event_type}-{event_id}",
                parent_loc_id=state_loc_id,
                admin_level=2,
                intersected=[state_loc_id],
                country_iso3=iso3,
                confidence=0.7
            )

        if len(state_counties) > 1:
            # Crosses county borders - state-level sibling
            return LocationResult(
                loc_id=f"{state_loc_id}-{self.event_type}-{event_id}",
                parent_loc_id=state_loc_id,
                admin_level=2,
                intersected=[c['loc_id'] for c in state_counties],
                country_iso3=iso3,
                confidence=0.9
            )

        # Single county - county-level entity
        county_loc_id = state_counties[0]['loc_id']
        return LocationResult(
            loc_id=f"{county_loc_id}-{self.event_type}-{event_id}",
            parent_loc_id=county_loc_id,
            admin_level=3,
            intersected=[county_loc_id],
            country_iso3=iso3,
            confidence=0.95
        )

    def locate_batch(
        self,
        features: List[Dict],
        event_id_field: str = 'event_id',
        geometry_field: str = 'perimeter',
        lat_field: str = 'latitude',
        lon_field: str = 'longitude',
        num_workers: int = None
    ) -> List[LocationResult]:
        """
        Locate multiple features in parallel.

        Args:
            features: List of feature dicts with geometry and event_id
            event_id_field: Name of the event_id field
            geometry_field: Name of the geometry field
            lat_field: Name of the latitude field
            lon_field: Name of the longitude field
            num_workers: Number of parallel workers (default: CPU count)

        Returns:
            List of LocationResults in same order as input
        """
        if num_workers is None:
            num_workers = max(1, multiprocessing.cpu_count() - 1)

        results = [None] * len(features)

        # For small batches, process sequentially
        if len(features) < 100 or num_workers == 1:
            for i, feature in enumerate(features):
                results[i] = self.locate(
                    feature.get(geometry_field, ''),
                    feature.get(event_id_field, str(i)),
                    feature.get(lat_field),
                    feature.get(lon_field)
                )
            return results

        # For large batches, process in chunks (can't pickle BoundaryIndex for multiprocessing)
        chunk_size = max(100, len(features) // num_workers)

        for i in range(0, len(features), chunk_size):
            chunk = features[i:i + chunk_size]
            for j, feature in enumerate(chunk):
                results[i + j] = self.locate(
                    feature.get(geometry_field, ''),
                    feature.get(event_id_field, str(i + j)),
                    feature.get(lat_field),
                    feature.get(lon_field)
                )

        return results


def load_existing_progress(output_file: Path) -> set:
    """
    Load existing partial progress from output file.
    Returns set of already-processed event_ids.
    """
    if not output_file.exists():
        return set()

    try:
        df = pd.read_parquet(output_file)
        processed_ids = set(df['event_id'].astype(str).unique())
        print(f"  Resuming: Found {len(processed_ids):,} fires already processed", flush=True)
        return processed_ids
    except Exception as e:
        print(f"  Warning: Could not read existing file: {e}", flush=True)
        return set()


def save_incremental(output_file: Path, df: pd.DataFrame):
    """Save results to parquet file."""
    if len(df) == 0:
        return

    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_file, index=False, compression='snappy')


def process_wildfire_year(
    fires_parquet: str,
    geometry_dir: str,
    output_path: str = None,
    year: int = None,
    force: bool = False,
    num_workers: int = None
) -> pd.DataFrame:
    """
    Process a year of wildfire data to add loc_ids.

    Uses MULTIPROCESSING for speed:
    1. Bucket fires by country using lat/lon centroid (single-threaded, fast)
    2. Process all fires in parallel using worker pool
    3. Each worker has its own GeometryLocator with R-tree indexes
    4. Incremental saves for crash recovery

    Features:
    - Multiprocessing: Uses all available CPUs
    - Resume capability: Detects partial files and continues
    - Incremental saves: After each batch for crash recovery
    - Progress display: Shows rate, ETA, and worker count
    - R-tree indexing: O(log n) admin unit lookups

    Args:
        fires_parquet: Path to fires parquet file
        geometry_dir: Path to geometry directory
        output_path: Optional output path for enriched parquet
        year: Year being processed (for logging)
        force: If True, reprocess even if output exists
        num_workers: Number of parallel workers (default: CPU count - 1)

    Returns:
        DataFrame with loc_id columns added
    """
    print(f"\n=== Processing wildfires{f' for {year}' if year else ''} ===", flush=True)

    output_file = Path(output_path) if output_path else None

    # Load fires
    df = pd.read_parquet(fires_parquet)
    total_fires = len(df)
    print(f"  Total fires in file: {total_fires:,}", flush=True)

    # Check for existing progress (resume capability)
    existing_df = None
    processed_ids = set()

    if output_file and output_file.exists() and not force:
        processed_ids = load_existing_progress(output_file)
        if processed_ids:
            # Load existing data to merge with new results
            existing_df = pd.read_parquet(output_file)

            # Filter out already-processed fires
            df = df[~df['event_id'].astype(str).isin(processed_ids)]

            if len(df) == 0:
                print(f"  Year {year}: All fires already processed", flush=True)
                return existing_df

            print(f"  Remaining fires to process: {len(df):,}", flush=True)

    # Set up multiprocessing
    if num_workers is None:
        num_workers = max(1, mp.cpu_count() - 1)

    fires_to_process = len(df)
    start_time = time.time()

    print(f"  Using {num_workers} worker processes", flush=True)

    # Prepare fire data for workers
    fire_data_list = df.to_dict('records')

    # Process in batches with multiprocessing
    BATCH_SIZE = 5000  # Process 5000 fires per batch for progress updates
    results_data = []

    with mp.Pool(
        processes=num_workers,
        initializer=_init_worker,
        initargs=(geometry_dir, "FIRE")
    ) as pool:
        for batch_start in range(0, fires_to_process, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, fires_to_process)
            batch = fire_data_list[batch_start:batch_end]

            # Process batch in parallel
            batch_results = pool.map(_locate_fire_worker, batch)

            # Merge results with original data
            for i, loc_result in enumerate(batch_results):
                row = batch[i].copy()
                row['loc_id'] = loc_result['loc_id']
                row['parent_loc_id'] = loc_result['parent_loc_id']
                row['sibling_level'] = loc_result['sibling_level']
                row['iso3'] = loc_result['iso3']
                row['loc_confidence'] = loc_result['loc_confidence']
                results_data.append(row)

            # Progress display
            fires_processed = batch_end
            elapsed = time.time() - start_time
            rate = fires_processed / elapsed if elapsed > 0 else 0
            remaining = (fires_to_process - fires_processed) / rate if rate > 0 else 0

            print(f"  Processed {fires_processed:,}/{fires_to_process:,} "
                  f"({rate:.1f}/sec, ~{remaining/60:.1f} min left)", flush=True)

            # Incremental save after each batch
            if output_file and results_data:
                new_df = pd.DataFrame(results_data)
                if existing_df is not None:
                    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                else:
                    combined_df = new_df
                save_incremental(output_file, combined_df)
                print(f"    [Saved checkpoint: {len(combined_df):,} total fires]", flush=True)

    # Final results
    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed/60:.1f} minutes", flush=True)

    # Build final dataframe
    result_df = pd.DataFrame(results_data)
    if existing_df is not None:
        result_df = pd.concat([existing_df, result_df], ignore_index=True)

    # Final save
    if output_file:
        save_incremental(output_file, result_df)
        file_size = output_file.stat().st_size / 1024 / 1024
        print(f"  Saved: {output_file.name} ({file_size:.2f} MB)", flush=True)

    print(f"  Total fires with loc_ids: {len(result_df):,}", flush=True)

    return result_df


def process_all_years(
    input_dir: str,
    geometry_dir: str,
    output_dir: str,
    force: bool = False,
    num_workers: int = None
):
    """
    Process all available wildfire years.
    Most recent years first for resume capability.
    """
    import traceback

    if num_workers is None:
        num_workers = max(1, mp.cpu_count() - 1)

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all year files
    year_files = sorted(input_path.glob('fires_*.parquet'), reverse=True)

    if not year_files:
        print(f"No fire files found in {input_dir}", flush=True)
        return

    years = [int(f.stem.split('_')[1]) for f in year_files]
    print(f"Found {len(years)} years: {years[0]} to {years[-1]} (processing newest first)", flush=True)
    print(f"Output: {output_path}", flush=True)
    print(f"Workers: {num_workers} (multiprocessing enabled)", flush=True)
    print(flush=True)

    total_start = time.time()
    total_processed = 0

    for year_file in year_files:
        year = int(year_file.stem.split('_')[1])
        output_file = output_path / f'fires_{year}_enriched.parquet'

        try:
            result_df = process_wildfire_year(
                str(year_file),
                geometry_dir,
                str(output_file),
                year,
                force,
                num_workers
            )
            total_processed += len(result_df)
        except Exception as e:
            print(f"  ERROR processing year {year}: {e}", flush=True)
            traceback.print_exc()
            continue

    total_elapsed = time.time() - total_start
    print(f"\n=== All years complete ===", flush=True)
    print(f"  Total fires processed: {total_processed:,}", flush=True)
    print(f"  Total time: {total_elapsed/3600:.1f} hours", flush=True)


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Assign loc_ids to wildfire features based on admin boundaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all years (newest first, with resume capability)
  python geometry_locator.py --all --geometry-dir /path/to/geometry

  # Process single year
  python geometry_locator.py fires_2023.parquet --geometry-dir /path/to/geometry -o fires_2023_enriched.parquet

  # Test with sample
  python geometry_locator.py fires_2023.parquet --geometry-dir /path/to/geometry --sample 5

  # Force reprocess (ignore existing progress)
  python geometry_locator.py --all --geometry-dir /path/to/geometry --force

Features:
  - Multiprocessing: Uses all available CPUs for parallel processing
  - R-tree spatial indexing for fast boundary lookups
  - Resume capability: Continues from partial files if interrupted
  - Incremental saves: Every 5000 fires for crash recovery
  - Progress display: Rate, ETA, and counts
        """
    )
    parser.add_argument("input", nargs='?', help="Input parquet file (or use --all)")
    parser.add_argument("--geometry-dir", required=True, help="Path to geometry directory")
    parser.add_argument("--output", "-o", help="Output parquet file")
    parser.add_argument("--output-dir", help="Output directory for --all mode")
    parser.add_argument("--event-type", default="FIRE", help="Event type (FIRE, FLOOD, etc.)")
    parser.add_argument("--year", type=int, help="Year being processed (for logging)")
    parser.add_argument("--sample", type=int, help="Process only N random samples (test mode)")
    parser.add_argument("--all", action='store_true', help="Process all years in input directory")
    parser.add_argument("--force", action='store_true', help="Reprocess even if output exists")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes (default: CPU count - 1)")

    args = parser.parse_args()

    # Required for Windows multiprocessing
    mp.freeze_support()

    if args.all:
        # Process all years
        if not args.input:
            # Default path for wildfires
            args.input = "C:/Users/Bryan/Desktop/county-map-data/global/wildfires/by_year"
        if not args.output_dir:
            args.output_dir = "C:/Users/Bryan/Desktop/county-map-data/global/wildfires/by_year_enriched"

        process_all_years(
            args.input,
            args.geometry_dir,
            args.output_dir,
            args.force,
            args.workers
        )

    elif args.sample:
        # Sample mode - test with N random fires
        df = pd.read_parquet(args.input)
        df = df.sample(min(args.sample, len(df)))

        locator = GeometryLocator(args.geometry_dir, event_type=args.event_type)
        features = df.to_dict('records')
        results = locator.locate_batch(features)

        for i, (feat, result) in enumerate(zip(features, results)):
            print(f"\n{i+1}. Event {feat.get('event_id', '?')}")
            print(f"   loc_id: {result.loc_id}")
            print(f"   parent: {result.parent_loc_id}")
            print(f"   level: {result.admin_level}")
            print(f"   country: {result.country_iso3}")
            print(f"   intersected: {result.intersected[:5]}...")
            print(f"   confidence: {result.confidence:.2f}")

    elif args.input:
        # Single file mode
        process_wildfire_year(
            args.input,
            args.geometry_dir,
            args.output,
            args.year,
            args.force,
            args.workers
        )

    else:
        num_cpus = mp.cpu_count()
        parser.print_help()
        print("\n" + "="*60)
        print("Geometry Locator - Assign loc_ids to geographic features")
        print("="*60)
        print(f"\nMultiprocessing: {num_cpus - 1} workers (your system has {num_cpus} CPUs)")
        print("Resume capability: Continues from partial files if interrupted")
