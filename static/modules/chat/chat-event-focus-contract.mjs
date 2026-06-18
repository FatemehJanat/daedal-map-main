export function parseEventTrackCoords(value) {
  if (!value) return [];
  let parsed = value;
  if (typeof parsed === 'string') {
    try {
      parsed = JSON.parse(parsed);
    } catch (_error) {
      return [];
    }
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter((coords) => Array.isArray(coords) && coords.length >= 2);
}

export function extendBoundsWithCoordinateList(bounds, coords) {
  if (!Array.isArray(coords) || !coords.length || !bounds?.extend) return;
  if (
    coords.length >= 2
    && Number.isFinite(Number(coords[0]))
    && Number.isFinite(Number(coords[1]))
  ) {
    bounds.extend([Number(coords[0]), Number(coords[1])]);
    return;
  }
  coords.forEach((entry) => extendBoundsWithCoordinateList(bounds, entry));
}

export function extendBoundsWithApproximateRadius(bounds, lon, lat, radiusKm) {
  if (!bounds?.extend) return;
  if (!Number.isFinite(lon) || !Number.isFinite(lat) || !Number.isFinite(radiusKm) || radiusKm <= 0) {
    return;
  }
  const latDelta = radiusKm / 111.32;
  const lonDivisor = Math.max(Math.cos((lat * Math.PI) / 180), 0.1);
  const lonDelta = radiusKm / (111.32 * lonDivisor);
  bounds.extend([lon - lonDelta, lat - latDelta]);
  bounds.extend([lon + lonDelta, lat + latDelta]);
}

export function getFocusedEventRadiusKm(feature = null) {
  const props = feature?.properties || {};
  const candidates = [
    props.initial_view_radius_km,
    props.damage_radius_km,
    props.felt_radius_km,
    props.impact_radius_km,
    props.radius_km,
    props.search_radius_km,
    props.extent_radius_km,
    props.max_radius_km
  ]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);

  if (candidates.length) {
    return Math.max(...candidates);
  }

  const eventType = String(props.event_type || '').trim().toLowerCase();
  const fallbackByType = {
    earthquake: 180,
    tsunami: 260,
    hurricane: 420,
    tornado: 90,
    wildfire: 120,
    flood: 140,
    volcano: 160,
    landslide: 60
  };
  return fallbackByType[eventType] || 120;
}

export function buildFocusedEventBounds(feature = null, deps = {}) {
  const createBounds = deps.createBounds || null;
  if (typeof createBounds !== 'function' || !feature) return null;

  const bounds = createBounds();
  const geometry = feature?.geometry || null;
  const props = feature?.properties || {};

  if (geometry?.coordinates) {
    extendBoundsWithCoordinateList(bounds, geometry.coordinates);
  }

  const bboxValues = [
    Number(props.bbox_min_lon),
    Number(props.bbox_min_lat),
    Number(props.bbox_max_lon),
    Number(props.bbox_max_lat)
  ];
  if (bboxValues.every((value) => Number.isFinite(value))) {
    bounds.extend([bboxValues[0], bboxValues[1]]);
    bounds.extend([bboxValues[2], bboxValues[3]]);
  }

  parseEventTrackCoords(props.track_coords).forEach((coords) => {
    bounds.extend([Number(coords[0]), Number(coords[1])]);
  });

  const centerLon = Number(
    props.centroid_lon
    ?? props.lon
    ?? (Array.isArray(geometry?.coordinates) ? geometry.coordinates[0] : NaN)
  );
  const centerLat = Number(
    props.centroid_lat
    ?? props.lat
    ?? (Array.isArray(geometry?.coordinates) ? geometry.coordinates[1] : NaN)
  );

  if (Number.isFinite(centerLon) && Number.isFinite(centerLat)) {
    extendBoundsWithApproximateRadius(bounds, centerLon, centerLat, getFocusedEventRadiusKm(feature));
  }

  if (typeof bounds.isEmpty === 'function' && bounds.isEmpty()) {
    return null;
  }
  return bounds;
}

export function getFocusedEventMaxZoom(bounds) {
  if (!bounds || typeof bounds.toArray !== 'function') {
    return 7;
  }
  const [[west, south], [east, north]] = bounds.toArray();
  const lonSpan = Math.abs(Number(east) - Number(west));
  const latSpan = Math.abs(Number(north) - Number(south));
  const maxSpan = Math.max(lonSpan, latSpan);
  if (!Number.isFinite(maxSpan)) return 7;
  if (maxSpan <= 0.2) return 6;
  if (maxSpan <= 1) return 6.5;
  if (maxSpan <= 5) return 7;
  if (maxSpan <= 20) return 7.5;
  return 8.5;
}

export function focusSingleEventContract(response, options = {}, deps = {}) {
  const MapAdapter = deps.MapAdapter || null;
  const isExactEventOrder = deps.isExactEventOrder || null;
  const createBounds = deps.createBounds || null;
  if (!MapAdapter) return false;

  const features = Array.isArray(response?.geojson?.features) ? response.geojson.features : [];
  if (features.length !== 1) return false;
  if (!options.allowSingleFeature) {
    if (typeof isExactEventOrder !== 'function' || !isExactEventOrder(options.order)) {
      return false;
    }
  }

  const feature = features[0];
  const bounds = buildFocusedEventBounds(feature, { createBounds });
  if (bounds && MapAdapter?.map?.fitBounds) {
    const basePadding = { top: 80, right: 80, bottom: 80, left: 80 };
    const padding = typeof MapAdapter.getFitBoundsPadding === 'function'
      ? MapAdapter.getFitBoundsPadding(basePadding)
      : basePadding;
    MapAdapter.map.fitBounds(bounds, {
      padding,
      duration: 1200,
      maxZoom: getFocusedEventMaxZoom(bounds)
    });
    return true;
  }

  const geometry = feature?.geometry || null;
  if (geometry?.type === 'Point') {
    const coords = Array.isArray(geometry.coordinates) ? geometry.coordinates : null;
    if (!coords || coords.length < 2) return false;
    const lon = Number(coords[0]);
    const lat = Number(coords[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return false;
    MapAdapter.flyTo([lon, lat], 6.5);
    return true;
  }

  if (geometry) {
    MapAdapter.fitToBounds(response.geojson, { maxZoom: 7.5 });
    return true;
  }

  return false;
}
