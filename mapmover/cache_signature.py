"""
Cache Signature System - Unified data identification across cache layers.

This module provides:
- CacheSignature: Identifies what data is in a cache (loc_ids, years, metrics)
- DataPackage: Container for data with its signature, supports export
- CacheInventory: Tracks what's loaded across the system

The loc_id system is the canonical identifier:
    {ISO3}[-{admin1}[-{admin2}]]

Examples:
    USA         - United States (country)
    USA-CA      - California (admin1)
    USA-CA-6037 - Los Angeles County (admin2)

Usage:
    # Create signature from data
    sig = CacheSignature.from_data(records, source_id="owid_co2")

    # Check if cache can serve a request
    if cached_sig.contains(requested_sig):
        # Serve from cache
    else:
        # Fetch delta
        delta = requested_sig.subtract(cached_sig)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union
import json


@dataclass(frozen=True)
class CacheSignature:
    """
    Immutable signature identifying what data is in a cache.

    The three axes of data identification:
    1. loc_ids: Which locations (using canonical loc_id format)
    2. years: Which years are present (as a set, not range - shows gaps)
    3. metrics: Which metrics/columns

    Optionally tracks source_id for multi-source caches.

    Using FrozenSet[int] for years instead of year_start/year_end because:
    - Shows gaps: If data has 2018, 2020, 2022 but not 2019, 2021 - signature shows this
    - Sparse data: Some sources have irregular years (1990, 2000, 2010, 2020)
    - Precision: contains() check is exact, not approximate
    """

    loc_ids: FrozenSet[str]
    years: FrozenSet[int]
    metrics: FrozenSet[str]
    source_id: Optional[str] = None

    @classmethod
    def from_data(
        cls,
        records: List[Dict],
        source_id: str = None,
        loc_id_field: str = "loc_id",
        year_field: str = "year"
    ) -> "CacheSignature":
        """
        Create signature by inspecting actual data records.

        Args:
            records: List of data dictionaries with loc_id, year, and metrics
            source_id: Optional source identifier
            loc_id_field: Field name for location ID (default: "loc_id")
            year_field: Field name for year (default: "year")

        Returns:
            CacheSignature describing the data
        """
        if not records:
            return cls(
                loc_ids=frozenset(),
                years=frozenset(),
                metrics=frozenset(),
                source_id=source_id
            )

        loc_ids = set()
        years = set()
        metrics = set()

        # Reserved fields that are not metrics
        reserved = {loc_id_field, year_field, "geometry", "_id", "properties"}

        for record in records:
            if loc_id_field in record:
                loc_ids.add(record[loc_id_field])
            if year_field in record:
                year_val = record[year_field]
                if isinstance(year_val, (int, float)) and year_val > 0:
                    years.add(int(year_val))

            # Collect metric fields
            for key in record.keys():
                if key not in reserved and not key.startswith("_"):
                    metrics.add(key)

        return cls(
            loc_ids=frozenset(loc_ids),
            years=frozenset(years),
            metrics=frozenset(metrics),
            source_id=source_id
        )

    @classmethod
    def from_order_items(cls, items: List[Dict]) -> "CacheSignature":
        """
        Create signature from order items (preprocessor output).

        Args:
            items: List of order items with source_id, metric, region, year/year_start/year_end

        Returns:
            CacheSignature describing what the order requests
        """
        loc_ids = set()
        years = set()
        metrics = set()
        source_ids = set()

        for item in items:
            # Collect metrics
            if "metric" in item:
                metrics.add(item["metric"])

            # Collect source_ids
            if "source_id" in item:
                source_ids.add(item["source_id"])

            # Collect loc_ids from region (may be expanded list or single value)
            region = item.get("region")
            if region:
                if isinstance(region, list):
                    loc_ids.update(region)
                else:
                    loc_ids.add(region)

            # Collect years - can be single year or range
            if "year" in item and item["year"]:
                years.add(int(item["year"]))
            if "year_start" in item and "year_end" in item:
                start = item.get("year_start")
                end = item.get("year_end")
                if start and end:
                    # Expand range into individual years
                    years.update(range(int(start), int(end) + 1))
            elif "year_start" in item and item["year_start"]:
                years.add(int(item["year_start"]))
            elif "year_end" in item and item["year_end"]:
                years.add(int(item["year_end"]))

        return cls(
            loc_ids=frozenset(loc_ids),
            years=frozenset(years),
            metrics=frozenset(metrics),
            source_id=list(source_ids)[0] if len(source_ids) == 1 else None
        )

    def contains(self, other: "CacheSignature") -> bool:
        """
        Check if this signature fully contains another.

        Returns True if this cache can serve all data requested by other.
        All checks are set subset operations - O(n) where n = smaller set.
        """
        # Check loc_ids
        if not other.loc_ids.issubset(self.loc_ids):
            return False

        # Check years - exact check, shows gaps
        if not other.years.issubset(self.years):
            return False

        # Check metrics
        if not other.metrics.issubset(self.metrics):
            return False

        return True

    def subtract(self, other: "CacheSignature") -> "CacheSignature":
        """
        Calculate what's in self but NOT in other (the delta to fetch).

        Returns a signature representing the missing data.
        """
        missing_locs = self.loc_ids - other.loc_ids
        missing_years = self.years - other.years
        missing_metrics = self.metrics - other.metrics

        return CacheSignature(
            loc_ids=missing_locs if missing_locs else self.loc_ids,
            years=missing_years if missing_years else self.years,
            metrics=missing_metrics if missing_metrics else self.metrics,
            source_id=self.source_id
        )

    def merge(self, other: "CacheSignature") -> "CacheSignature":
        """
        Merge two signatures (union of data).
        """
        return CacheSignature(
            loc_ids=self.loc_ids | other.loc_ids,
            years=self.years | other.years,
            metrics=self.metrics | other.metrics,
            source_id=self.source_id if self.source_id == other.source_id else None
        )

    def is_empty(self) -> bool:
        """Check if signature represents no data."""
        return len(self.loc_ids) == 0 and len(self.years) == 0 and len(self.metrics) == 0

    def to_dict(self) -> Dict:
        """Serialize to dictionary for transport."""
        return {
            "loc_ids": sorted(self.loc_ids),
            "years": sorted(self.years),
            "metrics": sorted(self.metrics),
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CacheSignature":
        """Deserialize from dictionary."""
        return cls(
            loc_ids=frozenset(data.get("loc_ids", [])),
            years=frozenset(data.get("years", [])),
            metrics=frozenset(data.get("metrics", [])),
            source_id=data.get("source_id"),
        )

    def summary(self) -> str:
        """Human-readable summary."""
        loc_count = len(self.loc_ids)
        metric_count = len(self.metrics)
        year_count = len(self.years)
        if year_count == 0:
            year_str = "no years"
        elif year_count <= 5:
            year_str = f"years {sorted(self.years)}"
        else:
            years_sorted = sorted(self.years)
            year_str = f"{year_count} years ({years_sorted[0]}-{years_sorted[-1]})"
        return f"{loc_count} locations, {metric_count} metrics, {year_str}"

    def year_range(self) -> Tuple[int, int]:
        """Get min/max years as tuple (for compatibility)."""
        if not self.years:
            return (0, 0)
        years_sorted = sorted(self.years)
        return (years_sorted[0], years_sorted[-1])


@dataclass
class DataPackage:
    """
    Container for data with its signature.

    Enables:
    - Tracking what data is loaded
    - Export to CSV/Parquet
    - Verification against other caches
    """

    signature: CacheSignature
    records: List[Dict]
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def from_records(
        cls,
        records: List[Dict],
        source_id: str = None,
        metadata: Dict = None
    ) -> "DataPackage":
        """Create package from records, auto-computing signature."""
        sig = CacheSignature.from_data(records, source_id=source_id)
        return cls(
            signature=sig,
            records=records,
            metadata=metadata or {}
        )

    def filter(
        self,
        loc_ids: Set[str] = None,
        years: Set[int] = None,
        year_start: int = None,
        year_end: int = None,
        metrics: Set[str] = None
    ) -> "DataPackage":
        """
        Filter package to subset of data.

        Args:
            loc_ids: Filter to these location IDs
            years: Filter to these specific years (set)
            year_start: Filter to years >= this value
            year_end: Filter to years <= this value
            metrics: Filter columns (not yet implemented)

        Returns new DataPackage with filtered records and updated signature.
        """
        filtered = self.records

        if loc_ids:
            filtered = [r for r in filtered if r.get("loc_id") in loc_ids]

        if years:
            filtered = [r for r in filtered if r.get("year") in years]

        if year_start is not None:
            filtered = [r for r in filtered if r.get("year", 0) >= year_start]

        if year_end is not None:
            filtered = [r for r in filtered if r.get("year", 9999) <= year_end]

        # Note: metric filtering would need column selection logic
        # For now, just filter rows

        return DataPackage.from_records(
            filtered,
            source_id=self.signature.source_id,
            metadata=self.metadata
        )

    def to_csv_rows(self) -> List[Dict]:
        """
        Prepare records for CSV export.

        Returns list of flat dictionaries suitable for csv.DictWriter.
        """
        if not self.records:
            return []

        # Flatten any nested structures
        rows = []
        for record in self.records:
            row = {}
            for key, value in record.items():
                if isinstance(value, dict):
                    # Flatten nested dict with prefix
                    for k, v in value.items():
                        row[f"{key}_{k}"] = v
                elif isinstance(value, (list, tuple)):
                    row[key] = json.dumps(value)
                else:
                    row[key] = value
            rows.append(row)

        return rows

    def get_columns(self) -> List[str]:
        """Get all column names from records."""
        if not self.records:
            return []

        columns = set()
        for record in self.records:
            columns.update(record.keys())

        # Order: loc_id, year first, then sorted metrics
        priority = ["loc_id", "year"]
        result = [c for c in priority if c in columns]
        result.extend(sorted(c for c in columns if c not in priority))
        return result

    def verify_against(self, other_sig: CacheSignature) -> Dict:
        """
        Verify this package against another signature.

        Returns dict with:
        - matches: bool
        - missing_locs: set of loc_ids in other but not here
        - extra_locs: set of loc_ids here but not in other
        - year_coverage: dict with comparison
        - metric_coverage: dict with comparison
        """
        my_sig = self.signature

        return {
            "matches": my_sig.contains(other_sig) and other_sig.contains(my_sig),
            "missing_locs": list(other_sig.loc_ids - my_sig.loc_ids),
            "extra_locs": list(my_sig.loc_ids - other_sig.loc_ids),
            "year_coverage": {
                "self_years": sorted(my_sig.years),
                "other_years": sorted(other_sig.years),
                "self_covers_other": other_sig.years.issubset(my_sig.years),
                "missing_years": sorted(other_sig.years - my_sig.years),
                "extra_years": sorted(my_sig.years - other_sig.years),
            },
            "metric_coverage": {
                "self": list(my_sig.metrics),
                "other": list(other_sig.metrics),
                "missing": list(other_sig.metrics - my_sig.metrics),
                "extra": list(my_sig.metrics - other_sig.metrics),
            }
        }


class CacheInventory:
    """
    Tracks what data is loaded in a cache layer.

    Each layer (backend, order_taker, frontend) can have its own inventory.
    Supports checking coverage and computing deltas.
    """

    def __init__(self, name: str = "unnamed"):
        self.name = name
        self._packages: Dict[str, DataPackage] = {}  # key -> package
        self._signatures: Dict[str, CacheSignature] = {}  # key -> signature

    def add(self, key: str, package: DataPackage):
        """Add or update a data package."""
        self._packages[key] = package
        self._signatures[key] = package.signature

    def add_signature(self, key: str, signature: CacheSignature):
        """Add just a signature (when we don't have the full data)."""
        self._signatures[key] = signature

    def get(self, key: str) -> Optional[DataPackage]:
        """Get package by key."""
        return self._packages.get(key)

    def get_signature(self, key: str) -> Optional[CacheSignature]:
        """Get signature by key."""
        return self._signatures.get(key)

    def has(self, key: str) -> bool:
        """Check if key exists."""
        return key in self._signatures

    def remove(self, key: str):
        """Remove a key from inventory."""
        self._packages.pop(key, None)
        self._signatures.pop(key, None)

    def clear(self):
        """Clear all entries."""
        self._packages.clear()
        self._signatures.clear()

    def combined_signature(self) -> CacheSignature:
        """Get merged signature of all cached data."""
        if not self._signatures:
            return CacheSignature(
                loc_ids=frozenset(),
                years=frozenset(),
                metrics=frozenset()
            )

        result = None
        for sig in self._signatures.values():
            if result is None:
                result = sig
            else:
                result = result.merge(sig)

        return result

    def can_serve(self, requested: CacheSignature) -> bool:
        """Check if inventory can fully serve a request."""
        combined = self.combined_signature()
        return combined.contains(requested)

    def compute_delta(self, requested: CacheSignature) -> CacheSignature:
        """Compute what needs to be fetched to serve request."""
        combined = self.combined_signature()
        return requested.subtract(combined)

    def stats(self) -> Dict:
        """Get inventory statistics."""
        combined = self.combined_signature()
        return {
            "name": self.name,
            "entry_count": len(self._signatures),
            "total_locations": len(combined.loc_ids),
            "total_metrics": len(combined.metrics),
            "total_years": len(combined.years),
            "year_range": combined.year_range(),
            "has_data": len(self._packages),
            "signature_only": len(self._signatures) - len(self._packages),
        }

    def to_dict(self) -> Dict:
        """Serialize inventory (signatures only, not data)."""
        return {
            "name": self.name,
            "entries": {
                key: sig.to_dict()
                for key, sig in self._signatures.items()
            }
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CacheInventory":
        """Deserialize inventory."""
        inv = cls(name=data.get("name", "unnamed"))
        for key, sig_data in data.get("entries", {}).items():
            inv.add_signature(key, CacheSignature.from_dict(sig_data))
        return inv
