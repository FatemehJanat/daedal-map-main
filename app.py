"""
County Map API - FastAPI Entry Point

This is the main entry point for the county-map application.
All business logic is in the mapmover/ package - this file only handles:
- FastAPI app setup
- CORS middleware
- Static file serving
- Route definitions (thin wrappers calling handler functions)
"""

import sys
import io
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

# Force UTF-8 encoding for all output streams
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base directory for file paths (works in Docker and locally)
BASE_DIR = Path(__file__).resolve().parent

# Import from mapmover package
from mapmover import (
    # Data loading
    initialize_catalog,
    # Geography
    load_conversions,
    # Logging
    logger,
    log_error_to_cloud,
)

# Order Taker system (Phase 1B - replaces old multi-LLM chat)
from mapmover.order_taker import interpret_request
from mapmover.order_executor import execute_order

# Preprocessor for tiered context system
from mapmover.preprocessor import preprocess_query

# Postprocessor for validation and derived field expansion
from mapmover.postprocessor import postprocess_order, get_display_items

# Geometry handlers (parquet-based)
from mapmover.geometry_handlers import (
    get_countries_geometry as get_countries_geometry_handler,
    get_location_children as get_location_children_handler,
    get_location_places as get_location_places_handler,
    get_location_info,
    get_viewport_geometry as get_viewport_geometry_handler,
    get_selection_geometries as get_selection_geometries_handler,
    clear_cache as clear_geometry_cache,
)

# Settings management
from mapmover.settings import (
    get_settings_with_status,
    save_settings,
    init_backup_folders,
)

# Create FastAPI app
app = FastAPI(
    title="County Map API",
    description="Geographic data exploration API",
    version="2.0.0"
)

# Configure logging
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Enable CORS so browser frontend can communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (JS, CSS, etc.)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# === Startup Event ===

@app.on_event("startup")
async def startup_event():
    """Initialize data catalog and load conversions on startup."""
    logger.info("Starting county-map API...")
    load_conversions()
    initialize_catalog()
    logger.info("Startup complete - data catalog initialized")


# === Health Check ===

@app.get("/health")
async def health_check():
    """Health check endpoint for Railway/Docker deployments."""
    return {"status": "healthy", "service": "county-map-api"}


# === Frontend ===

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the frontend HTML file."""
    template_path = BASE_DIR / "templates" / "index.html"
    return template_path.read_text(encoding='utf-8')


# === Geometry Endpoints ===

@app.get("/geometry/countries")
async def get_countries_geometry_endpoint(debug: bool = False):
    """
    Get all country geometries for initial map display.
    Returns a GeoJSON FeatureCollection with polygon countries only.
    """
    try:
        result = get_countries_geometry_handler(debug=debug)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in /geometry/countries: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/geometry/{loc_id}/children")
async def get_location_children_endpoint(loc_id: str):
    """
    Get child geometries for a location (drill-down).
    Examples:
    - /geometry/USA/children -> US states
    - /geometry/USA-CA/children -> California counties
    - /geometry/FRA/children -> French regions
    """
    try:
        result = get_location_children_handler(loc_id)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/children: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/geometry/{loc_id}/places")
async def get_location_places_endpoint(loc_id: str):
    """
    Get places (cities/towns) for a location as a separate overlay layer.
    """
    try:
        result = get_location_places_handler(loc_id)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/places: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/geometry/{loc_id}/info")
async def get_location_info_endpoint(loc_id: str):
    """
    Get information about a specific location.
    Returns name, admin_level, and whether children are available.
    """
    try:
        result = get_location_info(loc_id)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/info: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/geometry/viewport")
async def get_viewport_geometry_endpoint(level: int = 0, bbox: str = None, debug: bool = False):
    """
    Get geometry features within a viewport bounding box.

    Args:
        level: Admin level (0=countries, 1=states, 2=counties, 3=subdivisions)
        bbox: Bounding box as "minLon,minLat,maxLon,maxLat"
        debug: If true, include coverage info for level 0 features

    Returns:
        GeoJSON FeatureCollection with features intersecting the viewport
    """
    try:
        if bbox:
            # Parse bbox string
            parts = [float(x) for x in bbox.split(',')]
            if len(parts) != 4:
                return JSONResponse(
                    content={"error": "bbox must be minLon,minLat,maxLon,maxLat"},
                    status_code=400
                )
            bbox_tuple = tuple(parts)
        else:
            # Default to world view
            bbox_tuple = (-180, -90, 180, 90)

        result = get_viewport_geometry_handler(level, bbox_tuple, debug=debug)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in /geometry/viewport: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/geometry/cache/clear")
async def clear_geometry_cache_endpoint():
    """Clear the geometry cache. Useful after updating data files."""
    try:
        clear_geometry_cache()
        return JSONResponse(content={"message": "Geometry cache cleared"})
    except Exception as e:
        logger.error(f"Error clearing geometry cache: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/geometry/selection")
async def get_selection_geometry_endpoint(req: Request):
    """
    Get geometries for specific loc_ids for disambiguation selection mode.
    Used by SelectionManager to highlight candidate locations.

    Body: { loc_ids: ["CAN-BC", "USA-WA", ...] }
    Returns: GeoJSON FeatureCollection
    """
    try:
        body = await req.json()
        loc_ids = body.get("loc_ids", [])

        if not loc_ids:
            return JSONResponse(content={"type": "FeatureCollection", "features": []})

        result = get_selection_geometries_handler(loc_ids)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error in /geometry/selection: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Hurricane Data Endpoints ===

@app.get("/api/hurricane/track/{storm_id}")
async def get_hurricane_track(storm_id: str):
    """
    Get 6-hourly track positions for a specific hurricane.
    Returns timestamp, lat/lon, wind speed, pressure, category for each position.
    """
    import pandas as pd

    try:
        # Path to hurricane positions parquet
        positions_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/hurricanes/positions.parquet")

        if not positions_path.exists():
            return JSONResponse(content={"error": "Hurricane data not available"}, status_code=404)

        # Load and filter positions for this storm
        df = pd.read_parquet(positions_path)
        storm_df = df[df['storm_id'] == storm_id].copy()

        if len(storm_df) == 0:
            return JSONResponse(content={"error": f"Storm {storm_id} not found"}, status_code=404)

        # Sort by timestamp
        storm_df = storm_df.sort_values('timestamp')

        # Convert to list of dicts
        positions = []
        for _, row in storm_df.iterrows():
            positions.append({
                "timestamp": row['timestamp'].isoformat() if hasattr(row['timestamp'], 'isoformat') else str(row['timestamp']),
                "latitude": float(row['latitude']),
                "longitude": float(row['longitude']),
                "wind_kt": int(row['wind_kt']) if pd.notna(row['wind_kt']) else None,
                "pressure_mb": int(row['pressure_mb']) if pd.notna(row['pressure_mb']) else None,
                "category": row['category'] if pd.notna(row['category']) else None,
                "status": row['status'] if pd.notna(row['status']) else None,
                "loc_id": row['loc_id'] if pd.notna(row['loc_id']) else None
            })

        return JSONResponse(content={
            "storm_id": storm_id,
            "position_count": len(positions),
            "positions": positions
        })

    except Exception as e:
        logger.error(f"Error fetching hurricane track {storm_id}: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/hurricane/storms")
async def get_hurricane_storms(year: int = None, name: str = None, us_landfall: bool = None):
    """
    Get list of hurricanes/storms with optional filters.
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/hurricanes/storms.parquet")

        if not storms_path.exists():
            return JSONResponse(content={"error": "Hurricane data not available"}, status_code=404)

        df = pd.read_parquet(storms_path)

        # Apply filters
        if year is not None:
            df = df[df['year'] == year]
        if name is not None:
            df = df[df['name'].str.upper() == name.upper()]
        if us_landfall is not None:
            df = df[df['us_landfall'] == us_landfall]

        # Sort by year desc, max_wind desc
        df = df.sort_values(['year', 'max_wind_kt'], ascending=[False, False])

        # Convert to list
        storms = []
        for _, row in df.iterrows():
            storms.append({
                "storm_id": row['storm_id'],
                "name": row['name'],
                "year": int(row['year']),
                "basin": row['basin'],
                "max_wind_kt": int(row['max_wind_kt']) if pd.notna(row['max_wind_kt']) else None,
                "max_category": row['max_category'] if pd.notna(row['max_category']) else None,
                "us_landfall": bool(row['us_landfall']) if pd.notna(row['us_landfall']) else False,
                "start_date": str(row['start_date']) if pd.notna(row['start_date']) else None,
                "end_date": str(row['end_date']) if pd.notna(row['end_date']) else None
            })

        return JSONResponse(content={
            "count": len(storms),
            "storms": storms
        })

    except Exception as e:
        logger.error(f"Error fetching hurricane storms: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/hurricane/storms/geojson")
