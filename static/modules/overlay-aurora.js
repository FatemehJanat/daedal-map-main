/**
 * Aurora Overlay - live OVATION aurora forecast on the map.
 *
 * Draws the current aurora oval as a heatmap on the shared MapLibre map. Driven
 * by the shared Overlays panel: the "Aurora" overlay routes through
 * OverlayController.handleOverlayChange -> setEnabled(). This module owns only
 * the map layer + polling, not its own toggle button.
 *
 * Data: GET /api/ops/aurora (msgpack) -> { cells: [[lon, lat, probability], ...] }.
 * Note: OVATION longitudes are 0-360; we convert >180 to negative so the band
 * lands in the correct hemisphere. Heatmap is screen-space, so it renders best
 * in flat (mercator) view.
 */

import { fetchMsgpack } from './utils/fetch.js';

const POLL_INTERVAL_MS = 5 * 60_000;
const SRC_ID = 'aurora-src';
const LAYER_ID = 'aurora-heat';

let MapAdapter = null;

export const AuroraOverlay = {
  initialized: false,
  enabled: false,
  pollTimer: null,
  lastCells: null,

  init(deps = {}) {
    if (this.initialized) return;
    MapAdapter = deps.MapAdapter || MapAdapter;
    // A style reload (globe/satellite switch) drops custom layers; re-add ours.
    if (MapAdapter?.map) {
      MapAdapter.map.on('style.load', () => {
        if (this.enabled && this.lastCells) this._render(this.lastCells);
      });
    }
    // Re-assert after a globe/mercator projection toggle (may not fire style.load).
    window.addEventListener('map-overlays-reassert', () => {
      if (this.enabled && this.lastCells) this._render(this.lastCells);
    });
    this.initialized = true;
    console.log('AuroraOverlay initialized');
  },

  setEnabled(on) {
    this.enabled = Boolean(on);
    if (this.enabled) {
      this._refresh();
      this._startPolling();
    } else {
      this._stopPolling();
      this._removeLayer();
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
      const data = await fetchMsgpack('/api/ops/aurora');
      const cells = Array.isArray(data?.cells) ? data.cells : [];
      this.lastCells = cells;
      this._render(cells);
    } catch (err) {
      console.warn('AuroraOverlay: refresh failed', err);
    }
  },

  _toGeoJSON(cells) {
    const features = [];
    for (const c of cells) {
      if (!Array.isArray(c) || c.length < 3) continue;
      let lon = c[0];
      const lat = c[1];
      const prob = c[2];
      if (lon > 180) lon -= 360;  // OVATION uses 0-360 longitude
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [lon, lat] },
        properties: { prob }
      });
    }
    return { type: 'FeatureCollection', features };
  },

  _render(cells) {
    const map = MapAdapter?.map;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      map.once('load', () => this._render(cells));
      return;
    }
    const fc = this._toGeoJSON(cells);
    const source = map.getSource(SRC_ID);
    if (source) {
      source.setData(fc);
      return;
    }
    map.addSource(SRC_ID, { type: 'geojson', data: fc });
    map.addLayer({
      id: LAYER_ID,
      type: 'heatmap',
      source: SRC_ID,
      paint: {
        'heatmap-weight': ['interpolate', ['linear'], ['get', 'prob'], 0, 0, 100, 1],
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 2],
        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 8, 3, 20, 6, 45],
        'heatmap-opacity': 0.75,
        'heatmap-color': [
          'interpolate', ['linear'], ['heatmap-density'],
          0, 'rgba(0,0,0,0)',
          0.2, 'rgba(20,120,70,0.45)',
          0.45, 'rgba(0,210,130,0.65)',
          0.7, 'rgba(140,255,190,0.85)',
          1, 'rgba(225,255,235,0.95)'
        ]
      }
    });
  },

  _removeLayer() {
    const map = MapAdapter?.map;
    if (!map) return;
    try {
      if (map.getLayer(LAYER_ID)) map.removeLayer(LAYER_ID);
      if (map.getSource(SRC_ID)) map.removeSource(SRC_ID);
    } catch (e) { /* style may be mid-reload; ignore */ }
  }
};

export default AuroraOverlay;
