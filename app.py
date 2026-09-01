"""
County Map API - FastAPI entry point.

This file is intentionally thin:
- app setup
- middleware/static mounting
- router registration
- startup initialization
"""

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import msgpack
from mapmover.runtime_env_files import runtime_env_file_candidates


def _load_runtime_env() -> None:
    """Load local env files before mapmover imports resolve runtime config."""
    workspace_root = Path(__file__).resolve().parents[1]
    for env_path in runtime_env_file_candidates(workspace_root):
        if env_path.exists():
            load_dotenv(env_path, override=False)


_load_runtime_env()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from agent_surface_shared import render_app_llms_txt
from mapmover import initialize_catalog, load_conversions, logger
from mapmover.auth_context import get_authenticated_user, get_authenticated_user_async
from mapmover.logging_analytics import hash_ip_for_analytics, log_app_error, log_route_request_event
from mapmover.security import (
    get_allowed_origins,
    get_client_ip,
    is_https_request,
    log_startup_security_warnings,
    rate_limiter,
)
from mapmover.order_executor import execute_order
from mapmover.order_queue import processor as order_processor
from mapmover.routes.chat import router as chat_router
from mapmover.routes.api_query import router as api_query_router
from mapmover.routes.artifacts import router as artifacts_router
from mapmover.routes.disasters.earthquakes import router as earthquakes_router
from mapmover.routes.disasters.floods import router as floods_router
from mapmover.routes.disasters.hurricanes import router as hurricanes_router
from mapmover.routes.disasters.landslides import router as landslides_router
from mapmover.routes.disasters.nws_historical import router as nws_historical_router
from mapmover.routes.disasters.related import router as related_events_router
from mapmover.routes.disasters.tornadoes import router as tornadoes_router
from mapmover.routes.disasters.tsunamis import router as tsunamis_router
from mapmover.routes.disasters.volcanoes import router as volcanoes_router
from mapmover.routes.disasters.wildfires import router as wildfires_router
from mapmover.routes.raster import router as raster_router
from mapmover.routes.geometry import router as geometry_router
from mapmover.routes.mcp import router as mcp_router
from mapmover.routes.ops import router as ops_router
from mapmover.routes.private_mcp import router as private_mcp_router
from mapmover.routes.research import router as research_router
from mapmover.prewarm_status import begin_prewarm, run_prewarm_task
from mapmover.routes.system import prewarm_public_pack_catalog, router as system_router
from mapmover.routes.system import _require_local_or_admin
from mapmover.routes.weather import router as weather_router
from mapmover.runtime_build_info import runtime_build_info
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response


if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
SECURITY_TXT_PATH = BASE_DIR / "static" / "security.txt"
ROAD_NETWORK_PATH = BASE_DIR / "static" / "data" / "tiger2020_lake_county_primary_secondary_roads.geojson"
ROAD_NETWORK_BACKUP_DIR = BASE_DIR / "static" / "data" / "road_network_backups"


def _get_request_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _parse_env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _get_402index_verify_token() -> str:
    return str(os.getenv("INDEX402_VERIFY_TOKEN", "")).strip()


def _classify_route_surface(path: str) -> str:
    path = str(path or "").strip()
    if path.startswith("/mcp-private/"):
        return "private_mcp"
    if path == "/api/v1/query/dataset":
        return "agent_api_paid"
    if path == "/mcp" or path.startswith("/mcp/"):
        return "agent_api_mcp"
    if path == "/apis.json" or path.startswith("/.well-known/mcp/"):
        return "agent_api_discovery"
    if path == "/api/v1/guide" or path == "/api/v1/catalog" or path.startswith("/api/v1/packs/"):
        return "agent_api_discovery"
    if path.startswith("/api/catalog/packs"):
        return "human_app_catalog"
    return "shared_runtime"


