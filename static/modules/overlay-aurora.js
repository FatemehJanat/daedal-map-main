/**
 * Aurora Overlay - live OVATION aurora forecast on the map.
 *
 * A self-contained, toggleable overlay (like the ticker / animation controllers)
 * that draws the current aurora oval as a heatmap on the shared MapLibre map.
 * Available in all modes. Data: GET /api/ops/aurora (msgpack) ->
 * { cells: [[lon, lat, probability], ...], forecast_time, max_probability }.
 *
 * Note: OVATION longitudes are 0-360; we convert >180 to negative so the band
 * lands in the correct hemisphere. Heatmap is screen-space, so it renders best
 * in flat (mercator) view.
 */

import { fetchMsgpack } from './utils/fetch.js';

const STORAGE_KEY = 'auroraOverlayEnabled';
const POLL_INTERVAL_MS = 5 * 60_000;
const SRC_ID = 'aurora-src';
const LAYER_ID = 'aurora-heat';

let MapAdapter = null;

export const AuroraOverlay = {
  initialized: false,
  enabled: false,
  toggle: null,
  pollTimer: null,
  lastCells: null,

  init(deps = {}) {
    if (this.initialized) return;
    MapAdapter = deps.MapAdapter || MapAdapter;
    const parent = document.getElementById('mapContainer');
    if (!parent) {
      console.warn('AuroraOverlay: #mapContainer not found, skipping');
      return;
    }
    this._injectStyles();
    this._mountToggle(parent);

    // A style reload (globe/satellite switch) drops custom layers; re-add ours.
    if (MapAdapter?.map) {
      MapAdapter.map.on('style.load', () => {
        if (this.enabled && this.lastCells) this._render(this.lastCells);
      });
    }

    this.initialized = true;
    let stored = false;
    try { stored = localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) {}
    this.setEnabled(stored, { persist: false });
    console.log('AuroraOverlay initialized');
  },

  _injectStyles() {
    if (document.getElementById('aurora-overlay-styles')) return;
    const style = document.createElement('style');
    style.id = 'aurora-overlay-styles';
    style.textContent = `
      #auroraToggle {
        position: absolute; right: 10px; bottom: 78px; z-index: 46;
        background: rgba(13, 20, 36, 0.92); color: #9aa4bf;
        border: 1px solid #2a3a5e; border-radius: 14px; padding: 4px 12px;
        cursor: pointer; font-family: monospace; font-size: 12px;
      }
      #auroraToggle:hover { color: #8cffc0; border-color: #8cffc0; }
      #auroraToggle.on { color: #8cffc0; border-color: #8cffc0; }
      #auroraToggle .dot {
        display: inline-block; width: 7px; height: 7px; border-radius: 50%;
        background: #555; margin-right: 6px; vertical-align: middle;
      }
      #auroraToggle.on .dot { background: #00ff88; box-shadow: 0 0 6px #00ff88; }
    `;
    document.head.appendChild(style);
  },

  _mountToggle(parent) {
    const btn = document.createElement('button');
    btn.id = 'auroraToggle';
    btn.type = 'button';
    btn.title = 'Toggle the live aurora forecast overlay';
    btn.innerHTML = '<span class="dot"></span>Aurora';
    btn.addEventListener('click', () => this.setEnabled(!this.enabled));
    parent.appendChild(btn);
    this.toggle = btn;
  },

  setEnabled(on, { persist = true } = {}) {
    this.enabled = Boolean(on);
    this.toggle?.classList.toggle('on', this.enabled);
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, this.enabled ? '1' : '0'); } catch (e) {}
    }
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
