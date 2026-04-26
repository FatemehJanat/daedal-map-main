"""System, settings, queue, and cache API router endpoints."""

import csv
import io
import ipaddress
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import msgpack
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from mapmover.auth_context import build_session_cache_key, get_authenticated_user
from mapmover.corpus_registry import corpus_registry
from mapmover import ACCOUNT_URL, CacheSignature, clear_metadata_cache, initialize_catalog, logger, session_manager
from mapmover.order_queue import order_queue
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.security import get_client_ip, is_https_request, rate_limiter


router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[2]
_release_marker_cache = None
_release_marker_cache_time = 0.0
_RELEASE_MARKER_TTL_SECONDS = 60
_PUBLIC_PACK_CATALOG_TTL_SECONDS = 300
_public_pack_list_cache: dict[bool, dict[str, object]] = {
    False: {"value": None, "cached_at": 0.0},
    True: {"value": None, "cached_at": 0.0},
}
_public_pack_detail_cache: dict[tuple[str, bool], dict[str, object]] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clear_public_pack_catalog_cache() -> None:
    for mode in (False, True):
        _public_pack_list_cache[mode] = {"value": None, "cached_at": 0.0}
    _public_pack_detail_cache.clear()


def _is_loopback_host(value: str) -> bool:
    host = (value or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _hosted_pack_surface_locked() -> bool:
    from mapmover.paths import INSTALL_MODE, RUNTIME_MODE

    return RUNTIME_MODE == "cloud" or str(INSTALL_MODE).strip().lower() != "local"


def _pack_install_error(message: str, status_code: int = 403):
    return msgpack_error(message, status_code)


def _require_hosted_pack_local_disabled() -> Response | None:
    if _hosted_pack_surface_locked():
        return _pack_install_error("Local-path pack installs are disabled in hosted mode", 403)
    return None


def _require_hosted_https_ref(ref_value: str | None, field_name: str) -> Response | None:
    if not _hosted_pack_surface_locked() or not ref_value:
        return None
    parsed = urlparse(str(ref_value).strip())
    if parsed.scheme.lower() != "https":
        return _pack_install_error(f"{field_name} must use https in hosted mode", 403)
    if not parsed.netloc:
        return _pack_install_error(f"{field_name} must be an absolute https URL in hosted mode", 403)
    return None


def _require_hosted_allowed_ref_host(ref_value: str | None, field_name: str) -> Response | None:
    if not _hosted_pack_surface_locked() or not ref_value:
        return None
    allowed_hosts = {
        host.strip().lower()
        for host in os.getenv("HOSTED_PACK_REF_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    if not allowed_hosts:
        return _pack_install_error(
            "Hosted pack ref installs require HOSTED_PACK_REF_ALLOWED_HOSTS to be configured",
            503,
        )
    parsed = urlparse(str(ref_value).strip())
    host = (parsed.hostname or "").strip().lower()
    if host and host in allowed_hosts:
        return None
    return _pack_install_error(
        f"{field_name} host is not allowed in hosted mode",
        403,
    )


def _configured_host(url: str) -> str:
    parsed = urlparse((url or "").strip())
    return (parsed.netloc or parsed.path or "").split("/", 1)[0].lower()


def _hosted_auth_enabled() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))


def _is_localish_url(url: str) -> bool:
    host = _configured_host(url)
    return host in {"", "localhost", "127.0.0.1", "::1"}


def _require_local_or_admin(req: Request):
    client = getattr(req, "client", None)
    client_host = getattr(client, "host", "") if client else ""
    if _is_loopback_host(client_host):
        return None, None
    return _require_admin(req)


def _order_rate_limited_response(message: str, retry_after: int):
    response = msgpack_response({"error": message, "retry_after": retry_after}, 429)
    response.headers["Retry-After"] = str(retry_after)
    return response


def _resolve_order_session_key(req: Request, session_id: str | None):
    frontend_session_id = str(session_id or "").strip() or "anonymous"
    auth_user = get_authenticated_user(req)
    scoped_session_id = build_session_cache_key(frontend_session_id, auth_user)
    return frontend_session_id, scoped_session_id, auth_user


def _order_status_rate_limit(req: Request, auth_user: dict | None) -> Response | None:
    limiter_identity = (auth_user or {}).get("id") or get_client_ip(req) or "unknown"
    allowed, retry_after = rate_limiter.check(
        f"orders:status:{limiter_identity}",
        limit=int(os.getenv("ORDER_STATUS_RATE_LIMIT", "120")),
        window_seconds=int(os.getenv("ORDER_STATUS_RATE_WINDOW_SECONDS", "60")),
    )
    if not allowed:
        return _order_rate_limited_response("Too many order status requests. Please slow down and try again shortly.", retry_after)
    return None


def _admin_error(req: Request, message: str, status_code: int):
    if req.query_params.get("format") == "json":
        return JSONResponse({"error": message}, status_code=status_code)
    return msgpack_error(message, status_code)


def _require_admin(req: Request):
    """
    Require a verified admin/master user for hosted runtime/admin operations.

    For now we fail closed when the service-role key is absent so the hosted
    surface cannot silently fall back to permissive local/dev behavior.
    """
    deployment = str(os.getenv("DEPLOYMENT", "")).strip().lower()
    client_host = ((req.client.host if req.client else "") or "").strip().lower()
    if deployment == "local" and client_host in {"127.0.0.1", "::1", "localhost"}:
        return {"plan_id": "master", "is_admin": True, "local_dev_bypass": True}, None

    auth_user = get_authenticated_user(req)
    if not auth_user:
        logger.warning(
            "Denied hosted admin request: anonymous caller path=%s ip=%s",
            req.url.path,
            get_client_ip(req),
        )
        return None, _admin_error(req, "Unauthorized", 401)

    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not service_key:
        logger.warning(
            "Denied hosted admin request: service key missing path=%s user_id=%s",
            req.url.path,
            auth_user.get("id"),
        )
        return None, _admin_error(req, "Admin operations unavailable", 403)

    try:
        from supabase_client import SupabaseClient

        supa = SupabaseClient()
        context = supa.get_user_entitlement_context(auth_user.get("id"))
    except Exception as exc:
        logger.warning(f"Admin entitlement check failed: {exc}")
        return None, _admin_error(req, "Entitlement check failed", 500)

    if not context or context.get("error"):
        logger.warning(
            "Denied hosted admin request: entitlement lookup empty path=%s user_id=%s",
            req.url.path,
            auth_user.get("id"),
        )
        return None, _admin_error(req, "Forbidden", 403)
    if context.get("plan_id") != "master" and not context.get("is_admin"):
        logger.warning(
            "Denied hosted admin request: insufficient privileges path=%s user_id=%s plan_id=%s is_admin=%s",
            req.url.path,
            auth_user.get("id"),
            context.get("plan_id"),
            context.get("is_admin"),
        )
        return None, _admin_error(req, "Forbidden", 403)
    return context, None


def _best_source_text(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _default_pack_title(pack_id: str) -> str:
    pack_id = str(pack_id or "").strip()
    if not pack_id:
        return ""
    special = {
        "un_sdg": "UN SDGs",
        "world_factbook": "World Factbook",
        "owid_co2": "Our World in Data CO2",
    }
    if pack_id in special:
        return special[pack_id]
    acronyms = {"sdg", "un", "fx", "co2", "imf", "bop", "us", "usa", "epa", "cia", "nasa", "who", "bom", "zcta", "nrcan", "abs", "mcp", "api"}
    words = []
    for word in pack_id.replace("-", "_").split("_"):
        if not word:
            continue
        lower = word.lower()
        words.append(lower.upper() if lower in acronyms else lower.capitalize())
    return " ".join(words)


def _source_entity_label(source_url: str | None, fallback: str = "") -> str:
    text = str(source_url or "").strip().lower()
    if "unstats.un.org" in text:
        return "UN Statistics Division"
    if "worldbank.org" in text:
        return "World Bank"
    if "cia.gov" in text:
        return "CIA"
    if "imf.org" in text:
        return "International Monetary Fund"
    if "ecb.europa.eu" in text:
        return "European Central Bank"
    if "usgs.gov" in text:
        return "USGS"
    if "noaa.gov" in text or "ngdc.noaa.gov" in text:
        return "NOAA"
    if "smithsonian" in text:
        return "Smithsonian Institution"
    if "who.int" in text:
        return "World Health Organization"
    return str(fallback or "").strip()


def _normalized_upstream_sources(*values) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, dict):
                continue
            agency = str(entry.get("agency") or "").strip()
            source_url = str(entry.get("source_url") or "").strip()
            agency_upstream_url = str(entry.get("agency_upstream_url") or "").strip()
            license_text = str(entry.get("license") or "").strip()
            notes = str(entry.get("notes") or "").strip()
            source_id = str(entry.get("source_id") or "").strip()
            if not any([agency, source_url, agency_upstream_url, license_text, notes, source_id]):
                continue
            key = json.dumps(
                {
                    "agency": agency,
                    "source_url": source_url,
                    "agency_upstream_url": agency_upstream_url,
                    "license": license_text,
                    "notes": notes,
                    "source_id": source_id,
                },
                sort_keys=True,
            )
            if key in seen:
                continue
            seen.add(key)
            normalized.append({
                "source_id": source_id,
                "agency": agency,
                "agency_short": str(entry.get("agency_short") or "").strip(),
                "source_url": source_url,
                "agency_upstream_url": agency_upstream_url,
                "license": license_text,
                "rows_contributed": entry.get("rows_contributed"),
                "notes": notes,
            })
    return normalized


def _load_pack_source_docs(pack_sources: list[dict]) -> list[dict]:
    from mapmover.data_loading import load_source_metadata, load_source_reference

    docs = []
    for source in pack_sources:
        source_id = str(source.get("source_id") or "").strip()
        if not source_id:
            continue
        metadata = load_source_metadata(source_id) or {}
        reference = load_source_reference(source_id) or {}
        docs.append({
            "source_id": source_id,
            "catalog": source,
            "metadata": metadata,
            "reference": reference,
        })
    return docs


def _load_pack_reference(pack_id: str) -> dict:
    from mapmover.paths import DATA_ROOT
    from mapmover.runtime_config import get_runtime_config
    from mapmover.data_loading import _fetch_json_from_s3

    pack_id = str(pack_id or "").strip()
    if not pack_id:
        return {}
    runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()
    if runtime_mode == "cloud":
        try:
            data = _fetch_json_from_s3(f"packs/{pack_id}/reference.json")
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    path = DATA_ROOT / "packs" / pack_id / "reference.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _pack_display_meta(primary: dict, primary_doc: dict | None) -> dict:
    """Return display-oriented pack title/description from metadata/reference source files."""
    pack_id = str(primary.get("pack_id") or primary.get("source_id") or "").strip()
    metadata = (primary_doc or {}).get("metadata", {}) or {}
    ref_source = ((primary_doc or {}).get("reference", {}) or {}).get("source", {}) or {}
    ref_upstream = _normalized_upstream_sources(((primary_doc or {}).get("reference", {}) or {}).get("upstream_sources"))
    meta_upstream = _normalized_upstream_sources(metadata.get("upstream_sources"))
    upstream_sources = ref_upstream or meta_upstream
    primary_upstream = upstream_sources[0] if upstream_sources else {}
    pack_ref = _load_pack_reference(pack_id)
    if pack_ref:
        return {
            "source_name": _best_source_text(
                pack_ref.get("source_name"),
                ref_source.get("source_name"),
                metadata.get("source_name"),
                primary.get("source_name"),
            ),
            "description": _best_source_text(
                pack_ref.get("description"),
                ref_source.get("description"),
                metadata.get("description"),
                primary.get("description"),
            ),
            "source_url": _best_source_text(
                pack_ref.get("primary_source_url"),
                pack_ref.get("source_url"),
                metadata.get("primary_source_url"),
                primary_upstream.get("agency_upstream_url"),
                primary_upstream.get("source_url"),
                ref_source.get("source_url"),
                metadata.get("source_url"),
                primary.get("source_url"),
            ),
            "primary_source_name": _best_source_text(
                pack_ref.get("primary_source_name"),
                metadata.get("primary_source_name"),
                primary_upstream.get("agency"),
            ),
            "primary_source_license": _best_source_text(
                metadata.get("primary_source_license"),
                primary_upstream.get("license"),
                ref_source.get("license"),
                metadata.get("license"),
                primary.get("license"),
            ),
            "license": _best_source_text(
                pack_ref.get("license"),
                ref_source.get("license"),
                metadata.get("license"),
                primary.get("license"),
            ),
            "upstream_sources": upstream_sources,
        }
    source_count = int(primary.get("source_count") or 0)
    fallback_name = _default_pack_title(pack_id) if source_count > 1 else _best_source_text(
        ref_source.get("source_name"),
        metadata.get("source_name"),
        primary.get("source_name"),
        _default_pack_title(pack_id),
    )
    return {
        "source_name": fallback_name,
        "description": _best_source_text(
            ref_source.get("description"),
            metadata.get("description"),
            primary.get("description"),
        ),
        "source_url": _best_source_text(
            metadata.get("primary_source_url"),
            primary_upstream.get("agency_upstream_url"),
            primary_upstream.get("source_url"),
            ref_source.get("source_url"),
            metadata.get("source_url"),
            primary.get("source_url"),
        ),
        "primary_source_name": _best_source_text(
            metadata.get("primary_source_name"),
            primary_upstream.get("agency"),
        ),
        "primary_source_license": _best_source_text(
            metadata.get("primary_source_license"),
            primary_upstream.get("license"),
            ref_source.get("license"),
            metadata.get("license"),
            primary.get("license"),
        ),
        "license": _best_source_text(
            ref_source.get("license"),
            metadata.get("license"),
            primary.get("license"),
        ),
        "upstream_sources": upstream_sources,
    }


def _resolve_pack_temporal(pack_id: str, pack_sources: list[dict], primary: dict) -> dict:
    """
    Resolve pack time coverage with disaster-aware overrides.

    Disaster metadata uses the real archival year column and should override
    timestamp-based source coverage that can hide ancient/BCE records.
    """
    try:
        from mapmover.disaster_filters import get_disaster_metadata
        disaster_meta = get_disaster_metadata(pack_id)
        if disaster_meta:
            return {
                "start": disaster_meta.get("data_min_year"),
                "end": disaster_meta.get("data_max_year"),
                "granularity": (primary.get("temporal_coverage", {}) or {}).get("granularity") or "yearly",
            }
    except Exception:
        pass

    starts = []
    ends = []
    granularities = []

    for src in pack_sources:
        tc = src.get("temporal_coverage", {}) or {}
        start = tc.get("start")
        end = tc.get("end")
        granularity = tc.get("granularity")
        if start not in (None, "", "unknown"):
            starts.append(start)
        if end not in (None, "", "unknown"):
            ends.append(end)
        if granularity not in (None, "", "unknown"):
            granularities.append(granularity)

    return {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
        "granularity": granularities[0] if granularities else (primary.get("temporal_coverage", {}) or {}).get("granularity"),
    }


def _infer_supported_query_shapes(data_type: str, temporal: dict) -> list[str]:
    shapes = ["single_year_multi_location"]
    start = temporal.get("start")
    end = temporal.get("end")
    if start not in (None, "") and end not in (None, "") and start != end:
        shapes.extend(["multi_year_single_location", "multi_year_multi_location"])
    if str(data_type or "").strip().lower() == "events":
        shapes.append("filtered_event_query")
    return shapes


def _normalize_geographic_levels(*values) -> list[int]:
    levels = set()
    for value in values:
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, int):
                    levels.add(item)
                elif str(item).strip().isdigit():
                    levels.add(int(str(item).strip()))
            continue
        if isinstance(value, int):
            levels.add(value)
            continue
        text = str(value).strip()
        if text.isdigit():
            levels.add(int(text))
    return sorted(levels)


