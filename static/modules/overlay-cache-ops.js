import {
  activeFilters,
  calculateCacheSize,
  dataCache,
  loadedFilters,
  loadedRanges,
  loadedYears,
  metricCache,
  yearRangeCache
} from './overlay-cache.js';
import { GeometryModel } from './models/model-geometry.js';
import { mergeTemporalMetricPayload } from './temporal-payload.js';

function getGeometryFeatureKey(feature) {
  const props = feature?.properties || {};
  return props.feature_id || props.building_id || props.BLDGIDENT || props.loc_id || feature?.id || null;
}

export function getCachedData(overlayId) {
  return dataCache[overlayId] || null;
}

export function clearAllOverlayCaches() {
  for (const key in dataCache) {
    delete dataCache[key];
  }
  for (const key in loadedYears) {
    delete loadedYears[key];
  }
  for (const key in loadedRanges) {
    delete loadedRanges[key];
  }
  for (const key in yearRangeCache) {
    delete yearRangeCache[key];
  }
  for (const key in loadedFilters) {
    delete loadedFilters[key];
  }
}

export function clearOverlayData(overlayId) {
  delete dataCache[overlayId];
  delete loadedYears[overlayId];
  delete loadedRanges[overlayId];
  delete yearRangeCache[overlayId];
}

export function getLoadedYearsForOverlay(overlayId) {
  return loadedYears[overlayId] ? Array.from(loadedYears[overlayId]).sort((a, b) => a - b) : [];
}

export function getLoadedFiltersForOverlay(overlayId) {
  return loadedFilters[overlayId] || {};
}

export function getActiveFiltersForOverlay(overlayId, overlayEndpoints) {
  const config = overlayEndpoints[overlayId];
  if (!config) return {};

  const filters = {};
  if (config.params.min_magnitude) {
    filters.minMagnitude = parseFloat(config.params.min_magnitude);
  }
  if (config.params.min_category) {
    filters.minCategory = config.params.min_category;
  }
  if (config.params.min_scale) {
    filters.minScale = config.params.min_scale;
  }
  if (config.params.min_area_km2) {
    filters.minAreaKm2 = parseFloat(config.params.min_area_km2);
  }
  if (config.params.min_severity) {
    filters.minSeverity = parseFloat(config.params.min_severity);
  }

  return { ...filters, ...(activeFilters[overlayId] || {}) };
}

export function updateOverlayFilters(overlayId, newFilters, overlayEndpoints) {
  if (!overlayEndpoints[overlayId]) {
    console.warn(`Unknown overlay: ${overlayId}`);
    return false;
  }

  activeFilters[overlayId] = {
    ...(activeFilters[overlayId] || {}),
    ...newFilters
  };

  console.log(`OverlayController: Updated filters for ${overlayId}:`, activeFilters[overlayId]);
  return true;
}

export function clearOverlayFilters(overlayId) {
  delete activeFilters[overlayId];
  console.log(`OverlayController: Cleared filters for ${overlayId}`);
}

