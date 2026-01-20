"""
Session Cache Manager - Per-session data caching and tracking.

This module provides:
- SessionCache: Per-session inventory tracking what data has been loaded
- session_manager: Global manager for all active sessions

The cache tracks what data each session has loaded, enabling:
- Deduplication: Don't fetch data that's already been sent to frontend
- Recovery: Know what frontend has for session restore
- Export: Know what data to include in exports

Usage:
    from mapmover.session_cache import session_manager

    # Get or create session cache
    cache = session_manager.get_or_create(session_id)

    # Check if we can serve from cache
    requested_sig = CacheSignature.from_order_items(items)
    if cache.can_serve(requested_sig):
        return cache.get_cached_result(request_key)

    # After execution, store result
    cache.store_result(request_key, result, signature)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from .cache_signature import CacheSignature, CacheInventory, DataPackage

logger = logging.getLogger(__name__)


class SessionCache:
    """
    Per-session cache tracking what data has been loaded.

    Stores:
    - inventory: What data signatures have been loaded
    - results: Cached execution results (GeoJSON, etc.)
    - metadata: Session info (created, last activity, etc.)
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

        # Cache inventory (tracks signatures of loaded data)
        self.inventory = CacheInventory(name=f"session_{session_id}")

        # Cached results (request_key -> result)
        self._results: Dict[str, Dict] = {}

        # Chat history for session recovery
        self.chat_history: List[Dict] = []

        # Map state for recovery
        self.map_state: Dict = {}

    def touch(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now()

    def is_expired(self, ttl_hours: int = 4) -> bool:
        """Check if session has expired based on TTL."""
        return datetime.now() - self.last_activity > timedelta(hours=ttl_hours)

    def can_serve(self, requested: CacheSignature) -> bool:
        """Check if inventory can serve the requested data."""
        return self.inventory.can_serve(requested)

    def compute_delta(self, requested: CacheSignature) -> CacheSignature:
        """Compute what data needs to be fetched."""
        return self.inventory.compute_delta(requested)

    def store_result(
        self,
        request_key: str,
        result: Dict,
        signature: CacheSignature = None
    ):
        """
        Store execution result in cache.

        Args:
            request_key: Unique key for this request (hash of order items)
            result: The execution result (GeoJSON, etc.)
            signature: Optional signature of the data
        """
        self._results[request_key] = result
        if signature:
            self.inventory.add_signature(request_key, signature)
        self.touch()

    def get_cached_result(self, request_key: str) -> Optional[Dict]:
        """Get cached result by request key."""
        return self._results.get(request_key)

    def has_result(self, request_key: str) -> bool:
        """Check if result is cached."""
        return request_key in self._results

    def clear(self):
        """Clear all cached data."""
        self.inventory.clear()
        self._results.clear()
        self.chat_history.clear()
        self.map_state.clear()

    def get_status(self) -> Dict:
        """Get session status for recovery prompt."""
        stats = self.inventory.stats()
        return {
            "session_id": self.session_id,
            "has_data": stats["entry_count"] > 0,
            "cache_entries": stats["entry_count"],
            "total_locations": stats["total_locations"],
            "total_metrics": stats["total_metrics"],
            "total_years": stats["total_years"],
            "year_range": stats["year_range"],
            "chat_message_count": len(self.chat_history),
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
        }

    def stats(self) -> Dict:
        """Get detailed cache statistics."""
        inv_stats = self.inventory.stats()
        return {
            **inv_stats,
            "result_count": len(self._results),
            "chat_history_count": len(self.chat_history),
            "age_seconds": (datetime.now() - self.created_at).total_seconds(),
            "idle_seconds": (datetime.now() - self.last_activity).total_seconds(),
        }


class SessionManager:
    """
    Global manager for all active session caches.

    Handles:
    - Session creation and retrieval
    - TTL-based cleanup
    - Cross-session statistics
    """

    # Default TTL (4 hours for deployed, could be configured)
    DEFAULT_TTL_HOURS = 4

    def __init__(self):
        self._sessions: Dict[str, SessionCache] = {}
        self._last_cleanup = datetime.now()
        self._cleanup_interval = timedelta(minutes=5)

    def get(self, session_id: str) -> Optional[SessionCache]:
        """Get session cache if it exists."""
        cache = self._sessions.get(session_id)
        if cache:
            cache.touch()
        return cache

    def get_or_create(self, session_id: str) -> SessionCache:
        """Get existing session cache or create new one."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionCache(session_id)
            logger.info(f"Created new session cache: {session_id}")
        else:
            self._sessions[session_id].touch()

        # Periodically cleanup expired sessions
        self._maybe_cleanup()

        return self._sessions[session_id]

    def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        return session_id in self._sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session cache."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Deleted session cache: {session_id}")
            return True
        return False

    def clear_session(self, session_id: str) -> bool:
        """Clear a session's cache but keep the session."""
        cache = self._sessions.get(session_id)
        if cache:
            cache.clear()
            logger.info(f"Cleared session cache: {session_id}")
            return True
        return False

    def _maybe_cleanup(self):
        """Cleanup expired sessions if interval has passed."""
        now = datetime.now()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        expired = [
            sid for sid, cache in self._sessions.items()
            if cache.is_expired(self.DEFAULT_TTL_HOURS)
        ]

        for sid in expired:
            del self._sessions[sid]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")

    def stats(self) -> Dict:
        """Get overall statistics."""
        total_entries = 0
        total_results = 0

        for cache in self._sessions.values():
            stats = cache.stats()
            total_entries += stats.get("entry_count", 0)
            total_results += stats.get("result_count", 0)

        return {
            "active_sessions": len(self._sessions),
            "total_cache_entries": total_entries,
            "total_cached_results": total_results,
        }

    def list_sessions(self) -> List[Dict]:
        """List all active sessions with their status."""
        return [cache.get_status() for cache in self._sessions.values()]


# Global session manager instance
session_manager = SessionManager()
