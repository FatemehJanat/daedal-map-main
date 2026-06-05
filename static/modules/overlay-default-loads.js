import {
  getOpsOverlayIdsForFeeds,
  getOverlayCatalogEntriesByPackId,
  getOverlayCatalogEntryBySourceId,
  resolveOverlayIdFromPackId,
  resolveOverlayIdFromSourceId
} from './overlay-selector.js';

const DISASTER_PACKS = new Set([
  'earthquakes',
  'hurricanes',
  'volcanoes',
  'wildfires',
  'tsunamis',
  'tornadoes',
  'floods',
  'landslides',
  'drought'
]);

const SOURCE_TO_OVERLAY = {
  earthquakes_events: 'earthquakes',
  hurricanes_events: 'hurricanes',
  storms_tracks: 'hurricanes',
  storms: 'hurricanes',
  volcanoes_events: 'volcanoes',
  eruptions_events: 'volcanoes',
  wildfires_events: 'wildfires',
  tsunamis_events: 'tsunamis',
  tornadoes_events: 'tornadoes',
  floods_events: 'floods',
  landslides_events: 'landslides',
  drought_events: 'drought'
};

const OVERLAY_TO_FEED = {
  earthquakes: 'earthquakes',
  hurricanes: 'hurricanes_ibtracs_nrt',
  volcanoes: 'volcanoes',
  wildfires: 'wildfires_us_nifc',
  tsunamis: 'tsunamis',
  aurora: 'noaa_aurora',
  nws_alerts: 'usa_nws_alerts',
  currency: 'currency'
};

function getCurrentUtcYear() {
  return new Date().getUTCFullYear();
}

function cloneJsonSafe(value) {
  if (value == null) return value;
  return JSON.parse(JSON.stringify(value));
}

function materializeRelativeYears(items, relativeYears) {
  const yearsBack = Number(relativeYears);
  if (!Number.isFinite(yearsBack) || yearsBack <= 0) {
    return items;
  }
  const endYear = getCurrentUtcYear();
  const startYear = Math.max(1900, endYear - Math.trunc(yearsBack) + 1);
  return items.map((item) => {
    if (!item || typeof item !== 'object') return item;
    if (item.year_start || item.year_end) {
      return item;
    }
    return {
      ...item,
      year_start: startYear,
      year_end: endYear
    };
  });
}

function buildConfirmedOrderFromDefaultLoad(defaultLoad, fallbackSummary = '') {
  if (!defaultLoad || typeof defaultLoad !== 'object') return null;
  if (String(defaultLoad.kind || defaultLoad.type || 'confirmed_order').trim() !== 'confirmed_order') {
    return null;
  }

  const items = Array.isArray(defaultLoad.items)
    ? materializeRelativeYears(cloneJsonSafe(defaultLoad.items), defaultLoad.relative_years)
    : [];
  if (!items.length) return null;

  return {
    items,
    summary: String(defaultLoad.summary || fallbackSummary || '').trim()
  };
}

function getSourceDefaultLoadAction(sourceEntry) {
  if (!sourceEntry || typeof sourceEntry !== 'object') return null;
  const defaultLoad = buildConfirmedOrderFromDefaultLoad(
    sourceEntry.default_load,
    sourceEntry.default_response || sourceEntry.default_question || ''
  );
  if (!defaultLoad) return null;
  return {
    type: 'confirmed_order',
    order: defaultLoad,
    message: String(sourceEntry.default_response || '').trim()
  };
}

function getPackDefaultLoadAction(packId) {
  const entries = getOverlayCatalogEntriesByPackId(packId);
  for (const entry of entries) {
    const action = getSourceDefaultLoadAction(entry);
    if (action) return action;
  }
  return null;
}

function buildPresetOrderFromPackDefaults(packIds, fallbackSummary = '') {
  const items = [];
  let summary = '';
  for (const packId of packIds) {
    const action = getPackDefaultLoadAction(packId);
    const orderItems = Array.isArray(action?.order?.items) ? cloneJsonSafe(action.order.items) : [];
    if (!orderItems.length) {
      continue;
    }
    items.push(...orderItems);
    if (!summary && action?.order?.summary) {
      summary = String(action.order.summary).trim();
    }
  }
  if (!items.length) {
    return null;
  }
  return {
    items,
    summary: summary || fallbackSummary
  };
}

