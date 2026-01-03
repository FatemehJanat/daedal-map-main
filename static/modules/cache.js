/**
 * Caching modules for geometry features and location info.
 * Manages in-memory caches with expiry and size limits.
 */

import { CONFIG } from './config.js';

// ============================================================================
// GEOMETRY CACHE - In-memory cache for viewport-loaded features
// ============================================================================

export const GeometryCache = {
  features: new Map(),  // loc_id -> {feature, lastSeen, level}
  maxFeatures: CONFIG.viewport.maxFeatures,
  expiryMs: CONFIG.viewport.cacheExpiryMs,

  /**
   * Add features to cache
   */
  add(features) {
    const now = Date.now();
    for (const f of features) {
      const locId = f.properties?.loc_id;
      if (!locId) continue;

      this.features.set(locId, {
        feature: f,
        lastSeen: now,
        level: f.properties?.admin_level || 0
      });
    }
    this.cleanup();
  },

  /**
   * Remove expired and excess features
   */
  cleanup() {
    const now = Date.now();

    // Remove expired
    for (const [id, entry] of this.features) {
      if (now - entry.lastSeen > this.expiryMs) {
        this.features.delete(id);
      }
    }

    // Cap at max features (remove oldest)
    if (this.features.size > this.maxFeatures) {
      const sorted = [...this.features.entries()]
        .sort((a, b) => a[1].lastSeen - b[1].lastSeen);
      const toRemove = sorted.slice(0, this.features.size - this.maxFeatures);
      for (const [id] of toRemove) {
        this.features.delete(id);
      }
    }
  },

  /**
   * Get cached features for a given admin level
   */
  getForLevel(level) {
    const result = [];
    const now = Date.now();

    for (const [id, entry] of this.features) {
      if (entry.level === level) {
        result.push(entry.feature);
        entry.lastSeen = now;  // Touch on access
      }
    }
    return result;
  },

  /**
   * Clear all cached features
   */
  clear() {
    this.features.clear();
  }
};

// ============================================================================
// LOCATION INFO CACHE - API response cache for location details
// ============================================================================

export const LocationInfoCache = {
  cache: new Map(),
  maxSize: 500,
  expiryMs: 300000,  // 5 minutes

  /**
   * Get cached location info or null if not cached/expired
   */
  get(locId) {
    const entry = this.cache.get(locId);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > this.expiryMs) {
      this.cache.delete(locId);
      return null;
    }
    return entry.data;
  },

  /**
   * Store location info in cache
   */
  set(locId, data) {
    this.cache.set(locId, {
      data: data,
      timestamp: Date.now()
    });
    // Cleanup if over max size
    if (this.cache.size > this.maxSize) {
      const oldest = this.cache.keys().next().value;
      this.cache.delete(oldest);
    }
  },

  /**
   * Fetch location info from API
   */
  async fetch(locId) {
    // Check cache first
    const cached = this.get(locId);
    if (cached) return cached;

    try {
      const response = await fetch(`/geometry/${locId}/info`);
      if (!response.ok) return null;
      const data = await response.json();
      this.set(locId, data);
      return data;
    } catch (error) {
      console.error('Error fetching location info:', error);
      return null;
    }
  }
};
