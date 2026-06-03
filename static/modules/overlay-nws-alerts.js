/**
 * NWS Alerts Overlay - live US weather alerts on the map.
 *
 * Driven by the shared Overlays panel ("Live" category) via
 * OverlayController.handleOverlayChange('nws_alerts', ...). Reads
 * GET /api/ops/nws-alerts (msgpack), a GeoJSON FeatureCollection where each
 * alert is already shaped server-side:
 *   - display:'polygon' -> exact NWS warning polygon
 *   - display:'county'  -> highlighted affected county polygon(s)
 *   - display:'pin'     -> point marker at the centroid
 * Colors are by NWS severity. Renders on the shared MapLibre map.
 */

import { fetchMsgpack } from './utils/fetch.js';

const POLL_INTERVAL_MS = 5 * 60_000;
const SRC_ID = 'nws-alerts-src';
const FILL_ID = 'nws-alerts-fill';
const LINE_ID = 'nws-alerts-line';
const POINT_ID = 'nws-alerts-point';

// NWS severity -> color (data-driven paint).
const SEVERITY_COLOR = [
  'match', ['get', 'severity'],
  'Extreme', '#ff3b3b',
  'Severe', '#ff8c00',
  'Moderate', '#ffd24a',
  'Minor', '#4dd2ff',
  '#9aa4bf'
];

let MapAdapter = null;

export const NwsAlertsOverlay = {
  initialized: false,
  enabled: false,
  pollTimer: null,
  lastData: null,
  _popup: null,
  _clickBound: false,
  _popupHandler: null,
  _mouseenterHandler: null,
  _mouseleaveHandler: null,

  init(deps = {}) {
    if (this.initialized) return;
    MapAdapter = deps.MapAdapter || MapAdapter;
    if (MapAdapter?.map) {
      MapAdapter.map.on('style.load', () => {
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
    console.log('NwsAlertsOverlay initialized');
  },

  setEnabled(on) {
    this.enabled = Boolean(on);
    if (this.enabled) {
      this._refresh();
      this._startPolling();
    } else {
      this._stopPolling();
      this._removeLayers();
    }
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
      const data = await fetchMsgpack('/api/ops/nws-alerts');
      const fc = (data && data.type === 'FeatureCollection') ? data : { type: 'FeatureCollection', features: [] };
      this.lastData = fc;
      this._render(fc);
    } catch (err) {
      console.warn('NwsAlertsOverlay: refresh failed', err);
    }
  },

  _render(fc) {
    const map = MapAdapter?.map;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      map.once('load', () => this._render(fc));
      return;
    }
    const source = map.getSource(SRC_ID);
    if (source) {
      source.setData(fc);
      return;
    }
    map.addSource(SRC_ID, { type: 'geojson', data: fc });
    map.addLayer({
      id: FILL_ID, type: 'fill', source: SRC_ID,
      paint: { 'fill-color': SEVERITY_COLOR, 'fill-opacity': 0.22 }
    });
    map.addLayer({
      id: LINE_ID, type: 'line', source: SRC_ID,
      paint: { 'line-color': SEVERITY_COLOR, 'line-width': 1.5, 'line-opacity': 0.9 }
    });
    map.addLayer({
      id: POINT_ID, type: 'circle', source: SRC_ID,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        // A clear target dot per alert, white-ringed so it pops over the
        // currency choropleth and the highlighted areas.
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 4, 4, 6, 8, 9],
        'circle-color': SEVERITY_COLOR,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 2,
        'circle-opacity': 1
      }
    });
    this._bindPopup(map);
  },

  _bindPopup(map) {
    if (this._clickBound) return;
    const maplibre = window.maplibregl || (typeof maplibregl !== 'undefined' ? maplibregl : null);
    if (!maplibre) return;
    this._popupHandler = (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      const p = f.properties || {};
      const esc = (v) => String(v == null ? '' : v).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      const html = `<div style="font-family:monospace;font-size:12px;max-width:240px">
        <div style="font-weight:bold">${esc(p.event)}</div>
        <div style="color:#666">${esc(p.severity)}</div>
        ${p.area ? `<div style="margin-top:4px">${esc(p.area)}</div>` : ''}
        ${p.expires ? `<div style="color:#888;margin-top:4px">Expires: ${esc(p.expires)}</div>` : ''}
        ${(typeof p.alert_id === 'string' && /^https?:/.test(p.alert_id)) ? `<div style="margin-top:6px"><a href="${esc(p.alert_id)}" target="_blank" rel="noopener" style="color:#4dd2ff">More info (NWS) &rsaquo;</a></div>` : ''}
      </div>`;
      if (this._popup) this._popup.remove();
      this._popup = new maplibre.Popup({ closeButton: true })
        .setLngLat(e.lngLat).setHTML(html).addTo(map);
    };
    this._mouseenterHandler = () => { map.getCanvas().style.cursor = 'pointer'; };
    this._mouseleaveHandler = () => { map.getCanvas().style.cursor = ''; };
    for (const layerId of [FILL_ID, LINE_ID, POINT_ID]) {
      map.on('click', layerId, this._popupHandler);
      map.on('mouseenter', layerId, this._mouseenterHandler);
      map.on('mouseleave', layerId, this._mouseleaveHandler);
    }
    this._clickBound = true;
  },

  _unbindPopup(map) {
    if (!this._clickBound || !map) return;
    for (const layerId of [FILL_ID, LINE_ID, POINT_ID]) {
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
    const map = MapAdapter?.map;
    if (!map) return;
    try {
      this._unbindPopup(map);
      for (const id of [FILL_ID, LINE_ID, POINT_ID]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      if (map.getSource(SRC_ID)) map.removeSource(SRC_ID);
      if (this._popup) { this._popup.remove(); this._popup = null; }
    } catch (e) { /* style may be mid-reload; ignore */ }
  }
};

export default NwsAlertsOverlay;
