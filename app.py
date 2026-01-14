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

import msgpack
from fastapi import FastAPI, Request, Response
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


# === MessagePack Response Helpers ===

def msgpack_response(data: dict, status_code: int = 200) -> Response:
    """Standard MessagePack response for all API endpoints.

    Usage:
        return msgpack_response({"data": result, "count": len(result)})
    """
    return Response(
        content=msgpack.packb(data, use_bin_type=True),
        media_type="application/msgpack",
        status_code=status_code
    )


def msgpack_error(message: str, status_code: int = 500) -> Response:
    """Standard error response in MessagePack format."""
    return msgpack_response({"error": message}, status_code)


async def decode_request_body(request: Request) -> dict:
    """Decode MessagePack request body."""
    body_bytes = await request.body()
    return msgpack.unpackb(body_bytes, raw=False)


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
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/countries: {e}")
        return msgpack_error(str(e), 500)


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
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/children: {e}")
        return msgpack_error(str(e), 500)


@app.get("/geometry/{loc_id}/places")
async def get_location_places_endpoint(loc_id: str):
    """
    Get places (cities/towns) for a location as a separate overlay layer.
    """
    try:
        result = get_location_places_handler(loc_id)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/places: {e}")
        return msgpack_error(str(e), 500)


@app.get("/geometry/{loc_id}/info")
async def get_location_info_endpoint(loc_id: str):
    """
    Get information about a specific location.
    Returns name, admin_level, and whether children are available.
    """
    try:
        result = get_location_info(loc_id)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/info: {e}")
        return msgpack_error(str(e), 500)


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
                return msgpack_error("bbox must be minLon,minLat,maxLon,maxLat", 400)
            bbox_tuple = tuple(parts)
        else:
            # Default to world view
            bbox_tuple = (-180, -90, 180, 90)

        result = get_viewport_geometry_handler(level, bbox_tuple, debug=debug)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/viewport: {e}")
        return msgpack_error(str(e), 500)


@app.post("/geometry/cache/clear")
async def clear_geometry_cache_endpoint():
    """Clear the geometry cache. Useful after updating data files."""
    try:
        clear_geometry_cache()
        return msgpack_response({"message": "Geometry cache cleared"})
    except Exception as e:
        logger.error(f"Error clearing geometry cache: {e}")
        return msgpack_error(str(e), 500)


@app.post("/geometry/selection")
async def get_selection_geometry_endpoint(req: Request):
    """
    Get geometries for specific loc_ids for disambiguation selection mode.
    Used by SelectionManager to highlight candidate locations.

    Body: { loc_ids: ["CAN-BC", "USA-WA", ...] }
    Returns: GeoJSON FeatureCollection
    """
    try:
        body = await decode_request_body(req)
        loc_ids = body.get("loc_ids", [])

        if not loc_ids:
            return msgpack_response({"type": "FeatureCollection", "features": []})

        result = get_selection_geometries_handler(loc_ids)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/selection: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Hurricane data not available", 404)

        # Load and filter positions for this storm
        df = pd.read_parquet(positions_path)
        storm_df = df[df['storm_id'] == storm_id].copy()

        if len(storm_df) == 0:
            return msgpack_error(f"Storm {storm_id} not found", 404)

        # Sort by timestamp
        storm_df = storm_df.sort_values('timestamp')

        # Convert to GeoJSON FeatureCollection
        features = []
        for _, row in storm_df.iterrows():
            ts = row['timestamp'].isoformat() if hasattr(row['timestamp'], 'isoformat') else str(row['timestamp'])
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "timestamp": ts,
                    "wind_kt": int(row['wind_kt']) if pd.notna(row['wind_kt']) else None,
                    "pressure_mb": int(row['pressure_mb']) if pd.notna(row['pressure_mb']) else None,
                    "category": row['category'] if pd.notna(row['category']) else None,
                    "status": row['status'] if pd.notna(row['status']) else None,
                    "loc_id": row['loc_id'] if pd.notna(row['loc_id']) else None
                }
            })

        # Get time range
        time_start = storm_df['timestamp'].min()
        time_end = storm_df['timestamp'].max()

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": storm_id,
                "event_type": "hurricane",
                "total_count": len(features),
                "time_range": {
                    "start": time_start.isoformat() if hasattr(time_start, 'isoformat') else str(time_start),
                    "end": time_end.isoformat() if hasattr(time_end, 'isoformat') else str(time_end)
                }
            }
        })

    except Exception as e:
        logger.error(f"Error fetching hurricane track {storm_id}: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/hurricane/storms")
