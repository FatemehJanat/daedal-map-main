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
