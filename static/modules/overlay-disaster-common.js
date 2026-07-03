export function addGenericExitButton(id, text, color, onExit) {
  document.getElementById(id)?.remove();
  const btn = document.createElement('button');
  btn.id = id;
  btn.textContent = text;
  btn.style.cssText = `
    position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
    padding: 10px 20px; background: ${color}; color: white; border: none;
    border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500;
    z-index: 1000; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  `;
  btn.addEventListener('click', onExit);
  document.body.appendChild(btn);
}

export const MAX_LINKED_ANIMATION_EVENTS = 500;
export const MAX_EARTHQUAKE_SEQUENCE_EVENTS = MAX_LINKED_ANIMATION_EVENTS;
export const DEFAULT_EARTHQUAKE_SEQUENCE_PREVIEW_EVENTS = 50;

function getLinkedFeatureProps(feature) {
  return feature?.properties || {};
}

function getLinkedFeatureId(feature) {
  const props = getLinkedFeatureProps(feature);
  return String(props?.event_id || props?.loc_id || '').trim();
}

function getLinkedFeatureType(feature) {
  return String(getLinkedFeatureProps(feature)?.event_type || '').trim().toLowerCase();
}

function getEarthquakeFeatureMagnitude(feature) {
  const magnitude = Number(getLinkedFeatureProps(feature)?.magnitude);
  return Number.isFinite(magnitude) ? magnitude : Number.NEGATIVE_INFINITY;
}

function getLinkedFeatureTimestamp(feature, timeField = '') {
  const props = getLinkedFeatureProps(feature);
  const timestampText = (
    (timeField && props?.[timeField])
    || props?.chain_timestamp
    || props?.timestamp
    || props?.time
    || null
  );
  const timestamp = timestampText ? new Date(timestampText).getTime() : Number.POSITIVE_INFINITY;
  return Number.isFinite(timestamp) ? timestamp : Number.POSITIVE_INFINITY;
}

