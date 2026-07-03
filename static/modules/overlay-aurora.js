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
const STRONG_PROBABILITY_THRESHOLD = 50;

let MapAdapter = null;

export const AuroraOverlay = {
  initialized: false,
  enabled: false,
  pollTimer: null,
  lastCells: null,
  lastDisplayCells: null,
  lastPayload: null,

  init(deps = {}) {
    if (this.initialized) return;
    MapAdapter = deps.MapAdapter || MapAdapter;
    // A style reload (globe/satellite switch) drops custom layers; re-add ours.
    if (MapAdapter?.map) {
      MapAdapter.map.on('style.load', () => {
        if (this.enabled && this.lastDisplayCells) this._render(this.lastDisplayCells);
      });
    }
    // Re-assert after a globe/mercator projection toggle (may not fire style.load).
    window.addEventListener('map-overlays-reassert', () => {
      if (this.enabled && this.lastDisplayCells) this._render(this.lastDisplayCells);
    });
    this.initialized = true;
    console.log('AuroraOverlay initialized');
  },

  async setEnabled(on) {
    this.enabled = Boolean(on);
    if (this.enabled) {
      await this._refresh();
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
      this.lastPayload = data && typeof data === 'object' ? data : null;
      this.lastCells = cells;
      this.lastDisplayCells = this._selectDisplayCells(cells, this.lastPayload);
      this._render(this.lastDisplayCells);
    } catch (err) {
      console.warn('AuroraOverlay: refresh failed', err);
    }
  },

  _selectDisplayCells(cells, payload = null) {
    const strongCount = Number(payload?.strong_cell_count);
    if (!Number.isFinite(strongCount) || strongCount <= 0) {
      return Array.isArray(cells) ? cells : [];
    }
    const filtered = (Array.isArray(cells) ? cells : []).filter((cell) => {
      const probability = Number(Array.isArray(cell) ? cell[2] : null);
      return Number.isFinite(probability) && probability >= STRONG_PROBABILITY_THRESHOLD;
    });
    return filtered.length ? filtered : (Array.isArray(cells) ? cells : []);
  },

  getDisplayStats() {
    const snapshotCount = Number(this.lastPayload?.visible_cell_count);
    const visibleCount = Array.isArray(this.lastDisplayCells) ? this.lastDisplayCells.length : 0;
    const strongCount = Number(this.lastPayload?.strong_cell_count);
    const usingStrongBand = Number.isFinite(strongCount) && strongCount > 0 && visibleCount > 0 && visibleCount <= strongCount;
    return {
      snapshotCount: Number.isFinite(snapshotCount) ? snapshotCount : (Array.isArray(this.lastCells) ? this.lastCells.length : 0),
      visibleCount,
      usingStrongBand,
      filterDescription: usingStrongBand ? `probability ${STRONG_PROBABILITY_THRESHOLD}% and above` : null,
      maxProbability: Number(this.lastPayload?.max_probability),
    };
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