def _sample_questions_for_pack(pack_id: str, data_type: str, title: str) -> list[str]:
    samples = {
        "worldpop": [
            "Show me population of Canada from 2000 to 2020",
            "Show me population of European countries in 2000",
        ],
        "un_sdg": [
            "Show me poverty in African countries in 2012",
            "Show SDG 3 progress in Asian countries from 2000 to 2010",
        ],
        "currency": [
            "Show FX rates for Argentina from 2010 to 2024",
            "Compare FX rates for Argentina, Brazil, and Chile in 2020",
        ],
        "earthquakes": [
            "Show earthquake counts for Japan from 2000 to 2020",
            "Compare earthquake counts for Japan, Chile, and Indonesia in 2011",
        ],
        "floods": [
            "Show flood impacts for Bangladesh from 2000 to 2019",
            "Show flood impacts across South Asian countries in 2015",
        ],
        "hurricanes": [
            "Show hurricane frequency for Mexico from 1995 to 2024",
            "Show hurricane frequency across Gulf Coast countries from 1995 to 2024",
        ],
        "tsunamis": [
            "Show tsunami impacts across Pacific coastal countries in 2011",
            "Show tsunami impacts across Pacific countries from 2000 to 2020",
        ],
        "tornadoes": [
            "Show tornado counts for Texas from 1990 to 2020",
            "Compare the 10-year rolling tornado count for Texas counties between the 1990s and 2010s",
        ],
        "volcanoes": [
            "Compare volcano exposure for Indonesia, Japan, and the Philippines in 2020",
            "Show volcano exposure across Indonesia, Japan, and the Philippines from 2000 to 2020",
        ],
        "wildfires": [
            "Show wildfire exposure for California from 2004 to 2024",
            "Show me the areas with the highest wildfire exposure over the past 20 years",
        ],
        "fairfax_climate": [
            "Show Fairfax land surface temperature from 2024 to 2025",
            "Compare Fairfax heat by geography in 2025",
        ],
        "world_factbook": [
            "Show infrastructure indicators for Canada in the latest year",
            "Compare economic profile fields for Canada, USA, and Mexico",
        ],
    }
    if pack_id in samples:
        return samples[pack_id]
    if str(data_type or "").strip().lower() == "events":
        return [f"Show {title} events for one region in a time range"]
    return [f"Show {title} values for one or more regions over time"]


def _build_public_pack_list(api_ready_only: bool = False) -> list[dict]:
    cache_entry = _public_pack_list_cache.get(api_ready_only, {})
    cached_value = cache_entry.get("value")
    cached_at = float(cache_entry.get("cached_at") or 0.0)
    if isinstance(cached_value, list) and (time.time() - cached_at) < _PUBLIC_PACK_CATALOG_TTL_SECONDS:
        return cached_value

    from mapmover.data_loading import load_catalog

    catalog = load_catalog()
    all_sources = catalog.get("sources", [])
    pack_summaries = {
        str(pack.get("pack_id") or "").strip(): pack
        for pack in catalog.get("packs", [])
        if isinstance(pack, dict) and str(pack.get("pack_id") or "").strip()
    }
    published = [
        s for s in all_sources
        if s.get("pack_id") and (not api_ready_only or bool(s.get("api_ready", False)))
    ]

    pack_map = {}
    pack_counts = {}
    pack_sources_map = {}
    for s in published:
        pid = s["pack_id"]
        pack_counts[pid] = pack_counts.get(pid, 0) + 1
        pack_sources_map.setdefault(pid, []).append(s)
        if pid not in pack_map or s.get("source_id") == pid:
            pack_map[pid] = s

    packs = []
    for pid, s in pack_map.items():
        pack_summary = pack_summaries.get(pid, {})
        pack_sources = pack_sources_map.get(pid, [s])
        pack_docs = _load_pack_source_docs(pack_sources)
        primary_doc = next((doc for doc in pack_docs if doc.get("source_id") == s.get("source_id")), pack_docs[0] if pack_docs else None)
        display = _pack_display_meta(s, primary_doc)
        display_name = _best_source_text(
            pack_summary.get("pack_name"),
            display.get("source_name"),
            _default_pack_title(pid),
        )
        if len(pack_sources) > 1 and not _load_pack_reference(pid):
            display_name = _best_source_text(
                pack_summary.get("pack_name"),
                _default_pack_title(pid),
                display_name,
            )
        tc = _resolve_pack_temporal(pid, pack_sources, s)
        primary_source_url = _best_source_text(
            pack_summary.get("primary_source_url"),
            display.get("source_url"),
        )
        packs.append({
            "pack_id": pid,
            "pack_name": display_name,
            "title": display_name,
            "source_name": display_name,
            "description": _best_source_text(
                pack_summary.get("description"),
                display.get("description"),
            ),
            "source_url": primary_source_url,
            "license": _best_source_text(
                pack_summary.get("primary_source_license"),
                display.get("license", ""),
            ),
            "primary_source_name": _best_source_text(
                pack_summary.get("primary_source_name"),
                display.get("primary_source_name"),
                _source_entity_label(primary_source_url, display_name),
            ),
            "primary_source_url": primary_source_url,
            "upstream_sources": pack_summary.get("upstream_sources") or display.get("upstream_sources") or [],
            "category": s.get("category", "other"),
            "data_type": s.get("data_type", ""),
            "scope": s.get("scope", ""),
            "topic_tags": s.get("topic_tags") or [],
            "source_count": pack_counts[pid],
            "temporal_start": tc.get("start"),
            "temporal_end": tc.get("end"),
            "pack_maintainer_name": s.get("pack_maintainer_name") or s.get("maintainer_name") or "DaedalMap",
            "pack_maintainer_url": s.get("pack_maintainer_url") or s.get("maintainer_url") or ACCOUNT_URL,
        })

    packs.sort(key=lambda p: (p["category"], p["title"].lower()))
    _public_pack_list_cache[api_ready_only] = {"value": packs, "cached_at": time.time()}
    return packs