function getTornadoScaleValue(value) {
  if (value == null) return Number.NEGATIVE_INFINITY;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const parsed = parseInt(String(value).replace(/[^0-9]/g, ''), 10);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function getLinkedFeatureIntensityScore(feature) {
  const props = getLinkedFeatureProps(feature);
  const eventType = getLinkedFeatureType(feature);

  switch (eventType) {
    case 'earthquake':
      return Number(props?.magnitude) || Number.NEGATIVE_INFINITY;
    case 'tsunami':
      return Number(props?.max_water_height_m)
        || Number(props?.wave_height_m)
        || Number(props?.eq_magnitude)
        || Number.NEGATIVE_INFINITY;
    case 'volcano':
      return Number(props?.VEI) || Number(props?.vei) || Number.NEGATIVE_INFINITY;
    case 'hurricane':
    case 'tropical_storm':
      return Number(props?.max_category)
        || Number(props?.category)
        || Number(props?.max_wind_kt)
        || Number(props?.wind_kt)
        || Number.NEGATIVE_INFINITY;
    case 'tornado':
      return getTornadoScaleValue(props?.tornado_scale);
    case 'wildfire':
    case 'flood':
      return Number(props?.area_km2) || Number.NEGATIVE_INFINITY;
    case 'landslide':
      return Number(props?.deaths) || Number(props?.affected) || Number.NEGATIVE_INFINITY;
    default:
      return Number(props?.magnitude)
        || Number(props?.max_water_height_m)
        || Number(props?.VEI)
        || Number(props?.vei)
        || Number(props?.max_category)
        || Number(props?.category)
        || Number(props?.max_wind_kt)
        || Number(props?.wind_kt)
        || getTornadoScaleValue(props?.tornado_scale)
        || Number(props?.area_km2)
        || Number(props?.deaths)
        || Number(props?.affected)
        || Number.NEGATIVE_INFINITY;
  }
}

function compareLinkedFeatureChronology(a, b, options = {}) {
  const aProps = getLinkedFeatureProps(a);
  const bProps = getLinkedFeatureProps(b);
  const anchorFeatureId = String(options.anchorFeatureId || '').trim();
  if (anchorFeatureId) {
    const aIsAnchor = getLinkedFeatureId(a) === anchorFeatureId;
    const bIsAnchor = getLinkedFeatureId(b) === anchorFeatureId;
    if (aIsAnchor && !bIsAnchor) return -1;
    if (!aIsAnchor && bIsAnchor) return 1;
  } else {
    if (aProps?.is_mainshock && !bProps?.is_mainshock) return -1;
    if (!aProps?.is_mainshock && bProps?.is_mainshock) return 1;
  }

  const timeDiff = getLinkedFeatureTimestamp(a, options.timeField) - getLinkedFeatureTimestamp(b, options.timeField);
  if (timeDiff !== 0) return timeDiff;

  const intensityDiff = getLinkedFeatureIntensityScore(b) - getLinkedFeatureIntensityScore(a);
  if (intensityDiff !== 0) return intensityDiff;

  const aId = getLinkedFeatureId(a);
  const bId = getLinkedFeatureId(b);
  return aId.localeCompare(bId);
}

function compareLinkedFeaturePriority(a, b, options = {}) {
  const intensityDiff = getLinkedFeatureIntensityScore(b) - getLinkedFeatureIntensityScore(a);
  if (intensityDiff !== 0) return intensityDiff;

  const timeDiff = getLinkedFeatureTimestamp(a, options.timeField) - getLinkedFeatureTimestamp(b, options.timeField);
  if (timeDiff !== 0) return timeDiff;

  const aId = getLinkedFeatureId(a);
  const bId = getLinkedFeatureId(b);
  return aId.localeCompare(bId);
}

export function selectLinkedAnimationFeatures(features, options = {}) {
  const maxEvents = Math.max(1, Number(options.maxEvents) || MAX_LINKED_ANIMATION_EVENTS);
  const normalizedFeatures = Array.isArray(features)
    ? features.filter((feature) => getLinkedFeatureId(feature))
    : [];

  if (!normalizedFeatures.length) {
    return {
      anchorFeature: null,
      totalCount: 0,
      selectedCount: 0,
      truncatedCount: 0,
      selectedFeatures: []
    };
  }

  let anchorFeature = normalizedFeatures.find((feature) => feature === options.anchorFeature) || null;
  if (!anchorFeature && options.anchorFeatureId) {
    anchorFeature = normalizedFeatures.find((feature) => getLinkedFeatureId(feature) === String(options.anchorFeatureId).trim()) || null;
  }
  if (!anchorFeature) {
    anchorFeature = normalizedFeatures[0];
  }

  const anchorFeatureId = getLinkedFeatureId(anchorFeature);
  const candidateFeatures = normalizedFeatures.filter((feature) => getLinkedFeatureId(feature) !== anchorFeatureId);
  const selectedRelatedFeatures = candidateFeatures
    .slice()
    .sort((a, b) => compareLinkedFeaturePriority(a, b, options))
    .slice(0, Math.max(0, maxEvents - 1));

  const selectedFeatures = [anchorFeature, ...selectedRelatedFeatures]
    .sort((a, b) => compareLinkedFeatureChronology(a, b, {
      ...options,
      anchorFeatureId
    }));

  return {
    anchorFeature,
    totalCount: normalizedFeatures.length,
    selectedCount: selectedFeatures.length,
    truncatedCount: Math.max(0, normalizedFeatures.length - selectedFeatures.length),
    selectedFeatures
  };
}

export function selectEarthquakeSequenceFeatures(features, options = {}) {
  const maxPreviewEvents = Math.max(1, Number(options.maxPreviewEvents) || DEFAULT_EARTHQUAKE_SEQUENCE_PREVIEW_EVENTS);
  const normalizedFeatures = Array.isArray(features)
    ? features.filter((feature) => getLinkedFeatureId(feature))
    : [];

  let mainshockFeature = normalizedFeatures.find((feature) => getLinkedFeatureProps(feature)?.is_mainshock);
  if (!mainshockFeature && normalizedFeatures.length > 0) {
    mainshockFeature = normalizedFeatures.reduce((best, candidate) => (
      getEarthquakeFeatureMagnitude(candidate) > getEarthquakeFeatureMagnitude(best) ? candidate : best
    ), normalizedFeatures[0]);
  }

  const selectedSequence = selectLinkedAnimationFeatures(normalizedFeatures, {
    ...options,
    maxEvents: options.maxEvents || MAX_EARTHQUAKE_SEQUENCE_EVENTS,
    anchorFeature: mainshockFeature,
    timeField: 'timestamp'
  });

  return {
    mainshockFeature: selectedSequence.anchorFeature,
    totalCount: selectedSequence.totalCount,
    selectedCount: selectedSequence.selectedCount,
    truncatedCount: selectedSequence.truncatedCount,
    selectedFeatures: selectedSequence.selectedFeatures,
    previewFeatures: selectedSequence.selectedFeatures.slice(0, maxPreviewEvents)
  };
}

export function beginFocusedAnimationSession(controller, overlayIds = [], options = {}) {
  const normalizedOverlayIds = Array.isArray(overlayIds) ? overlayIds.filter(Boolean) : [];
  const captureOverlayIds = typeof controller?.captureFocusedOverlayIds === 'function'
    ? controller.captureFocusedOverlayIds(normalizedOverlayIds)
    : normalizedOverlayIds;
  const returnViewState = controller?.captureViewState?.() || null;
  controller?.enterFocusedOverlayMode?.(returnViewState, captureOverlayIds);
  const entryDurationMs = Number.isFinite(Number(options.entryDurationMs))
    ? Math.max(0, Number(options.entryDurationMs))
    : 0;
  const autoPlayDelayMs = Number.isFinite(Number(options.autoPlayDelayMs))
    ? Math.max(0, Number(options.autoPlayDelayMs))
    : Math.max(600, entryDurationMs + 250);

  return {
    overlayIds: normalizedOverlayIds,
    restoreOverlayIds: captureOverlayIds,
    returnViewState,
    entryDurationMs,
    autoPlayDelayMs,
    restore() {
      controller?.restoreViewState?.(returnViewState, captureOverlayIds);
    }
  };
}

export function getBoundsFromCoords(coords) {
  if (!coords || coords.length === 0) return null;
  let minLng = Infinity;
  let maxLng = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const [lng, lat] of coords) {
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  return [[minLng, minLat], [maxLng, maxLat]];
}

export function createCircleFeature(centerLon, centerLat, radiusKm, steps = 64) {
  const coords = [];
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    const latOffset = (radiusKm / 111) * Math.cos(angle);
    const lonOffset = (radiusKm / (111 * Math.cos(centerLat * Math.PI / 180))) * Math.sin(angle);
    coords.push([centerLon + lonOffset, centerLat + latOffset]);
  }
  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [coords] }
  };
}

export function collectGeometryCoords(geom) {
  const coords = [];
  if (!geom || !geom.coordinates) return coords;
  if (geom.type === 'Polygon') coords.push(...geom.coordinates[0]);
  if (geom.type === 'MultiPolygon') {
    for (const poly of geom.coordinates) coords.push(...poly[0]);
  }
  return coords;
}

export function computeGeometryCenter(geometry) {
  if (!geometry?.coordinates) return [0, 0];
  let sumLon = 0;
  let sumLat = 0;
  let count = 0;
  if (geometry.type === 'Polygon') {
    for (const pt of geometry.coordinates[0]) {
      sumLon += pt[0];
      sumLat += pt[1];
      count++;
    }
  } else if (geometry.type === 'MultiPolygon') {
    for (const poly of geometry.coordinates) {
      for (const pt of poly[0]) {
        sumLon += pt[0];
        sumLat += pt[1];
        count++;
      }
    }
  }
  return count > 0 ? [sumLon / count, sumLat / count] : [0, 0];
}