export function resolveOverlayIdForOrderResult(response, order = null) {
  const directOverlayId = String(response?.overlay_id || '').trim();
  if (directOverlayId) return directOverlayId;

  const packId = String(response?.pack_id || order?.pack_id || order?.items?.[0]?.pack_id || '').trim();
  const overlayIdFromPack = resolveOverlayIdFromPackId(packId);
  if (overlayIdFromPack) {
    return overlayIdFromPack;
  }
  if (packId && DISASTER_PACKS.has(packId)) {
    return packId;
  }

  const responseSourceId = String(response?.source_id || order?.source_id || order?.items?.[0]?.source_id || '').trim();
  const overlayIdFromSource = resolveOverlayIdFromSourceId(responseSourceId);
  if (overlayIdFromSource) {
    return overlayIdFromSource;
  }
  if (responseSourceId && SOURCE_TO_OVERLAY[responseSourceId]) {
    return SOURCE_TO_OVERLAY[responseSourceId];
  }
  if (responseSourceId.endsWith('_events')) {
    const stripped = responseSourceId.slice(0, -'_events'.length);
    if (DISASTER_PACKS.has(stripped)) {
      return stripped;
    }
  }

  const eventType = String(response?.event_type || '').trim().toLowerCase();
  if (eventType && DISASTER_PACKS.has(`${eventType}s`)) {
    return `${eventType}s`;
  }
  if (eventType === 'hurricane') return 'hurricanes';
  if (eventType === 'wildfire') return 'wildfires';
  if (eventType === 'tsunami') return 'tsunamis';
  if (eventType === 'tornado') return 'tornadoes';
  if (eventType === 'flood') return 'floods';
  if (eventType === 'landslide') return 'landslides';
  if (eventType === 'earthquake') return 'earthquakes';
  if (eventType === 'volcano') return 'volcanoes';

  return '';
}

export function buildPackDefaultLoadOrder(packId) {
  const normalizedPackId = String(packId || '').trim();
  if (!normalizedPackId) return null;
  const metadataAction = getPackDefaultLoadAction(normalizedPackId);
  if (metadataAction?.order) {
    return metadataAction.order;
  }
  return null;
}

export function buildSourceDefaultLoadOrder(sourceId) {
  const normalizedSourceId = String(sourceId || '').trim();
  if (!normalizedSourceId) return null;
  const metadataAction = getSourceDefaultLoadAction(getOverlayCatalogEntryBySourceId(normalizedSourceId));
  if (metadataAction?.order) {
    return metadataAction.order;
  }
  return null;
}

export function resolveDefaultLoadAction({ lane = 'explore', overlayId = '', packId = '', sourceId = '', feedId = '', presetId = '' } = {}) {
  const normalizedLane = String(lane || 'explore').trim().toLowerCase();
  const normalizedPresetId = String(presetId || '').trim();
  if (normalizedPresetId === 'explore:disasters_2020_2025') {
    const presetOrder = buildPresetOrderFromPackDefaults(
      ['earthquakes', 'hurricanes', 'volcanoes', 'wildfires', 'tsunamis', 'tornadoes'],
      'Loading disaster defaults'
    );
    if (presetOrder) {
      return {
        type: 'confirmed_order',
        order: presetOrder
      };
    }
    return null;
  }

  const normalizedPackId = String(packId || '').trim();
  if (normalizedPackId) {
    const metadataAction = getPackDefaultLoadAction(normalizedPackId);
    if (metadataAction) {
      return metadataAction;
    }
    const order = buildPackDefaultLoadOrder(normalizedPackId);
    if (order) {
      return { type: 'confirmed_order', order };
    }
  }

  const normalizedSourceId = String(sourceId || '').trim();
  if (normalizedLane === 'explore' && normalizedSourceId) {
    const metadataAction = getSourceDefaultLoadAction(getOverlayCatalogEntryBySourceId(normalizedSourceId));
    if (metadataAction) {
      return metadataAction;
    }
    const order = buildSourceDefaultLoadOrder(normalizedSourceId);
    if (order) {
      return { type: 'confirmed_order', order };
    }
  }

  const normalizedOverlayId = String(overlayId || '').trim();
  if (normalizedLane === 'explore' && normalizedOverlayId) {
    const order = buildPackDefaultLoadOrder(normalizedOverlayId);
    if (order) {
      return {
        type: 'confirmed_order',
        order
      };
    }
  }

  const normalizedFeedId = String(feedId || '').trim();
  if (normalizedLane === 'ops' && normalizedFeedId) {
    const overlayIds = getOpsOverlayIdsForFeeds([normalizedFeedId]);
    if (overlayIds.length) {
      return {
        type: 'overlay_activation',
        overlayIds
      };
    }
  }

  if (normalizedLane === 'ops' && normalizedOverlayId) {
    const mappedFeedId = OVERLAY_TO_FEED[normalizedOverlayId];
    if (mappedFeedId) {
      return {
        type: 'overlay_activation',
        overlayIds: [normalizedOverlayId],
        feedId: mappedFeedId
      };
    }
  }

  return null;
}