def _build_public_pack_detail(pack_id: str, api_ready_only: bool = False) -> dict | None:
    cache_key = (str(pack_id or ""), bool(api_ready_only))
    cached_entry = _public_pack_detail_cache.get(cache_key)
    if cached_entry and (time.time() - float(cached_entry.get("cached_at") or 0.0)) < _PUBLIC_PACK_CATALOG_TTL_SECONDS:
        cached_value = cached_entry.get("value")
        return cached_value if isinstance(cached_value, dict) else None

    from mapmover.data_loading import load_catalog

    catalog = load_catalog()
    all_sources = catalog.get("sources", [])
    pack_summaries = {
        str(pack.get("pack_id") or "").strip(): pack
        for pack in catalog.get("packs", [])
        if isinstance(pack, dict) and str(pack.get("pack_id") or "").strip()
    }
    pack_sources = [
        s for s in all_sources
        if s.get("pack_id") == pack_id and (not api_ready_only or bool(s.get("api_ready", False)))
    ]
    if not pack_sources:
        return None

    primary = next((s for s in pack_sources if s.get("source_id") == pack_id), pack_sources[0])
    pack_summary = pack_summaries.get(pack_id, {})
    pack_docs = _load_pack_source_docs(pack_sources)
    primary_doc = next((doc for doc in pack_docs if doc.get("source_id") == primary.get("source_id")), pack_docs[0] if pack_docs else None)
    primary_meta = ((primary_doc or {}).get("metadata", {}) or {})
    display = _pack_display_meta(primary, primary_doc)
    display_name = _best_source_text(
        pack_summary.get("pack_name"),
        display.get("source_name"),
        _default_pack_title(pack_id),
    )
    if len(pack_sources) > 1 and not _load_pack_reference(pack_id):
        display_name = _best_source_text(
            pack_summary.get("pack_name"),
            _default_pack_title(pack_id),
            display_name,
        )

    all_metrics = {}
    for doc in pack_docs:
        ref_metrics = ((doc.get("reference", {}) or {}).get("metrics", {}) or {})
        meta_metrics = (doc.get("metadata", {}) or {}).get("metrics", {}) or {}
        for key, value in ref_metrics.items():
            all_metrics[key] = value
        for key, value in meta_metrics.items():
            if key in all_metrics:
                continue
            if isinstance(value, dict):
                all_metrics[key] = value.get("description") or value.get("name") or ""
            else:
                all_metrics[key] = value

    subsources = []
    docs_by_source = {doc.get("source_id"): doc for doc in pack_docs}
    for s in pack_sources:
        doc = docs_by_source.get(s.get("source_id")) or {}
        sref = (doc.get("reference", {}) or {})
        smeta = (doc.get("metadata", {}) or {})
        sref_source = sref.get("source", {}) or {}
        supstream = _normalized_upstream_sources(smeta.get("upstream_sources"), sref.get("upstream_sources"))
        primary_upstream = supstream[0] if supstream else {}
        smetrics = sref.get("metrics", {}) or {}
        if not smetrics:
            for key, value in (smeta.get("metrics", {}) or {}).items():
                if isinstance(value, dict):
                    smetrics[key] = value.get("description") or value.get("name") or ""
                else:
                    smetrics[key] = value
        stc = s.get("temporal_coverage", {}) or {}
        subsources.append({
            "source_id": s.get("source_id"),
            "source_name": _best_source_text(
                sref_source.get("source_name"),
                smeta.get("source_name"),
                s.get("source_name", ""),
            ),
            "description": _best_source_text(
                sref_source.get("description"),
                smeta.get("description"),
                s.get("description", ""),
            ),
            "source_url": _best_source_text(
                smeta.get("primary_source_url"),
                primary_upstream.get("agency_upstream_url"),
                primary_upstream.get("source_url"),
                sref_source.get("source_url"),
                smeta.get("source_url"),
                s.get("source_url", ""),
            ),
            "license": _best_source_text(
                sref_source.get("license"),
                smeta.get("license"),
                s.get("license", ""),
            ),
            "primary_source_name": _best_source_text(
                smeta.get("primary_source_name"),
                primary_upstream.get("agency"),
            ),
            "primary_source_url": _best_source_text(
                smeta.get("primary_source_url"),
                primary_upstream.get("agency_upstream_url"),
                primary_upstream.get("source_url"),
                sref_source.get("source_url"),
                smeta.get("source_url"),
                s.get("source_url", ""),
            ),
            "primary_source_license": _best_source_text(
                smeta.get("primary_source_license"),
                primary_upstream.get("license"),
                sref_source.get("license"),
                smeta.get("license"),
                s.get("license", ""),
            ),
            "upstream_sources": supstream,
            "path": s.get("path", ""),
            "metric_count": len(smetrics),
            "metrics": smetrics,
            "temporal_coverage": {
                "start": stc.get("start"),
                "end": stc.get("end"),
                "granularity": stc.get("granularity"),
            },
            "coverage_description": s.get("coverage_description", ""),
            "geographic_level": s.get("geographic_level"),
            "interaction_mode": s.get("interaction_mode"),
        })

    temporal = _resolve_pack_temporal(pack_id, pack_sources, primary)

    primary_source_url = _best_source_text(
        pack_summary.get("primary_source_url"),
        display.get("source_url", ""),
    )

    payload = {
        "pack_id": pack_id,
        "pack_name": display_name,
        "title": display_name,
        "source_name": display_name,
        "description": _best_source_text(
            pack_summary.get("description"),
            display.get("description", ""),
        ),
        "source_url": primary_source_url,
        "primary_source_name": _best_source_text(
            pack_summary.get("primary_source_name"),
            display.get("primary_source_name"),
            _source_entity_label(primary_source_url, display_name),
        ),
        "primary_source_url": primary_source_url,
        "upstream_sources": pack_summary.get("upstream_sources") or display.get("upstream_sources") or [],
        "license": _best_source_text(
            pack_summary.get("primary_source_license"),
            display.get("license", ""),
        ),
        "category": _best_source_text(primary_meta.get("category"), primary.get("category", "")),
        "data_type": _best_source_text(primary_meta.get("data_type"), primary.get("data_type", "")),
        "scope": _best_source_text(primary_meta.get("scope"), primary.get("scope", "")),
        "topic_tags": primary_meta.get("topic_tags") or primary.get("topic_tags") or [],
        "keywords": primary_meta.get("keywords") or primary.get("keywords") or [],
        "geographic_level": primary_meta.get("geographic_level") or primary.get("geographic_level"),
        "coverage_description": _best_source_text(primary_meta.get("coverage_description"), primary.get("coverage_description", "")),
        "temporal_coverage": temporal,
        "metrics": all_metrics,
        "llm_summary": _best_source_text(primary_meta.get("llm_summary"), primary.get("llm_summary", "")),
        "source_count": len(pack_sources),
        "source_ids": [s["source_id"] for s in pack_sources],
        "subsources": subsources,
    }
    _public_pack_detail_cache[cache_key] = {"value": payload, "cached_at": time.time()}
    return payload


def _build_v1_guide_payload() -> dict:
    return {
        "guide_version": "1.0",
        "generated_at": _utc_now_iso(),
        "title": "DaedalMap API Guide",
        "principles": [
            "If a request can be answered as one query from one source, it belongs in the easy deterministic lane.",
            "Free discovery should be separate from paid data retrieval.",
            "The first-wave query model is built around source, metric, location, and time.",
        ],
        "free_calls": [
            {"id": "guide", "path": "/api/v1/guide", "purpose": "How the API works"},
            {"id": "catalog", "path": "/api/v1/catalog", "purpose": "What exists overall"},
            {"id": "pack_detail", "path": "/api/v1/packs/{pack_id}", "purpose": "What exists inside one pack"},
        ],
        "query_dimensions": ["source", "metric", "location", "time"],
        "query_shapes": [
            "single_year_multi_location",
            "multi_year_single_location",
            "multi_year_multi_location",
        ],
        "commercial_access": {
            "required_for_data_calls": True,
            "first_paid_candidate": "/api/v1/query/dataset",
            "modes": ["wallet_pay"],
        },
        "current_live_scope": {
            "agent_ready_packs": _current_agent_pack_ids(),
            "future_payment_modes": ["account_credit"],
        },
    }


def prewarm_public_pack_catalog() -> None:
    try:
        _build_public_pack_list(api_ready_only=False)
        logger.info("Pre-warmed public pack catalog")
    except Exception as exc:
        logger.warning("Public pack catalog prewarm failed: %s", exc)


def _current_agent_pack_ids() -> list[str]:
    pack_ids = {
        str(pack.get("pack_id") or "").strip()
        for pack in _build_public_pack_list(api_ready_only=True)
        if str(pack.get("pack_id") or "").strip()
    }
    return sorted(pack_ids)


def _public_app_url() -> str:
    from mapmover.paths import APP_URL

    return str(APP_URL or "").rstrip("/")


def _public_site_url() -> str:
    from mapmover.paths import SITE_URL

    return str(SITE_URL or "").rstrip("/")


def _docs_url(path: str) -> str:
    return f"{_public_site_url()}{path}"


def _pack_is_paid(pack_id: str | None) -> bool:
    from mapmover.routes.mcp import _paid_pack_ids

    return str(pack_id or "").strip() in _paid_pack_ids()


def _normalize_mcp_facade_pack_id(pack_id: str | None) -> str | None:
    from mapmover.routes.mcp import _normalize_pack_id

    return _normalize_pack_id(pack_id)


def _mcp_remote_path(pack_id: str | None = None) -> str:
    normalized = _normalize_mcp_facade_pack_id(pack_id)
    return f"/mcp/{normalized}" if normalized else "/mcp"


def _mcp_pricing_payload(pack_id: str | None = None) -> dict:
    from mapmover.routes.mcp import _free_pack_ids

    normalized = _normalize_mcp_facade_pack_id(pack_id)
    if normalized in _free_pack_ids():
        return {
            "model": "free",
            "notes": "No payment required for this MCP facade.",
        }
    return {
        "model": "per_row",
        "base_price_usd": 0.01,
        "base_rows_included": 100,
        "per_row_usd": 0.0001,
        "max_price_usd": 0.50,
        "currency": "USDC",
        "network": "Base",
        "payment_protocol": "x402",
        "notes": "The 402 challenge returns the exact price before payment.",
    }


def _mcp_auth_notes() -> str:
    from mapmover.routes.mcp import _free_pack_ids, _paid_pack_ids

    free = ", ".join(sorted(_free_pack_ids()))
    paid = ", ".join(sorted(_paid_pack_ids()))
    return (
        f"No API key required. {free} are free lanes. "
        f"{paid} use x402 on Base mainnet with USDC. Free discovery endpoints require no payment."
    )


