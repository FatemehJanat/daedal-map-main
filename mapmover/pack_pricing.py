from __future__ import annotations

# Single source of truth for pack pricing classification.
# Add new packs here when they are published. Keep in sync with
# PACK_SERVER_PROFILES in routes/mcp.py (which has the full profile).
FREE_PACK_IDS: frozenset[str] = frozenset(
    {
        "currency",
        "hurricanes",
        "un_sdg",
        "volcanoes",
        "world_factbook",
    }
)

PAID_PACK_IDS: frozenset[str] = frozenset(
    {
        "earthquakes",
        "tsunamis",
    }
)
