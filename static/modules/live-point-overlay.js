/**
 * Live point overlay - reusable Ops overlay for "location with updating data"
 * feeds (ocean buoys, weather stations, sensors, points of interest).
 *
 * One renderer, per-feed config. createLivePointOverlay(config) returns an
 * overlay object with the same lifecycle as the bespoke live overlays
 * (init / setEnabled / getDisplayStats / render / popup), driven entirely by
 * config: a generic /api/ops/points/<id> endpoint, an icon, a color-by-property
 * ramp, and a popup field list. Add a new feed = one config block + a backend
 * POINT_FEEDS entry (see mapmover/ops_point_feeds.py). No new overlay classes.
 *
 * See county-map-private/docs/CLIMATE_DISPLAY.md (Live Point Feeds).
 */

import { fetchMsgpack } from './utils/fetch.js';

const POLL_INTERVAL_MS = 5 * 60_000;

// Build a MapLibre data-driven color expression from {prop, stops, nullColor}.
function colorExpression(colorBy) {
  if (!colorBy || !Array.isArray(colorBy.stops) || !colorBy.stops.length) {
    return colorBy?.nullColor || '#7fb2ff';
  }
  const interp = ['interpolate', ['linear'], ['to-number', ['get', colorBy.prop]]];
  for (const [value, color] of colorBy.stops) interp.push(value, color);
  // Points missing the colored property fall back to nullColor instead of erroring.
  return ['case', ['==', ['get', colorBy.prop], null], colorBy.nullColor || '#9aa4bf', interp];
}