def _build_mcp_server_card_payload(pack_id: str | None = None) -> dict:
    from mapmover.routes.mcp import get_server_description, get_server_info

    app_url = _public_app_url()
    pack_ids = _current_agent_pack_ids()
    normalized = _normalize_mcp_facade_pack_id(pack_id)

    return {
        "serverInfo": {
            **get_server_info(normalized),
            "description": get_server_description(normalized),
        },
        "websiteUrl": _public_site_url(),
        "documentationUrl": _docs_url("/docs/for-agents"),
        "transport": "streamable-http",
        "authentication": {
            "type": "none",
            "notes": (
                _mcp_auth_notes()
            ),
        },
        "pricing": _mcp_pricing_payload(normalized),
        "tools": [
            {
                "name": "get_catalog",
                "description": "List the current agent-ready packs. Free discovery.",
                "paid": False,
            },
            {
                "name": "get_pack",
                "description": "Get detailed metadata and first-query guidance for one pack. Free discovery.",
                "paid": False,
            },
            {
                "name": "get_earthquake_events",
                "description": "Query structured earthquake event data.",
                "paid": True,
                "source_id": "earthquakes_events",
            },
            {
                "name": "get_volcanic_activity",
                "description": "Query structured volcanic eruption records.",
                "paid": False,
                "source_id": "volcanoes_events",
            },
            {
                "name": "get_tsunami_events",
                "description": "Query structured tsunami event records.",
                "paid": True,
                "source_id": "tsunamis_events",
            },
            {
                "name": "get_fx_rates",
                "description": "Query structured historical FX rate data.",
                "paid": False,
                "source_id": "fx_usd_historical",
            },
            {
                "name": "query_dataset",
                "description": _mcp_auth_notes(),
                "paid": False,
                "source_id": "any",
            },
        ],
        "resources": [
            {
                "name": "agent_catalog",
                "description": "Machine-readable catalog of all live agent-ready data packs",
                "uri": f"{app_url}/api/v1/catalog",
            },
            {
                "name": "pack_details",
                "description": "Detailed pack metadata and quick-start guidance",
                "uri": f"{app_url}/api/v1/packs/{{pack_id}}",
            },
        ],
        "metadata": {
            "live_pack_ids": pack_ids,
            "loc_id_guide_url": _docs_url("/docs/loc-id"),
            "examples_url": _docs_url("/docs/agent-examples"),
        },
    }


def _build_apis_json_payload() -> dict:
    app_url = _public_app_url()
    docs_url = _docs_url("/docs/for-agents")
    return {
        "name": "DaedalMap API",
        "description": (
            "Agent-ready geographic data intelligence API. Historical datasets for earthquakes, "
            "volcanic activity, tsunamis, and foreign exchange rates. Mixed free and x402-paid "
            "structured access with free discovery."
        ),
        "url": app_url,
        "version": "1.0",
        "contact": {"url": docs_url},
        "tags": ["geospatial", "hazard", "earthquakes", "volcanoes", "tsunamis", "fx", "x402", "mcp"],
        "apis": [
            {
                "name": "DaedalMap Agent API",
                "description": _mcp_auth_notes(),
                "humanUrl": docs_url,
                "baseUrl": f"{app_url}/api/v1",
                "version": "v1",
                "tags": ["geospatial", "hazard", "economics", "x402", "agent"],
                "contact": {"url": docs_url},
                "properties": [
                    {"type": "x-discovery", "url": f"{app_url}/api/v1/guide"},
                    {"type": "x-catalog", "url": f"{app_url}/api/v1/catalog"},
                    {"type": "x-pack-docs", "url": f"{app_url}/api/v1/packs/{{pack_id}}"},
                    {"type": "x-mcp-server-card", "url": f"{app_url}/.well-known/mcp/server-card.json"},
                    {"type": "x-payment-protocol", "value": "x402", "network": "Base", "currency": "USDC"},
                ],
            },
            {
                "name": "DaedalMap MCP Server",
                "description": "Streamable HTTP MCP server for the DaedalMap agent lane.",
                "humanUrl": docs_url,
                "baseUrl": f"{app_url}/mcp",
                "version": "1.0",
                "tags": ["mcp", "geospatial", "hazard", "x402"],
                "properties": [
                    {"type": "x-mcp-transport", "value": "streamable-http"},
                    {"type": "x-mcp-registry", "value": "com.daedalmap/county-map"},
                    {"type": "x-loc-id-guide", "url": _docs_url("/docs/loc-id")},
                ],
            },
        ],
    }


def _build_mcp_server_json_payload(pack_id: str | None = None) -> dict:
    from mapmover.routes.mcp import get_server_description, get_server_info, get_server_registry_meta

    app_url = _public_app_url()
    normalized = _normalize_mcp_facade_pack_id(pack_id)
    server_info = get_server_info(normalized)
    publisher_meta = get_server_registry_meta(normalized)
    publisher_meta["pricing"] = _mcp_pricing_payload(normalized)
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": server_info["name"],
        "title": server_info["title"],
        "description": get_server_description(normalized),
        "version": server_info["version"],
        "repository": {
            "url": "https://github.com/xyver/daedal-map",
            "source": "github",
        },
        "websiteUrl": _public_site_url(),
        "remotes": [
            {
                "type": "streamable-http",
                "url": f"{app_url}{_mcp_remote_path(normalized)}",
            }
        ],
        "_meta": {
            "io.modelcontextprotocol.registry/publisher-provided": publisher_meta
        },
    }


def _build_v1_catalog_payload() -> dict:
    catalog_packs = []
    for pack in _build_public_pack_list(api_ready_only=True):
        detail = _build_public_pack_detail(pack.get("pack_id", ""), api_ready_only=True) or {}
        temporal = {
            "start": (detail.get("temporal_coverage") or {}).get("start", pack.get("temporal_start")),
            "end": (detail.get("temporal_coverage") or {}).get("end", pack.get("temporal_end")),
        }
        data_type = detail.get("data_type") or pack.get("data_type", "")
        title = pack.get("source_name") or pack.get("pack_id")
        geographic_levels = _normalize_geographic_levels(
            detail.get("geographic_level"),
            [source.get("geographic_level") for source in detail.get("subsources") or []],
        )
        catalog_packs.append({
            "pack_id": pack.get("pack_id"),
            "title": title,
            "short_description": pack.get("description", ""),
            "category": pack.get("category", "other"),
            "data_types": [data_type] if data_type else [],
            "scopes": [pack.get("scope")] if pack.get("scope") else [],
            "geographic_levels": geographic_levels,
            "temporal_start": temporal.get("start"),
            "temporal_end": temporal.get("end"),
            "metric_count": len(detail.get("metrics") or {}),
            "source_count": pack.get("source_count", 0),
            "supported_query_shapes": _infer_supported_query_shapes(data_type, temporal),
            "sample_questions": _sample_questions_for_pack(pack.get("pack_id", ""), data_type, title)[:1],
            "free_detail": True,
            "paid_data_calls": _pack_is_paid(pack.get("pack_id")),
            "query_target_type": "source",
        })

    return {
        "catalog_version": "1.0",
        "generated_at": _utc_now_iso(),
        "source_mode": "public_runtime",
        "pack_count": len(catalog_packs),
        "packs": catalog_packs,
    }


def _build_v1_pack_payload(pack_id: str) -> dict | None:
    pack = _build_public_pack_detail(pack_id, api_ready_only=True)
    if not pack:
        return None

    temporal = pack.get("temporal_coverage") or {}
    data_type = pack.get("data_type", "")
    title = pack.get("source_name") or pack_id
    pack_sources = []
    for source in pack.get("subsources") or []:
        source_temporal = source.get("temporal_coverage") or {}
        source_metrics = source.get("metrics") or {}
        pack_sources.append({
            "source_id": source.get("source_id"),
            "source_name": source.get("source_name"),
            "path": source.get("path"),
            "data_type": data_type,
            "short_description": source.get("description", ""),
            "metric_count": len(source_metrics),
            "metric_ids": sorted(source_metrics.keys()),
            "temporal_coverage": source_temporal,
            "time_field": "year" if source_temporal.get("granularity") == "yearly" else "time",
            "location_field": "loc_id",
            "supported_query_shapes": _infer_supported_query_shapes(data_type, source_temporal or temporal),
            "queryable": True,
        })

    return {
        "pack_version": "1.0",
        "generated_at": _utc_now_iso(),
        "pack": {
            "pack_id": pack_id,
            "title": title,
            "description": pack.get("description", ""),
            "source_count": pack.get("source_count", 0),
            "source_ids": pack.get("source_ids", []),
            "data_types": [data_type] if data_type else [],
            "category": pack.get("category", "other"),
            "location": {
                "scopes": [pack.get("scope")] if pack.get("scope") else [],
                "geographic_levels": [],
                "coverage_description": pack.get("coverage_description", ""),
            },
            "topic_tags": pack.get("topic_tags") or [],
            "temporal_coverage": temporal,
            "metric_count": len(pack.get("metrics") or {}),
            "metrics": pack.get("metrics") or {},
            "supported_query_shapes": _infer_supported_query_shapes(data_type, temporal),
            "sample_questions": _sample_questions_for_pack(pack_id, data_type, title),
            "query_dimensions": {
                "source": "single_required_for_execution",
                "data": "single_or_variable_within_source",
                "location": "single_or_variable",
                "time": "single_or_variable",
            },
            "query_rule": "easy_if_one_query_one_source",
            "free_detail": True,
            "paid_data_calls": _pack_is_paid(pack_id),
            "sources": pack_sources,
        },
    }


async def decode_request_body(request: Request) -> dict:
    """Decode MessagePack request body."""
    body_bytes = await request.body()
    return msgpack.unpackb(body_bytes, raw=False)


@router.get("/health")
async def health_check():
    """Health check endpoint for Railway/Docker deployments."""
    return {"status": "healthy", "service": "county-map-api"}


@router.post("/api/feedback")
async def submit_feedback(request: Request):
    """Accept anonymous feedback and write it to the Supabase feedback table.
    Accepts both msgpack (map app) and JSON (the .com site).
    """
    from mapmover.paths import APP_URL

    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.check(f"feedback:ip:{client_ip}", limit=8, window_seconds=600)
    if not allowed:
        response = msgpack_response({"error": "Too many feedback submissions", "retry_after": retry_after}, 429)
        response.headers["Retry-After"] = str(retry_after)
        return response

    try:
        content_type = request.headers.get("content-type", "")
        raw = await request.body()
        if "application/json" in content_type:
            body = json.loads(raw)
        else:
            body = msgpack.unpackb(raw, raw=False)
    except Exception:
        return msgpack_error("Invalid request body", 400)

    message = (body.get("message") or "").strip()
    if not message:
        return msgpack_error("Message is required", 400)
    if len(message) > 2000:
        return msgpack_error("Message too long (max 2000 chars)", 400)

    auth_user = get_authenticated_user(request)
    verified_user_id = (auth_user or {}).get("id")
    requested_user_id = body.get("user_id") or None
    user_id = verified_user_id if verified_user_id else None
    if requested_user_id and requested_user_id != verified_user_id:
        logger.warning(
            "Ignoring spoofed feedback user_id: requested=%s verified=%s ip=%s",
            requested_user_id,
            verified_user_id,
            client_ip,
        )

    # Derive source from configured app/site URLs rather than hardcoded domains.
    origin = request.headers.get("origin", "") or request.headers.get("referer", "")
    origin_lower = origin.lower()
    app_host = _configured_host(APP_URL)
    site_host = _configured_host(ACCOUNT_URL)
    if app_host and app_host in origin_lower:
        source = app_host
    elif site_host and site_host in origin_lower:
        source = site_host
    else:
        source = "local"

    try:
        from supabase_client import get_supabase_client
        sb = get_supabase_client()
        if sb:
            row = {"message": message, "source": source}
            if user_id:
                row["user_id"] = user_id
            sb.client.table("feedback").insert(row).execute()
        else:
            logger.warning("Feedback received but Supabase not configured: %s", message[:80])
    except Exception as exc:
        logger.error("Failed to save feedback: %s", exc)
        return msgpack_error("Could not save feedback right now", 500)

    return msgpack_response({"ok": True})