async def get_hurricane_storms_geojson(year: int = None, us_landfall: bool = None):
    """
    Get storms as GeoJSON points (for map marker display).
    Each storm is placed at its max intensity position.
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/hurricanes/storms.parquet")
        positions_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/hurricanes/positions.parquet")

        if not storms_path.exists() or not positions_path.exists():
            return JSONResponse(content={"error": "Hurricane data not available"}, status_code=404)

        # Load storms
        storms_df = pd.read_parquet(storms_path)

        # Apply filters
        if year is not None:
            storms_df = storms_df[storms_df['year'] == year]
        if us_landfall is not None:
            storms_df = storms_df[storms_df['us_landfall'] == us_landfall]

        if len(storms_df) == 0:
            return JSONResponse(content={
                "type": "FeatureCollection",
                "features": []
            })

        # Load positions for these storms
        positions_df = pd.read_parquet(positions_path)
        storm_ids = storms_df['storm_id'].tolist()
        positions_df = positions_df[positions_df['storm_id'].isin(storm_ids)]

        # Find max intensity position for each storm
        max_positions = positions_df.loc[
            positions_df.groupby('storm_id')['wind_kt'].idxmax()
        ][['storm_id', 'latitude', 'longitude', 'timestamp', 'category']].copy()

        # Merge with storm metadata
        merged = storms_df.merge(max_positions, on='storm_id', how='left')

        # Build GeoJSON features
        features = []
        for _, row in merged.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "storm_id": row['storm_id'],
                    "name": row['name'] if pd.notna(row['name']) else row['storm_id'],
                    "year": int(row['year']),
                    "max_wind_kt": int(row['max_wind_kt']) if pd.notna(row['max_wind_kt']) else None,
                    "max_category": row['max_category'] if pd.notna(row['max_category']) else None,
                    "category": row['category'] if pd.notna(row['category']) else None,
                    "us_landfall": bool(row['us_landfall']) if pd.notna(row['us_landfall']) else False,
                    "start_date": str(row['start_date']) if pd.notna(row['start_date']) else None,
                    "end_date": str(row['end_date']) if pd.notna(row['end_date']) else None
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching hurricane storms GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Earthquake Data Endpoints ===

@app.get("/api/earthquakes/geojson")
async def get_earthquakes_geojson(year: int = None, min_magnitude: float = 5.0, limit: int = None):
    """
    Get earthquakes as GeoJSON points for map display.
    Default: M5.0+ earthquakes (significant ones visible on map).
    Uses global data if available, falls back to USA data.
    """
    import pandas as pd

    try:
        # Global earthquake data
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/usgs_earthquakes/events.parquet")

        if not events_path.exists():
            return JSONResponse(content={"error": "Earthquake data not available"}, status_code=404)

        df = pd.read_parquet(events_path)

        # Extract year from timestamp if not already present
        if 'year' not in df.columns and 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df['year'] = df['timestamp'].dt.year

        # Apply filters
        if year is not None and 'year' in df.columns:
            df = df[df['year'] == year]
        if min_magnitude is not None:
            df = df[df['magnitude'] >= min_magnitude]

        # Optional limit
        if limit is not None and limit > 0:
            df = df.nlargest(limit, 'magnitude')

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "magnitude": float(row['magnitude']) if pd.notna(row['magnitude']) else None,
                    "depth_km": float(row['depth_km']) if pd.notna(row.get('depth_km')) else None,
                    "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 0,
                    "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 0,
                    "place": row.get('place', ''),
                    "time": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "year": int(row['year']) if 'year' in row and pd.notna(row['year']) else None,
                    "loc_id": row.get('loc_id', ''),
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    # Aftershock sequence columns
                    "mainshock_id": row.get('mainshock_id') if pd.notna(row.get('mainshock_id')) else None,
                    "sequence_id": row.get('sequence_id') if pd.notna(row.get('sequence_id')) else None,
                    "is_mainshock": bool(row.get('is_mainshock')) if pd.notna(row.get('is_mainshock')) else False,
                    "aftershock_count": int(row.get('aftershock_count', 0)) if pd.notna(row.get('aftershock_count')) else 0
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching earthquakes GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/earthquakes/sequence/{sequence_id}")
async def get_earthquake_sequence(sequence_id: str, min_magnitude: float = None):
    """
    Get all earthquakes in a specific aftershock sequence.
    No magnitude filter by default - returns ALL events in the sequence.
    This allows viewing the full aftershock sequence even when the main
    earthquake list is filtered to M4.5+.
    """
    import pandas as pd

    try:
        # Global earthquake data
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/usgs_earthquakes/events.parquet")

        if not events_path.exists():
            return JSONResponse(content={"error": "Earthquake data not available"}, status_code=404)

        df = pd.read_parquet(events_path)

        # Filter to this sequence only
        df = df[df['sequence_id'] == sequence_id]

        if len(df) == 0:
            return JSONResponse(content={"error": f"Sequence {sequence_id} not found"}, status_code=404)

        # Optional magnitude filter (but default is no filter for full sequence)
        if min_magnitude is not None:
            df = df[df['magnitude'] >= min_magnitude]

        # Extract year from timestamp if not already present
        if 'year' not in df.columns and 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df['year'] = df['timestamp'].dt.year

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "magnitude": float(row['magnitude']) if pd.notna(row['magnitude']) else None,
                    "depth_km": float(row['depth_km']) if pd.notna(row.get('depth_km')) else None,
                    "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 0,
                    "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 0,
                    "place": row.get('place', ''),
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "time": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "year": int(row['year']) if 'year' in row and pd.notna(row['year']) else None,
                    "loc_id": row.get('loc_id', ''),
                    "mainshock_id": row.get('mainshock_id') if pd.notna(row.get('mainshock_id')) else None,
                    "sequence_id": row.get('sequence_id') if pd.notna(row.get('sequence_id')) else None,
                    "is_mainshock": bool(row.get('is_mainshock')) if pd.notna(row.get('is_mainshock')) else False,
                    "aftershock_count": int(row.get('aftershock_count', 0)) if pd.notna(row.get('aftershock_count')) else 0
                }
            })

        logger.info(f"Returning {len(features)} events for sequence {sequence_id}")

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "sequence_id": sequence_id
        })

    except Exception as e:
        logger.error(f"Error fetching earthquake sequence {sequence_id}: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Volcano Data Endpoints ===

@app.get("/api/volcanoes/geojson")
async def get_volcanoes_geojson(active_only: bool = None):
    """
    Get volcanoes as GeoJSON points for map display.
    Uses global data if available, falls back to USA data.
    """
    import pandas as pd

    try:
        # Global volcano data
        volcanoes_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/volcanoes.parquet")

        if not volcanoes_path.exists():
            return JSONResponse(content={"error": "Volcano data not available"}, status_code=404)

        df = pd.read_parquet(volcanoes_path)

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "volcano_id": row.get('volcano_id', ''),
                    "volcano_name": row.get('volcano_name', ''),
                    "VEI": int(row['last_known_VEI']) if pd.notna(row.get('last_known_VEI')) else None,
                    "eruption_count": int(row['eruption_count']) if pd.notna(row.get('eruption_count')) else 0,
                    "last_eruption_year": int(row['last_eruption_year']) if pd.notna(row.get('last_eruption_year')) else None,
                    "loc_id": row.get('loc_id', '')
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching volcanoes GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/eruptions/geojson")
async def get_eruptions_geojson(year: int = None, min_vei: int = None):
    """
    Get volcanic eruptions as GeoJSON points for map display.
    Radii are pre-calculated in the data pipeline using VEI-based formulas.
    Uses global data if available, falls back to USA data.
    """
    import pandas as pd

    try:
        # Global eruption data
        eruptions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/events.parquet")

        if not eruptions_path.exists():
            return JSONResponse(content={"error": "Eruption data not available"}, status_code=404)

        df = pd.read_parquet(eruptions_path)

        # Extract year from timestamp if not already present
        if 'year' not in df.columns and 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df['year'] = df['timestamp'].dt.year

        # Apply filters
        if year is not None and 'year' in df.columns:
            df = df[df['year'] == year]
        if min_vei is not None and 'vei' in df.columns:
            df = df[df['vei'] >= min_vei]

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            # Handle both 'vei' and 'VEI' column names
            vei_val = row.get('vei') or row.get('VEI')
            vei_int = int(vei_val) if pd.notna(vei_val) else None

            # Read pre-calculated radii from parquet (standard event schema)
            felt_radius = float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 10.0
            damage_radius = float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 3.0

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "eruption_id": int(row['eruption_id']) if pd.notna(row.get('eruption_id')) else None,
                    "volcano_name": row.get('volcano_name', ''),
                    "VEI": vei_int,
                    "felt_radius_km": felt_radius,
                    "damage_radius_km": damage_radius,
                    "activity_type": row.get('activity_type', ''),
                    "activity_area": row.get('activity_area', '') if pd.notna(row.get('activity_area')) else None,
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "end_year": int(row['end_year']) if pd.notna(row.get('end_year')) else None,
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "end_timestamp": str(row['end_timestamp']) if pd.notna(row.get('end_timestamp')) else None,
                    "duration_days": float(row['duration_days']) if pd.notna(row.get('duration_days')) else None,
                    "is_ongoing": bool(row['is_ongoing']) if pd.notna(row.get('is_ongoing')) else False,
                    "loc_id": row.get('loc_id', ''),
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude'])
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching eruptions GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Tsunami Data Endpoints ===

@app.get("/api/tsunamis/geojson")
async def get_tsunamis_geojson(year: int = None, min_year: int = 1900, cause: str = None):
    """
    Get tsunami source events as GeoJSON points for map display.
    Uses global NOAA NCEI data.
    """
    import pandas as pd

    try:
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/events.parquet")

        if not events_path.exists():
            return JSONResponse(content={"error": "Tsunami data not available"}, status_code=404)

        df = pd.read_parquet(events_path)

        # Apply filters
        if year is not None:
            df = df[df['year'] == year]
        elif min_year is not None:
            df = df[df['year'] >= min_year]

        if cause is not None:
            df = df[df['cause'].str.lower() == cause.lower()]

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "country": row.get('country', ''),
                    "location": row.get('location', '') if pd.notna(row.get('location')) else None,
                    "cause": row.get('cause', ''),
                    "eq_magnitude": float(row['eq_magnitude']) if pd.notna(row.get('eq_magnitude')) else None,
                    "max_water_height_m": float(row['max_water_height_m']) if pd.notna(row.get('max_water_height_m')) else None,
                    "intensity": float(row['intensity']) if pd.notna(row.get('intensity')) else None,
                    "runup_count": int(row['num_runups']) if pd.notna(row.get('num_runups')) else 0,
                    "deaths": int(row['deaths']) if pd.notna(row.get('deaths')) else None,
                    "damage_millions": float(row['damage_millions']) if pd.notna(row.get('damage_millions')) else None,
                    "loc_id": row.get('loc_id', ''),
                    "is_source": True  # Mark as source event for display
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "year_range": [int(df['year'].min()), int(df['year'].max())] if len(df) > 0 else None
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tsunamis GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/tsunamis/{event_id}/runups")
async def get_tsunami_runups(event_id: str):
    """
    Get runup observations for a specific tsunami event.
    Returns points where the tsunami was observed at coastlines.
    """
    import pandas as pd

    try:
        runups_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/runups.parquet")
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/events.parquet")

        if not runups_path.exists():
            return JSONResponse(content={"error": "Runup data not available"}, status_code=404)

        # Load runups for this event
        runups_df = pd.read_parquet(runups_path)
        runups_df = runups_df[runups_df['event_id'] == event_id]

        if len(runups_df) == 0:
            return JSONResponse(content={"error": f"No runups found for event {event_id}"}, status_code=404)

        # Load source event for reference
        source_event = None
        if events_path.exists():
            events_df = pd.read_parquet(events_path)
            event_row = events_df[events_df['event_id'] == event_id]
            if len(event_row) > 0:
                row = event_row.iloc[0]
                source_event = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row['longitude']), float(row['latitude'])]
                    },
                    "properties": {
                        "event_id": event_id,
                        "year": int(row['year']) if pd.notna(row.get('year')) else None,
                        "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                        "cause": row.get('cause', ''),
                        "eq_magnitude": float(row['eq_magnitude']) if pd.notna(row.get('eq_magnitude')) else None,
                        "max_water_height_m": float(row['max_water_height_m']) if pd.notna(row.get('max_water_height_m')) else None,
                        "_isSource": True,
                        "is_source": True
                    }
                }

        # Build runup features
        features = []
        for _, row in runups_df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "runup_id": row.get('runup_id', ''),
                    "event_id": event_id,
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "country": row.get('country', ''),
                    "location_name": row.get('location', '') if pd.notna(row.get('location')) else None,
                    "water_height_m": float(row['water_height_m']) if pd.notna(row.get('water_height_m')) else None,
                    "dist_from_source_km": float(row['dist_from_source_km']) if pd.notna(row.get('dist_from_source_km')) else None,
                    "travel_time_hours": float(row['arrival_travel_time_min']) / 60 if pd.notna(row.get('arrival_travel_time_min')) else None,
                    "deaths": int(row['deaths']) if pd.notna(row.get('deaths')) else None,
                    "_isSource": False,
                    "is_source": False
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "source": source_event,
            "metadata": {
                "event_id": event_id,
                "runup_count": len(features)
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tsunami runups: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/tsunamis/{event_id}/animation")
async def get_tsunami_animation_data(event_id: str):
    """
    Get combined source + runups data formatted for radial animation.
    Includes source event marked with is_source=true and runups with distance data.
    """
    import pandas as pd

    try:
        runups_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/runups.parquet")
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/events.parquet")

        if not events_path.exists() or not runups_path.exists():
            return JSONResponse(content={"error": "Tsunami data not available"}, status_code=404)

        # Load source event
        events_df = pd.read_parquet(events_path)
        event_row = events_df[events_df['event_id'] == event_id]

        if len(event_row) == 0:
            return JSONResponse(content={"error": f"Event {event_id} not found"}, status_code=404)

        row = event_row.iloc[0]

        # Build all features (source + runups)
        features = []

        # Source event
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(row['longitude']), float(row['latitude'])]
            },
            "properties": {
                "event_id": event_id,
                "year": int(row['year']) if pd.notna(row.get('year')) else None,
                "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                "cause": row.get('cause', ''),
                "eq_magnitude": float(row['eq_magnitude']) if pd.notna(row.get('eq_magnitude')) else None,
                "max_water_height_m": float(row['max_water_height_m']) if pd.notna(row.get('max_water_height_m')) else None,
                "deaths": int(row['deaths']) if pd.notna(row.get('deaths')) else None,
                "is_source": True
            }
        })

        # Load runups
        runups_df = pd.read_parquet(runups_path)
        runups_df = runups_df[runups_df['event_id'] == event_id]

        for _, rrow in runups_df.iterrows():
            if pd.isna(rrow['latitude']) or pd.isna(rrow['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(rrow['longitude']), float(rrow['latitude'])]
                },
                "properties": {
                    "runup_id": rrow.get('runup_id', ''),
                    "event_id": event_id,
                    "country": rrow.get('country', ''),
                    "location_name": rrow.get('location', '') if pd.notna(rrow.get('location')) else None,
                    "water_height_m": float(rrow['water_height_m']) if pd.notna(rrow.get('water_height_m')) else None,
                    "dist_from_source_km": float(rrow['dist_from_source_km']) if pd.notna(rrow.get('dist_from_source_km')) else None,
                    "deaths": int(rrow['deaths']) if pd.notna(rrow.get('deaths')) else None,
                    "is_source": False
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": event_id,
                "source_timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                "runup_count": len(features) - 1,
                "animation_mode": "radial"
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tsunami animation data: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/events/nearby-earthquakes")
async def get_nearby_earthquakes(
    lat: float,
    lon: float,
    timestamp: str = None,
    year: int = None,
    radius_km: float = 150.0,
    days_before: int = 30,
    days_after: int = 60,
    min_magnitude: float = 3.0
):
    """
    Find earthquakes near a location within a time window.
    Used for cross-linking volcanic eruptions to related earthquakes.

    Parameters:
    - lat, lon: Center point (volcano location)
    - timestamp: ISO timestamp of eruption (searches before AND after)
    - year: Fallback if no timestamp (searches whole year)
    - radius_km: Search radius (default 150km for volcanic influence)
    - days_before: Days to search before event (precursor quakes)
    - days_after: Days to search after event (triggered quakes)
    - min_magnitude: Minimum magnitude (default 3.0)

    Returns GeoJSON with earthquakes in the window, plus metadata.
    """
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta

    try:
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/usgs_earthquakes/events.parquet")

        if not events_path.exists():
            return JSONResponse(content={"error": "Earthquake data not available"}, status_code=404)

        df = pd.read_parquet(events_path)

        # Haversine distance filter (approximate, using km)
        # At equator: 1 degree = ~111km
        lat_range = radius_km / 111.0
        lon_range = radius_km / (111.0 * np.cos(np.radians(lat)))

        df = df[
            (df['latitude'] >= lat - lat_range) &
            (df['latitude'] <= lat + lat_range) &
            (df['longitude'] >= lon - lon_range) &
            (df['longitude'] <= lon + lon_range)
        ]

        # Time filter - search both BEFORE and AFTER the event
        if timestamp:
            try:
                event_time = pd.to_datetime(timestamp)
                # Convert to timezone-naive for comparison with datetime64
                if event_time.tzinfo is not None:
                    event_time = event_time.tz_convert('UTC').tz_localize(None)
                start_time = event_time - timedelta(days=days_before)
                end_time = event_time + timedelta(days=days_after)
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                # Make df timestamps timezone-naive too
                if df['timestamp'].dt.tz is not None:
                    df['timestamp'] = df['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)
                df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
                logger.info(f"Searching earthquakes from {start_time} to {end_time}")
            except Exception as e:
                logger.warning(f"Could not parse timestamp {timestamp}: {e}")
        elif year:
            # Fallback: filter by year
            if 'year' not in df.columns and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                df['year'] = df['timestamp'].dt.year
            df = df[df['year'] == year]

        # Magnitude filter
        df = df[df['magnitude'] >= min_magnitude]

        if len(df) == 0:
            return JSONResponse(content={
                "type": "FeatureCollection",
                "features": [],
                "count": 0,
                "search_params": {"lat": lat, "lon": lon, "radius_km": radius_km}
            })

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "magnitude": float(row['magnitude']) if pd.notna(row['magnitude']) else None,
                    "depth_km": float(row['depth_km']) if pd.notna(row.get('depth_km')) else None,
                    "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 0,
                    "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 0,
                    "place": row.get('place', ''),
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "time": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "year": int(row['year']) if 'year' in row and pd.notna(row['year']) else None,
                    "sequence_id": row.get('sequence_id') if pd.notna(row.get('sequence_id')) else None,
                    "is_mainshock": bool(row.get('is_mainshock')) if pd.notna(row.get('is_mainshock')) else False
                }
            })

        logger.info(f"Found {len(features)} earthquakes within {radius_km}km of ({lat}, {lon})")

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
            "search_params": {
                "lat": lat,
                "lon": lon,
                "radius_km": radius_km,
                "days_after": days_after,
                "min_magnitude": min_magnitude
            }
        })

    except Exception as e:
        logger.error(f"Error finding nearby earthquakes: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/events/nearby-volcanoes")
async def get_nearby_volcanoes(
    lat: float,
    lon: float,
    timestamp: str = None,
    year: int = None,
    radius_km: float = 150.0,
    days_before: int = 30,
    min_vei: int = None
):
    """
    Find volcanic eruptions near a location within a time window.
    Used for cross-linking earthquakes to potential volcanic triggers.

    Parameters:
    - lat, lon: Center point (earthquake epicenter)
    - timestamp: ISO timestamp to search before (preferred)
    - year: Fallback if no timestamp (searches whole year)
    - radius_km: Search radius (default 150km for volcanic influence)
    - days_before: Time window before event (default 30 days - eruption precedes quake)
    - min_vei: Minimum VEI (optional)

    Returns GeoJSON with eruptions in the window, plus metadata.
    """
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta

    try:
        eruptions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/events.parquet")

        if not eruptions_path.exists():
            return JSONResponse(content={"error": "Volcano data not available"}, status_code=404)

        df = pd.read_parquet(eruptions_path)

        # Haversine distance filter (approximate, using km)
        lat_range = radius_km / 111.0
        lon_range = radius_km / (111.0 * np.cos(np.radians(lat)))

        df = df[
            (df['latitude'] >= lat - lat_range) &
            (df['latitude'] <= lat + lat_range) &
            (df['longitude'] >= lon - lon_range) &
            (df['longitude'] <= lon + lon_range)
        ]

        # Time filter - look BEFORE the earthquake (eruption triggers quake)
        if timestamp:
            try:
                end_time = pd.to_datetime(timestamp)
                # Convert to timezone-naive for comparison with datetime64
                if end_time.tzinfo is not None:
                    end_time = end_time.tz_convert('UTC').tz_localize(None)
                start_time = end_time - timedelta(days=days_before)
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                # Make df timestamps timezone-naive too
                if df['timestamp'].dt.tz is not None:
                    df['timestamp'] = df['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)
                df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
            except Exception as e:
                logger.warning(f"Could not parse timestamp {timestamp}: {e}")
        elif year:
            # Fallback: filter by year
            if 'year' not in df.columns and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                df['year'] = df['timestamp'].dt.year
            df = df[df['year'] == year]

        # VEI filter
        if min_vei is not None:
            vei_col = 'vei' if 'vei' in df.columns else 'VEI'
            if vei_col in df.columns:
                df = df[df[vei_col] >= min_vei]

        if len(df) == 0:
            return JSONResponse(content={
                "type": "FeatureCollection",
                "features": [],
                "count": 0,
                "search_params": {"lat": lat, "lon": lon, "radius_km": radius_km}
            })

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            vei_val = row.get('vei') or row.get('VEI')
            vei_int = int(vei_val) if pd.notna(vei_val) else None

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "eruption_id": int(row['eruption_id']) if pd.notna(row.get('eruption_id')) else None,
                    "volcano_name": row.get('volcano_name', ''),
                    "VEI": vei_int,
                    "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 10.0,
                    "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 3.0,
                    "activity_type": row.get('activity_type', ''),
                    "activity_area": row.get('activity_area', '') if pd.notna(row.get('activity_area')) else None,
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "end_year": int(row['end_year']) if pd.notna(row.get('end_year')) else None,
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "end_timestamp": str(row['end_timestamp']) if pd.notna(row.get('end_timestamp')) else None,
                    "duration_days": float(row['duration_days']) if pd.notna(row.get('duration_days')) else None,
                    "is_ongoing": bool(row['is_ongoing']) if pd.notna(row.get('is_ongoing')) else False,
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude'])
                }
            })

        logger.info(f"Found {len(features)} eruptions within {radius_km}km of ({lat}, {lon})")

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
            "search_params": {
                "lat": lat,
                "lon": lon,
                "radius_km": radius_km,
                "days_before": days_before,
                "min_vei": min_vei
            }
        })

    except Exception as e:
        logger.error(f"Error finding nearby volcanoes: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/events/nearby-tsunamis")
async def get_nearby_tsunamis(
    lat: float,
    lon: float,
    timestamp: str = None,
    year: int = None,
    radius_km: float = 300.0,
    days_before: int = 1,
    days_after: int = 30
):
    """
    Find tsunamis near a location within a time window.
    Used for cross-linking earthquakes to tsunami effects.

    Parameters:
    - lat, lon: Center point (earthquake epicenter)
    - timestamp: ISO timestamp to search around (preferred)
    - year: Fallback if no timestamp (searches whole year)
    - radius_km: Search radius (default 300km - tsunamis travel far)
    - days_before: Time window before event (default 1 day)
    - days_after: Time window after event (default 30 days)

    Returns GeoJSON with tsunamis in the window, plus metadata.
    """
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta

    try:
        tsunamis_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/events.parquet")

        if not tsunamis_path.exists():
            return JSONResponse(content={"error": "Tsunami data not available"}, status_code=404)

        df = pd.read_parquet(tsunamis_path)

        # Haversine distance filter (approximate, using km)
        lat_range = radius_km / 111.0
        lon_range = radius_km / (111.0 * np.cos(np.radians(lat)))

        df = df[
            (df['latitude'] >= lat - lat_range) &
            (df['latitude'] <= lat + lat_range) &
            (df['longitude'] >= lon - lon_range) &
            (df['longitude'] <= lon + lon_range)
        ]

        # Time filter - look around the earthquake (tsunami follows quake)
        if timestamp:
            try:
                center_time = pd.to_datetime(timestamp)
                if center_time.tzinfo is not None:
                    center_time = center_time.tz_convert('UTC').tz_localize(None)
                start_time = center_time - timedelta(days=days_before)
                end_time = center_time + timedelta(days=days_after)
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                if df['timestamp'].dt.tz is not None:
                    df['timestamp'] = df['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)
                df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
            except Exception as e:
                logger.warning(f"Could not parse timestamp {timestamp}: {e}")
        elif year:
            # Fallback: filter by year
            if 'year' not in df.columns and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                df['year'] = df['timestamp'].dt.year
            df = df[df['year'] == year]

        if len(df) == 0:
            return JSONResponse(content={
                "type": "FeatureCollection",
                "features": [],
                "count": 0,
                "search_params": {"lat": lat, "lon": lon, "radius_km": radius_km}
            })

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "cause": row.get('cause', ''),
                    "cause_code": int(row['cause_code']) if pd.notna(row.get('cause_code')) else None,
                    "eq_magnitude": float(row['eq_magnitude']) if pd.notna(row.get('eq_magnitude')) else None,
                    "max_water_height_m": float(row['max_water_height_m']) if pd.notna(row.get('max_water_height_m')) else None,
                    "intensity": float(row['intensity']) if pd.notna(row.get('intensity')) else None,
                    "deaths": int(row['deaths']) if pd.notna(row.get('deaths')) else None,
                    "num_runups": int(row['num_runups']) if pd.notna(row.get('num_runups')) else 0,
                    "runup_count": int(row['num_runups']) if pd.notna(row.get('num_runups')) else 0,
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                    "country": row.get('country', ''),
                    "location": row.get('location', ''),
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    "is_source": True  # Mark as source for display styling
                }
            })

        logger.info(f"Found {len(features)} tsunamis within {radius_km}km of ({lat}, {lon})")

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
            "search_params": {
                "lat": lat,
                "lon": lon,
                "radius_km": radius_km,
                "days_before": days_before,
                "days_after": days_after
            }
        })

    except Exception as e:
        logger.error(f"Error finding nearby tsunamis: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Wildfire Data Endpoints ===

@app.get("/api/wildfires/geojson")
async def get_wildfires_geojson(year: int = None, min_acres: int = None):
    """
    Get wildfires as GeoJSON for map display.
    Returns fire perimeter polygons or centroids.
    """
    import pandas as pd
    import json as json_lib

    try:
        fires_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/wildfires/fires.parquet")

        if not fires_path.exists():
            return JSONResponse(content={"error": "Wildfire data not available"}, status_code=404)

        df = pd.read_parquet(fires_path)

        # Apply filters
        if year is not None:
            df = df[df['year'] == year]
        if min_acres is not None:
            df = df[df['acres'] >= min_acres]

        # Limit for performance
        if len(df) > 500:
            df = df.nlargest(500, 'acres')

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            # Check if we have polygon geometry
            geom = None
            if 'geometry' in row and pd.notna(row['geometry']):
                try:
                    if isinstance(row['geometry'], str):
                        geom = json_lib.loads(row['geometry'])
                    else:
                        geom = row['geometry']
                except:
                    pass

            # Fallback to centroid point if no polygon
            if geom is None:
                if pd.isna(row.get('latitude')) or pd.isna(row.get('longitude')):
                    continue
                geom = {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                }

            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "name": row.get('fire_name', row.get('name', '')),
                    "acres": float(row['acres']) if pd.notna(row.get('acres')) else None,
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "start_date": str(row['start_date']) if pd.notna(row.get('start_date')) else None,
                    "status": row.get('status', ''),
                    "percent_contained": float(row['percent_contained']) if pd.notna(row.get('percent_contained')) else None,
                    "loc_id": row.get('loc_id', '')
                }
            })

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching wildfires GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Tropical Storm Data Endpoints ===

@app.get("/api/storms/geojson")
async def get_storms_geojson(year: int = None, min_year: int = 1950, basin: str = None, min_category: str = None):
    """
    Get tropical storms as GeoJSON points for map display.
    Each storm is represented by a single point at its maximum intensity location.
    Default: storms from 1950-present.
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/storms.parquet")
        positions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/positions.parquet")

        if not storms_path.exists():
            return JSONResponse(content={"error": "Storm data not available"}, status_code=404)

        storms_df = pd.read_parquet(storms_path)
        positions_df = pd.read_parquet(positions_path)

        # Apply year filter
        if year is not None:
            storms_df = storms_df[storms_df['year'] == year]
        elif min_year is not None:
            storms_df = storms_df[storms_df['year'] >= min_year]

        # Basin filter
        if basin is not None:
            storms_df = storms_df[storms_df['basin'] == basin.upper()]

        # Category filter
        if min_category is not None:
            cat_order = {'TD': 0, 'TS': 1, 'Cat1': 2, 'Cat2': 3, 'Cat3': 4, 'Cat4': 5, 'Cat5': 6}
            min_cat_val = cat_order.get(min_category, 0)
            storms_df = storms_df[storms_df['max_category'].map(lambda x: cat_order.get(x, 0) >= min_cat_val)]

        # Get max intensity position for each storm
        storm_ids = storms_df['storm_id'].tolist()
        positions_subset = positions_df[positions_df['storm_id'].isin(storm_ids)]

        # Find position with max wind for each storm
        max_positions = positions_subset.loc[positions_subset.groupby('storm_id')['wind_kt'].idxmax()]

        # Build GeoJSON features
        features = []
        for _, storm in storms_df.iterrows():
            storm_id = storm['storm_id']
            max_pos = max_positions[max_positions['storm_id'] == storm_id]

            if len(max_pos) == 0:
                continue

            pos = max_pos.iloc[0]
            if pd.isna(pos['latitude']) or pd.isna(pos['longitude']):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(pos['longitude']), float(pos['latitude'])]
                },
                "properties": {
                    "storm_id": storm_id,
                    "name": storm.get('name') if pd.notna(storm.get('name')) else None,
                    "year": int(storm['year']),
                    "basin": storm['basin'],
                    "max_wind_kt": int(storm['max_wind_kt']) if pd.notna(storm['max_wind_kt']) else None,
                    "min_pressure_mb": int(storm['min_pressure_mb']) if pd.notna(storm['min_pressure_mb']) else None,
                    "max_category": storm['max_category'],
                    "num_positions": int(storm['num_positions']),
                    "start_date": str(storm['start_date']) if pd.notna(storm.get('start_date')) else None,
                    "end_date": str(storm['end_date']) if pd.notna(storm.get('end_date')) else None,
                    "made_landfall": bool(storm.get('made_landfall', False)),
                    "latitude": float(pos['latitude']),
                    "longitude": float(pos['longitude'])
                }
            })

        logger.info(f"Returning {len(features)} storms for year={year}, min_year={min_year}, basin={basin}")

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        })

    except Exception as e:
        logger.error(f"Error fetching storms GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/storms/{storm_id}/track")
