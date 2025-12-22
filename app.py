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
    get_data_catalog,
    get_ultimate_metadata,
    # Geography
    load_conversions,
    # Logging
    logger,
    log_conversation,
    log_error_to_cloud,
    # Meta queries
    detect_meta_query,
    handle_meta_query,
    # Map state
    get_map_state,
    # Chat handlers
    fetch_and_return_data,
    determine_chat_intent,
    handle_modify_request,
)

# Geometry handlers (parquet-based)
from mapmover.geometry_handlers import (
    get_countries_geometry as get_countries_geometry_handler,
    get_location_children as get_location_children_handler,
    get_location_places as get_location_places_handler,
    get_location_info,
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


@app.post("/geometry/cache/clear")
async def clear_geometry_cache_endpoint():
    """Clear the geometry cache. Useful after updating data files."""
    try:
        clear_geometry_cache()
        return JSONResponse(content={"message": "Geometry cache cleared"})
    except Exception as e:
        logger.error(f"Error clearing geometry cache: {e}")
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
    Creates geometry/, data/, metadata/ folders at the backup path.
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


# === Data Endpoints ===

@app.post("/location")
async def location_endpoint(req: Request):
    """
    Legacy endpoint for direct data queries (used by embedded widget).
    Delegates to fetch_and_return_data for unified code path.
    """
    try:
        data = await req.json()
        user_query = data.get("query", "")
        current_view = data.get("currentView", {})

        if not user_query:
            return JSONResponse(content={"error": "No query provided"}, status_code=400)

        logger.debug(f"=== Processing query via /location: {user_query} ===")

        # Check for meta query
        meta_type = detect_meta_query(user_query)
        if meta_type:
            logger.debug(f"Detected meta query type: {meta_type}")
            meta_response = handle_meta_query(meta_type, user_query, get_ultimate_metadata(), get_data_catalog())
            return JSONResponse(content={
                "geojson": {"type": "FeatureCollection", "features": []},
                "meta_response": meta_response,
                "message": meta_response.get('answer', ''),
                "selected_file": "metadata",
                "is_meta_query": True
            })

        # Delegate to unified data fetching
        return await fetch_and_return_data(user_query, current_view, display_immediately=True, endpoint="location")

    except Exception as e:
        error_details = {
            "timestamp": datetime.now().isoformat(),
            "error_type": type(e).__name__,
            "query": user_query if 'user_query' in locals() else "Unknown",
            "error_message": str(e),
            "traceback": traceback.format_exc()
        }
        logger.error(f"Unexpected Error: {json.dumps(error_details, indent=2)}")
        log_error_to_cloud(type(e).__name__, str(e),
                         query=user_query if 'user_query' in locals() else None,
                         tb=traceback.format_exc())
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/chat")
async def chat_endpoint(req: Request):
    """
    Conversational chat endpoint that supports back-and-forth dialogue.
    Uses a two-stage approach:
    1. Conversation LLM decides intent (chat, clarify, or fetch data)
    2. If fetch data, uses the existing query parsing chain
    """
    try:
        data = await req.json()
        user_query = data.get("query", "")
        current_view = data.get("currentView", {})
        chat_history = data.get("chatHistory", [])
        session_id = data.get("sessionId")

        if not user_query:
            return JSONResponse(content={"error": "No query provided"}, status_code=400)

        logger.debug(f"Chat query: {user_query[:100]}...")
        logger.debug(f"Chat history length: {len(chat_history)}, session: {session_id}")

        # Build conversation context
        history_context = ""
        if chat_history:
            recent_history = chat_history[-6:]
            for msg in recent_history:
                role = "User" if msg.get("role") == "user" else "Assistant"
                content = msg.get("content", "")
                history_context += f"{role}: {content}\n"

        # Stage 1: Determine intent
        intent_result = await determine_chat_intent(user_query, history_context)
        logger.debug(f"Chat intent: {intent_result.get('intent', 'unknown')}")

        intent = intent_result.get("intent", "chat")
        response_text = intent_result.get("response", "")

        # Handle different intents
        if intent == "fetch_data":
            data_query = intent_result.get("data_query", user_query)
            wants_immediate_display = intent_result.get("display_immediately", False)
            return await fetch_and_return_data(
                data_query, current_view, wants_immediate_display,
                endpoint="chat", session_id=session_id
            )

        elif intent == "clarify":
            log_conversation(
                session_id=session_id,
                query=user_query,
                response_text=response_text,
                intent="clarify",
                endpoint="chat"
            )
            return JSONResponse(content={
                "message": response_text,
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": True
            })

        elif intent == "modify_data":
            modify_action = intent_result.get("modify_action", "")
            return await handle_modify_request(modify_action, current_view, session_id=session_id)

        elif intent == "meta":
            meta_type = detect_meta_query(user_query)
            if meta_type:
                meta_response = handle_meta_query(meta_type, user_query, get_ultimate_metadata(), get_data_catalog())
                final_response = meta_response.get('answer', response_text)
                log_conversation(
                    session_id=session_id,
                    query=user_query,
                    response_text=final_response,
                    intent="meta",
                    endpoint="chat"
                )
                return JSONResponse(content={
                    "message": final_response,
                    "geojson": {"type": "FeatureCollection", "features": []},
                    "needsMoreInfo": False,
                    "is_meta_query": True
                })
            else:
                log_conversation(
                    session_id=session_id,
                    query=user_query,
                    response_text=response_text,
                    intent="meta",
                    endpoint="chat"
                )
                return JSONResponse(content={
                    "message": response_text,
                    "geojson": {"type": "FeatureCollection", "features": []},
                    "needsMoreInfo": False
                })

        else:
            # General conversation
            log_conversation(
                session_id=session_id,
                query=user_query,
                response_text=response_text,
                intent="chat",
                endpoint="chat"
            )
            return JSONResponse(content={
                "message": response_text,
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": False
            })

    except Exception as e:
        logger.error(f"Chat error: {e}")
        traceback.print_exc()
        return JSONResponse(content={
            "message": "Sorry, I encountered an error. Please try again.",
            "geojson": {"type": "FeatureCollection", "features": []},
            "error": str(e)
        }, status_code=500)


# === Main Entry Point ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)
