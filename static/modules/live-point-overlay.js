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
const POLLUTANT_LABELS = { pm25: 'PM2.5', pm10: 'PM10', o3: 'O₃', no2: 'NO₂', so2: 'SO₂', co: 'CO' };

// Build a MapLibre data-driven color expression from {prop, stops, nullColor}.
function colorExpression(colorBy) {
  if (colorBy?.directProp) return ['coalesce', ['get', colorBy.directProp], colorBy.nullColor || '#9aa4bf'];
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
    _viewportRefreshTimer: null,
    _moveendHandler: null,

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
        if (config.viewportQuery) {
          this._moveendHandler = () => {
            if (!this.enabled) return;
            clearTimeout(this._viewportRefreshTimer);
            this._viewportRefreshTimer = setTimeout(() => this._refresh(), 150);
          };
          map.on('moveend', this._moveendHandler);
        }
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
      clearTimeout(this._viewportRefreshTimer);
      this._viewportRefreshTimer = null;
    },

    async _refresh() {
      if (!this.enabled) return;
      try {
        let endpoint = config.endpoint;
        const map = this.MapAdapter?.map;
        if (config.viewportQuery && map) {
          const bounds = map.getBounds();
          endpoint = `${config.endpoint}?bbox=${[bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(',')}&zoom=${encodeURIComponent(map.getZoom().toFixed(2))}`;
        }
        if (config.wipOnly) {
          const joiner = endpoint.includes('?') ? '&' : '?';
          endpoint = `${endpoint}${joiner}catalog_surface=wip&catalog_lane=ops`;
        }
        const data = await fetchMsgpack(endpoint);
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
          'circle-opacity': config.hideCircleForSource
            ? ['case', ['==', ['get', 'source_label'], config.hideCircleForSource], 0, 0.92]
            : 0.92,
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
          ...(config.icon.filter ? { filter: config.icon.filter } : {}),
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
      if (field?.format === 'datetime') {
        const parsed = new Date(value);
        if (!Number.isNaN(parsed.getTime())) {
          return new Intl.DateTimeFormat(undefined, {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
          }).format(parsed);
        }
      }
      if (field?.format === 'measurements' && Array.isArray(value)) {
        return value.map((item) => `${item.parameter || 'unknown'}: ${item.value ?? '?'} ${item.unit || ''}`.trim()).join(' · ');
      }
      if (Array.isArray(value)) return value.map((item) => typeof item === 'string' ? item : (item?.name || item?.id || '')).filter(Boolean).join(', ');
      if (typeof value === 'object') return value.name || value.id || null;
      if (typeof value === 'number' && Number.isFinite(field?.digits)) {
        return value.toFixed(field.digits);
      }
      return String(value);
    },

    _measurementItems(value) {
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (_) { return []; }
      }
      return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
    },

    _bindPopup(map) {
      if (this._clickBound) return;
      const esc = (v) => String(v == null ? '' : v).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      this._popupHandler = (e) => {
        const f = e.features && e.features[0];
        if (!f) return;
        const p = f.properties || {};
        const titleVal = config.popup?.titleProp ? p[config.popup.titleProp] : '';
        const renderRows = (fields) => (fields || []).map((field) => {
          if (field.format === 'measurementRows') {
            const measurements = this._measurementItems(p[field.prop]);
            return measurements.map((item) => {
              const parameter = POLLUTANT_LABELS[String(item.parameter || '').toLowerCase()] || String(item.parameter || 'Unknown');
              const value = item.value ?? '?';
              const unit = item.unit ? ` ${item.unit}` : '';
              return `<div><span style="color:#888">${esc(parameter)}:</span> ${esc(value)}${esc(unit)}</div>`;
            }).join('');
          }
          const shown = this._fmt(p[field.prop], field);
          if (shown == null) return '';
          const unit = field.unit ? ` ${esc(field.unit)}` : '';
          return `<div><span style="color:#888">${esc(field.label)}:</span> ${esc(shown)}${unit}</div>`;
        }).join('');
        const tabs = Array.isArray(config.popup?.tabs) && config.popup.tabs.length
          ? config.popup.tabs : [{ id: 'details', label: 'Details', fields: config.popup?.fields || [] }];
        const rootId = `lpo-popup-${config.id}`;
        const headerRows = renderRows(config.popup?.headerFields || []);
        const detailButtonHtml = (config.popup?.detailEndpoint && p.location_id && !p.is_cluster)
          ? `<button type="button" data-live-detail style="margin-top:7px;border:1px solid #475569;border-radius:3px;background:#1e293b;color:#e5f0ff;padding:3px 6px;cursor:pointer;font:inherit;font-size:11px">Load full station details</button><div data-live-detail-result style="margin-top:5px"></div>`
          : '';
        const tabHtml = tabs.length > 1 ? `
          <div style="display:flex;gap:4px;margin:7px 0 6px;border-bottom:1px solid #334155">
            ${tabs.map((tab, index) => `<button type="button" data-live-tab="${esc(tab.id)}" style="border:0;border-bottom:2px solid ${index === 0 ? '#60a5fa' : 'transparent'};background:transparent;color:${index === 0 ? '#e5f0ff' : '#9aa4bf'};padding:3px 5px;cursor:pointer;font:inherit;font-size:11px">${esc(tab.label)}</button>`).join('')}
          </div>
          ${tabs.map((tab, index) => `<div data-live-panel="${esc(tab.id)}" style="display:${index === 0 ? 'block' : 'none'}">${renderRows(tab.fields)}${tab.id === 'data' ? detailButtonHtml : ''}</div>`).join('')}`
          : renderRows(tabs[0].fields);
        const html = `<div class="live-point-popup" data-live-popup="${esc(rootId)}" style="font-family:monospace;font-size:12px;max-width:260px">
          ${titleVal ? `<div style="font-weight:bold">${esc(config.popup.titlePrefix || '')}${esc(titleVal)}</div>` : ''}
          ${headerRows ? `<div style="margin-top:3px;color:#cbd5e1">${headerRows}</div>` : ''}
          ${tabHtml}
          ${(config.popup?.noticeBySource?.[p.source_label] || config.popup?.notice) ? `<div style="margin-top:6px;color:#9aa4bf;font-size:11px">${esc(config.popup?.noticeBySource?.[p.source_label] || config.popup.notice)}</div>` : ''}
          ${(config.popup?.sourceUrl || (config.popup?.sourceUrlProp && p[config.popup.sourceUrlProp])) ? `<div style="margin-top:4px;font-size:11px"><a href="${esc(p[config.popup?.sourceUrlProp] || config.popup.sourceUrl)}" target="_blank" rel="noopener">Source</a></div>` : ''}
        </div>`;
        // Live points participate in the one shared popup contract. This keeps
        // a buoy click above the point/raster inspector rather than opening a
        // second independent MapLibre popup.
        this.MapAdapter?.registerFeaturePopupClick?.();
        this.MapAdapter?.showPopup?.([e.lngLat.lng, e.lngLat.lat], html);
        if (tabs.length > 1) {
          setTimeout(() => {
            const root = document.querySelector(`[data-live-popup="${rootId}"]`);
            if (!root) return;
            root.querySelectorAll('[data-live-tab]').forEach((button) => button.addEventListener('click', () => {
              const selected = button.dataset.liveTab;
              root.querySelectorAll('[data-live-panel]').forEach((panel) => {
                panel.style.display = panel.dataset.livePanel === selected ? 'block' : 'none';
              });
              root.querySelectorAll('[data-live-tab]').forEach((tab) => {
                const active = tab.dataset.liveTab === selected;
                tab.style.borderBottomColor = active ? '#60a5fa' : 'transparent';
                tab.style.color = active ? '#e5f0ff' : '#9aa4bf';
              });
            }));
            const detailButton = root.querySelector('[data-live-detail]');
            detailButton?.addEventListener('click', async () => {
              detailButton.disabled = true;
              detailButton.textContent = 'Loading station details…';
              try {
                const detail = await fetchMsgpack(`${config.popup.detailEndpoint}/${encodeURIComponent(p.location_id)}?catalog_surface=wip&catalog_lane=ops`);
                const result = root.querySelector('[data-live-detail-result]');
                if (result && detail && typeof detail === 'object') {
                  const readingHtml = this._measurementItems(detail.measurements).map((item) => {
                    const parameter = POLLUTANT_LABELS[String(item.parameter || '').toLowerCase()] || String(item.parameter || 'Unknown');
                    return `${esc(parameter)}: ${esc(item.value ?? '?')}${item.unit ? ` ${esc(item.unit)}` : ''}`;
                  }).join('<br>') || 'No current readings returned';
                  const stationText = [this._fmt(detail.provider), this._fmt(detail.owner), this._fmt(detail.license)].filter(Boolean).map(esc).join(' · ');
                  result.innerHTML = `<div style="color:#cbd5e1;font-size:11px"><strong>Full source readings</strong><br>${readingHtml}${stationText ? `<br><span style="color:#9aa4bf">${stationText}</span>` : ''}</div>`;
                  detailButton.textContent = 'Station details loaded';
                }
              } catch (err) {
                detailButton.textContent = 'Details unavailable';
                console.warn(`LivePointOverlay[${config.id}]: station details failed`, err);
              }
            });
          }, 0);
        }
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

const AIR_MONITOR_PIN_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 34">
  <path d="M14 2.5 C7.7 2.5 4 7.2 4 12.8 C4 20.2 14 31.3 14 31.3 C14 31.3 24 20.2 24 12.8 C24 7.2 20.3 2.5 14 2.5Z" fill="#6a5acd" stroke="#ffffff" stroke-width="1.8"/>
  <circle cx="14" cy="12.7" r="4.2" fill="#e9e4ff"/>
  <path d="M10.6 12.7 H17.4 M14 9.3 V16.1" stroke="#6a5acd" stroke-width="1.4" stroke-linecap="round"/>
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

const AIRNOW_CONFIG = {
  id: 'airnow', feedId: 'airnow', endpoint: '/api/ops/points/airnow',
  colorBy: { prop: 'aqi', stops: [[0, '#00e400'], [51, '#ffff00'], [101, '#ff7e00'], [151, '#ff0000'], [201, '#8f3f97'], [301, '#7e0023']], nullColor: '#9aa4bf' },
  popup: {
    titleProp: 'reporting_area',
    fields: [
      { label: 'State / province', prop: 'state' }, { label: 'Pollutant', prop: 'parameter' },
      { label: 'AQI', prop: 'aqi', digits: 0 }, { label: 'Category', prop: 'category' },
      { label: 'Observed', prop: 'observed_at' }, { label: 'Reporting agency', prop: 'agency' },
    ],
    notice: 'Preliminary AirNow conditions; subject to change. Not regulatory or trend data.',
    sourceUrl: 'https://www.airnow.gov/',
  },
};

const AIR_QUALITY_STATIONS_CONFIG = {
  id: 'air_quality_stations', feedId: 'air_quality_stations', endpoint: '/api/ops/points/air_quality_stations',
  viewportQuery: true,
  wipOnly: true,
  colorBy: { directProp: 'marker_color', nullColor: '#9aa4bf' },
  hideCircleForSource: 'OpenAQ',
  icon: { svg: AIR_MONITOR_PIN_SVG, pixelSize: [36, 44], minzoom: 0, size: ['interpolate', ['linear'], ['zoom'], 0, 0.45, 5, 0.7, 9, 0.9], filter: ['==', ['get', 'source_label'], 'OpenAQ'] },
  popup: {
    titleProp: 'station_name',
    headerFields: [{ label: 'Last updated', prop: 'observed_at', format: 'datetime' }],
    tabs: [
      { id: 'station', label: 'Station info', fields: [
        { label: 'Source', prop: 'source_label' }, { label: 'Type', prop: 'station_kind' },
        { label: 'Locality', prop: 'locality' }, { label: 'Country', prop: 'country' },
        { label: 'Provider / agency', prop: 'provider' }, { label: 'Owner', prop: 'owner' },
        { label: 'Licence', prop: 'license' }, { label: 'Licence status', prop: 'license_status' },
        { label: 'Attribution', prop: 'attribution' },
      ] },
      { id: 'data', label: 'Data', fields: [
        { prop: 'measurements', format: 'measurementRows' },
        { label: 'AQI', prop: 'value', digits: 0 }, { label: 'AQI category', prop: 'category' },
      ] },
    ],
    noticeBySource: {
      AirNow: 'Preliminary AirNow conditions; subject to change. Not regulatory or trend data.',
      OpenAQ: 'OpenAQ shows source-native readings for six core pollutants, not global AQI.',
    },
    detailEndpoint: '/api/ops/openaq/stations',
    sourceUrlProp: 'source_url',
  },
};

// Registry of live point overlays. Add a config here (+ a backend POINT_FEEDS
// entry) to surface a new station/sensor feed.
export const LIVE_POINT_OVERLAYS = {
  buoys: createLivePointOverlay(BUOYS_CONFIG),
  airnow: createLivePointOverlay(AIRNOW_CONFIG),
  air_quality_stations: createLivePointOverlay(AIR_QUALITY_STATIONS_CONFIG),
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