@router.get("/debug/cache")
async def debug_cache(req: Request):
    """List files in the runtime data root."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    from mapmover.duckdb_helpers import is_cloud_mode
    from mapmover.paths import DATA_ROOT
    data_dir = DATA_ROOT
    if not data_dir.exists():
        return {"error": f"data root does not exist: {data_dir}"}
    files = sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob("*") if p.is_file())
    return {
        "cloud_mode": is_cloud_mode(),
        "data_root": str(data_dir),
        "file_count": len(files),
        "files": files,
    }


@router.get("/debug/s3")
async def debug_s3(req: Request):
    """Test DuckDB S3/httpfs connectivity against a known small file in R2."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    import traceback
    from mapmover.duckdb_helpers import _make_connection, is_cloud_mode, path_to_uri
    from mapmover.paths import DATA_ROOT

    if not is_cloud_mode():
        return {"cloud_mode": False, "error": "Not in cloud mode"}

    # Use a small known file: global/un_sdg/06/all_countries.parquet
    test_path = DATA_ROOT / "global" / "un_sdg" / "06" / "all_countries.parquet"
    uri = path_to_uri(test_path)

    result = {"cloud_mode": True, "uri": uri}
    try:
        con = _make_connection()
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [uri]).fetchone()
        con.close()
        result["row_count"] = rows[0] if rows else 0
        result["ok"] = True
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
    return result


@router.get("/debug/geometry")
async def debug_geometry(req: Request):
    """Test geometry loading and SDG order pipeline."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    import traceback
    import pandas as pd
    from mapmover.paths import DATA_ROOT, GEOMETRY_DIR
    from mapmover.geometry_handlers import load_global_countries, get_geometry_path

    result = {
        "DATA_ROOT": str(DATA_ROOT),
        "GEOMETRY_DIR": str(GEOMETRY_DIR),
        "geometry_dir_exists": GEOMETRY_DIR.exists(),
    }

    global_csv = GEOMETRY_DIR / "global.csv"
    result["global_csv_path"] = str(global_csv)
    result["global_csv_exists"] = global_csv.exists()

    try:
        geom_path = get_geometry_path()
        result["get_geometry_path"] = str(geom_path) if geom_path else None
    except Exception as e:
        result["get_geometry_path_error"] = str(e)

    try:
        df = load_global_countries()
        if df is None:
            result["load_global_countries"] = None
        else:
            result["load_global_countries_rows"] = len(df)
            result["load_global_countries_cols"] = list(df.columns)
            has_geom = "geometry" in df.columns
            result["has_geometry_col"] = has_geom
            if has_geom:
                non_null = df["geometry"].notna().sum()
                result["non_null_geometry"] = int(non_null)
                sample = df[df["geometry"].notna()]["geometry"].iloc[0][:80] if non_null > 0 else None
                result["geometry_sample"] = sample
    except Exception as e:
        result["load_global_countries_error"] = str(e)
        result["traceback"] = traceback.format_exc()

    return result


def _get_entitled_packs(req: Request):
    """
    Return the set of pack_ids this request is entitled to, or None for full bypass.

    None  -> full bypass: all catalog sources returned, including those without pack_id.
             Applies to: master plan, is_admin=True, or no service key (dev/self-host).
    set() -> anonymous or entitlement lookup failed: geometry_global only.
    {..}  -> authenticated user: their entitled pack_ids from Supabase.

    Plan tiers:
      master      -> None (owner, sees everything including untagged/unreleased sources)
      is_admin    -> None (admin flag on any plan, same full bypass)
      enterprise  -> entitled packs from pack_entitlements
      pro         -> entitled packs from pack_entitlements
      member      -> entitled packs from pack_entitlements
      free        -> entitled packs from pack_entitlements (usually geometry_global only)
      anonymous   -> empty set
    """
    auth_user = get_authenticated_user(req)
    if not auth_user:
        return set()

    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not service_key:
        # Dev / self-host mode: no entitlement enforcement
        return None

    user_id = auth_user.get("id")
    try:
        from supabase_client import SupabaseClient
        supa = SupabaseClient()
        context = supa.get_user_entitlement_context(user_id)
        if context and not context.get("error"):
            # Master plan or admin flag: full bypass, no pack_id filtering at all
            if context.get("plan_id") == "master" or context.get("is_admin"):
                return None
            user_packs = set(context.get("user_packs") or [])
            org_packs = set(context.get("org_packs") or [])
            return user_packs | org_packs
    except Exception as exc:
        logger.warning(f"Entitlement lookup failed for catalog filter: {exc}")

    # Fallback: authenticated but entitlement fetch failed
    return set()


@router.get("/api/catalog/sources")
async def get_catalog_sources(req: Request):
    """
    Return catalog sources filtered to what this request is entitled to see.

    Master / admin / no-service-key: all sources, including those without pack_id.
    Authenticated user: only sources whose pack_id is in their entitled set.
    Anonymous: empty list.

    Response fields per source: source_id, pack_id, source_name, category,
    data_type, scope, topic_tags.  Full catalog metadata is not included to
    keep the response small.
    """
    from mapmover.data_loading import load_catalog

    entitled = _get_entitled_packs(req)
    all_sources = load_catalog().get("sources", [])

    SUMMARY_KEYS = {"source_id", "pack_id", "source_name", "category", "data_type", "scope", "topic_tags"}

    if entitled is None:
        # Master / bypass: return everything
        sources = [{k: s.get(k) for k in SUMMARY_KEYS} for s in all_sources]
    elif not entitled:
        # Anonymous or entitlement lookup failed
        sources = []
    else:
        sources = [
            {k: s.get(k) for k in SUMMARY_KEYS}
            for s in all_sources
            if s.get("pack_id") in entitled
        ]

    return msgpack_response({"sources": sources, "total": len(sources)})


@router.get("/api/catalog/packs")
async def get_catalog_packs_list(req: Request):
    """
    Return the human/app pack catalog: all published app-visible packs.
    No auth required - pack_id assignment is the publish gate for this surface.
    Supports ?format=json for the .com packs browsing page and app-side catalog use.
    """
    from fastapi.responses import JSONResponse

    packs = _build_public_pack_list()

    fmt = req.query_params.get("format", "")
    if fmt == "json":
        return JSONResponse({"packs": packs, "total": len(packs)})
    return msgpack_response({"packs": packs, "total": len(packs)})


@router.get("/api/catalog/packs/{pack_id}")
async def get_catalog_pack(pack_id: str, req: Request):
    """
    Return full metadata for one human/app pack profile by pack_id.
    Merges all app-visible sources sharing that pack_id into one pack profile.
    Published packs are publicly readable without auth.
    Supports ?format=json for the .com public pack profile pages.
    """
    from fastapi.responses import JSONResponse

    pack = _build_public_pack_detail(pack_id)
    if not pack:
        return msgpack_error("Pack not found", 404)

    fmt = req.query_params.get("format", "")
    if fmt == "json":
        return JSONResponse({"pack": pack})
    return msgpack_response({"pack": pack})


@router.get("/api/v1/guide")
async def get_v1_guide():
    """Return the agent/API usage guide for the current v1 discovery surface."""
    from mapmover.data_loading import load_api_guide

    payload = load_api_guide() or _build_v1_guide_payload()
    return JSONResponse(payload)


@router.get("/api/v1/catalog")
async def get_v1_catalog():
    """Return the agent/API catalog filtered to sources marked api_ready."""
    from mapmover.data_loading import load_api_catalog

    payload = load_api_catalog()
    return JSONResponse(payload)


@router.get("/.well-known/mcp/server-card.json")
async def get_mcp_server_card():
    response = JSONResponse(_build_mcp_server_card_payload())
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/.well-known/mcp/{pack_id}/server-card.json")
async def get_pack_mcp_server_card(pack_id: str):
    normalized = _normalize_mcp_facade_pack_id(pack_id)
    if not normalized:
        return JSONResponse({"error": "Pack MCP facade not found"}, status_code=404)
    response = JSONResponse(_build_mcp_server_card_payload(normalized))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/apis.json")
async def get_apis_json():
    response = JSONResponse(_build_apis_json_payload())
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/mcp/server.json")
async def get_mcp_server_json():
    response = JSONResponse(_build_mcp_server_json_payload())
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/mcp/{pack_id}/server.json")
async def get_pack_mcp_server_json(pack_id: str):
    normalized = _normalize_mcp_facade_pack_id(pack_id)
    if not normalized:
        return JSONResponse({"error": "Pack MCP facade not found"}, status_code=404)
    response = JSONResponse(_build_mcp_server_json_payload(normalized))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/v1/packs/{pack_id}")
async def get_v1_pack(pack_id: str):
    """Return the agent/API pack detail filtered to api_ready sources only."""
    from mapmover.data_loading import load_api_pack_detail

    payload = load_api_pack_detail(pack_id)
    if not payload:
        return JSONResponse({"error": "Pack not found"}, status_code=404)
    return JSONResponse(payload)


@router.get("/api/catalog/overlays")
async def get_catalog_overlays(req: Request):
    """Get overlay tree from the catalog, filtered to the user's entitled packs."""
    from mapmover.data_loading import load_catalog

    catalog = load_catalog()
    entitled = _get_entitled_packs(req)

    all_sources = catalog.get("sources", [])

    if entitled is None:
        # No service key - dev/self-host mode, return everything
        filtered_sources = all_sources
    else:
        # Filter to entitled packs; sources with no pack_id are excluded
        # geometry_global is always included for authenticated users
        entitled_with_base = entitled | {"geometry_global"}
        if entitled:
            # Authenticated with entitlements: include entitled packs + geometry_global
            filtered_sources = [
                s for s in all_sources
                if s.get("pack_id") in entitled_with_base
            ]
        else:
            # Anonymous: geometry_global only
            filtered_sources = [
                s for s in all_sources
                if s.get("pack_id") == "geometry_global"
            ]

    return msgpack_response(
        {
            "sources": filtered_sources,
            "overlay_tree": catalog.get("overlay_tree", {}),
            "overlay_count": len(filtered_sources),
        }
    )