export function createLivePointOverlay(config) {
  const SRC_ID = `lpo-${config.id}-src`;
  const CIRCLE_ID = `lpo-${config.id}-circle`;
  const HIT_LAYER_ID = `lpo-${config.id}-hit`;
  const ICON_LAYER_ID = `lpo-${config.id}-icon`;
  const ICON_IMAGE_ID = `lpo-${config.id}-img`;

  return {
    config,
    initialized: false,
    enabled: false,
    pollTimer: null,
    lastData: null,
    MapAdapter: null,
    _clickBound: false,
    _popupHandler: null,
    _mouseenterHandler: null,
    _mouseleaveHandler: null,
    _iconLoadPromise: null,

    init(deps = {}) {
      if (this.initialized) return;
      this.MapAdapter = deps.MapAdapter || this.MapAdapter;
      const map = this.MapAdapter?.map;
      if (map) {
        map.on('style.load', () => {
          if (!this.enabled || !this.lastData) return;
          this._clickBound = false;
          this._render(this.lastData);
        });
      }
      // Re-assert after a globe/mercator projection toggle (may not fire style.load).
      window.addEventListener('map-overlays-reassert', () => {
        if (!this.enabled || !this.lastData) return;
        this._clickBound = false;
        this._render(this.lastData);
      });
      this.initialized = true;
      console.log(`LivePointOverlay[${config.id}] initialized`);
    },

    async setEnabled(on) {
      this.enabled = Boolean(on);
      if (this.enabled) {
        await this._refresh();
        this._startPolling();
      } else {
        this._stopPolling();
        this._removeLayers();
      }
    },

    getDisplayStats() {
      const count = Array.isArray(this.lastData?.features) ? this.lastData.features.length : 0;
      return { snapshotCount: count, visibleCount: count };
    },

    _startPolling() {
      this._stopPolling();
      this.pollTimer = setInterval(() => this._refresh(), POLL_INTERVAL_MS);
    },

    _stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },

    async _refresh() {
      if (!this.enabled) return;
      try {
        const data = await fetchMsgpack(config.endpoint);
        const fc = (data && data.type === 'FeatureCollection') ? data : { type: 'FeatureCollection', features: [] };
        this.lastData = fc;
        this._render(fc);
      } catch (err) {
        console.warn(`LivePointOverlay[${config.id}]: refresh failed`, err);
      }
    },

    async _render(fc) {
      const map = this.MapAdapter?.map;
      if (!map) return;
      if (!map.isStyleLoaded()) {
        map.once('load', () => this._render(fc));
        return;
      }
      await this._ensureIcon(map);
      const source = map.getSource(SRC_ID);
      if (source) {
        source.setData(fc);
        return;
      }
      map.addSource(SRC_ID, { type: 'geojson', data: fc });
      map.addLayer({
        id: CIRCLE_ID, type: 'circle', source: SRC_ID,
        paint: {
          'circle-color': colorExpression(config.colorBy),
          'circle-radius': config.circleRadius || ['interpolate', ['linear'], ['zoom'], 1, 3.6, 4, 6, 8, 10.5],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 0.8,
          'circle-opacity': 0.92,
        },
      });
      map.addLayer({
        id: HIT_LAYER_ID, type: 'circle', source: SRC_ID,
        paint: {
          'circle-radius': config.hitRadius || ['interpolate', ['linear'], ['zoom'], 1, 7.2, 4, 12, 8, 21],
          'circle-color': '#ffffff',
          'circle-opacity': 0,
        },
      });
      if (config.icon) {
        map.addLayer({
          id: ICON_LAYER_ID, type: 'symbol', source: SRC_ID,
          minzoom: config.icon.minzoom ?? 3,
          layout: {
            'icon-image': ICON_IMAGE_ID,
            'icon-size': config.icon.size ?? ['interpolate', ['linear'], ['zoom'], 3, 0.5, 8, 0.85],
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
        });
      }
      this._bindPopup(map);
    },

    async _ensureIcon(map) {
      if (!map || !config.icon?.svg || map.hasImage(ICON_IMAGE_ID)) return;
      if (this._iconLoadPromise) { await this._iconLoadPromise; return; }
      const [w, h] = config.icon.pixelSize || [28, 34];
      this._iconLoadPromise = new Promise((resolve, reject) => {
        const img = new Image(w, h);
        img.onload = () => {
          try {
            if (!map.hasImage(ICON_IMAGE_ID)) map.addImage(ICON_IMAGE_ID, img, { pixelRatio: 2 });
            resolve();
          } catch (e) { reject(e); }
        };
        img.onerror = reject;
        img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(config.icon.svg)}`;
      }).finally(() => { this._iconLoadPromise = null; });
      await this._iconLoadPromise;
    },

    _fmt(value, field) {
      if (value == null || value === '') return null;
      if (typeof value === 'number' && Number.isFinite(field?.digits)) {
        return value.toFixed(field.digits);
      }
      return String(value);
    },

    _bindPopup(map) {
      if (this._clickBound) return;
      const esc = (v) => String(v == null ? '' : v).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      this._popupHandler = (e) => {
        const f = e.features && e.features[0];
        if (!f) return;
        const p = f.properties || {};
        const titleVal = config.popup?.titleProp ? p[config.popup.titleProp] : '';
        const rows = (config.popup?.fields || []).map((field) => {
          const shown = this._fmt(p[field.prop], field);
          if (shown == null) return '';
          const unit = field.unit ? ` ${esc(field.unit)}` : '';
          return `<div><span style="color:#888">${esc(field.label)}:</span> ${esc(shown)}${unit}</div>`;
        }).join('');
        const html = `<div style="font-family:monospace;font-size:12px;max-width:220px">
          ${titleVal ? `<div style="font-weight:bold">${esc(config.popup.titlePrefix || '')}${esc(titleVal)}</div>` : ''}
          ${rows}
        </div>`;
        // Live points participate in the one shared popup contract. This keeps
        // a buoy click above the point/raster inspector rather than opening a
        // second independent MapLibre popup.
        this.MapAdapter?.registerFeaturePopupClick?.();
        this.MapAdapter?.showPopup?.([e.lngLat.lng, e.lngLat.lat], html);
        if (this.MapAdapter) {
          this.MapAdapter.popupLocked = true;
          this.MapAdapter.setSelectedPopupContext?.({
            kind: 'live_point',
            overlayId: config.id,
            properties: p,
          });
        }
      };
      this._mouseenterHandler = () => { map.getCanvas().style.cursor = 'pointer'; };
      this._mouseleaveHandler = () => { map.getCanvas().style.cursor = ''; };
      for (const layerId of [HIT_LAYER_ID, CIRCLE_ID, ICON_LAYER_ID]) {
        if (!map.getLayer(layerId)) continue;
        map.on('click', layerId, this._popupHandler);
        map.on('mouseenter', layerId, this._mouseenterHandler);
        map.on('mouseleave', layerId, this._mouseleaveHandler);
      }
      this._clickBound = true;
    },

    _unbindPopup(map) {
      if (!this._clickBound || !map) return;
      for (const layerId of [HIT_LAYER_ID, CIRCLE_ID, ICON_LAYER_ID]) {
        if (this._popupHandler) map.off('click', layerId, this._popupHandler);
        if (this._mouseenterHandler) map.off('mouseenter', layerId, this._mouseenterHandler);
        if (this._mouseleaveHandler) map.off('mouseleave', layerId, this._mouseleaveHandler);
      }
      this._clickBound = false;
      this._popupHandler = null;
      this._mouseenterHandler = null;
      this._mouseleaveHandler = null;
    },

    _removeLayers() {
      const map = this.MapAdapter?.map;
      if (!map) return;
      try {
        this._unbindPopup(map);
        for (const id of [ICON_LAYER_ID, HIT_LAYER_ID, CIRCLE_ID]) {
          if (map.getLayer(id)) map.removeLayer(id);
        }
        if (map.getSource(SRC_ID)) map.removeSource(SRC_ID);
        if (this.MapAdapter?.selectedPopupContext?.kind === 'live_point'
          && this.MapAdapter.selectedPopupContext.overlayId === config.id) {
          this.MapAdapter.hidePopup?.();
        }
      } catch (e) { /* style may be mid-reload; ignore */ }
    },
  };
}

// SST color ramp shared with the ocean grid (sst_c, -2..36 C, blue -> red).
const SST_STOPS = [
  [-2, '#2b2c7f'], [0, '#2f6db3'], [10, '#5ec5ff'], [18, '#f8f7cf'],
  [24, '#f5a65b'], [30, '#df5b3f'], [36, '#7f0000'],
];

const BUOY_ICON_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 34">
  <line x1="14" y1="2" x2="14" y2="11" stroke="#ffffff" stroke-width="2"/>
  <circle cx="14" cy="3.5" r="2.4" fill="#ffd24a" stroke="#ffffff" stroke-width="1"/>
  <path d="M6 13 H22 L19 25 H9 Z" fill="#e8552d" stroke="#ffffff" stroke-width="1.6"/>
  <rect x="8.5" y="16" width="11" height="2.6" fill="#ffffff" opacity="0.9"/>
</svg>`.trim();

const BUOYS_CONFIG = {
  id: 'buoys',
  feedId: 'noaa_ndbc',
  endpoint: '/api/ops/points/buoys',
  colorBy: { prop: 'sst_c', stops: SST_STOPS, nullColor: '#9aa4bf' },
  circleRadius: ['interpolate', ['linear'], ['zoom'], 1, 3.6, 4, 6, 8, 10.5],
  hitRadius: ['interpolate', ['linear'], ['zoom'], 1, 7.2, 4, 12, 8, 21],
  icon: { svg: BUOY_ICON_SVG, pixelSize: [42, 51], minzoom: 3, size: ['interpolate', ['linear'], ['zoom'], 3, 0.75, 8, 1.275] },
  popup: {
    titleProp: 'station_id',
    titlePrefix: 'Buoy ',
    fields: [
      { label: 'Sea temp', prop: 'sst_c', unit: 'C', digits: 1 },
      { label: 'Air temp', prop: 'air_c', unit: 'C', digits: 1 },
      { label: 'Wave', prop: 'wave_m', unit: 'm', digits: 1 },
      { label: 'Wind', prop: 'wind_mps', unit: 'm/s', digits: 1 },
      { label: 'Observed', prop: 'obs_utc' },
    ],
  },
};

// Registry of live point overlays. Add a config here (+ a backend POINT_FEEDS
// entry) to surface a new station/sensor feed.
export const LIVE_POINT_OVERLAYS = {
  buoys: createLivePointOverlay(BUOYS_CONFIG),
};

export function getLivePointOverlay(overlayId) {
  return LIVE_POINT_OVERLAYS[String(overlayId || '').trim()] || null;
}

export function initLivePointOverlays(deps) {
  for (const overlay of Object.values(LIVE_POINT_OVERLAYS)) overlay.init(deps);
}

export function livePointOverlayFeedId(overlayId) {
  return LIVE_POINT_OVERLAYS[String(overlayId || '').trim()]?.config?.feedId || null;
}