def _rate_limit_config_for_surface(surface: str) -> tuple[int, int] | None:
    if surface == "private_mcp":
        return None
    if surface == "agent_api_discovery":
        return (
            _parse_env_int("AGENT_API_DISCOVERY_RATE_LIMIT", 25),
            _parse_env_int("AGENT_API_DISCOVERY_RATE_WINDOW_SECONDS", 10),
        )
    if surface == "human_app_catalog":
        return (
            _parse_env_int("APP_CATALOG_RATE_LIMIT", 60),
            _parse_env_int("APP_CATALOG_RATE_WINDOW_SECONDS", 10),
        )
    if surface == "agent_api_paid":
        return (
            _parse_env_int("AGENT_API_PAID_RATE_LIMIT", 12),
            _parse_env_int("AGENT_API_PAID_RATE_WINDOW_SECONDS", 60),
        )
    if surface == "agent_api_mcp":
        return (
            _parse_env_int("AGENT_API_MCP_RATE_LIMIT", 30),
            _parse_env_int("AGENT_API_MCP_RATE_WINDOW_SECONDS", 60),
        )
    return None


def _shared_runtime_rate_limit_for_path(path: str) -> tuple[int, int] | None:
    path = str(path or "").strip()
    if path.startswith("/api/") or path.startswith("/geometry/"):
        return (
            _parse_env_int("SHARED_RUNTIME_ANON_RATE_LIMIT", 120),
            _parse_env_int("SHARED_RUNTIME_ANON_RATE_WINDOW_SECONDS", 60),
        )
    return None


def _rate_limit_response(surface: str, retry_after: int):
    messages = {
        "agent_api_discovery": "Too many agent API discovery requests. Please slow down and try again shortly.",
        "human_app_catalog": "Too many catalog requests. Please slow down and try again shortly.",
        "agent_api_paid": "Too many paid API requests. Please wait a moment and try again.",
        "agent_api_mcp": "Too many MCP requests. Please wait a moment and try again.",
    }
    response = JSONResponse(
        {
            "error": messages.get(surface, "Too many requests."),
            "retry_after": retry_after,
            "surface": surface,
        },
        status_code=429,
    )
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Daedal-Surface"] = surface
    return response