async def get_hurricane_storms(year: int = None, name: str = None, us_landfall: bool = None):
    """
    Get list of hurricanes/storms with optional filters.
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/hurricanes/storms.parquet")

        if not storms_path.exists():
            return msgpack_error("Hurricane data not available", 404)

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

        return msgpack_response({
            "count": len(storms),
            "storms": storms
        })

    except Exception as e:
        logger.error(f"Error fetching hurricane storms: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Hurricane data not available", 404)

        # Load storms
        storms_df = pd.read_parquet(storms_path)

        # Apply filters
        if year is not None:
            storms_df = storms_df[storms_df['year'] == year]
        if us_landfall is not None:
            storms_df = storms_df[storms_df['us_landfall'] == us_landfall]

        if len(storms_df) == 0:
            return msgpack_response({
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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching hurricane storms GeoJSON: {e}")
        return msgpack_error(str(e), 500)


# === Earthquake Data Endpoints ===

@app.get("/api/earthquakes/geojson")
async def get_earthquakes_geojson(year: int = None, min_magnitude: float = None, limit: int = None):
    """
    Get earthquakes as GeoJSON points for map display.
    No default magnitude filter - frontend controls filtering.
    Uses global data if available, falls back to USA data.
    """
    import pandas as pd

    try:
        # Global earthquake data
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/earthquakes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Earthquake data not available", 404)

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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching earthquakes GeoJSON: {e}")
        return msgpack_error(str(e), 500)


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
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/earthquakes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Earthquake data not available", 404)

        df = pd.read_parquet(events_path)

        # Filter to this sequence only
        df = df[df['sequence_id'] == sequence_id]

        if len(df) == 0:
            return msgpack_error(f"Sequence {sequence_id} not found", 404)

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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "sequence_id": sequence_id
        })

    except Exception as e:
        logger.error(f"Error fetching earthquake sequence {sequence_id}: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/earthquakes/aftershocks/{event_id}")
async def get_earthquake_aftershocks(event_id: str, min_magnitude: float = None):
    """
    Get all aftershocks for a specific mainshock by event_id.
    This queries by mainshock_id, which correctly captures all aftershocks
    even when a large aftershock becomes a mainshock itself (nested sequences).
    Returns the mainshock plus all events where mainshock_id = event_id.
    """
    import pandas as pd

    try:
        # Global earthquake data
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/earthquakes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Earthquake data not available", 404)

        df = pd.read_parquet(events_path)

        # Get the mainshock itself
        mainshock_df = df[df['event_id'] == event_id]

        if len(mainshock_df) == 0:
            return msgpack_error(f"Event {event_id} not found", 404)

        # Get all aftershocks (events where mainshock_id = event_id)
        aftershocks_df = df[df['mainshock_id'] == event_id]

        # Combine mainshock and aftershocks
        result_df = pd.concat([mainshock_df, aftershocks_df], ignore_index=True)

        # Optional magnitude filter
        if min_magnitude is not None:
            result_df = result_df[result_df['magnitude'] >= min_magnitude]

        # Extract year from timestamp if not already present
        if 'year' not in result_df.columns and 'timestamp' in result_df.columns:
            result_df['timestamp'] = pd.to_datetime(result_df['timestamp'], errors='coerce')
            result_df['year'] = result_df['timestamp'].dt.year

        # Build GeoJSON features
        features = []
        for _, row in result_df.iterrows():
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

        logger.info(f"Returning {len(features)} events for mainshock {event_id} (1 mainshock + {len(features)-1} aftershocks)")

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": event_id,
                "event_type": "earthquake",
                "total_count": len(features),
                "aftershock_count": len(features) - 1
            }
        })

    except Exception as e:
        logger.error(f"Error fetching aftershocks for {event_id}: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Volcano data not available", 404)

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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching volcanoes GeoJSON: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/eruptions/geojson")
async def get_eruptions_geojson(year: int = None, min_vei: int = None, min_year: int = None, exclude_ongoing: bool = False):
    """
    Get volcanic eruptions as GeoJSON points for map display.
    Radii are pre-calculated in the data pipeline using VEI-based formulas.
    Uses global data if available, falls back to USA data.

    Query params:
    - year: Filter to single year
    - min_year: Minimum year filter
    - min_vei: Minimum VEI filter
    - exclude_ongoing: If true, exclude ongoing eruptions (for animated overlays)
    """
    import pandas as pd

    try:
        # Global eruption data
        eruptions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/events.parquet")

        if not eruptions_path.exists():
            return msgpack_error("Eruption data not available", 404)

        df = pd.read_parquet(eruptions_path)

        # Extract year from timestamp if not already present
        if 'year' not in df.columns and 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df['year'] = df['timestamp'].dt.year

        # Apply filters
        if year is not None and 'year' in df.columns:
            df = df[df['year'] == year]
        if min_year is not None and 'year' in df.columns:
            df = df[df['year'] >= min_year]
        if min_vei is not None and 'vei' in df.columns:
            df = df[df['vei'] >= min_vei]

        # Exclude ongoing eruptions (for animated timeline - they have no end date)
        if exclude_ongoing and 'is_ongoing' in df.columns:
            df = df[df['is_ongoing'] != True]

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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching eruptions GeoJSON: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Tsunami data not available", 404)

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
                    "runup_count": int(row['runup_count']) if pd.notna(row.get('runup_count')) else 0,
                    "deaths": int(row['deaths']) if pd.notna(row.get('deaths')) else None,
                    "damage_millions": float(row['damage_millions']) if pd.notna(row.get('damage_millions')) else None,
                    "loc_id": row.get('loc_id', ''),
                    "is_source": True  # Mark as source event for display
                }
            })

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "year_range": [int(df['year'].min()), int(df['year'].max())] if len(df) > 0 else None
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tsunamis GeoJSON: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Runup data not available", 404)

        # Load runups for this event
        runups_df = pd.read_parquet(runups_path)
        runups_df = runups_df[runups_df['event_id'] == event_id]

        if len(runups_df) == 0:
            return msgpack_error(f"No runups found for event {event_id}", 404)

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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "source": source_event,
            "metadata": {
                "event_id": event_id,
                "event_type": "tsunami",
                "total_count": len(features),
                "runup_count": len(features)
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tsunami runups: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Tsunami data not available", 404)

        # Load source event
        events_df = pd.read_parquet(events_path)
        event_row = events_df[events_df['event_id'] == event_id]

        if len(event_row) == 0:
            return msgpack_error(f"Event {event_id} not found", 404)

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
                    "arrival_travel_time_min": float(rrow['arrival_travel_time_min']) if pd.notna(rrow.get('arrival_travel_time_min')) else None,
                    "timestamp": str(rrow['timestamp']) if pd.notna(rrow.get('timestamp')) else None,
                    "deaths": int(rrow['deaths']) if pd.notna(rrow.get('deaths')) else None,
                    "is_source": False
                }
            })

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": event_id,
                "event_type": "tsunami",
                "total_count": len(features),
                "source_timestamp": str(row['timestamp']) if pd.notna(row.get('timestamp')) else None,
                "runup_count": len(features) - 1,
                "animation_mode": "radial"
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tsunami animation data: {e}")
        return msgpack_error(str(e), 500)


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
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/earthquakes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Earthquake data not available", 404)

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
            return msgpack_response({
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

        return msgpack_response({
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
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Volcano data not available", 404)

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
            return msgpack_response({
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

        return msgpack_response({
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
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Tsunami data not available", 404)

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
            return msgpack_response({
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
                    "num_runups": int(row['runup_count']) if pd.notna(row.get('num_runups')) else 0,
                    "runup_count": int(row['runup_count']) if pd.notna(row.get('runup_count')) else 0,
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

        return msgpack_response({
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
        return msgpack_error(str(e), 500)


# === Wildfire Data Endpoints ===

@app.get("/api/wildfires/geojson")
async def get_wildfires_geojson(
    year: int = None,
    min_year: int = 2010,
    max_year: int = None,
    min_area_km2: float = None,
    include_perimeter: bool = False
):
    """
    Get wildfires as GeoJSON for map display.
    Uses Global Fire Atlas data with yearly partitions for efficient loading.

    No default area filter - frontend controls filtering.
    Set include_perimeter=true to get polygon geometries.

    Memory-efficient: Uses yearly parquet files with pyarrow predicate pushdown.
    """
    import pyarrow.parquet as pq
    import pyarrow as pa
    import pandas as pd
    import json as json_lib

    try:
        # Use enriched files with loc_id columns
        by_year_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/wildfires/by_year_enriched")
        # Fallback to raw files if enriched not available
        if not by_year_path.exists():
            by_year_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/wildfires/by_year")

        if not by_year_path.exists():
            return msgpack_error("Wildfire data not available", 404)

        # Determine year range
        if year is not None:
            years_to_load = [year]
        else:
            end_year = max_year if max_year else 2024
            years_to_load = list(range(min_year, end_year + 1))

        # Columns to read (exclude perimeter for fast initial load)
        # Include loc_id columns for location filtering
        columns = ['event_id', 'timestamp', 'latitude', 'longitude', 'area_km2',
                   'burned_acres', 'duration_days', 'land_cover', 'source', 'has_progression',
                   'loc_id', 'parent_loc_id', 'sibling_level', 'iso3', 'loc_confidence']
        if include_perimeter:
            columns.append('perimeter')

        # Load from yearly partition files with pyarrow filters
        all_tables = []
        for yr in years_to_load:
            # Use enriched files first, fallback to raw
            year_file = by_year_path / f"fires_{yr}_enriched.parquet"
            if not year_file.exists():
                year_file = by_year_path / f"fires_{yr}.parquet"
            if not year_file.exists():
                continue

            # Pyarrow predicate pushdown - only reads matching row groups
            filters = [('area_km2', '>=', min_area_km2)] if min_area_km2 is not None else None
            table = pq.read_table(
                year_file,
                columns=columns,
                filters=filters
            )
            if table.num_rows > 0:
                all_tables.append(table)

        if not all_tables:
            return msgpack_response({
                "type": "FeatureCollection",
                "features": [],
                "metadata": {"count": 0, "min_area_km2": min_area_km2, "min_year": min_year}
            })

        # Concatenate tables and convert to pandas for GeoJSON building
        combined = pa.concat_tables(all_tables)
        df = combined.to_pandas()

        # Extract year from timestamp
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['year'] = df['timestamp'].dt.year

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            # Use perimeter polygon if requested and available
            if include_perimeter and 'perimeter' in row and pd.notna(row['perimeter']):
                try:
                    geom = json_lib.loads(row['perimeter']) if isinstance(row['perimeter'], str) else row['perimeter']
                except:
                    geom = {"type": "Point", "coordinates": [float(row['longitude']), float(row['latitude'])]}
            else:
                geom = {"type": "Point", "coordinates": [float(row['longitude']), float(row['latitude'])]}

            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "event_id": row.get('event_id', ''),
                    "area_km2": float(row['area_km2']) if pd.notna(row.get('area_km2')) else None,
                    "burned_acres": float(row['burned_acres']) if pd.notna(row.get('burned_acres')) else None,
                    "duration_days": int(row['duration_days']) if pd.notna(row.get('duration_days')) else None,
                    "year": int(row['year']) if pd.notna(row.get('year')) else None,
                    "timestamp": row['timestamp'].isoformat() if pd.notna(row.get('timestamp')) else None,
                    "land_cover": row.get('land_cover', ''),
                    "source": row.get('source', 'global_fire_atlas'),
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    "has_progression": bool(row.get('has_progression', False)),
                    # Location assignment columns
                    "loc_id": row.get('loc_id', ''),
                    "parent_loc_id": row.get('parent_loc_id', ''),
                    "sibling_level": int(row['sibling_level']) if pd.notna(row.get('sibling_level')) else None,
                    "iso3": row.get('iso3', ''),
                    "loc_confidence": float(row['loc_confidence']) if pd.notna(row.get('loc_confidence')) else None
                }
            })

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "min_area_km2": min_area_km2,
                "min_year": min_year,
                "max_year": max_year or 2024,
                "include_perimeter": include_perimeter,
                "source": "Global Fire Atlas v2024"
            }
        })

    except Exception as e:
        logger.error(f"Error fetching wildfires GeoJSON: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/wildfires/{event_id}/perimeter")
async def get_wildfire_perimeter(event_id: str, year: int = None):
    """
    Get perimeter polygon for a single wildfire.
    Used for on-demand loading when user clicks a fire.

    If year is provided, reads from yearly partition (~90MB) instead of main file (2GB).
    Much more memory efficient when year is known (frontend has it from the point data).
    """
    import pyarrow.parquet as pq
    import json as json_lib

    try:
        by_year_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/wildfires/by_year")
        main_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/wildfires/fires.parquet")

        # Try yearly partition first if year provided (much more efficient)
        if year is not None and by_year_path.exists():
            year_file = by_year_path / f"fires_{year}.parquet"
            if year_file.exists():
                table = pq.read_table(
                    year_file,
                    columns=['event_id', 'perimeter'],
                    filters=[('event_id', '=', event_id)]
                )
                if table.num_rows > 0:
                    perimeter_str = table.column('perimeter')[0].as_py()
                    if perimeter_str:
                        perimeter = json_lib.loads(perimeter_str) if isinstance(perimeter_str, str) else perimeter_str
                        return msgpack_response({
                            "type": "Feature",
                            "geometry": perimeter,
                            "properties": {"event_id": event_id, "year": year}
                        })

        # Fallback: search main file (slower but works without year)
        if main_path.exists():
            table = pq.read_table(
                main_path,
                columns=['event_id', 'perimeter'],
                filters=[('event_id', '=', event_id)]
            )

            if table.num_rows == 0:
                return msgpack_error(f"Fire {event_id} not found", 404)

            perimeter_str = table.column('perimeter')[0].as_py()

            if perimeter_str is None:
                return msgpack_error("No perimeter data for this fire", 404)

            perimeter = json_lib.loads(perimeter_str) if isinstance(perimeter_str, str) else perimeter_str

            return msgpack_response({
                "type": "Feature",
                "geometry": perimeter,
                "properties": {"event_id": event_id}
            })

        return msgpack_error("Wildfire data not available", 404)

    except Exception as e:
        logger.error(f"Error fetching wildfire perimeter: {e}")
        return msgpack_error(str(e), 500)




@app.get("/api/wildfires/{event_id}/progression")
async def get_wildfire_progression(event_id: str, year: int = None):
    """
    Get daily fire progression snapshots for animation.
    Returns an array of daily perimeters showing fire spread over time.
    """
    import pyarrow.parquet as pq
    import json as json_lib

    try:
        progression_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/wildfires")

        # Try year-specific file first
        if year:
            prog_file = progression_path / f"fire_progression_{year}.parquet"
        else:
            prog_file = progression_path / "fire_progression_2024.parquet"

        if not prog_file.exists():
            return msgpack_response({
                "type": "FeatureCollection",
                "features": [],
                "metadata": {
                    "event_id": event_id,
                    "event_type": "wildfire",
                    "total_count": 0,
                    "error": "No progression data available"
                }
            })

        # Read progression data for this fire
        table = pq.read_table(
            prog_file,
            filters=[('event_id', '=', str(event_id))]
        )

        if table.num_rows == 0:
            return msgpack_response({
                "type": "FeatureCollection",
                "features": [],
                "metadata": {
                    "event_id": event_id,
                    "event_type": "wildfire",
                    "total_count": 0,
                    "error": "Fire not found in progression data"
                }
            })

        # Convert to GeoJSON FeatureCollection
        df = table.to_pandas()
        df = df.sort_values('day_num')

        features = []
        for _, row in df.iterrows():
            perimeter = json_lib.loads(row['perimeter']) if isinstance(row['perimeter'], str) else row['perimeter']
            date_str = row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])
            features.append({
                "type": "Feature",
                "geometry": perimeter,
                "properties": {
                    "date": date_str,
                    "day_num": int(row['day_num']),
                    "area_km2": float(row['area_km2'])
                }
            })

        # Get time range from dates
        time_start = df['date'].min()
        time_end = df['date'].max()

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": event_id,
                "event_type": "wildfire",
                "total_count": len(features),
                "time_range": {
                    "start": time_start.strftime('%Y-%m-%d') if hasattr(time_start, 'strftime') else str(time_start),
                    "end": time_end.strftime('%Y-%m-%d') if hasattr(time_end, 'strftime') else str(time_end)
                }
            }
        })

    except Exception as e:
        logger.error(f"Error fetching wildfire progression: {e}")
        return msgpack_error(str(e), 500)


# === Flood Data Endpoints ===

@app.get("/api/floods/geojson")
async def get_floods_geojson(
    year: int = None,
    min_year: int = 1985,
    max_year: int = None,
    include_geometry: bool = False
):
    """
    Get global floods as GeoJSON for map display.
    Data sources: Global Flood Database (2000-2018) + Dartmouth Flood Observatory (1985-2019).

    Default: Returns flood events as points (centroid of flood extent).
    Set include_geometry=true to load full flood extent polygons from GeoJSON files.

    Query params:
    - year: Filter to single year
    - min_year: Start year (default 1985)
    - max_year: End year (default current)
    - include_geometry: Load flood extent polygons (slower, more data)
    """
    import pandas as pd
    import json as json_lib

    try:
        # Use enriched file with loc_id columns
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/floods/events_enriched.parquet")
        # Fallback to raw file if enriched not available
        if not events_path.exists():
            events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/floods/events.parquet")
        geometry_dir = Path("C:/Users/Bryan/Desktop/county-map-data/global/floods/geometries")

        if not events_path.exists():
            return msgpack_error("Flood data not available", 404)

        df = pd.read_parquet(events_path)

        # Apply year filters
        if year is not None:
            df = df[df['year'] == year]
        else:
            if min_year:
                df = df[df['year'] >= min_year]
            if max_year:
                df = df[df['year'] <= max_year]

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row.get('latitude')) or pd.isna(row.get('longitude')):
                continue

            event_id = row.get('event_id', '')

            # Load geometry from perimeter column (merged from GeoJSON files) if requested
            geom = None
            if include_geometry:
                # Try perimeter column first (enriched file has merged geometries)
                perimeter = row.get('perimeter')
                if pd.notna(perimeter) and perimeter:
                    try:
                        geom = json_lib.loads(perimeter) if isinstance(perimeter, str) else perimeter
                    except Exception as e:
                        logger.warning(f"Failed to parse flood perimeter for {event_id}: {e}")

                # Fallback to GeoJSON file if no perimeter column
                if not geom and event_id:
                    geom_file = geometry_dir / f"flood_{event_id}.geojson"
                    if geom_file.exists():
                        try:
                            with open(geom_file, 'r') as f:
                                geom_data = json_lib.load(f)
                                if geom_data.get('geometry'):
                                    geom = geom_data['geometry']
                        except Exception as e:
                            logger.warning(f"Failed to load flood geometry {geom_file}: {e}")

            # Fall back to point if no geometry loaded
            if not geom:
                geom = {"type": "Point", "coordinates": [float(row['longitude']), float(row['latitude'])]}

            # Build properties
            props = {
                "event_id": event_id,
                "year": int(row['year']) if pd.notna(row.get('year')) else None,
                "timestamp": row['timestamp'].isoformat() if pd.notna(row.get('timestamp')) else None,
                "end_timestamp": row['end_timestamp'].isoformat() if pd.notna(row.get('end_timestamp')) else None,
                "duration_days": int(row['duration_days']) if pd.notna(row.get('duration_days')) else None,
                "country": str(row.get('country', '')) if pd.notna(row.get('country')) else None,
                "area_km2": float(row['area_km2']) if pd.notna(row.get('area_km2')) else None,
                "severity": int(row['severity']) if pd.notna(row.get('severity')) else None,
                "deaths": int(row['deaths']) if pd.notna(row.get('deaths')) else None,
                "displaced": int(row['displaced']) if pd.notna(row.get('displaced')) else None,
                "source": str(row.get('source', '')) if pd.notna(row.get('source')) else None,
                "has_geometry": bool(row.get('has_geometry', False)),
                "latitude": float(row['latitude']),
                "longitude": float(row['longitude']),
                # Location assignment columns
                "loc_id": str(row.get('loc_id', '')) if pd.notna(row.get('loc_id')) else None,
                "parent_loc_id": str(row.get('parent_loc_id', '')) if pd.notna(row.get('parent_loc_id')) else None,
                "sibling_level": int(row['sibling_level']) if pd.notna(row.get('sibling_level')) else None,
                "iso3": str(row.get('iso3', '')) if pd.notna(row.get('iso3')) else None,
                "loc_confidence": float(row['loc_confidence']) if pd.notna(row.get('loc_confidence')) else None
            }

            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": props
            })

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "min_year": min_year,
                "max_year": max_year or 2019,
                "include_geometry": include_geometry
            }
        })

    except Exception as e:
        logger.error(f"Error fetching floods: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/drought/geojson")
async def get_drought_geojson(
    country: str = 'CAN',
    year: int = None,
    month: int = None,
    severity: str = None,
    min_year: int = None,
    max_year: int = None
):
    """
    Get drought monitoring data as GeoJSON for choropleth animation.
    Data sources: Agriculture Canada Drought Monitor (2019-present).

    Returns monthly drought area polygons colored by severity (D0-D4).

    Query params:
    - country: Country code (default 'CAN')
    - year: Filter to single year
    - month: Filter to specific month (1-12)
    - severity: Filter to severity level (D0, D1, D2, D3, D4)
    - min_year: Start year (default 2019)
    - max_year: End year (default current)
    """
    import pandas as pd
    import json as json_lib
    from shapely import wkt
    from shapely.geometry import mapping

    try:
        # Route to correct country data file
        if country == 'CAN':
            data_path = Path("C:/Users/Bryan/Desktop/county-map-data/countries/CAN/drought/snapshots.parquet")
        else:
            return msgpack_error(f"Drought data not available for country: {country}", 404)

        if not data_path.exists():
            return msgpack_error("Drought data not available", 404)

        df = pd.read_parquet(data_path)

        # Apply filters
        if year is not None:
            df = df[df['year'] == year]
        else:
            if min_year:
                df = df[df['year'] >= min_year]
            if max_year:
                df = df[df['year'] <= max_year]

        if month is not None:
            df = df[df['month'] == month]

        if severity:
            df = df[df['severity'] == severity.upper()]

        # Sort by severity_code so D0 renders first, D4 renders last (on top)
        df = df.sort_values('severity_code')

        # Helper to convert pandas/numpy types to Python native types for msgpack
        def to_python(val):
            if pd.isna(val):
                return None
            if hasattr(val, 'item'):  # numpy scalar
                return val.item()
            return val

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            # Parse WKT geometry to GeoJSON
            geom = None
            if pd.notna(row.get('geometry')):
                try:
                    # Convert WKT to Shapely geometry, then to GeoJSON
                    shapely_geom = wkt.loads(row['geometry'])
                    geom = mapping(shapely_geom)
                except Exception as e:
                    logger.warning(f"Failed to parse drought geometry for {row.get('snapshot_id')}: {e}")
                    continue

            if not geom:
                continue

            # Build properties - convert all numpy types to native Python
            props = {
                "snapshot_id": str(row.get('snapshot_id', '')),
                "timestamp": row['timestamp'].isoformat() if pd.notna(row.get('timestamp')) else None,
                "end_timestamp": row['end_timestamp'].isoformat() if pd.notna(row.get('end_timestamp')) else None,
                "duration_days": to_python(row.get('duration_days')),
                "year": to_python(row.get('year')),
                "month": to_python(row.get('month')),
                "severity": str(row.get('severity', '')),
                "severity_code": to_python(row.get('severity_code')),
                "severity_name": str(row.get('severity_name', '')),
                "area_km2": to_python(row.get('area_km2')),
                "iso3": str(row.get('iso3', '')),
                "provinces_affected": str(row.get('provinces_affected', '')) if pd.notna(row.get('provinces_affected')) else None
            }

            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": props
            })

        # Calculate max_year safely (convert numpy type to Python int)
        max_year_value = None
        if max_year:
            max_year_value = max_year
        elif len(df) > 0:
            max_year_value = int(df['year'].max())

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "country": country,
                "min_year": min_year or 2019,
                "max_year": max_year_value
            }
        })

    except Exception as e:
        logger.error(f"Error fetching drought data: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/floods/{event_id}/geometry")
async def get_flood_geometry(event_id: str):
    """
    Get the flood extent polygon for a specific flood event.
    Returns the GeoJSON geometry for displaying the flooded area.
    """
    import json as json_lib

    try:
        geometry_dir = Path("C:/Users/Bryan/Desktop/county-map-data/global/floods/geometries")
        geom_file = geometry_dir / f"flood_{event_id}.geojson"

        if not geom_file.exists():
            return msgpack_error(f"Geometry not found for {event_id}", 404)

        with open(geom_file, 'r') as f:
            geom_data = json_lib.load(f)

        return msgpack_response(geom_data)

    except Exception as e:
        logger.error(f"Error fetching flood geometry: {e}")
        return msgpack_error(str(e), 500)


# === Tornado Data Endpoints ===

@app.get("/api/tornadoes/geojson")
async def get_tornadoes_geojson(year: int = None, min_year: int = 1990, min_scale: str = None):
    """
    Get tornadoes as GeoJSON points for map display.
    Default: tornadoes from 1990-present (most reliable data).
    Filter by EF/F scale (e.g., 'EF3' or 'F3').

    Only returns "starter" tornadoes for initial display:
    - Standalone tornadoes (no sequence)
    - First tornado in each sequence (sequence_position == 1)

    Linked tornadoes are fetched on-demand via /api/tornadoes/{id}/sequence
    when user clicks "View tornado sequence".

    Data sources: USA (NOAA 1950+), Canada (CNTD 1980-2009, NTP 2017+)
    """
    import pandas as pd

    try:
        # Global tornadoes dataset (USA + Canada)
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tornadoes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Tornado data not available", 404)

        df = pd.read_parquet(events_path)

        # Already filtered to tornadoes only in global dataset
        df = df.copy()

        # Extract year from timestamp
        time_col = 'timestamp' if 'timestamp' in df.columns else 'time'
        if time_col in df.columns:
            df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
            df['year'] = df[time_col].dt.year

        # Apply filters
        if year is not None and 'year' in df.columns:
            df = df[df['year'] == year]
        elif min_year is not None and 'year' in df.columns:
            df = df[df['year'] >= min_year]

        if min_scale is not None and 'tornado_scale' in df.columns:
            # Parse scale to numeric for comparison
            def parse_scale(s):
                if pd.isna(s):
                    return -1
                s = str(s).upper().replace('EF', '').replace('F', '')
                try:
                    return int(s)
                except:
                    return -1
            df['_scale_num'] = df['tornado_scale'].apply(parse_scale)
            min_num = parse_scale(min_scale)
            df = df[df['_scale_num'] >= min_num]

        # Filter to starter events only:
        # - Standalone tornadoes (sequence_id is null/NA)
        # - First tornado in each sequence (sequence_position == 1)
        if 'sequence_id' in df.columns and 'sequence_position' in df.columns:
            is_standalone = df['sequence_id'].isna()
            is_sequence_start = df['sequence_position'] == 1
            df = df[is_standalone | is_sequence_start]

        # Build GeoJSON features
        features = []
        for _, row in df.iterrows():
            if pd.isna(row['latitude']) or pd.isna(row['longitude']):
                continue

            time_val = row.get('timestamp') or row.get('time')

            # Include sequence info so frontend knows if "View sequence" is available
            sequence_count = int(row['sequence_count']) if pd.notna(row.get('sequence_count')) else None
            has_sequence = sequence_count is not None and sequence_count > 1

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": str(row.get('event_id', '')),
                    "tornado_scale": row.get('tornado_scale', ''),
                    "tornado_length_mi": float(row['tornado_length_mi']) if pd.notna(row.get('tornado_length_mi')) else 0,
                    "tornado_width_yd": int(row['tornado_width_yd']) if pd.notna(row.get('tornado_width_yd')) else 0,
                    "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 5,
                    "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 0.05,
                    "timestamp": str(time_val) if pd.notna(time_val) else None,
                    "year": int(row['year']) if 'year' in row and pd.notna(row['year']) else None,
                    "deaths_direct": int(row['deaths_direct']) if pd.notna(row.get('deaths_direct')) else 0,
                    "injuries_direct": int(row['injuries_direct']) if pd.notna(row.get('injuries_direct')) else 0,
                    "damage_property": int(row['damage_property']) if pd.notna(row.get('damage_property')) else 0,
                    "location": row.get('location', ''),
                    "loc_id": row.get('loc_id', ''),
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    # Track end point for drill-down
                    "end_latitude": float(row['end_latitude']) if pd.notna(row.get('end_latitude')) else None,
                    "end_longitude": float(row['end_longitude']) if pd.notna(row.get('end_longitude')) else None,
                    # Sequence info for "View sequence" button
                    "sequence_count": sequence_count,
                    "has_sequence": has_sequence,
                    # Event type for model routing
                    "event_type": "tornado"
                }
            })

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as e:
        logger.error(f"Error fetching tornadoes GeoJSON: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/tornadoes/{event_id}")
async def get_tornado_detail(event_id: str):
    """
    Get detailed info for a single tornado including track endpoints.
    Returns start point, end point, track line, and impact radius for drill-down view.
    """
    import pandas as pd

    try:
        # Global tornadoes dataset (USA + Canada)
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tornadoes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Tornado data not available", 404)

        df = pd.read_parquet(events_path)

        # Find the specific tornado (event_id is always string in parquet)
        tornado = df[df['event_id'].astype(str) == str(event_id)]

        if len(tornado) == 0:
            return msgpack_error("Tornado not found", 404)

        row = tornado.iloc[0]

        # Build response with track data
        time_col = 'timestamp' if 'timestamp' in row.index else 'time'
        time_val = row.get(time_col)
        timestamp_str = str(time_val) if pd.notna(time_val) else None

        # Calculate impact width in km (yards to km)
        width_km = (row.get('tornado_width_yd', 0) or 0) * 0.0009144

        # Common properties for all features
        props = {
            "event_id": str(row['event_id']),
            "tornado_scale": row.get('tornado_scale', ''),
            "tornado_length_mi": float(row['tornado_length_mi']) if pd.notna(row.get('tornado_length_mi')) else 0,
            "tornado_width_yd": int(row['tornado_width_yd']) if pd.notna(row.get('tornado_width_yd')) else 0,
            "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 5,
            "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 0.05,
            "width_km": width_km,
            "timestamp": timestamp_str,
            "deaths_direct": int(row['deaths_direct']) if pd.notna(row.get('deaths_direct')) else 0,
            "deaths_indirect": int(row['deaths_indirect']) if pd.notna(row.get('deaths_indirect')) else 0,
            "injuries_direct": int(row['injuries_direct']) if pd.notna(row.get('injuries_direct')) else 0,
            "injuries_indirect": int(row['injuries_indirect']) if pd.notna(row.get('injuries_indirect')) else 0,
            "damage_property": int(row['damage_property']) if pd.notna(row.get('damage_property')) else 0,
            "damage_crops": int(row['damage_crops']) if pd.notna(row.get('damage_crops')) else 0,
            "location": row.get('location', ''),
            "loc_id": row.get('loc_id', '')
        }

        features = []

        # Start point feature
        start_lat = float(row['latitude'])
        start_lon = float(row['longitude'])
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [start_lon, start_lat]
            },
            "properties": {**props, "point_type": "start"}
        })

        # Add track LineString if we have both endpoints
        end_lat = float(row['end_latitude']) if pd.notna(row.get('end_latitude')) else None
        end_lon = float(row['end_longitude']) if pd.notna(row.get('end_longitude')) else None

        if end_lat is not None and end_lon is not None:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[start_lon, start_lat], [end_lon, end_lat]]
                },
                "properties": {**props, "geometry_type": "track"}
            })

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": str(row['event_id']),
                "event_type": "tornado",
                "total_count": len(features),
                "time_range": {
                    "start": timestamp_str,
                    "end": timestamp_str
                }
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tornado detail: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/tornadoes/{event_id}/sequence")
async def get_tornado_sequence(event_id: str):
    """
    Get a sequence of linked tornadoes (same storm system).
    Uses pre-computed sequence_id from data import (like earthquake aftershocks).
    Note: Sequences currently only available for USA tornadoes (1hr/10km linking).
    """
    import pandas as pd

    try:
        # Global tornadoes dataset (USA + Canada)
        events_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tornadoes/events.parquet")

        if not events_path.exists():
            return msgpack_error("Tornado data not available", 404)

        df = pd.read_parquet(events_path)
        # Already filtered to tornadoes only in global dataset

        # Find the seed tornado (event_id is always string in parquet)
        seed = df[df['event_id'].astype(str) == str(event_id)]

        if len(seed) == 0:
            return msgpack_error("Tornado not found", 404)

        seed_row = seed.iloc[0]

        # Check if this tornado has a sequence_id (pre-computed during import)
        sequence_id = seed_row.get('sequence_id')
        if pd.isna(sequence_id) or sequence_id is None:
            # No linked sequence - return just this tornado for single-path animation
            sequence_df = seed.copy()
        else:
            # Get all tornadoes in this sequence
            sequence_df = df[df['sequence_id'] == sequence_id].copy()

        # Sort by sequence_position (or timestamp as fallback)
        if 'sequence_position' in sequence_df.columns and sequence_df['sequence_position'].notna().any():
            sequence_df = sequence_df.sort_values('sequence_position')
        elif 'timestamp' in sequence_df.columns:
            sequence_df = sequence_df.sort_values('timestamp')

        # Extract year from timestamp if not present
        if 'year' not in sequence_df.columns and 'timestamp' in sequence_df.columns:
            sequence_df['timestamp'] = pd.to_datetime(sequence_df['timestamp'], errors='coerce')
            sequence_df['year'] = sequence_df['timestamp'].dt.year

        # Build GeoJSON features
        features = []
        for pos, (idx, row) in enumerate(sequence_df.iterrows(), 1):
            time_val = row.get('timestamp')
            raw_scale = row.get('tornado_scale', '')
            scale = str(raw_scale).upper() if pd.notna(raw_scale) else ''

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row['longitude']), float(row['latitude'])]
                },
                "properties": {
                    "event_id": str(row.get('event_id', '')),
                    "tornado_scale": scale if scale else '',
                    "tornado_length_mi": float(row['tornado_length_mi']) if pd.notna(row.get('tornado_length_mi')) else 0,
                    "tornado_width_yd": int(row['tornado_width_yd']) if pd.notna(row.get('tornado_width_yd')) else 0,
                    "felt_radius_km": float(row['felt_radius_km']) if pd.notna(row.get('felt_radius_km')) else 5,
                    "damage_radius_km": float(row['damage_radius_km']) if pd.notna(row.get('damage_radius_km')) else 0.05,
                    "timestamp": str(time_val) if pd.notna(time_val) else None,
                    "year": int(row['year']) if 'year' in row and pd.notna(row['year']) else None,
                    "deaths_direct": int(row['deaths_direct']) if pd.notna(row.get('deaths_direct')) else 0,
                    "injuries_direct": int(row['injuries_direct']) if pd.notna(row.get('injuries_direct')) else 0,
                    "damage_property": float(row['damage_property']) if pd.notna(row.get('damage_property')) else 0,
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    "end_latitude": float(row['end_latitude']) if pd.notna(row.get('end_latitude')) else None,
                    "end_longitude": float(row['end_longitude']) if pd.notna(row.get('end_longitude')) else None,
                    "is_seed": str(row.get('event_id', '')) == str(seed_row.get('event_id', '')),
                    "sequence_position": int(row['sequence_position']) if pd.notna(row.get('sequence_position')) else pos,
                    "sequence_count": int(row['sequence_count']) if pd.notna(row.get('sequence_count')) else len(sequence_df),
                    "event_type": "tornado",
                    "location": str(row.get('location', '')) if pd.notna(row.get('location')) else ''
                }
            }

            # Add track geometry if end coordinates exist
            if pd.notna(row.get('end_latitude')) and pd.notna(row.get('end_longitude')):
                feature["properties"]["track"] = {
                    "type": "LineString",
                    "coordinates": [
                        [float(row['longitude']), float(row['latitude'])],
                        [float(row['end_longitude']), float(row['end_latitude'])]
                    ]
                }

            features.append(feature)

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "event_id": str(seed_row.get('event_id', '')),
                "event_type": "tornado",
                "total_count": len(features),
                "sequence_id": str(sequence_id) if pd.notna(sequence_id) else None
            }
        })

    except Exception as e:
        logger.error(f"Error fetching tornado sequence: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Storm data not available", 404)

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

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        })

    except Exception as e:
        logger.error(f"Error fetching storms GeoJSON: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Storm data not available", 404)

        positions_df = pd.read_parquet(positions_path)
        storm_positions = positions_df[positions_df['storm_id'] == storm_id].sort_values('timestamp')

        if len(storm_positions) == 0:
            return msgpack_error(f"Storm {storm_id} not found", 404)

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

        return msgpack_response({
            "storm_id": storm_id,
            "name": storm_name,
            "positions": positions,
            "count": len(positions)
        })

    except Exception as e:
        logger.error(f"Error fetching storm track: {e}")
        return msgpack_error(str(e), 500)


@app.get("/api/storms/tracks/geojson")
async def get_storm_tracks_geojson(year: int = None, min_year: int = 1950, basin: str = None, min_category: str = None):
    """
    Get storm tracks as GeoJSON LineStrings for yearly overview display.
    Each storm is a LineString colored by max category.
    Loads all storms from min_year (default 1950) to present.
    Optional min_category filter: TD, TS, Cat1, Cat2, Cat3, Cat4, Cat5
    """
    import pandas as pd

    try:
        storms_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/storms.parquet")
        positions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms/positions.parquet")

        if not storms_path.exists():
            return msgpack_error("Storm data not available", 404)

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

        # Category filter - filter by minimum category
        if min_category is not None:
            cat_order = {'TD': 0, 'TS': 1, 'Cat1': 2, 'Cat2': 3, 'Cat3': 4, 'Cat4': 5, 'Cat5': 6}
            min_cat_val = cat_order.get(min_category, 0)
            storms_df['cat_val'] = storms_df['max_category'].map(lambda x: cat_order.get(x, 0))
            storms_df = storms_df[storms_df['cat_val'] >= min_cat_val]
            storms_df = storms_df.drop(columns=['cat_val'])

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

        logger.info(f"Returning {len(features)} storm tracks for year={year}, min_year={min_year}, basin={basin}, min_category={min_category}")

        return msgpack_response({
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        })

    except Exception as e:
        logger.error(f"Error fetching storm tracks GeoJSON: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_error("Storm data not available", 404)

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

        return msgpack_response({
            "storms": storms,
            "count": len(storms)
        })

    except Exception as e:
        logger.error(f"Error fetching storms list: {e}")
        return msgpack_error(str(e), 500)


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
            return msgpack_response(data)
        else:
            return msgpack_error("admin_levels.json not found", 404)
    except Exception as e:
        logger.error(f"Error loading admin_levels.json: {e}")
        return msgpack_error(str(e), 500)


# === Settings Endpoints ===

@app.get("/settings")
async def get_settings():
    """
    Get current application settings.
    Returns backup path and folder existence status.
    """
    try:
        settings = get_settings_with_status()
        return msgpack_response(settings)
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return msgpack_error(str(e), 500)


@app.post("/settings")
async def update_settings(req: Request):
    """
    Update application settings.
    Accepts: { backup_path: "..." }
    """
    try:
        data = await decode_request_body(req)
        backup_path = data.get("backup_path", "")

        # Save the settings
        success = save_settings({"backup_path": backup_path})

        if success:
            settings = get_settings_with_status()
            return msgpack_response({"success": True, "settings": settings})
        else:
            return msgpack_error("Failed to save settings", 500)
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return msgpack_error(str(e), 500)


@app.post("/settings/init-folders")
async def initialize_folders(req: Request):
    """
    Initialize the backup folder structure.
    Creates geometry/ and data/ folders at the backup path.
    """
    try:
        data = await decode_request_body(req)
        backup_path = data.get("backup_path", "")

        if not backup_path:
            return msgpack_error("Backup path is required", 400)

        # Save the path and create folders
        save_settings({"backup_path": backup_path})
        folders = init_backup_folders(backup_path)

        return msgpack_response({
            "success": True,
            "folders": folders,
            "message": f"Initialized folders at {backup_path}"
        })
    except Exception as e:
        logger.error(f"Error initializing folders: {e}")
        return msgpack_error(str(e), 500)


# === Filter Intent Handler (Overlay Integration) ===

def handle_filter_intent(filter_intent: dict, cache_stats: dict, active_overlays: dict) -> dict:
    """
    Handle filter-related queries without LLM call.

    Returns response dict or None if should fall through to LLM.
    """
    if not filter_intent:
        return None

    intent_type = filter_intent.get("type")
    overlay = filter_intent.get("overlay")

    if intent_type == "read_filters":
        # User is asking about current filters - respond from cache
        if not overlay:
            return {
                "type": "chat",
                "message": "No overlay is currently active. Enable an overlay from the right panel to see event data.",
                "from_cache": True
            }

        stats = cache_stats.get(overlay, {}) if cache_stats else {}
        filters = active_overlays.get("filters", {}) if active_overlays else {}
        count = stats.get("count", 0)

        # Build response message based on overlay type
        if overlay == "earthquakes":
            min_mag = stats.get("minMag") or filters.get("minMagnitude", "?")
            max_mag = stats.get("maxMag") or "?"
            message = f"Currently showing {count} earthquakes"
            if min_mag != "?":
                message += f", magnitude {min_mag} to {max_mag}"
            message += "."
        elif overlay == "hurricanes":
            cats = stats.get("categories", [])
            message = f"Currently showing {count} hurricanes"
            if cats:
                message += f" (categories: {', '.join(str(c) for c in cats)})"
            message += "."
        elif overlay == "wildfires":
            min_area = stats.get("minAreaKm2") or filters.get("minAreaKm2", "?")
            message = f"Currently showing {count} wildfires"
            if min_area != "?":
                message += f" (minimum {min_area} km2)"
            message += "."
        elif overlay == "volcanoes":
            min_vei = stats.get("minVei") or filters.get("minVei", "?")
            max_vei = stats.get("maxVei") or "?"
            message = f"Currently showing {count} volcanic eruptions"
            if min_vei != "?":
                message += f", VEI {min_vei} to {max_vei}"
            message += "."
        elif overlay == "tornadoes":
            scales = stats.get("scales", [])
            message = f"Currently showing {count} tornadoes"
            if scales:
                message += f" (scales: {', '.join(str(s) for s in scales)})"
            message += "."
        else:
            message = f"Currently showing {count} {overlay} events."

        # Add year range if available
        years = stats.get("years", [])
        if years and len(years) > 0:
            message += f" Data loaded for {years[0]}-{years[-1]}."

        return {
            "type": "cache_answer",
            "message": message,
            "from_cache": True,
            "overlay": overlay,
            "stats": stats
        }

    elif intent_type == "change_filters":
        # User wants to change filters - return filter_update response
        new_filters = {}

        if "minMagnitude" in filter_intent:
            new_filters["minMagnitude"] = filter_intent["minMagnitude"]
        if "maxMagnitude" in filter_intent:
            new_filters["maxMagnitude"] = filter_intent["maxMagnitude"]
        if "minVei" in filter_intent:
            new_filters["minVei"] = filter_intent["minVei"]
        if "minCategory" in filter_intent:
            new_filters["minCategory"] = filter_intent["minCategory"]
        if "minScale" in filter_intent:
            new_filters["minScale"] = filter_intent["minScale"]
        if "minAreaKm2" in filter_intent:
            new_filters["minAreaKm2"] = filter_intent["minAreaKm2"]
        if filter_intent.get("clear"):
            new_filters["clear"] = True

        # Build confirmation message
        if new_filters.get("clear"):
            message = f"Clearing filters for {overlay}. Showing all events."
        else:
            filter_parts = []
            if "minMagnitude" in new_filters and "maxMagnitude" in new_filters:
                filter_parts.append(f"magnitude {new_filters['minMagnitude']}-{new_filters['maxMagnitude']}")
            elif "minMagnitude" in new_filters:
                filter_parts.append(f"magnitude {new_filters['minMagnitude']}+")
            elif "maxMagnitude" in new_filters:
                filter_parts.append(f"magnitude up to {new_filters['maxMagnitude']}")
            if "minVei" in new_filters:
                filter_parts.append(f"VEI {new_filters['minVei']}+")
            if "minCategory" in new_filters:
                filter_parts.append(f"category {new_filters['minCategory']}+")
            if "minScale" in new_filters:
                filter_parts.append(f"EF{new_filters['minScale']}+")
            if "minAreaKm2" in new_filters:
                filter_parts.append(f"area {new_filters['minAreaKm2']}+ km2")

            message = f"Updating {overlay} to show " + ", ".join(filter_parts) + "."

        return {
            "type": "filter_update",
            "message": message,
            "overlay": overlay,
            "filters": new_filters
        }

    return None


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
        body = await decode_request_body(req)

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
                return msgpack_response(response)
            except Exception as e:
                logger.error(f"Order execution error: {e}")
                return msgpack_response({
                    "type": "error",
                    "message": str(e)
                }, status_code=400)

        # Otherwise, interpret the natural language request
        query = body.get("query", "")
        chat_history = body.get("chatHistory", [])
        viewport = body.get("viewport")  # {center, zoom, bounds, adminLevel}
        resolved_location = body.get("resolved_location")  # From disambiguation selection
        active_overlays = body.get("activeOverlays")  # {type, filters, allActive}
        cache_stats = body.get("cacheStats")  # {overlayId: {count, years, minMag, ...}}

        if not query:
            return msgpack_error("No query provided", 400)

        logger.debug(f"Chat query: {query[:100]}...")
        if active_overlays and active_overlays.get("type"):
            logger.debug(f"Active overlay: {active_overlays.get('type')} with filters: {active_overlays.get('filters')}")

        # Run preprocessor to extract hints (Tier 2) with viewport context
        hints = preprocess_query(query, viewport=viewport, active_overlays=active_overlays, cache_stats=cache_stats)
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

                return msgpack_response({
                    "type": "navigate",
                    "message": f"Showing {len(loc_ids_to_show)} locations on the map. Click any location to see data options.",
                    "locations": previous_options if previous_options else [{"loc_id": lid} for lid in loc_ids_to_show],
                    "loc_ids": loc_ids_to_show,
                    "original_query": query,
                    "geojson": geojson,
                })
            else:
                # No previous disambiguation found - tell user
                return msgpack_response({
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
                return msgpack_response({
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

            return msgpack_response({
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

            return msgpack_response({
                "type": "disambiguate",
                "message": f"I found {len(options)} locations matching '{query_term}'. Please click on the one you meant:",
                "query_term": query_term,
                "original_query": query,
                "options": options,  # List of {matched_term, iso3, country_name, loc_id, admin_level}
                "geojson": {"type": "FeatureCollection", "features": []},
            })

        # Check for filter intent - respond from cache without LLM call
        filter_intent = hints.get("filter_intent")
        if filter_intent:
            filter_response = handle_filter_intent(filter_intent, cache_stats, active_overlays)
            if filter_response:
                logger.debug(f"Filter intent handled: {filter_intent.get('type')}")
                return msgpack_response(filter_response)

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
            return msgpack_response({
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
            return msgpack_response({
                "type": "clarify",
                "message": result["message"],
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": True
            })
        else:
            # General chat response (not a data request)
            return msgpack_response({
                "type": "chat",
                "message": result["message"],
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": False
            })

    except Exception as e:
        logger.error(f"Chat error: {e}")
        traceback.print_exc()
        return msgpack_response({
            "type": "error",
            "message": "Sorry, I encountered an error. Please try again.",
            "geojson": {"type": "FeatureCollection", "features": []},
            "error": str(e)
        }, status_code=500)


# === Main Entry Point ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)