export function getCacheStats(overlayEndpoints) {
  const sizeInfo = calculateCacheSize();
  const stats = {
    overlays: {},
    totals: {
      features: 0,
      bytes: 0,
      timesLoaded: 0,
      overlaysActive: 0
    }
  };

  for (const overlayId of Object.keys(overlayEndpoints)) {
    const features = dataCache[overlayId]?.features || [];
    const years = loadedYears[overlayId] ? Array.from(loadedYears[overlayId]).sort((a, b) => a - b) : [];
    const ranges = (loadedRanges[overlayId] || []).filter(r => !r.loading);
    const overlaySize = sizeInfo.perOverlay[overlayId] || { features: 0, bytes: 0 };

    if (features.length > 0 || years.length > 0) {
      let rangeStart = null;
      let rangeEnd = null;
      if (ranges.length > 0) {
        rangeStart = Math.min(...ranges.map(r => r.start));
        rangeEnd = Math.max(...ranges.map(r => r.end));
      }

      stats.overlays[overlayId] = {
        features: features.length,
        sizeMB: (overlaySize.bytes / (1024 * 1024)).toFixed(2),
        timesLoaded: years.length,
        years,
        yearRange: years.length > 0 ? `${years[0]}-${years[years.length - 1]}` : 'none',
        ranges,
        rangeStart,
        rangeEnd,
        dataType: 'events'
      };

      stats.totals.features += features.length;
      stats.totals.bytes += overlaySize.bytes;
      stats.totals.timesLoaded += years.length;
      stats.totals.overlaysActive++;
    }
  }

  for (const sourceId of Object.keys(metricCache)) {
    const cached = metricCache[sourceId];
    const features = cached?.geojson?.features || [];
    const overlaySize = sizeInfo.perOverlay[sourceId] || { features: 0, bytes: 0 };
    const timeRange = cached?.time_range || cached?.year_range;
    const isGeometry = cached?.dataType === 'geometry';

    if (features.length > 0) {
      const times = timeRange?.available || timeRange?.available_years || [];
      stats.overlays[sourceId] = {
        features: features.length,
        sizeMB: (overlaySize.bytes / (1024 * 1024)).toFixed(2),
        timesLoaded: times.length,
        years: times,
        yearRange: isGeometry ? 'n/a' : (timeRange ? `${timeRange.min}-${timeRange.max}` : 'none'),
        dataType: cached?.dataType || 'metrics'
      };

      stats.totals.features += features.length;
      stats.totals.bytes += overlaySize.bytes;
      stats.totals.timesLoaded += times.length;
      stats.totals.overlaysActive++;
    }
  }

  stats.totals.sizeMB = (stats.totals.bytes / (1024 * 1024)).toFixed(2);
  console.table(stats.overlays);
  console.log(`Total: ${stats.totals.features} features across ${stats.totals.timesLoaded} time-loads (${stats.totals.sizeMB} MB)`);
  return stats;
}

export function ingestMetricData(sourceId, geojson, timeData = null, timeRange = null) {
  if (!geojson?.features) {
    console.warn(`OverlayController: Cannot ingest metrics - invalid data for source: ${sourceId}`);
    return;
  }

  const existing = metricCache[sourceId];
  if (existing) {
    const existingFeatures = existing.geojson?.features || [];
    const existingLocIds = new Set(
      existingFeatures.map((feature) => feature?.properties?.loc_id || feature?.id).filter(Boolean)
    );
    const newFeatures = (geojson.features || []).filter((feature) => {
      const locId = feature?.properties?.loc_id || feature?.id;
      return !locId || !existingLocIds.has(locId);
    });

    const mergedTemporal = mergeTemporalMetricPayload(
      {
        time_data: existing.time_data || existing.year_data || {},
        time_range: existing.time_range || existing.year_range || null
      },
      {
        time_data: timeData || {},
        time_range: timeRange || null
      }
    );

    metricCache[sourceId] = {
      ...existing,
      geojson: {
        type: 'FeatureCollection',
        features: existingFeatures.concat(newFeatures)
      },
      time_data: mergedTemporal?.timeData || {},
      time_range: mergedTemporal?.timeRange || null,
      // TEMPORARY MIRROR: remove these after all cache consumers switch to time_*.
      year_data: mergedTemporal?.timeData || {},
      year_range: mergedTemporal?.timeRange
        ? {
            min: mergedTemporal.timeRange.min,
            max: mergedTemporal.timeRange.max,
            available_years: mergedTemporal.timeRange.available
          }
        : null,
      loadedAt: Date.now()
    };
  } else {
    metricCache[sourceId] = {
      geojson,
      time_data: timeData || {},
      time_range: timeRange || null,
      // TEMPORARY MIRROR: remove these after all cache consumers switch to time_*.
      year_data: timeData || {},
      year_range: timeRange
        ? {
            min: timeRange.min,
            max: timeRange.max,
            available_years: timeRange.available || timeRange.available_years || []
          }
        : null,
      loadedAt: Date.now()
    };
  }

  console.log(`OverlayController: Ingested ${geojson.features.length} ${sourceId} features into metrics cache`);
  const cacheSize = calculateCacheSize();
  window.dispatchEvent(new CustomEvent('overlayCacheUpdated', { detail: cacheSize }));
}