@router.get("/api/runtime/packs/state")
async def get_runtime_packs_state(req: Request):
    """Return runtime-local pack installation and activation state."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.data_loading import load_full_catalog
    from mapmover.pack_state import get_runtime_pack_summary
    from mapmover.runtime_config import get_runtime_config
    from mapmover.paths import DATA_ROOT, INSTALL_MODE, PACKS_ROOT, RUNTIME_MODE

    summary = get_runtime_pack_summary(load_full_catalog())
    cloud_cfg = get_runtime_config().get("cloud", {})
    summary.update({
        "install_mode": INSTALL_MODE,
        "runtime_mode": RUNTIME_MODE,
        "data_root": str(DATA_ROOT),
        "packs_root": str(PACKS_ROOT),
        "cloud_prefix": str(cloud_cfg.get("prefix", "")).strip(),
        "staging_prefix": str(os.getenv("S3_STAGING_PREFIX", "staging")).strip(),
        "published_prefix": str(os.getenv("S3_PUBLISHED_PREFIX", "published")).strip(),
    })
    return msgpack_response(summary)


@router.get("/api/runtime/packs/release-markers")
async def get_runtime_pack_release_markers(req: Request):
    """Return optional pack release markers for release-lane visibility."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.paths import APP_ROOT
    global _release_marker_cache, _release_marker_cache_time

    def _response(payload: dict):
        if req.query_params.get("format") == "json":
            return JSONResponse(payload)
        return msgpack_response(payload)

    now = time.time()
    if _release_marker_cache is not None and (now - _release_marker_cache_time) < _RELEASE_MARKER_TTL_SECONDS:
        return _response(_release_marker_cache)

    candidates = []
    configured = os.getenv("PACK_RELEASE_MARKERS_PATH", "").strip()
    if configured:
        candidates.append(Path(configured))

    # Local dev convenience: if the private repo is present beside the public app,
    # surface the latest generated marker file without requiring a second server.
    candidates.append(
        APP_ROOT.parent / "county-map-private" / "build" / "qa" / "results" / "pack_release_markers_latest.json"
    )

    for candidate in candidates:
        try:
            if candidate.exists():
                with candidate.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict):
                    _release_marker_cache = payload
                    _release_marker_cache_time = now
                    return _response(payload)
        except Exception:
            continue

    try:
        import boto3

        bucket = os.getenv("S3_BUCKET", "").strip()
        if bucket:
            control_prefix = os.getenv("S3_CONTROL_PREFIX", "control").strip().strip("/")
            key = f"{control_prefix}/pack_release_markers_latest.json" if control_prefix else "pack_release_markers_latest.json"
            endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
            region = os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION") or "auto"
            client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
            response = client.get_object(Bucket=bucket, Key=key)
            payload = json.loads(response["Body"].read().decode("utf-8"))
            if isinstance(payload, dict):
                _release_marker_cache = payload
                _release_marker_cache_time = now
                return _response(payload)
    except Exception:
        pass

    payload = {"generated_at": None, "packs": []}
    _release_marker_cache = payload
    _release_marker_cache_time = now
    return _response(payload)


@router.post("/api/runtime/packs/active")
async def set_runtime_active_packs(req: Request):
    """Set the runtime-local active pack ids and refresh the active catalog."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.data_loading import load_full_catalog
    from mapmover.pack_state import materialize_active_data_root, set_active_pack_ids

    try:
        body = await decode_request_body(req)
        active_pack_ids = body.get("active_pack_ids", [])
        catalog_mode = body.get("catalog_mode") or None
        state = set_active_pack_ids(active_pack_ids, catalog_mode=catalog_mode)
        materialization = materialize_active_data_root(load_full_catalog(), state)
        clear_metadata_cache()
        clear_public_pack_catalog_cache()
        initialize_catalog()
        logger.info(
            "Hosted runtime packs updated: user_id=%s active_pack_ids=%s catalog_mode=%s",
            (get_authenticated_user(req) or {}).get("id"),
            state.get("active_pack_ids", []),
            state.get("catalog_mode"),
        )
        return msgpack_response({"ok": True, "state": state, "materialization": materialization})
    except Exception as exc:
        logger.error(f"Error updating runtime active packs: {exc}")
        return msgpack_error(str(exc), 500)


@router.post("/api/runtime/packs/install-local")
async def install_runtime_pack_local(req: Request):
    """Bootstrap a local installed pack from the current full data tree."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.data_loading import load_full_catalog
    from mapmover.pack_manager import install_pack_from_local_catalog

    try:
        body = await decode_request_body(req)
        pack_id = str(body.get("pack_id", "")).strip()
        source_data_root = body.get("source_data_root") or None
        activate = bool(body.get("activate", False))
        replace_existing = bool(body.get("replace_existing", True))
        if not pack_id:
            return msgpack_error("pack_id is required", 400)
        local_install_error = _require_hosted_pack_local_disabled()
        if local_install_error:
            return local_install_error

        result = install_pack_from_local_catalog(
            pack_id,
            load_full_catalog(),
            source_data_root=source_data_root,
            activate=activate,
            replace_existing=replace_existing,
        )
        clear_metadata_cache()
        clear_public_pack_catalog_cache()
        initialize_catalog()
        logger.info(
            "Runtime pack installed from local catalog: user_id=%s pack_id=%s activate=%s",
            (get_authenticated_user(req) or {}).get("id"),
            pack_id,
            activate,
        )
        return msgpack_response({"ok": True, **result})
    except Exception as exc:
        logger.error(f"Error installing runtime pack locally: {exc}")
        return msgpack_error(str(exc), 500)


@router.post("/api/runtime/packs/uninstall")
async def uninstall_runtime_pack(req: Request):
    """Remove an installed runtime pack and refresh the active catalog if needed."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.data_loading import load_full_catalog
    from mapmover.pack_manager import uninstall_pack

    try:
        body = await decode_request_body(req)
        pack_id = str(body.get("pack_id", "")).strip()
        if not pack_id:
            return msgpack_error("pack_id is required", 400)

        result = uninstall_pack(pack_id, load_full_catalog())
        clear_metadata_cache()
        clear_public_pack_catalog_cache()
        initialize_catalog()
        logger.info(
            "Runtime pack uninstalled: user_id=%s pack_id=%s",
            (get_authenticated_user(req) or {}).get("id"),
            pack_id,
        )
        return msgpack_response({"ok": True, **result})
    except Exception as exc:
        logger.error(f"Error uninstalling runtime pack: {exc}")
        return msgpack_error(str(exc), 500)


@router.post("/api/runtime/packs/install-manifest")
async def install_runtime_pack_manifest(req: Request):
    """Install a staged pack artifact from a local manifest path."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.pack_manager import install_pack_from_manifest

    try:
        body = await decode_request_body(req)
        manifest_path = body.get("manifest_path")
        activate = bool(body.get("activate", False))
        replace_existing = bool(body.get("replace_existing", True))
        if not manifest_path:
            return msgpack_error("manifest_path is required", 400)
        manifest_install_error = _require_hosted_pack_local_disabled()
        if manifest_install_error:
            return manifest_install_error

        result = install_pack_from_manifest(
            manifest_path,
            activate=activate,
            replace_existing=replace_existing,
        )
        clear_metadata_cache()
        clear_public_pack_catalog_cache()
        initialize_catalog()
        logger.info(
            "Runtime pack installed from manifest: user_id=%s manifest_path=%s activate=%s",
            (get_authenticated_user(req) or {}).get("id"),
            manifest_path,
            activate,
        )
        return msgpack_response({"ok": True, **result})
    except Exception as exc:
        logger.error(f"Error installing runtime pack from manifest: {exc}")
        return msgpack_error(str(exc), 500)


@router.post("/api/runtime/packs/install-ref")
async def install_runtime_pack_ref(req: Request):
    """Stage and install a pack artifact from a manifest reference."""
    _context, error = _require_admin(req)
    if error:
        return error

    from mapmover.pack_manager import install_pack_from_manifest_ref

    try:
        body = await decode_request_body(req)
        manifest_ref = body.get("manifest_ref")
        artifact_base_ref = body.get("artifact_base_ref") or None
        activate = bool(body.get("activate", False))
        replace_existing = bool(body.get("replace_existing", True))
        if not manifest_ref:
            return msgpack_error("manifest_ref is required", 400)
        manifest_ref_error = _require_hosted_https_ref(manifest_ref, "manifest_ref")
        if manifest_ref_error:
            return manifest_ref_error
        manifest_host_error = _require_hosted_allowed_ref_host(manifest_ref, "manifest_ref")
        if manifest_host_error:
            return manifest_host_error
        artifact_ref_error = _require_hosted_https_ref(artifact_base_ref, "artifact_base_ref")
        if artifact_ref_error:
            return artifact_ref_error
        artifact_host_error = _require_hosted_allowed_ref_host(artifact_base_ref, "artifact_base_ref")
        if artifact_host_error:
            return artifact_host_error

        result = install_pack_from_manifest_ref(
            manifest_ref,
            artifact_base_ref=artifact_base_ref,
            activate=activate,
            replace_existing=replace_existing,
        )
        clear_metadata_cache()
        clear_public_pack_catalog_cache()
        initialize_catalog()
        logger.info(
            "Runtime pack installed from manifest ref: user_id=%s manifest_ref=%s activate=%s",
            (get_authenticated_user(req) or {}).get("id"),
            manifest_ref,
            activate,
        )
        return msgpack_response({"ok": True, **result})
    except Exception as exc:
        logger.error(f"Error installing runtime pack from manifest ref: {exc}")
        return msgpack_error(str(exc), 500)


@router.post("/api/admin/catalog/refresh")
async def admin_catalog_refresh(req: Request):
    """
    Force an immediate refresh from R2 for runtime catalog, agent catalog, or both.
    Restricted to master plan and is_admin users only.
    """
    import mapmover.data_loading as _dl

    auth_user = get_authenticated_user(req)
    if not auth_user:
        logger.warning(
            "Denied admin catalog refresh: anonymous caller ip=%s",
            get_client_ip(req),
        )
        return msgpack_error("Unauthorized", 401)

    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if service_key:
        try:
            from supabase_client import SupabaseClient
            supa = SupabaseClient()
            context = supa.get_user_entitlement_context(auth_user.get("id"))
            if not context or context.get("error"):
                logger.warning(
                    "Denied admin catalog refresh: entitlement lookup empty user_id=%s",
                    auth_user.get("id"),
                )
                return msgpack_error("Forbidden", 403)
            if context.get("plan_id") != "master" and not context.get("is_admin"):
                logger.warning(
                    "Denied admin catalog refresh: insufficient privileges user_id=%s plan_id=%s is_admin=%s",
                    auth_user.get("id"),
                    context.get("plan_id"),
                    context.get("is_admin"),
                )
                return msgpack_error("Forbidden", 403)
        except Exception as exc:
            logger.warning(f"Admin catalog refresh: entitlement check failed: {exc}")
            return msgpack_error("Entitlement check failed", 500)

    wants_json = "application/json" in (req.headers.get("accept", "") or "").lower()
    surface = str(req.query_params.get("surface", "all") or "all").strip().lower()
    if surface not in {"all", "runtime", "agent"}:
        return msgpack_error("surface must be one of: all, runtime, agent", 400)

    refreshed: list[str] = []
    source_count = None
    api_pack_count = None

    if surface in {"all", "runtime"}:
        _dl._catalog_cache = None
        _dl._catalog_cache_time = 0.0
        _dl._catalog_missing_time = 0.0
        clear_metadata_cache()
        clear_public_pack_catalog_cache()
        initialize_catalog()
        source_count = len((_dl.load_catalog() or {}).get("sources", []))
        refreshed.append("runtime")

    if surface in {"all", "agent"}:
        _dl.clear_api_discovery_cache()
        api_pack_count = len((_dl.load_api_catalog() or {}).get("packs", []))
        refreshed.append("agent")

    payload = {
        "ok": True,
        "surface": surface,
        "refreshed": refreshed,
        "source_count": source_count,
        "api_pack_count": api_pack_count,
        "message": "Requested catalog caches cleared and refreshed",
    }
    if wants_json:
        return JSONResponse(payload)
    return msgpack_response(payload)


