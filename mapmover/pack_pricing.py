from __future__ import annotations

# Single source of truth for pack pricing classification.
# Default is PAID: any pack NOT in FREE_PACK_IDS is treated as paid by
# pack_requires_commercial_access(). So every FREE pack MUST be listed here, in
# the same commit as its PACK_SERVER_PROFILES entry in routes/mcp.py.
# Full free<->paid switch checklist (enforcement, advertised pricing, license,
# public docs, and catalog surfaces):
# county-map-private/docs/future/API/mcp_publishing.md section 15.
FREE_PACK_IDS: frozenset[str] = frozenset(
    {
        "currency",
        "floods",
        "un_sdg",
        "volcanoes",
    }
)

PAID_PACK_IDS: frozenset[str] = frozenset(
    {
        "earthquakes",
        "tsunamis",
        "hurricanes",
        "tornadoes",
        "world_factbook",
        "worldpop",
    }
)