export function getCachedMetricData(sourceId) {
  return metricCache[sourceId] || null;
}

export function clearMetricCacheEntry(sourceId) {
  if (metricCache[sourceId]) {
    delete metricCache[sourceId];
    const cacheSize = calculateCacheSize();
    window.dispatchEvent(new CustomEvent('overlayCacheUpdated', { detail: cacheSize }));
    console.log(`OverlayController: Cleared metrics cache for ${sourceId}`);
  }
}

export function renderGeometryData(sourceId, geojson, geometryType = 'zcta', options = {}) {
  if (!geojson?.features) {
    console.warn(`OverlayController: Cannot render geometry - invalid data for source: ${sourceId}`);
    return 0;
  }

  const existing = metricCache[sourceId];
  if (existing?.geojson?.features) {
    const existingKeys = new Set(existing.geojson.features.map(getGeometryFeatureKey).filter(Boolean));
    const newFeatures = geojson.features.filter((feature) => {
      const key = getGeometryFeatureKey(feature);
      return !key || !existingKeys.has(key);
    });
    existing.geojson.features = existing.geojson.features.concat(newFeatures);
    existing.loadedAt = Date.now();
    existing.geometryType = geometryType;
    console.log(`OverlayController: Accumulated ${newFeatures.length} new ${geometryType} features (total: ${existing.geojson.features.length})`);
  } else {
    metricCache[sourceId] = {
      geojson,
      time_data: {},
      time_range: null,
      year_data: {},
      year_range: null,
      dataType: 'geometry',
      geometryType,
      loadedAt: Date.now()
    };
  }

  window.dispatchEvent(new CustomEvent('overlayCacheUpdated'));
  console.log(`OverlayController: Stored ${metricCache[sourceId].geojson.features.length} ${geometryType} features in cache`);
  return metricCache[sourceId].geojson.features.length;
}

export function refreshGeometryFromCache() {
  let totalFeatures = 0;
  for (const [sourceId, cached] of Object.entries(metricCache)) {
    if (cached?.dataType !== 'geometry' || !cached?.geojson?.features?.length) continue;
    const geometryType = cached.geometryType || 'geometry';
    GeometryModel.render(cached.geojson, geometryType, { showLabels: false });
    totalFeatures += cached.geojson.features.length;
    console.log(`OverlayController: Rendered ${cached.geojson.features.length} ${geometryType} features from cache (${sourceId})`);
  }

  if (totalFeatures > 0) {
    console.log(`OverlayController: Refreshed ${totalFeatures} total geometry features from cache`);
  }
}

export function removeGeometryData(sourceId, criteria) {
  const cached = metricCache[sourceId];
  if (!cached?.geojson?.features) {
    console.warn(`OverlayController: No cached geometry for source: ${sourceId}`);
    return { removed: 0, remaining: 0 };
  }

  const originalCount = cached.geojson.features.length;
  const { loc_ids, regions } = criteria;

  if (loc_ids && loc_ids.length > 0) {
    const locIdSet = new Set(loc_ids);
    cached.geojson.features = cached.geojson.features.filter(f => !locIdSet.has(f.properties?.loc_id));
    console.log(`OverlayController: Removed ${loc_ids.length} features by loc_id from ${sourceId}`);
  } else if (regions && regions.length > 0) {
    const prefixes = regions.map(r => `${r}-`);
    const regionSet = new Set(regions);
    cached.geojson.features = cached.geojson.features.filter(f => {
      const parentId = f.properties?.parent_id || '';
      const matchesPrefix = prefixes.some(p => parentId.startsWith(p));
      const matchesExact = regionSet.has(parentId);
      return !matchesPrefix && !matchesExact;
    });
    console.log(`OverlayController: Removed features matching regions: ${regions.join(', ')}`);
  } else {
    console.warn('OverlayController: removeGeometryData called without loc_ids or regions');
    return { removed: 0, remaining: originalCount };
  }

  const removedCount = originalCount - cached.geojson.features.length;
  cached.loadedAt = Date.now();

  if (cached.geojson.features.length === 0) {
    delete metricCache[sourceId];
  }

  window.dispatchEvent(new CustomEvent('overlayCacheUpdated'));
  console.log(`OverlayController: Removal complete - removed ${removedCount}, remaining ${cached.geojson?.features?.length || 0}`);
  return { removed: removedCount, remaining: cached.geojson?.features?.length || 0 };
}