def _apply_surface_headers(response, request: Request, surface: str) -> None:
    response.headers["X-Daedal-Surface"] = surface
    build_info = runtime_build_info()
    commit_short = build_info.get("commit_short") or ""
    if commit_short:
        response.headers["X-Daedal-Build"] = commit_short
    if build_info.get("branch"):
        response.headers["X-Daedal-Branch"] = build_info["branch"]
    if surface == "agent_api_discovery":
        response.headers["Cache-Control"] = "public, max-age=300, s-maxage=300"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Vary"] = "Accept, Accept-Encoding, Origin"
        return
    if surface == "human_app_catalog":
        response.headers["Cache-Control"] = "public, max-age=120, s-maxage=120"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Vary"] = "Accept, Accept-Encoding, Origin"
        return
    if surface == "agent_api_paid":
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Vary"] = "Accept, Accept-Encoding, Authorization, Origin"
        return
    if surface == "agent_api_mcp":
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Vary"] = "Accept, Accept-Encoding, Authorization, Origin, MCP-Protocol-Version"
        return
    if surface == "private_mcp":
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Vary"] = "Accept, Accept-Encoding, Authorization, Origin, MCP-Protocol-Version"
        return
    if str(request.url.path or "").startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize data catalog, conversions, and order processor on startup."""
    import asyncio
    import threading

    logger.info("Starting county-map API...")
    log_startup_security_warnings(logger)
    load_conversions()
    initialize_catalog()

    async def async_execute_order(items, hints):
        loop = asyncio.get_event_loop()
        order = {"items": items, "summary": hints.get("summary", "")}
        return await loop.run_in_executor(None, execute_order, order)

    order_processor.set_executor(async_execute_order)
    await order_processor.start()
    logger.info("Startup complete - data catalog and order processor initialized")

    # Fire pre-warmers in background threads so startup is not blocked.
    # In cloud mode this populates DuckDB httpfs metadata cache, our in-memory
    # DataFrame cache, and the geometry cache so cold object-storage fetches do not hit
    # the first user requests.
    try:
        from mapmover.data_loading import prewarm_api_catalog
        from mapmover.duckdb_helpers import is_cloud_mode, prewarm_disaster_sources
        from mapmover.geometry_handlers import prewarm_geometry
        from mapmover.paths import GLOBAL_DIR
        tasks = ["public_pack_catalog", "api_catalog"]
        if is_cloud_mode():
            tasks.extend(["disasters", "geometry"])
        begin_prewarm(tasks)
        t_public_catalog = threading.Thread(
            target=run_prewarm_task,
            args=("public_pack_catalog", prewarm_public_pack_catalog),
            daemon=True,
            name="prewarm-public-pack-catalog",
        )
        t_public_catalog.start()
        t_api_catalog = threading.Thread(
            target=run_prewarm_task,
            args=("api_catalog", prewarm_api_catalog),
            daemon=True,
            name="prewarm-api-catalog",
        )
        t_api_catalog.start()
        if is_cloud_mode():
            t_disaster = threading.Thread(
                target=run_prewarm_task,
                args=("disasters", prewarm_disaster_sources, GLOBAL_DIR),
                daemon=True,
                name="prewarm-disasters",
            )
            t_disaster.start()

            t_geom = threading.Thread(
                target=run_prewarm_task,
                args=("geometry", prewarm_geometry),
                daemon=True,
                name="prewarm-geometry",
            )
            t_geom.start()

            logger.info("Pre-warmers started: public-pack-catalog + api-catalog + disasters + geometry")
        else:
            logger.info("Pre-warmers started: public-pack-catalog + api-catalog")
    except Exception as exc:
        logger.warning("Pre-warmer failed to start: %s", exc)

    yield


app = FastAPI(
    title="County Map API",
    description="Geographic data exploration API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "Referer", "X-Requested-With"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    path = str(request.url.path)
    surface = "agent_api" if (path.startswith("/api/") or path.startswith("/mcp")) else "human_app"
    log_app_error(
        type(exc).__name__,
        str(exc),
        surface=surface,
        path=path,
        traceback=traceback.format_exc(),
    )
    return JSONResponse({"error": "Internal server error"}, status_code=500)


def _apply_common_security_headers(response, request: Request, path: str) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    if path == "/static/browser-corpus-bridge.html" or path == "/road-network-editor":
        try:
            if "X-Frame-Options" in response.headers:
                del response.headers["X-Frame-Options"]
        except Exception:
            pass
        if path == "/road-network-editor":
            response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        else:
            response.headers["Content-Security-Policy"] = (
                "frame-ancestors 'self' http://localhost:8080 https://www.daedalmap.com https://daedalmap.com"
            )
    else:
        response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if is_https_request(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def static_no_cache(request: Request, call_next):
    """Force revalidation on static JS and CSS so deploys are immediately visible."""
    started_at = time.perf_counter()
    path = request.url.path
    surface = _classify_route_surface(path)
    request.state.analytics_surface = surface
    # Keep this conservative by default.  The public API only accepts small
    # JSON/control payloads; larger uploads belong in the offline pipeline,
    # not the request path.  Use the shared parser so a malformed deployment
    # variable cannot turn a request into a middleware 500.
    max_body_bytes = _parse_env_int("MAX_REQUEST_BODY_BYTES", 1_048_576)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_body_bytes:
                return JSONResponse({"error": "Request body too large"}, status_code=413)
        except ValueError:
            pass

    if path.startswith("/static/"):
        # Static assets skip auth, rate limiting, and analytics logging;
        # security headers (including the browser-corpus-bridge frame
        # exception) still apply.
        response = await call_next(request)
        if path.endswith(".js") or path.endswith(".mjs") or path.endswith(".css"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        _apply_common_security_headers(response, request, path)
        return response

    auth_user = await get_authenticated_user_async(request)
    auth_user_id = str((auth_user or {}).get("id") or "").strip() or None
    client_ip = get_client_ip(request)
    rate_limit_config = _rate_limit_config_for_surface(surface)
    if rate_limit_config is None and not auth_user_id and surface == "shared_runtime":
        rate_limit_config = _shared_runtime_rate_limit_for_path(path)
    if rate_limit_config is not None and request.method != "OPTIONS":
        limit, window_seconds = rate_limit_config
        limiter_key = auth_user_id or client_ip or "unknown"
        allowed, retry_after = rate_limiter.check(
            f"surface:{surface}:{limiter_key}",
            limit=limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            response = _rate_limit_response(surface, retry_after)
            response_size_bytes = len(getattr(response, "body", b"") or b"")
            ip_hash = hash_ip_for_analytics(_get_request_ip(request))
            user_agent = request.headers.get("user-agent", "").strip() or None
            log_route_request_event(
                method=request.method,
                path=path,
                surface=surface,
                status_code=response.status_code,
                execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
                auth_user_id=auth_user_id,
                ip_hash=ip_hash,
                user_agent=user_agent,
                request_id=getattr(request.state, "analytics_request_id", None),
                pack_id=getattr(request.state, "analytics_pack_id", None),
                source_id=getattr(request.state, "analytics_source_id", None),
                response_size_bytes=response_size_bytes,
                rate_limited=True,
                retry_after_seconds=retry_after,
                error_code="rate_limited",
                metadata=getattr(request.state, "analytics_metadata", None),
            )
            return response

    response = await call_next(request)
    _apply_common_security_headers(response, request, path)
    _apply_surface_headers(response, request, surface)

    ip_hash = hash_ip_for_analytics(_get_request_ip(request))
    user_agent = request.headers.get("user-agent", "").strip() or None
    request_id = getattr(request.state, "analytics_request_id", None)
    pack_id = getattr(request.state, "analytics_pack_id", None)
    source_id = getattr(request.state, "analytics_source_id", None)
    response_size_bytes = len(getattr(response, "body", b"") or b"")
    log_route_request_event(
        method=request.method,
        path=path,
        surface=surface,
        status_code=response.status_code,
        execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
        auth_user_id=auth_user_id,
        ip_hash=ip_hash,
        user_agent=user_agent,
        request_id=request_id,
        pack_id=pack_id,
        source_id=source_id,
        response_size_bytes=response_size_bytes,
        challenge_issued=bool(response.status_code == 402 and response.headers.get("payment-required")),
        settlement_failed=bool(getattr(request.state, "analytics_settlement_failed", False)),
        concurrency_rejected=bool(getattr(request.state, "analytics_concurrency_rejected", False)),
        error_code=getattr(request.state, "analytics_error_code", None),
        metadata=getattr(request.state, "analytics_metadata", None),
    )
    return response


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    content = (
        "User-agent: *\n"
        "Allow: /\n\n"
        "User-agent: GPTBot\n"
        "Allow: /\n\n"
        "User-agent: ClaudeBot\n"
        "Allow: /\n\n"
        "User-agent: GoogleBot\n"
        "Allow: /\n"
    )
    return PlainTextResponse(content)


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    return PlainTextResponse(render_app_llms_txt())


@app.get("/api/config/maps-key", include_in_schema=False)
async def maps_key_config():
    return JSONResponse({"key": os.getenv("GOOGLE_MAPS_API_KEY", "").strip()})


@app.get("/security.txt", include_in_schema=False)
async def security_txt():
    return FileResponse(SECURITY_TXT_PATH, media_type="text/plain; charset=utf-8")


@app.get("/wep", include_in_schema=False)
@app.get("/prototype/lake-county-nri", include_in_schema=False)
async def wildfire_emergency_planning():
    return FileResponse(BASE_DIR / "templates" / "lake_county_nri.html", media_type="text/html; charset=utf-8")


@app.get("/manager", include_in_schema=False)
async def wildfire_equity_manager():
    return FileResponse(BASE_DIR / "templates" / "wildfire_equity_manager.html", media_type="text/html; charset=utf-8")


@app.get("/road-network-editor", include_in_schema=False)
async def road_network_editor():
    return FileResponse(BASE_DIR / "templates" / "road_network_editor.html", media_type="text/html; charset=utf-8")


@app.get("/api/road-network", include_in_schema=False)
async def get_road_network_geojson():
    try:
        if not ROAD_NETWORK_PATH.exists():
            return msgpack_error("Road network file not found", 404)
        data = json.loads(ROAD_NETWORK_PATH.read_text(encoding="utf-8"))
        return msgpack_response({"geojson": data, "source": str(ROAD_NETWORK_PATH.name)})
    except Exception as exc:
        logger.error("Failed to load road network geojson: %s", exc)
        return msgpack_error("Failed to load road network geojson", 500)


@app.post("/api/road-network", include_in_schema=False)
async def save_road_network_geojson(req: Request):
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    try:
        payload = msgpack.unpackb(await req.body(), raw=False)
    except Exception:
        return msgpack_error("Invalid MessagePack payload", 400)

    geojson = payload.get("geojson") if isinstance(payload, dict) else None
    if not isinstance(geojson, dict):
        return msgpack_error("Missing geojson object", 400)
    if geojson.get("type") != "FeatureCollection":
        return msgpack_error("geojson must be a FeatureCollection", 400)

    features = geojson.get("features")
    if not isinstance(features, list):
        return msgpack_error("geojson.features must be an array", 400)

    allowed_geom_types = {"LineString", "MultiLineString"}
    for feature in features:
        if not isinstance(feature, dict):
            return msgpack_error("Each feature must be an object", 400)
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            return msgpack_error("Each feature must include a geometry object", 400)
        geom_type = geometry.get("type")
        if geom_type not in allowed_geom_types:
            return msgpack_error("Road features must be LineString or MultiLineString", 400)

    try:
        ROAD_NETWORK_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = ROAD_NETWORK_BACKUP_DIR / f"roads_{timestamp}.geojson"

        if ROAD_NETWORK_PATH.exists():
            backup_path.write_text(ROAD_NETWORK_PATH.read_text(encoding="utf-8"), encoding="utf-8")

        ROAD_NETWORK_PATH.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
        return msgpack_response(
            {
                "ok": True,
                "saved_features": len(features),
                "target": str(ROAD_NETWORK_PATH.name),
                "backup": str(backup_path.name),
            }
        )
    except Exception as exc:
        logger.error("Failed to save road network geojson: %s", exc)
        return msgpack_error("Failed to save road network geojson", 500)


@app.get("/.well-known/security.txt", include_in_schema=False)
async def well_known_security_txt():
    return FileResponse(SECURITY_TXT_PATH, media_type="text/plain; charset=utf-8")


@app.get("/.well-known/402index-verify.txt", include_in_schema=False)
async def well_known_402index_verify():
    token = _get_402index_verify_token()
    if not token:
        return PlainTextResponse("Not found", status_code=404)
    return PlainTextResponse(token, media_type="text/plain; charset=utf-8")


def _site_url() -> str:
    from mapmover.paths import SITE_URL
    return str(SITE_URL or os.getenv("SITE_URL", "https://daedalmap.com")).rstrip("/")


@app.get("/docs", include_in_schema=False)
async def redirect_docs():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/docs", status_code=302)


@app.get("/docs/{path:path}", include_in_schema=False)
async def redirect_docs_path(path: str):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/docs/{path}", status_code=302)


@app.get("/about", include_in_schema=False)
async def redirect_about():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/about", status_code=302)


@app.get("/pricing", include_in_schema=False)
async def redirect_pricing():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/pricing", status_code=302)


@app.get("/packs", include_in_schema=False)
async def redirect_packs():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/packs", status_code=302)


@app.get("/packs/{path:path}", include_in_schema=False)
async def redirect_packs_path(path: str):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/packs/{path}", status_code=302)


@app.get("/roadmap", include_in_schema=False)
async def redirect_roadmap():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/roadmap", status_code=302)


@app.get("/login", include_in_schema=False)
async def redirect_login():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{_site_url()}/login", status_code=302)

app.include_router(system_router)
app.include_router(mcp_router)
app.include_router(private_mcp_router)
app.include_router(api_query_router)
app.include_router(artifacts_router)
app.include_router(geometry_router)
app.include_router(raster_router)
app.include_router(earthquakes_router)
app.include_router(related_events_router)
app.include_router(volcanoes_router)
app.include_router(landslides_router)
app.include_router(nws_historical_router)
app.include_router(tsunamis_router)
app.include_router(hurricanes_router)
app.include_router(tornadoes_router)
app.include_router(floods_router)
app.include_router(wildfires_router)
app.include_router(weather_router)
app.include_router(chat_router)
app.include_router(ops_router)
app.include_router(research_router)



if __name__ == "__main__":
    import socket
    import uvicorn
    from mapmover.paths import APP_HOST, APP_PORT

    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) != 0

    port = APP_PORT if _port_free(APP_PORT) else APP_PORT + 1
    if port != APP_PORT:
        print(f"Port {APP_PORT} in use, falling back to {port}")
    uvicorn.run(app, host=APP_HOST, port=port)
