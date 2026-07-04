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
 * Colors are by alert family. Renders on the shared MapLibre map.
 */

import { fetchMsgpack } from './utils/fetch.js';

const POLL_INTERVAL_MS = 5 * 60_000;
const SRC_ID = 'nws-alerts-src';
const FILL_ID = 'nws-alerts-fill';
const LINE_ID = 'nws-alerts-line';
const EXTREME_LINE_ID = 'nws-alerts-extreme-line';
const POINT_ID = 'nws-alerts-point';
const PIN_IMAGE_PREFIX = 'nws-alert-pin';
const LEGEND_ID = 'nws-alerts-legend';

const ALERT_FAMILIES = {
  tornado: { label: 'Tornado', color: '#b026ff', lineColor: '#f5d0fe' },
  thunderstorm: { label: 'Thunderstorm', color: '#facc15', lineColor: '#fef08a' },
  flood: { label: 'Flood', color: '#0284c7', lineColor: '#bae6fd' },
  winter: { label: 'Winter', color: '#38bdf8', lineColor: '#e0f2fe' },
  heat: { label: 'Heat', color: '#f97316', lineColor: '#fed7aa' },
  fire: { label: 'Fire weather', color: '#dc2626', lineColor: '#fecaca' },
  marine: { label: 'Marine/coastal', color: '#0d9488', lineColor: '#99f6e4' },
  dust: { label: 'Dust', color: '#a16207', lineColor: '#fde68a' },
  other: { label: 'Other alerts', color: '#a3a3a3', lineColor: '#e5e7eb' },
};

const FAMILY_KEYS = Object.keys(ALERT_FAMILIES);

function buildFamilyMatch(key) {
  const expression = ['match', ['get', 'alert_family']];
  for (const family of FAMILY_KEYS) {
    expression.push(family, ALERT_FAMILIES[family][key]);
  }
  expression.push(ALERT_FAMILIES.other[key]);
  return expression;
}

const FAMILY_FILL_COLOR = buildFamilyMatch('color');
const FAMILY_LINE_COLOR = buildFamilyMatch('lineColor');

const FILL_OPACITY = [
  'case',
  ['==', ['get', 'severity'], 'Extreme'], 0.34,
  ['==', ['get', 'urgency'], 'Immediate'], 0.28,
  0.22
];

const LINE_WIDTH = [
  'case',
  ['==', ['get', 'severity'], 'Extreme'], 3.2,
  ['==', ['get', 'urgency'], 'Immediate'], 2.5,
  1.7
];

const PIN_SIZE = ['interpolate', ['linear'], ['zoom'], 1, 0.74, 4, 0.86, 8, 1.02];

function normalizeAlertFamily(eventName) {
  const text = String(eventName || '').trim().toLowerCase();
  if (!text) return 'other';
  if (text.includes('tornado')) return 'tornado';
  if (text.includes('thunderstorm')) return 'thunderstorm';
  if (text.includes('flash flood') || text.includes('flood')) return 'flood';
  if (
    text.includes('winter') ||
    text.includes('snow') ||
    text.includes('blizzard') ||
    text.includes('ice') ||
    text.includes('freezing')
  ) return 'winter';
  if (text.includes('heat')) return 'heat';
  if (text.includes('fire') || text.includes('red flag')) return 'fire';
  if (
    text.includes('marine') ||
    text.includes('coastal') ||
    text.includes('surf') ||
    text.includes('rip current') ||
    text.includes('gale') ||
    text.includes('small craft')
  ) return 'marine';
  if (text.includes('dust')) return 'dust';
  return 'other';
}