async def get_storm_track(storm_id: str):
    """
    Get full track positions for a specific storm.
    Returns all 6-hourly positions with wind radii data for animation.
    """
    import pandas as pd

    try:
        positions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/positions.parquet")
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/storms.parquet")

        if not positions_path.exists():
            return JSONResponse(content={"error": "Storm data not available"}, status_code=404)

        positions_df = pd.read_parquet(positions_path)
        storm_positions = positions_df[positions_df['storm_id'] == storm_id].sort_values('timestamp')

        if len(storm_positions) == 0:
            return JSONResponse(content={"error": f"Storm {storm_id} not found"}, status_code=404)

        # Get storm metadata
        storms_df = pd.read_parquet(storms_path)
        storm_meta = storms_df[storms_df['storm_id'] == storm_id]
        storm_name = storm_meta.iloc[0]['name'] if len(storm_meta) > 0 and pd.notna(storm_meta.iloc[0]['name']) else storm_id

        # Build positions array
        positions = []
        for _, pos in storm_positions.iterrows():
            positions.append({
                "timestamp": str(pos['timestamp']) if pd.notna(pos['timestamp']) else None,
                "latitude": float(pos['latitude']),
                "longitude": float(pos['longitude']),
                "wind_kt": int(pos['wind_kt']) if pd.notna(pos['wind_kt']) else None,
                "pressure_mb": int(pos['pressure_mb']) if pd.notna(pos['pressure_mb']) else None,
                "category": pos['category'],
                "status": pos.get('status') if pd.notna(pos.get('status')) else None,
                # Wind radii
                "r34_ne": int(pos['r34_ne']) if pd.notna(pos.get('r34_ne')) else None,
                "r34_se": int(pos['r34_se']) if pd.notna(pos.get('r34_se')) else None,
                "r34_sw": int(pos['r34_sw']) if pd.notna(pos.get('r34_sw')) else None,
                "r34_nw": int(pos['r34_nw']) if pd.notna(pos.get('r34_nw')) else None,
                "r50_ne": int(pos['r50_ne']) if pd.notna(pos.get('r50_ne')) else None,
                "r50_se": int(pos['r50_se']) if pd.notna(pos.get('r50_se')) else None,
                "r50_sw": int(pos['r50_sw']) if pd.notna(pos.get('r50_sw')) else None,
                "r50_nw": int(pos['r50_nw']) if pd.notna(pos.get('r50_nw')) else None,
                "r64_ne": int(pos['r64_ne']) if pd.notna(pos.get('r64_ne')) else None,
                "r64_se": int(pos['r64_se']) if pd.notna(pos.get('r64_se')) else None,
                "r64_sw": int(pos['r64_sw']) if pd.notna(pos.get('r64_sw')) else None,
                "r64_nw": int(pos['r64_nw']) if pd.notna(pos.get('r64_nw')) else None,
            })

        return JSONResponse(content={
            "storm_id": storm_id,
            "name": storm_name,
            "positions": positions,
            "count": len(positions)
        })

    except Exception as e:
        logger.error(f"Error fetching storm track: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/storms/tracks/geojson")
