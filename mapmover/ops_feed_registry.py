"""Canonical logical Ops-feed availability registry.

The shared data-root registry is deliberately outside ``catalog.json``:
Ops feeds are current-state contracts, not Explore/Research packs.  It defines
the universe of runtime-enabled feeds once; defaults and account eligibility
are explicit flags on each record.
"""

from __future__ import annotations

import json
from pathlib import Path

from mapmover.paths import DATA_ROOT


REGISTRY_PATH = DATA_ROOT / "ops_feed_registry.json"


def load_ops_feed_records(path: Path | None = None) -> list[dict]:
    """Return valid logical feed records, failing closed for malformed rows."""
    try:
        payload = json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Cloud runtimes read data control files from the published S3 prefix;
        # they do not require every small registry file to be present in the
        # container's filesystem.
        try:
            from mapmover.data_loading import _fetch_json_from_s3
            payload = _fetch_json_from_s3("ops_feed_registry.json")
        except Exception:
            return []
    records = payload.get("feeds") if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return []
    return [
        record for record in records
        if isinstance(record, dict) and str(record.get("feed_id") or "").strip()
    ]


def ops_feed_ids(*, flag: str = "runtime_enabled") -> tuple[str, ...]:
    return tuple(
        str(record["feed_id"]).strip()
        for record in load_ops_feed_records()
        if bool(record.get(flag))
    )