@router.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the frontend HTML shell with cache-busting version stamps on static assets."""
    template_path = BASE_DIR / "templates" / "index.html"
    static_dir = BASE_DIR / "static"

    def _v(rel: str) -> str:
        p = static_dir / rel
        try:
            return str(int(p.stat().st_mtime))
        except OSError:
            return "0"

    html = template_path.read_text(encoding="utf-8")
    html = html.replace('href="/static/styles/map.css"', f'href="/static/styles/map.css?v={_v("styles/map.css")}"')
    html = html.replace('href="/static/styles/chat.css"', f'href="/static/styles/chat.css?v={_v("styles/chat.css")}"')
    return html


@router.get("/settings", response_class=HTMLResponse)
async def serve_settings_page(request: Request):
    """Serve local runtime setup guidance, or redirect to hosted account settings."""
    from mapmover.paths import CONFIG_DIR, DATA_ROOT, PACKS_ROOT, SETTINGS_PATH, SITE_URL
    from mapmover.runtime_config import get_runtime_config

    if _hosted_auth_enabled() and not _is_localish_url(SITE_URL):
        return RedirectResponse(url=f"{SITE_URL}/account", status_code=302)
    runtime_mode = str(get_runtime_config().get("mode", "") or os.getenv("RUNTIME_MODE", "")).strip().lower()
    if runtime_mode and runtime_mode != "local":
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)

    llm_ready = bool(os.getenv("ANTHROPIC_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip())
    llm_status = "Configured" if llm_ready else "Missing"
    llm_note = (
        "Chat can run with your configured provider key."
        if llm_ready
        else "Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env before using chat."
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Local Setup - DaedalMap</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f1724;
                color: #e5eef8;
                margin: 0;
                padding: 32px 18px 48px;
            }}
            .shell {{
                max-width: 820px;
                margin: 0 auto;
            }}
            .card {{
                background: #152235;
                border: 1px solid rgba(147, 197, 253, 0.12);
                border-radius: 14px;
                padding: 22px 24px;
                margin-top: 18px;
            }}
            h1, h2 {{
                margin: 0 0 12px;
            }}
            p, li {{
                line-height: 1.6;
                color: #bfd0e4;
            }}
            ul {{
                margin: 10px 0 0 18px;
                padding: 0;
            }}
            code {{
                background: rgba(15, 23, 36, 0.7);
                border-radius: 6px;
                padding: 2px 6px;
                color: #f8fafc;
            }}
            .status-ok {{
                color: #86efac;
                font-weight: 700;
            }}
            .status-warn {{
                color: #fbbf24;
                font-weight: 700;
            }}
            a {{
                color: #7dd3fc;
            }}
        </style>
    </head>
    <body>
        <div class="shell">
            <h1>Local Runtime Setup</h1>
            <p>This self-host runtime does not require a hosted DaedalMap account. For a usable local setup, configure your LLM key and point the runtime at local data.</p>

            <div class="card">
                <h2>Required Settings</h2>
                <ul>
                    <li><code>OPENAI_API_KEY</code> or <code>ANTHROPIC_API_KEY</code>: <span class="{"status-ok" if llm_ready else "status-warn"}">{llm_status}</span></li>
                    <li><code>DATA_ROOT</code>: point this at your local data tree if you are not using the default app-data location</li>
                </ul>
                <p>{llm_note}</p>
            </div>

            <div class="card">
                <h2>Current Runtime Paths</h2>
                <ul>
                    <li><code>DATA_ROOT</code>: {DATA_ROOT}</li>
                    <li><code>PACKS_ROOT</code>: {PACKS_ROOT}</li>
                    <li><code>CONFIG_DIR</code>: {CONFIG_DIR}</li>
                    <li><code>SETTINGS_PATH</code>: {SETTINGS_PATH}</li>
                </ul>
            </div>

            <div class="card">
                <h2>Notes</h2>
                <ul>
                    <li>Hosted account, billing, and admin controls are optional and are not required for self-host/local use.</li>
                    <li>Pack download/install flow is still being built. For now, local data should come from your existing data tree under <code>DATA_ROOT</code>.</li>
                    <li>See <a href="/">the app</a> to return to the map runtime.</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/reference/admin-levels")
async def get_admin_levels():
    """Get admin level names for all countries."""
    try:
        ref_path = BASE_DIR / "mapmover" / "reference" / "admin_levels.json"
        if not ref_path.exists():
            return msgpack_error("admin_levels.json not found", 404)

        with open(ref_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return msgpack_response(data)
    except Exception as e:
        logger.error(f"Error loading admin_levels.json: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/auth/config")
async def get_auth_config():
    """Return safe public auth configuration for the frontend."""
    from mapmover.paths import ACCOUNT_URL, SITE_URL

    enabled = _hosted_auth_enabled()
    return {
        "enabled": enabled,
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY", ""),
        "site_url": SITE_URL,
        "account_url": ACCOUNT_URL if enabled else "/settings",
    }


@router.get("/api/auth/me")
async def get_auth_me(req: Request):
    """
    Return the current user's identity and plan info.

    - Unauthenticated: returns guest defaults
    - Authenticated without service key: returns basic identity from token
    - Authenticated with service key: returns full profile and plan from Supabase
    """
    auth_user = get_authenticated_user(req)

    if not auth_user:
        return msgpack_response({
            "authenticated": False,
            "plan_id": "free",
            "enabled_shells": ["simple"],
            "max_packs": 2,
        })

    user_id = auth_user.get("id")
    email = auth_user.get("email")

    # Try to load full profile via service key
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if service_key:
        try:
            from supabase_client import SupabaseClient
            supa = SupabaseClient()
            context = supa.get_user_entitlement_context(user_id)
            if context and not context.get("error"):
                return msgpack_response({
                    "authenticated": True,
                    "user_id": user_id,
                    "email": email,
                    "plan_id": context.get("plan_id", "free"),
                    "is_admin": context.get("is_admin", False),
                    "enabled_shells": context.get("enabled_shells", ["simple"]),
                    "max_packs": context.get("max_packs", 2),
                    "org_id": context.get("org_id"),
                    "user_packs": context.get("user_packs", []),
                    "org_packs": context.get("org_packs", []),
                    "account_url": ACCOUNT_URL,
                })
        except Exception as exc:
            logger.warning(f"Failed to load entitlement context: {exc}")

    # Fallback: identity from token only, default to free plan
    return msgpack_response({
        "authenticated": True,
        "user_id": user_id,
        "email": email,
        "plan_id": "free",
        "enabled_shells": ["simple"],
        "max_packs": 2,
    })


@router.post("/api/orders/queue")
async def queue_order_endpoint(req: Request):
    """Add an order to the processing queue."""
    try:
        body = await decode_request_body(req)
        items = body.get("items", [])
        hints = body.get("hints", {})
        frontend_session_id, session_id, auth_user = _resolve_order_session_key(req, body.get("session_id"))
        limiter_identity = (auth_user or {}).get("id") or get_client_ip(req) or "unknown"
        allowed, retry_after = rate_limiter.check(f"orders:queue:{limiter_identity}", limit=20, window_seconds=60)
        if not allowed:
            return _order_rate_limited_response("Too many queued orders. Please slow down and try again shortly.", retry_after)
        if not items:
            return msgpack_error("No items provided", 400)

        queue_id = order_queue.add(items, hints, session_id)
        order = order_queue.get(queue_id)
        return msgpack_response(
            {
                "queue_id": queue_id,
                "status": "queued",
                "position": order.position if order else 0,
                "message": order.message if order else "Queued",
                "session_id": frontend_session_id,
            }
        )
    except Exception as e:
        logger.error(f"Error queueing order: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/orders/status")
async def get_order_status_endpoint(req: Request):
    """Get status of one or more queued orders."""
    try:
        body = await decode_request_body(req)
        queue_ids = body.get("queue_ids", [])
        _frontend_session_id, session_id, auth_user = _resolve_order_session_key(req, body.get("session_id"))
        rate_limit = _order_status_rate_limit(req, auth_user)
        if rate_limit:
            return rate_limit
        if not queue_ids:
            return msgpack_error("No queue_ids provided", 400)

        statuses = {}
        for qid in queue_ids:
            if not order_queue.belongs_to_session(qid, session_id):
                statuses[qid] = {"error": "Not found", "status": "not_found"}
                continue
            status = order_queue.get_status(qid)
            statuses[qid] = status if status else {"error": "Not found", "status": "not_found"}
        return msgpack_response(statuses)
    except Exception as e:
        logger.error(f"Error getting order status: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/orders/status/{queue_id}")
async def get_single_order_status_endpoint(queue_id: str, req: Request):
    """Get status of a single queued order."""
    try:
        _frontend_session_id, session_id, auth_user = _resolve_order_session_key(req, req.query_params.get("session_id"))
        rate_limit = _order_status_rate_limit(req, auth_user)
        if rate_limit:
            return rate_limit
        if not order_queue.belongs_to_session(queue_id, session_id):
            return msgpack_error("Order not found", 404)
        status = order_queue.get_status(queue_id)
        if not status:
            return msgpack_error("Order not found", 404)
        return msgpack_response(status)
    except Exception as e:
        logger.error(f"Error getting order status: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/orders/cancel")
async def cancel_order_endpoint(req: Request):
    """Cancel a pending order."""
    try:
        body = await decode_request_body(req)
        queue_id = body.get("queue_id")
        _frontend_session_id, session_id, auth_user = _resolve_order_session_key(req, body.get("session_id"))
        rate_limit = _order_status_rate_limit(req, auth_user)
        if rate_limit:
            return rate_limit
        if not queue_id:
            return msgpack_error("No queue_id provided", 400)
        if not order_queue.belongs_to_session(queue_id, session_id):
            return msgpack_response({"cancelled": False, "reason": "Order not found or not owned by this session"})

        cancelled = order_queue.cancel(queue_id)
        if cancelled:
            return msgpack_response({"cancelled": True})
        return msgpack_response({"cancelled": False, "reason": "Order not found or already processing"})
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/orders/session/{session_id}")
async def get_session_orders_endpoint(session_id: str, req: Request):
    """Get all queued orders for a session."""
    try:
        _frontend_session_id, scoped_session_id, auth_user = _resolve_order_session_key(req, session_id)
        rate_limit = _order_status_rate_limit(req, auth_user)
        if rate_limit:
            return rate_limit
        return msgpack_response({"orders": order_queue.get_session_orders(scoped_session_id)})
    except Exception as e:
        logger.error(f"Error getting session orders: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/session/clear")
async def clear_session_endpoint(req: Request):
    """Clear session cache for a chat session."""
    try:
        body = await decode_request_body(req)
        frontend_session_id = body.get("sessionId")
        if not frontend_session_id:
            return msgpack_error("sessionId required", 400)
        auth_user = get_authenticated_user(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)

        cleared = session_manager.clear_session(session_id)
        corpus_registry.clear_session(session_id)
        if cleared:
            logger.info(f"Cleared session cache: {session_id}")
            return msgpack_response({"status": "cleared", "sessionId": frontend_session_id})
        return msgpack_response({"status": "not_found", "sessionId": frontend_session_id})
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/session/clear-source")
async def clear_session_source_endpoint(req: Request):
    """Clear a specific source from session cache."""
    try:
        body = await decode_request_body(req)
        frontend_session_id = body.get("sessionId")
        source_id = body.get("sourceId")
        if not frontend_session_id or not source_id:
            return msgpack_error("sessionId and sourceId required", 400)
        auth_user = get_authenticated_user(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)

        cache = session_manager.get(session_id)
        if not cache:
            return msgpack_response({"status": "not_found", "sessionId": frontend_session_id})

        removed = cache.clear_source(source_id)
        artifacts_removed = corpus_registry.remove_source(session_id, source_id)
        logger.info(f"Cleared source '{source_id}' from session {session_id}: {removed} keys removed")
        return msgpack_response({"status": "cleared", "sourceId": source_id, "keys_removed": removed, "artifacts_removed": artifacts_removed})
    except Exception as e:
        logger.error(f"Error clearing session source: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/session/{session_id}/status")
async def get_session_status_endpoint(session_id: str):
    """Get session status for recovery prompt."""
    try:
        cache = session_manager.get(session_id)
        if not cache:
            return msgpack_response({"exists": False, "session_id": session_id})

        status = cache.get_status()
        status["cached_results"] = len(cache._results)
        status["inventory"] = {
            "total_locations": status.get("total_locations", 0),
            "total_metrics": status.get("total_metrics", 0),
        }
        return msgpack_response({"exists": True, **status})
    except Exception as e:
        logger.error(f"Error getting session status: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/cache/inventory/{session_id}")
async def get_cache_inventory_endpoint(session_id: str):
    """Get detailed cache inventory for a session."""
    try:
        cache = session_manager.get(session_id)
        if not cache:
            return msgpack_response({"exists": False, "session_id": session_id})

        inventory_stats = cache.inventory.stats()
        combined = cache.inventory.combined_signature()
        return msgpack_response(
            {
                "exists": True,
                "session_id": session_id,
                "inventory": {
                    "entry_count": inventory_stats["entry_count"],
                    "total_locations": inventory_stats["total_locations"],
                    "total_years": inventory_stats["total_years"],
                    "total_metrics": inventory_stats["total_metrics"],
                    "year_range": inventory_stats["year_range"],
                },
                "combined_signature": {
                    "loc_id_count": len(combined.loc_ids),
                    "year_count": len(combined.years),
                    "metric_count": len(combined.metrics),
                    "years": sorted(combined.years) if combined.years else [],
                    "metrics": sorted(combined.metrics) if combined.metrics else [],
                },
                "cached_results": len(cache._results),
            }
        )
    except Exception as e:
        logger.error(f"Error getting cache inventory: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/cache/delta")
async def compute_cache_delta_endpoint(req: Request):
    """Compute what data needs to be fetched given what is already cached."""
    try:
        body = await decode_request_body(req)
        session_id = body.get("sessionId", "anonymous")
        want = body.get("want", {})
        if not want:
            return msgpack_error("'want' field required", 400)

        requested = CacheSignature(
            loc_ids=frozenset(want.get("loc_ids", [])),
            years=frozenset(want.get("years", [])),
            metrics=frozenset(want.get("metrics", [])),
        )
        cache = session_manager.get(session_id)
        if not cache:
            return msgpack_response(
                {
                    "need_fetch": True,
                    "delta": {
                        "loc_ids": list(requested.loc_ids),
                        "years": sorted(requested.years),
                        "metrics": list(requested.metrics),
                    },
                    "have": {"loc_ids": [], "years": [], "metrics": []},
                }
            )

        if cache.can_serve(requested):
            return msgpack_response(
                {
                    "need_fetch": False,
                    "delta": {"loc_ids": [], "years": [], "metrics": []},
                    "have": {
                        "loc_ids": list(requested.loc_ids),
                        "years": sorted(requested.years),
                        "metrics": list(requested.metrics),
                    },
                }
            )

        delta = cache.compute_delta(requested)
        combined = cache.inventory.combined_signature()
        return msgpack_response(
            {
                "need_fetch": True,
                "delta": {
                    "loc_ids": list(delta.loc_ids),
                    "years": sorted(delta.years),
                    "metrics": list(delta.metrics),
                },
                "have": {
                    "loc_ids": list(combined.loc_ids),
                    "years": sorted(combined.years),
                    "metrics": list(combined.metrics),
                },
            }
        )
    except Exception as e:
        logger.error(f"Error computing cache delta: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/cache/export")
async def export_cache_endpoint(req: Request):
    """Export cached data as CSV or JSON."""
    try:
        body = await decode_request_body(req)
        session_id = body.get("sessionId", "anonymous")
        export_format = body.get("format", "csv")
        filters = body.get("filters", {})

        cache = session_manager.get(session_id)
        if not cache:
            return msgpack_error("Session not found", 404)

        all_rows = []
        for result in cache._results.values():
            features = result.get("geojson", {}).get("features", [])
            for feature in features:
                props = feature.get("properties", {})
                if filters.get("loc_ids") and props.get("loc_id") not in filters["loc_ids"]:
                    continue
                if filters.get("years"):
                    year = props.get("year")
                    if year is not None and int(year) not in filters["years"]:
                        continue

                row = {}
                for key, value in props.items():
                    if key in ["geometry", "type"]:
                        continue
                    if filters.get("metrics"):
                        non_metric_keys = {"loc_id", "year", "name", "country", "admin_level", "parent_id", "iso3"}
                        if key not in non_metric_keys and key not in filters["metrics"]:
                            continue
                    row[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
                all_rows.append(row)

        if not all_rows:
            return msgpack_error("No data in cache", 404)

        if export_format == "json":
            return msgpack_response({"format": "json", "row_count": len(all_rows), "data": all_rows})

        columns = set()
        for row in all_rows:
            columns.update(row.keys())

        priority_cols = ["loc_id", "year", "name", "country", "admin_level"]
        ordered_cols = [c for c in priority_cols if c in columns]
        ordered_cols += sorted(c for c in columns if c not in priority_cols)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=ordered_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
        csv_content = output.getvalue()

        return Response(
            content=csv_content.encode("utf-8"),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=export_{session_id[:8]}.csv"},
        )
    except Exception as e:
        logger.error(f"Error exporting cache: {e}")
        return msgpack_error(str(e), 500)


@router.get("/debug/process")
async def debug_process(req: Request):
    """Show process-level memory usage broken down by component."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    import gc
    import sys
    import tracemalloc

    result = {}

    # RSS from /proc/self/status (Linux only - works on Railway)
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    result["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("VmPeak:"):
                    result["peak_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("VmSize:"):
                    result["vms_mb"] = round(int(line.split()[1]) / 1024, 1)
    except Exception as e:
        result["proc_error"] = str(e)

    # Python object counts by type (top 20 by count)
    gc.collect()
    type_counts = {}
    for obj in gc.get_objects():
        t = type(obj).__name__
        type_counts[t] = type_counts.get(t, 0) + 1
    top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    result["top_object_types"] = [{"type": t, "count": c} for t, c in top_types]

    # Top modules by their attribute sizes (approximation of import footprint)
    module_sizes = {}
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        try:
            sz = sys.getsizeof(mod)
            module_sizes[name.split(".")[0]] = module_sizes.get(name.split(".")[0], 0) + sz
        except Exception:
            pass
    top_modules = sorted(module_sizes.items(), key=lambda x: x[1], reverse=True)[:15]
    result["top_modules_kb"] = [{"module": m, "kb": round(s / 1024, 1)} for m, s in top_modules]

    # tracemalloc snapshot - top 10 allocations by file
    if not tracemalloc.is_tracing():
        tracemalloc.start()
        result["tracemalloc"] = "just started - re-hit this endpoint in 30s for useful data"
    else:
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics("filename")[:10]
        result["tracemalloc_top_mb"] = [
            {"file": str(s.traceback).split("/")[-1], "mb": round(s.size / (1024 * 1024), 2), "count": s.count}
            for s in stats
        ]

    return result


@router.get("/debug/memory")
async def debug_memory(req: Request):
    """Show what is in the in-memory caches and estimated RAM usage."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    import time
    from mapmover.duckdb_helpers import _CACHE, _CACHE_LOCK, DEFAULT_CACHE_TTL
    from mapmover.geometry_handlers import _country_parquet_cache, _country_parquet_cache_lock

    now = time.monotonic()

    # Disaster DataFrame cache
    with _CACHE_LOCK:
        cache_snapshot = list(_CACHE.items())

    disaster_entries = []
    for key, (df, expires_at) in cache_snapshot:
        permanent = expires_at == float("inf")
        ttl_remaining = None if permanent else max(0, expires_at - now)
        mem_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
        disaster_entries.append({
            "key": key,
            "rows": len(df),
            "cols": len(df.columns),
            "mem_mb": round(mem_mb, 2),
            "permanent": permanent,
            "ttl_remaining_s": None if permanent else round(ttl_remaining),
            "expired": False if permanent else ttl_remaining == 0,
        })
    disaster_entries.sort(key=lambda x: x["mem_mb"], reverse=True)
    disaster_total_mb = sum(e["mem_mb"] for e in disaster_entries)

    # Geometry parquet cache (permanent, no TTL)
    with _country_parquet_cache_lock:
        geom_snapshot = list(_country_parquet_cache.items())

    geom_entries = []
    for key, df in geom_snapshot:
        mem_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
        geom_entries.append({
            "key": str(key),
            "rows": len(df),
            "mem_mb": round(mem_mb, 2),
        })
    geom_entries.sort(key=lambda x: x["mem_mb"], reverse=True)
    geom_total_mb = sum(e["mem_mb"] for e in geom_entries)

    return {
        "disaster_cache": {
            "entry_count": len(disaster_entries),
            "total_mb": round(disaster_total_mb, 2),
            "default_ttl_s": DEFAULT_CACHE_TTL,
            "entries": disaster_entries,
        },
        "geometry_cache": {
            "entry_count": len(geom_entries),
            "total_mb": round(geom_total_mb, 2),
            "note": "permanent, no TTL",
            "entries": geom_entries,
        },
        "combined_cache_mb": round(disaster_total_mb + geom_total_mb, 2),
    }


@router.get("/api/orders/stats")
async def get_queue_stats_endpoint(req: Request):
    """Get queue statistics for monitoring/debugging."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error

    try:
        return msgpack_response(order_queue.stats())
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return msgpack_error(str(e), 500)