async def get_storm_tracks_geojson(year: int = None, min_year: int = 1950, basin: str = None):
    """
    Get storm tracks as GeoJSON LineStrings for yearly overview display.
    Each storm is a LineString colored by max category.
    Loads all storms from min_year (default 1950) to present.
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/storms.parquet")
        positions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/positions.parquet")

        if not storms_path.exists():
            return JSONResponse(content={"error": "Storm data not available"}, status_code=404)

        storms_df = pd.read_parquet(storms_path)
        positions_df = pd.read_parquet(positions_path)

        # Apply year filter - min_year defaults to 1950
        if year is not None:
            storms_df = storms_df[storms_df['year'] == year]
        elif min_year is not None:
            storms_df = storms_df[storms_df['year'] >= min_year]

        # Basin filter
        if basin is not None:
            storms_df = storms_df[storms_df['basin'] == basin.upper()]

        # Build storm metadata lookup dict (O(1) access)
        storms_df = storms_df.set_index('storm_id')
        storm_ids_set = set(storms_df.index.tolist())

        # Filter positions to only those storms, sort once
        positions_subset = positions_df[positions_df['storm_id'].isin(storm_ids_set)].copy()
        positions_subset = positions_subset.dropna(subset=['latitude', 'longitude'])
        positions_subset = positions_subset.sort_values(['storm_id', 'timestamp'])

        # Build coordinate lists using groupby (vectorized, much faster than iterrows)
        coords_by_storm = {}
        for storm_id, group in positions_subset.groupby('storm_id'):
            coords = list(zip(group['longitude'].tolist(), group['latitude'].tolist()))
            if len(coords) >= 2:
                coords_by_storm[storm_id] = [[float(lon), float(lat)] for lon, lat in coords]

        # Build features from storms that have valid tracks
        features = []
        for storm_id, coords in coords_by_storm.items():
            storm = storms_df.loc[storm_id]
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                },
                "properties": {
                    "storm_id": storm_id,
                    "name": storm.get('name') if pd.notna(storm.get('name')) else None,
                    "year": int(storm['year']),
                    "basin": storm['basin'],
                    "max_wind_kt": int(storm['max_wind_kt']) if pd.notna(storm['max_wind_kt']) else None,
                    "min_pressure_mb": int(storm['min_pressure_mb']) if pd.notna(storm['min_pressure_mb']) else None,
                    "max_category": storm['max_category'],
                    "num_positions": int(storm['num_positions']),
                    "start_date": str(storm['start_date']) if pd.notna(storm.get('start_date')) else None,
                    "end_date": str(storm['end_date']) if pd.notna(storm.get('end_date')) else None,
                    "made_landfall": bool(storm.get('made_landfall', False))
                }
            })

        logger.info(f"Returning {len(features)} storm tracks for year={year}, min_year={min_year}, basin={basin}")

        return JSONResponse(content={
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        })

    except Exception as e:
        logger.error(f"Error fetching storm tracks GeoJSON: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/storms/list")
async def get_storms_list(year: int = None, min_year: int = 1950, basin: str = None, limit: int = 100):
    """
    Get list of storms with metadata for filtering/selection.
    Returns compact list without track data.
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/storms.parquet")

        if not storms_path.exists():
            return JSONResponse(content={"error": "Storm data not available"}, status_code=404)

        storms_df = pd.read_parquet(storms_path)

        # Apply filters
        if year is not None:
            storms_df = storms_df[storms_df['year'] == year]
        elif min_year is not None:
            storms_df = storms_df[storms_df['year'] >= min_year]

        if basin is not None:
            storms_df = storms_df[storms_df['basin'] == basin.upper()]

        # Sort by max wind (strongest first)
        storms_df = storms_df.sort_values('max_wind_kt', ascending=False)

        # Apply limit
        if limit is not None and limit > 0:
            storms_df = storms_df.head(limit)

        # Build list
        storms = []
        for _, storm in storms_df.iterrows():
            storms.append({
                "storm_id": storm['storm_id'],
                "name": storm.get('name') if pd.notna(storm.get('name')) else None,
                "year": int(storm['year']),
                "basin": storm['basin'],
                "max_wind_kt": int(storm['max_wind_kt']) if pd.notna(storm['max_wind_kt']) else None,
                "max_category": storm['max_category'],
                "start_date": str(storm['start_date']) if pd.notna(storm.get('start_date')) else None,
            })

        return JSONResponse(content={
            "storms": storms,
            "count": len(storms)
        })

    except Exception as e:
        logger.error(f"Error fetching storms list: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Reference Data Endpoints ===

@app.get("/reference/admin-levels")
async def get_admin_levels():
    """
    Get admin level names for all countries.
    Used by frontend for popup display (e.g., "Clackamas" -> "Clackamas County").
    """
    try:
        ref_path = BASE_DIR / "mapmover" / "reference" / "admin_levels.json"
        if ref_path.exists():
            with open(ref_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return JSONResponse(content=data)
        else:
            return JSONResponse(content={"error": "admin_levels.json not found"}, status_code=404)
    except Exception as e:
        logger.error(f"Error loading admin_levels.json: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Settings Endpoints ===

@app.get("/settings")
async def get_settings():
    """
    Get current application settings.
    Returns backup path and folder existence status.
    """
    try:
        settings = get_settings_with_status()
        return JSONResponse(content=settings)
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/settings")
async def update_settings(req: Request):
    """
    Update application settings.
    Accepts: { backup_path: "..." }
    """
    try:
        data = await req.json()
        backup_path = data.get("backup_path", "")

        # Save the settings
        success = save_settings({"backup_path": backup_path})

        if success:
            settings = get_settings_with_status()
            return JSONResponse(content={"success": True, "settings": settings})
        else:
            return JSONResponse(
                content={"error": "Failed to save settings"},
                status_code=500
            )
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/settings/init-folders")
async def initialize_folders(req: Request):
    """
    Initialize the backup folder structure.
    Creates geometry/ and data/ folders at the backup path.
    """
    try:
        data = await req.json()
        backup_path = data.get("backup_path", "")

        if not backup_path:
            return JSONResponse(
                content={"error": "Backup path is required"},
                status_code=400
            )

        # Save the path and create folders
        save_settings({"backup_path": backup_path})
        folders = init_backup_folders(backup_path)

        return JSONResponse(content={
            "success": True,
            "folders": folders,
            "message": f"Initialized folders at {backup_path}"
        })
    except Exception as e:
        logger.error(f"Error initializing folders: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Chat Endpoint (Order Taker Model) ===

@app.post("/chat")
async def chat_endpoint(req: Request):
    """
    Chat endpoint - Order Taker model (Phase 1B).

    Flow:
    1. User sends query -> Returns order for confirmation
    2. User confirms order -> Executes and returns GeoJSON data

    Request body:
    - query: str - Natural language query
    - chatHistory: list - Previous messages for context
    - confirmed_order: dict - If present, execute this order directly
    """
    try:
        body = await req.json()

        # Check if this is a confirmed order execution
        if body.get("confirmed_order"):
            try:
                result = execute_order(body["confirmed_order"])
                response = {
                    "type": "data",
                    "geojson": result["geojson"],
                    "summary": result["summary"],
                    "count": result["count"],
                    "sources": result.get("sources", [])
                }
                # Include multi-year data if present (for time slider)
                if result.get("multi_year"):
                    response["multi_year"] = True
                    response["year_data"] = result["year_data"]
                    response["year_range"] = result["year_range"]
                    response["metric_key"] = result.get("metric_key")
                    response["available_metrics"] = result.get("available_metrics", [])
                    response["metric_year_ranges"] = result.get("metric_year_ranges", {})
                return JSONResponse(content=response)
            except Exception as e:
                logger.error(f"Order execution error: {e}")
                return JSONResponse(content={
                    "type": "error",
                    "message": str(e)
                }, status_code=400)

        # Otherwise, interpret the natural language request
        query = body.get("query", "")
        chat_history = body.get("chatHistory", [])
        viewport = body.get("viewport")  # {center, zoom, bounds, adminLevel}
        resolved_location = body.get("resolved_location")  # From disambiguation selection

        if not query:
            return JSONResponse(content={"error": "No query provided"}, status_code=400)

        logger.debug(f"Chat query: {query[:100]}...")

        # Run preprocessor to extract hints (Tier 2) with viewport context
        hints = preprocess_query(query, viewport=viewport)
        if hints.get("summary"):
            logger.debug(f"Preprocessor hints: {hints['summary']}")

        # If resolved_location is provided, skip disambiguation and use it directly
        if resolved_location:
            logger.debug(f"Using resolved location: {resolved_location}")
            # Override preprocessor hints with resolved location
            hints["location"] = {
                "matched_term": resolved_location.get("matched_term"),
                "iso3": resolved_location.get("iso3"),
                "country_name": resolved_location.get("country_name"),
                "loc_id": resolved_location.get("loc_id"),
                "is_subregion": resolved_location.get("loc_id") != resolved_location.get("iso3"),
                "source": "disambiguation_selection"
            }
            hints["disambiguation"] = None  # Clear disambiguation flag

        # Check for "show borders" intent - display geometry from previous disambiguation
        if hints.get("show_borders"):
            # Check for previous_disambiguation passed from frontend
            previous_options = body.get("previous_disambiguation_options", [])

            if previous_options:
                loc_ids_to_show = [opt.get("loc_id") for opt in previous_options if opt.get("loc_id")]
            else:
                # Fallback: search for the term from recent chat if available
                loc_ids_to_show = []

            if loc_ids_to_show:
                logger.debug(f"Show borders: displaying {len(loc_ids_to_show)} locations")
                # Fetch geometry for these locations
                from mapmover.data_loading import fetch_geometries_by_loc_ids
                geojson = fetch_geometries_by_loc_ids(loc_ids_to_show)

                return JSONResponse(content={
                    "type": "navigate",
                    "message": f"Showing {len(loc_ids_to_show)} locations on the map. Click any location to see data options.",
                    "locations": previous_options if previous_options else [{"loc_id": lid} for lid in loc_ids_to_show],
                    "loc_ids": loc_ids_to_show,
                    "original_query": query,
                    "geojson": geojson,
                })
            else:
                # No previous disambiguation found - tell user
                return JSONResponse(content={
                    "type": "chat",
                    "reply": "I don't have a list of locations to display. Please first ask about specific locations (e.g., 'show me washington county') to get a list.",
                })

        # Check for navigation intent - zoom to locations without data request
        navigation = hints.get("navigation")
        if navigation and navigation.get("is_navigation"):
            locations = navigation.get("locations", [])
            loc_ids = [loc.get("loc_id") for loc in locations if loc.get("loc_id")]

            # Check for drill-down pattern (e.g., "texas counties" -> show counties of Texas)
            if len(locations) == 1 and locations[0].get("drill_to_level"):
                loc = locations[0]
                loc_id = loc.get("loc_id")
                drill_level = loc.get("drill_to_level")
                name = loc.get("matched_term", loc_id)

                logger.debug(f"Drill-down request: {name} -> {drill_level}")

                # Return a drilldown response that tells frontend to drill into this location
                return JSONResponse(content={
                    "type": "drilldown",
                    "message": f"Showing {drill_level} of {name}...",
                    "loc_id": loc_id,
                    "name": name,
                    "drill_to_level": drill_level,
                    "original_query": query,
                })

            # Build display names with parent context (e.g., "vancouver (BC)" vs "vancouver (WA)")
            def get_display_name(loc):
                name = loc.get("matched_term", loc.get("loc_id", "?"))
                loc_id = loc.get("loc_id", "")
                # Parse loc_id format: ISO3-PARENT-NAME or ISO3-STATE
                parts = loc_id.split("-") if loc_id else []
                if len(parts) >= 2:
                    # Use state/province code as context (e.g., "WA", "BC")
                    parent_code = parts[1]
                    return f"{name} ({parent_code})"
                elif loc.get("country_name"):
                    # Fallback to country name
                    return f"{name} ({loc.get('country_name')})"
                return name

            loc_names = [get_display_name(loc) for loc in locations]

            logger.debug(f"Navigation request for {len(locations)} locations: {loc_ids}")

            # Format message based on count
            if len(locations) == 1:
                message = f"Showing {loc_names[0]}. What data would you like to see for this location?"
            else:
                message = f"Showing {len(locations)} locations: {', '.join(loc_names[:5])}{'...' if len(loc_names) > 5 else ''}. What data would you like to see?"

            return JSONResponse(content={
                "type": "navigate",
                "message": message,
                "locations": locations,
                "loc_ids": loc_ids,
                "original_query": query,
                "geojson": {"type": "FeatureCollection", "features": []},
            })

        # Check for disambiguation needed - return early without LLM call
        disambiguation = hints.get("disambiguation")
        if disambiguation and disambiguation.get("needed"):
            options = disambiguation.get("options", [])
            query_term = disambiguation.get("query_term", "location")
            logger.debug(f"Disambiguation needed for '{query_term}' with {len(options)} options")

            return JSONResponse(content={
                "type": "disambiguate",
                "message": f"I found {len(options)} locations matching '{query_term}'. Please click on the one you meant:",
                "query_term": query_term,
                "original_query": query,
                "options": options,  # List of {matched_term, iso3, country_name, loc_id, admin_level}
                "geojson": {"type": "FeatureCollection", "features": []},
            })

        # Single LLM call to interpret request (with Tier 3/4 context from hints)
        result = interpret_request(query, chat_history, hints=hints)

        if result["type"] == "order":
            # Run postprocessor to validate and expand derived fields
            processed = postprocess_order(result["order"], hints)
            logger.debug(f"Postprocessor: {processed.get('validation_summary')}")

            # Get display items (filtered for user view - hides for_derivation items, adds derived specs)
            display_items = get_display_items(
                processed.get("items", []),
                processed.get("derived_specs", [])
            )

            # Return order for UI confirmation
            return JSONResponse(content={
                "type": "order",
                "order": {
                    **result["order"],
                    "items": display_items,
                    "derived_specs": processed.get("derived_specs", []),
                },
                "full_order": processed,  # Full order for execution
                "summary": result["summary"],
                "validation_summary": processed.get("validation_summary"),
                "all_valid": processed.get("all_valid", True)
            })
        elif result["type"] == "clarify":
            # Need more information from user
            return JSONResponse(content={
                "type": "clarify",
                "message": result["message"],
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": True
            })
        else:
            # General chat response (not a data request)
            return JSONResponse(content={
                "type": "chat",
                "message": result["message"],
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": False
            })

    except Exception as e:
        logger.error(f"Chat error: {e}")
        traceback.print_exc()
        return JSONResponse(content={
            "type": "error",
            "message": "Sorry, I encountered an error. Please try again.",
            "geojson": {"type": "FeatureCollection", "features": []},
            "error": str(e)
        }, status_code=500)


# === Main Entry Point ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)