function decorateAlertFeatures(fc) {
  const features = Array.isArray(fc?.features) ? fc.features : [];
  return {
    ...fc,
    type: 'FeatureCollection',
    features: features.map((feature) => {
      const props = { ...(feature?.properties || {}) };
      const alertFamily = String(props.alert_family || '').trim() || normalizeAlertFamily(props.event);
      return {
        ...feature,
        properties: {
          ...props,
          alert_family: alertFamily,
          alert_family_label: ALERT_FAMILIES[alertFamily]?.label || ALERT_FAMILIES.other.label,
        }
      };
    })
  };
}

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
  _pinLoadPromise: null,
  _legendEl: null,
  _legendClickHandler: null,

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

  getActiveAlertCount() {
    const features = this.lastData?.features;
    if (!Array.isArray(features) || !features.length) return 0;
    const alertIds = new Set();
    for (const feature of features) {
      const props = feature?.properties;
      const alertId = String(props?.alert_id || '').trim();
      if (alertId) alertIds.add(alertId);
    }
    return alertIds.size;
  },

  getDisplayStats() {
    const features = Array.isArray(this.lastData?.features) ? this.lastData.features : [];
    const alertIds = new Set();
    const bySeverity = {};
    const byFamily = {};
    for (const feature of features) {
      const props = feature?.properties || {};
      const alertId = String(props.alert_id || '').trim();
      const severity = String(props.severity || '').trim() || 'Unknown';
      const family = String(props.alert_family || normalizeAlertFamily(props.event)).trim() || 'other';
      if (!alertId || alertIds.has(alertId)) continue;
      alertIds.add(alertId);
      bySeverity[severity] = (bySeverity[severity] || 0) + 1;
      byFamily[family] = (byFamily[family] || 0) + 1;
    }
    return {
      snapshotCount: alertIds.size,
      visibleCount: alertIds.size,
      bySeverity,
      byFamily,
    };
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
      const raw = (data && data.type === 'FeatureCollection') ? data : { type: 'FeatureCollection', features: [] };
      const fc = decorateAlertFeatures(raw);
      this.lastData = fc;
      this._render(fc);
    } catch (err) {
      console.warn('NwsAlertsOverlay: refresh failed', err);
    }
  },

  async _render(fc) {
    const map = MapAdapter?.map;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      map.once('load', () => this._render(fc));
      return;
    }
    await this._ensurePinImages(map);
    const source = map.getSource(SRC_ID);
    if (source) {
      source.setData(fc);
      this._renderLegend(fc);
      return;
    }
    map.addSource(SRC_ID, { type: 'geojson', data: fc });
    map.addLayer({
      id: FILL_ID, type: 'fill', source: SRC_ID,
      paint: { 'fill-color': FAMILY_FILL_COLOR, 'fill-opacity': FILL_OPACITY }
    });
    map.addLayer({
      id: EXTREME_LINE_ID, type: 'line', source: SRC_ID,
      filter: ['==', ['get', 'severity'], 'Extreme'],
      paint: { 'line-color': '#ffffff', 'line-width': 5.2, 'line-opacity': 0.55 }
    });
    map.addLayer({
      id: LINE_ID, type: 'line', source: SRC_ID,
      paint: { 'line-color': FAMILY_LINE_COLOR, 'line-width': LINE_WIDTH, 'line-opacity': 0.95 }
    });
    map.addLayer({
      id: POINT_ID, type: 'symbol', source: SRC_ID,
      filter: ['==', ['geometry-type'], 'Point'],
      layout: {
        'icon-image': [
          'match', ['get', 'alert_family'],
          'tornado', `${PIN_IMAGE_PREFIX}-tornado`,
          'thunderstorm', `${PIN_IMAGE_PREFIX}-thunderstorm`,
          'flood', `${PIN_IMAGE_PREFIX}-flood`,
          'winter', `${PIN_IMAGE_PREFIX}-winter`,
          'heat', `${PIN_IMAGE_PREFIX}-heat`,
          'fire', `${PIN_IMAGE_PREFIX}-fire`,
          'marine', `${PIN_IMAGE_PREFIX}-marine`,
          'dust', `${PIN_IMAGE_PREFIX}-dust`,
          `${PIN_IMAGE_PREFIX}-other`
        ],
        'icon-size': PIN_SIZE,
        'icon-anchor': 'bottom',
        'icon-allow-overlap': true,
        'icon-ignore-placement': true
      },
      paint: {
        'icon-opacity': 1
      }
    });
    this._bindPopup(map);
    this._renderLegend(fc);
  },

  async _ensurePinImages(map) {
    if (!map) return;
    const missing = FAMILY_KEYS.filter((key) => !map.hasImage(`${PIN_IMAGE_PREFIX}-${key}`));
    if (missing.length === 0) return;
    if (this._pinLoadPromise) {
      await this._pinLoadPromise;
      return;
    }

    this._pinLoadPromise = Promise.all(missing.map((key) => this._loadPinImage(map, key, ALERT_FAMILIES[key].color)))
      .finally(() => {
        this._pinLoadPromise = null;
      });
    await this._pinLoadPromise;
  },

  _pinSvg(color) {
    return `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 40">
        <path d="M14 1.5 C7.1 1.5 1.5 7.1 1.5 14 C1.5 24.2 12.4 34.6 13.2 35.3 C13.7 35.8 14.4 35.8 14.8 35.3 C15.6 34.6 26.5 24.2 26.5 14 C26.5 7.1 20.9 1.5 14 1.5 Z" fill="${color}" stroke="#ffffff" stroke-width="2"/>
        <circle cx="14" cy="14" r="4.2" fill="#ffffff" opacity="0.92"/>
      </svg>
    `.trim();
  },

  _loadPinImage(map, key, color) {
    return new Promise((resolve, reject) => {
      const img = new Image(28, 40);
      img.onload = () => {
        try {
          const imageId = `${PIN_IMAGE_PREFIX}-${key}`;
          if (!map.hasImage(imageId)) {
            map.addImage(imageId, img, { pixelRatio: 2 });
          }
          resolve();
        } catch (error) {
          reject(error);
        }
      };
      img.onerror = reject;
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(this._pinSvg(color))}`;
    });
  },

  _bindPopup(map) {
    if (this._clickBound) return;
    const maplibre = window.maplibregl || (typeof maplibregl !== 'undefined' ? maplibregl : null);
    if (!maplibre) return;
    this._popupHandler = (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      const p = f.properties || {};
      const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));
      const text = (v) => esc(v).replace(/\r?\n/g, '<br>');
      const detail = (label, value) => value ? `
        <details class="nws-popup-detail">
          <summary>${label}</summary>
          <div class="nws-popup-detail-body">${text(value)}</div>
        </details>` : '';
      const html = `<div class="nws-alert-popup">
        <div class="nws-popup-title">${esc(p.event)}</div>
        <div class="nws-popup-classification">${esc(p.alert_family_label || '')}${p.severity ? ` | ${esc(p.severity)}` : ''}</div>
        ${(p.urgency || p.certainty) ? `<div class="nws-popup-confidence">${esc(p.urgency || '')}${p.urgency && p.certainty ? ' / ' : ''}${esc(p.certainty || '')}</div>` : ''}
        ${(p.instruction || p.description || p.area) ? `<div class="nws-popup-details">${detail('Instructions', p.instruction)}${detail('Description', p.description)}${detail('Areas', p.area)}</div>` : ''}
        ${p.expires ? `<div class="nws-popup-expires"><span>Expires</span>${esc(p.expires)}</div>` : ''}
        ${(typeof p.alert_id === 'string' && /^https?:/.test(p.alert_id)) ? `<a class="nws-popup-source" href="${esc(p.alert_id)}" target="_blank" rel="noopener" title="Opens the original machine-readable NWS alert record">Official NWS source (JSON) &rsaquo;</a>` : ''}
      </div>`;
      if (this._popup) this._popup.remove();
      this._popup = new maplibre.Popup({ closeButton: true, maxWidth: '340px' })
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

  _renderLegend(fc) {
    const features = Array.isArray(fc?.features) ? fc.features : [];
    const countsByFamily = new Map();
    const seenAlertIds = new Set();
    for (const feature of features) {
      const props = feature?.properties || {};
      const alertId = String(props.alert_id || '').trim();
      if (alertId && seenAlertIds.has(alertId)) continue;
      if (alertId) seenAlertIds.add(alertId);
      const family = String(props.alert_family || '').trim() || 'other';
      countsByFamily.set(family, (countsByFamily.get(family) || 0) + 1);
    }

    if (!features.length || countsByFamily.size === 0) {
      this._removeLegend();
      return;
    }

    const legend = this._ensureLegend();
    const rows = [...countsByFamily.entries()]
      .sort((a, b) => {
        const orderA = FAMILY_KEYS.indexOf(a[0]);
        const orderB = FAMILY_KEYS.indexOf(b[0]);
        return (orderA === -1 ? 99 : orderA) - (orderB === -1 ? 99 : orderB);
      })
      .map(([family, count]) => {
        const meta = ALERT_FAMILIES[family] || ALERT_FAMILIES.other;
        return `<button type="button" data-family="${family}" title="Zoom to ${meta.label}" style="appearance:none;border:0;background:transparent;color:inherit;font:inherit;width:100%;display:flex;align-items:center;gap:7px;margin-top:5px;padding:3px 2px;border-radius:4px;cursor:pointer;text-align:left;">
          <span style="width:10px;height:10px;border-radius:50%;background:${meta.color};border:1px solid rgba(255,255,255,.8);display:inline-block;"></span>
          <span style="flex:1;">${meta.label}</span>
          <span style="color:#9ca3af;">${count}</span>
        </button>`;
      })
      .join('');

    legend.innerHTML = `<div style="font-weight:700;margin-bottom:4px;">NWS alerts</div>${rows}
      <div style="margin-top:8px;color:#9ca3af;font-size:11px;">Thicker outline = higher urgency/severity</div>`;
    this._bindLegendClicks(legend);
  },

  _ensureLegend() {
    if (this._legendEl?.isConnected) return this._legendEl;
    const legend = document.createElement('div');
    legend.id = LEGEND_ID;
    Object.assign(legend.style, {
      position: 'absolute',
      right: '14px',
      bottom: '88px',
      zIndex: '20',
      minWidth: '176px',
      maxWidth: '240px',
      padding: '10px 12px',
      borderRadius: '6px',
      background: 'rgba(12, 18, 32, 0.88)',
      color: '#f8fafc',
      boxShadow: '0 10px 24px rgba(0, 0, 0, 0.26)',
      border: '1px solid rgba(148, 163, 184, 0.28)',
      fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: '12px',
      lineHeight: '1.25',
      pointerEvents: 'auto',
    });
    const mapContainer = MapAdapter?.map?.getContainer?.();
    (mapContainer || document.body).appendChild(legend);
    this._legendEl = legend;
    return legend;
  },

  _bindLegendClicks(legend) {
    if (!legend || this._legendClickHandler) return;
    this._legendClickHandler = (event) => {
      const button = event.target?.closest?.('button[data-family]');
      if (!button) return;
      event.preventDefault();
      this._zoomToFamily(button.dataset.family);
    };
    legend.addEventListener('click', this._legendClickHandler);
  },

  _zoomToFamily(family) {
    const map = MapAdapter?.map;
    const targetFamily = String(family || '').trim();
    const features = Array.isArray(this.lastData?.features) ? this.lastData.features : [];
    if (!map || !targetFamily || !features.length) return;

    const bounds = this._boundsForFeatures(features.filter((feature) => {
      const props = feature?.properties || {};
      return String(props.alert_family || '').trim() === targetFamily;
    }));
    if (!bounds) return;

    const [[minLon, minLat], [maxLon, maxLat]] = bounds;
    if (minLon === maxLon && minLat === maxLat) {
      map.easeTo({ center: [minLon, minLat], zoom: Math.max(map.getZoom(), 7), duration: 650 });
      return;
    }
    map.fitBounds(bounds, {
      padding: { top: 96, bottom: 120, left: 80, right: 280 },
      maxZoom: 9,
      duration: 750,
    });
  },

  _boundsForFeatures(features) {
    let minLon = Infinity;
    let minLat = Infinity;
    let maxLon = -Infinity;
    let maxLat = -Infinity;

    const visit = (value) => {
      if (!Array.isArray(value)) return;
      if (value.length >= 2 && Number.isFinite(Number(value[0])) && Number.isFinite(Number(value[1]))) {
        const lon = Number(value[0]);
        const lat = Number(value[1]);
        minLon = Math.min(minLon, lon);
        minLat = Math.min(minLat, lat);
        maxLon = Math.max(maxLon, lon);
        maxLat = Math.max(maxLat, lat);
        return;
      }
      for (const child of value) visit(child);
    };

    for (const feature of features) {
      visit(feature?.geometry?.coordinates);
    }
    if (![minLon, minLat, maxLon, maxLat].every(Number.isFinite)) return null;
    return [[minLon, minLat], [maxLon, maxLat]];
  },

  _removeLegend() {
    if (this._legendEl) {
      if (this._legendClickHandler) {
        this._legendEl.removeEventListener('click', this._legendClickHandler);
        this._legendClickHandler = null;
      }
      this._legendEl.remove();
      this._legendEl = null;
    }
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
      for (const id of [FILL_ID, EXTREME_LINE_ID, LINE_ID, POINT_ID]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      if (map.getSource(SRC_ID)) map.removeSource(SRC_ID);
      if (this._popup) { this._popup.remove(); this._popup = null; }
      this._removeLegend();
    } catch (e) { /* style may be mid-reload; ignore */ }
  }
};

export default NwsAlertsOverlay;