export function removeEventData(sourceId, criteria) {
  const cached = metricCache[sourceId];
  if (!cached?.geojson?.features) {
    console.warn(`OverlayController: No cached events for source: ${sourceId}`);
    return { removed: 0, remaining: 0 };
  }

  const originalCount = cached.geojson.features.length;
  const { event_ids, regions } = criteria;

  if (event_ids && event_ids.length > 0) {
    const eventIdSet = new Set(event_ids);
    cached.geojson.features = cached.geojson.features.filter(f => {
      const eventId = f.properties?.event_id || f.id;
      return !eventIdSet.has(eventId);
    });
    console.log(`OverlayController: Removed ${event_ids.length} events by event_id from ${sourceId}`);
  } else if (regions && regions.length > 0) {
    const prefixes = regions.map(r => `${r}-`);
    const regionSet = new Set(regions);
    cached.geojson.features = cached.geojson.features.filter(f => {
      const locId = f.properties?.loc_id || '';
      const matchesPrefix = prefixes.some(p => locId.startsWith(p));
      const matchesExact = regionSet.has(locId);
      return !matchesPrefix && !matchesExact;
    });
    console.log(`OverlayController: Removed events matching regions: ${regions.join(', ')}`);
  } else {
    console.warn('OverlayController: removeEventData called without event_ids or regions');
    return { removed: 0, remaining: originalCount };
  }

  const removedCount = originalCount - cached.geojson.features.length;
  cached.loadedAt = Date.now();

  if (cached.geojson.features.length === 0) {
    delete metricCache[sourceId];
  }

  window.dispatchEvent(new CustomEvent('overlayCacheUpdated'));
  console.log(`OverlayController: Event removal complete - removed ${removedCount}, remaining ${cached.geojson?.features?.length || 0}`);
  return { removed: removedCount, remaining: cached.geojson?.features?.length || 0 };
}

export function removeMetricData(sourceId, criteria) {
  const cached = metricCache[sourceId];
  if (!cached) {
    console.warn(`OverlayController: No cached metrics for source: ${sourceId}`);
    return { removed: 0, remaining: 0 };
  }

  const { loc_ids, years, metric } = criteria;
  let removedCount = 0;

  const timeData = cached.time_data || cached.year_data || null;
  if (timeData && metric) {
    const locIdSet = loc_ids?.length > 0 ? new Set(loc_ids) : null;
    const yearSet = years?.length > 0 ? new Set(years.map(String)) : null;

    for (const [yearStr, locData] of Object.entries(timeData)) {
      if (yearSet && !yearSet.has(yearStr)) continue;

      for (const [locId, metrics] of Object.entries(locData)) {
        if (locIdSet && !locIdSet.has(locId)) continue;
        if (metrics[metric] !== undefined) {
          delete metrics[metric];
          removedCount++;
        }
      }
    }
    console.log(`OverlayController: Removed ${removedCount} metric values for '${metric}' from ${sourceId}`);
  }

  if (cached.geojson?.features && metric) {
    const locIdSet = loc_ids?.length > 0 ? new Set(loc_ids) : null;
    for (const feature of cached.geojson.features) {
      if (locIdSet && !locIdSet.has(feature.properties?.loc_id)) continue;
      if (feature.properties?.[metric] !== undefined) {
        delete feature.properties[metric];
      }
    }
  }

  cached.loadedAt = Date.now();
  const hasTimeData = timeData && Object.keys(timeData).length > 0;
  const hasFeatures = cached.geojson?.features?.length > 0;

  if (!hasTimeData && !hasFeatures) {
    delete metricCache[sourceId];
  }

  window.dispatchEvent(new CustomEvent('overlayCacheUpdated'));
  console.log(`OverlayController: Metric removal complete - removed ${removedCount} cells`);
  return { removed: removedCount, remaining: hasTimeData ? Object.keys(timeData).length : 0 };
}
