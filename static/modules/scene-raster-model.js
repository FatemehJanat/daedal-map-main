/**
 * Scene raster model for source-driven image overlays.
 */

let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

const SOURCE_ID = 'scene-raster-source';
const LAYER_ID = 'scene-raster-layer';

const DEFAULT_COLOR_STOPS = [
  [85, '#313695'],
  [93, '#4575b4'],
  [98, '#74add1'],
  [103, '#fee090'],
  [108, '#fdae61'],
  [113, '#f46d43'],
  [118, '#d73027'],
  [125, '#a50026'],
  [135, '#67001f'],
];

const DEFAULT_MIN_F = 90;
const DEFAULT_MAX_F = 130;
const DEFAULT_OPACITY = 0.75;

function hexToRgb(hex) {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result
    ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) }
    : { r: 128, g: 128, b: 128 };
}

function buildColorLUT(minF, maxF, stops) {
  const range = maxF - minF;
  const lut = new Array(256);

  for (let i = 0; i < 256; i += 1) {
    const value = minF + (i / 255) * range;

    let low = stops[0];
    let high = stops[stops.length - 1];
    for (let j = 0; j < stops.length - 1; j += 1) {
      if (value >= stops[j][0] && value <= stops[j + 1][0]) {
        low = stops[j];
        high = stops[j + 1];
        break;
      }
    }

    const t = high[0] === low[0] ? 0 : (value - low[0]) / (high[0] - low[0]);
    const lc = hexToRgb(low[1]);
    const hc = hexToRgb(high[1]);

    lut[i] = [
      Math.round(lc.r + t * (hc.r - lc.r)),
      Math.round(lc.g + t * (hc.g - lc.g)),
      Math.round(lc.b + t * (hc.b - lc.b)),
      210,
    ];
  }

  return lut;
}

export const SceneRasterModel = {
  pixels: null,
  width: 0,
  height: 0,
  bounds: null,
  period: null,
  sourceId: null,

  minF: DEFAULT_MIN_F,
  maxF: DEFAULT_MAX_F,
  opacity: DEFAULT_OPACITY,
  colorStops: DEFAULT_COLOR_STOPS,
  colorLUT: null,

  canvas: null,
  ctx: null,
  isVisible: false,
  displayMode: 'scene',
  clipEntries: [],

  async load(sourceId, period) {
    const { fetchMsgpack } = await import('./utils/fetch.js');

    let data;
    try {
      data = await fetchMsgpack(`/api/raster/${encodeURIComponent(sourceId)}/${encodeURIComponent(period)}`);
    } catch (err) {
      console.error('SceneRasterModel: fetch failed', err);
      return false;
    }

    if (!data || !data.pixels) {
      console.error('SceneRasterModel: empty response');
      return false;
    }

    const raw = data.pixels;
    const aligned = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
    this.pixels = new Float32Array(aligned);
    this.width = data.width;
    this.height = data.height;
    this.bounds = data.bounds;
    this.period = data.period;
    this.sourceId = data.source_id || sourceId;
    this.displayMode = 'scene';
    this._clearClipLayers();

    this._ensureCanvas();
    this._rebuildLUT();
    this._render();
    this._updateMapSource();

    return true;
  },

  setColorRange(minF, maxF) {
    this.minF = minF;
    this.maxF = maxF;
    if (this.pixels || (this.clipEntries && this.clipEntries.length)) {
      this._rebuildLUT();
      if (this.pixels) {
        this._render();
        this._updateMapSource();
      }
      for (const entry of this.clipEntries || []) {
        this._renderClipEntry(entry);
      }
      if (this.clipEntries?.length) {
        this._updateClipLayers();
      }
    }
  },

  setOpacity(opacity) {
    this.opacity = opacity;
    if (MapAdapter?.map?.getLayer(LAYER_ID)) {
      MapAdapter.map.setPaintProperty(LAYER_ID, 'raster-opacity', opacity);
    }
    for (const entry of this.clipEntries || []) {
      if (MapAdapter?.map?.getLayer(entry.layerId)) {
        MapAdapter.map.setPaintProperty(entry.layerId, 'raster-opacity', opacity);
      }
    }
  },

  show() {
    if (this.displayMode === 'clips') {
      for (const entry of this.clipEntries || []) {
        if (MapAdapter?.map?.getLayer(entry.layerId)) {
          MapAdapter.map.setLayoutProperty(entry.layerId, 'visibility', 'visible');
        }
      }
      this.isVisible = true;
      return;
    }
    if (!this.pixels) return;
    if (MapAdapter?.map?.getLayer(LAYER_ID)) {
      MapAdapter.map.setLayoutProperty(LAYER_ID, 'visibility', 'visible');
    }
    this.isVisible = true;
  },

  hide() {
    if (MapAdapter?.map?.getLayer(LAYER_ID)) {
      MapAdapter.map.setLayoutProperty(LAYER_ID, 'visibility', 'none');
    }
    for (const entry of this.clipEntries || []) {
      if (MapAdapter?.map?.getLayer(entry.layerId)) {
        MapAdapter.map.setLayoutProperty(entry.layerId, 'visibility', 'none');
      }
    }
    this.isVisible = false;
  },

  async loadClips(sourceId, payload) {
    const clips = payload?.clips || [];
    if (!clips.length) return false;

    this.displayMode = 'clips';
    this.period = payload?.period || this.period;
    this.sourceId = payload?.source_id || sourceId;
    this._clearClipLayers();
    if (MapAdapter?.map?.getLayer(LAYER_ID)) {
      MapAdapter.map.setLayoutProperty(LAYER_ID, 'visibility', 'none');
    }

    this._rebuildLUT();
    this.clipEntries = clips.map((clip, index) => {
      const raw = clip.pixels;
      const aligned = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
      const pixels = new Float32Array(aligned);
      const canvas = document.createElement('canvas');
      canvas.width = clip.width;
      canvas.height = clip.height;
      const ctx = canvas.getContext('2d');
      const entry = {
        locId: clip.loc_id,
        sourceId: `${SOURCE_ID}-clip-${index}`,
        layerId: `${LAYER_ID}-clip-${index}`,
        pixels,
        width: clip.width,
        height: clip.height,
        bounds: clip.bounds,
        canvas,
        ctx
      };
      this._renderClipEntry(entry);
      return entry;
    });
    this._updateClipLayers();
    this.isVisible = true;
    return true;
  },

  cleanup() {
    const map = MapAdapter?.map;
    if (map) {
      if (map.getLayer(LAYER_ID)) map.removeLayer(LAYER_ID);
      if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID);
    }
    this._clearClipLayers();
    this.pixels = null;
    this.canvas = null;
    this.ctx = null;
    this.bounds = null;
    this.period = null;
    this.sourceId = null;
    this.isVisible = false;
    this.displayMode = 'scene';
  },

  _ensureCanvas() {
    if (!this.canvas || this.canvas.width !== this.width || this.canvas.height !== this.height) {
      this.canvas = document.createElement('canvas');
      this.canvas.width = this.width;
      this.canvas.height = this.height;
      this.ctx = this.canvas.getContext('2d');
    }
  },

  _rebuildLUT() {
    this.colorLUT = buildColorLUT(this.minF, this.maxF, this.colorStops);
  },

  _render() {
    if (!this.pixels || !this.ctx || !this.colorLUT) return;

    const imageData = this.ctx.createImageData(this.width, this.height);
    const px = imageData.data;
    const lut = this.colorLUT;
    const minF = this.minF;
    const maxF = this.maxF;
    const range = maxF - minF;

    for (let i = 0; i < this.pixels.length; i += 1) {
      const val = this.pixels[i];
      const idx = i * 4;

      if (!val || val === 0) {
        px[idx] = px[idx + 1] = px[idx + 2] = px[idx + 3] = 0;
        continue;
      }

      const norm = Math.max(0, Math.min(1, (val - minF) / range));
      const lutIdx = Math.round(norm * 255);
      const color = lut[lutIdx];

      px[idx] = color[0];
      px[idx + 1] = color[1];
      px[idx + 2] = color[2];
      px[idx + 3] = color[3];
    }

    this.ctx.putImageData(imageData, 0, 0);
  },

  _renderClipEntry(entry) {
    if (!entry?.pixels || !entry?.ctx || !this.colorLUT) return;
    const imageData = entry.ctx.createImageData(entry.width, entry.height);
    const px = imageData.data;
    const lut = this.colorLUT;
    const minF = this.minF;
    const maxF = this.maxF;
    const range = maxF - minF;

    for (let i = 0; i < entry.pixels.length; i += 1) {
      const val = entry.pixels[i];
      const idx = i * 4;
      if (!val || val === 0) {
        px[idx] = px[idx + 1] = px[idx + 2] = px[idx + 3] = 0;
        continue;
      }
      const norm = Math.max(0, Math.min(1, (val - minF) / range));
      const lutIdx = Math.round(norm * 255);
      const color = lut[lutIdx];
      px[idx] = color[0];
      px[idx + 1] = color[1];
      px[idx + 2] = color[2];
      px[idx + 3] = color[3];
    }

    entry.ctx.putImageData(imageData, 0, 0);
  },

  _updateMapSource() {
    const map = MapAdapter?.map;
    if (!map || !this.bounds || !this.canvas) return;

    const { west, south, east, north } = this.bounds;
    const coordinates = [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ];

    const dataUrl = this.canvas.toDataURL('image/png');
    const existing = map.getSource(SOURCE_ID);

    if (existing) {
      existing.updateImage({ url: dataUrl, coordinates });
    } else {
      map.addSource(SOURCE_ID, { type: 'image', url: dataUrl, coordinates });

      let labelLayerId;
      for (const layer of map.getStyle().layers) {
        if (layer.type === 'symbol' && layer.layout?.['text-field']) {
          labelLayerId = layer.id;
          break;
        }
      }

      map.addLayer({
        id: LAYER_ID,
        type: 'raster',
        source: SOURCE_ID,
        paint: {
          'raster-opacity': this.opacity,
          'raster-fade-duration': 0,
        },
      }, labelLayerId);

      this.isVisible = true;
    }
  },

  _updateClipLayers() {
    const map = MapAdapter?.map;
    if (!map) return;

    let labelLayerId;
    for (const layer of map.getStyle().layers) {
      if (layer.type === 'symbol' && layer.layout?.['text-field']) {
        labelLayerId = layer.id;
        break;
      }
    }

    for (const entry of this.clipEntries || []) {
      const { west, south, east, north } = entry.bounds || {};
      if ([west, south, east, north].some((value) => !Number.isFinite(value))) continue;
      const coordinates = [
        [west, north],
        [east, north],
        [east, south],
        [west, south],
      ];
      const dataUrl = entry.canvas.toDataURL('image/png');
      const existing = map.getSource(entry.sourceId);
      if (existing) {
        existing.updateImage({ url: dataUrl, coordinates });
      } else {
        map.addSource(entry.sourceId, { type: 'image', url: dataUrl, coordinates });
        map.addLayer({
          id: entry.layerId,
          type: 'raster',
          source: entry.sourceId,
          paint: {
            'raster-opacity': this.opacity,
            'raster-fade-duration': 0,
          },
        }, labelLayerId);
      }
    }
  },

  _clearClipLayers() {
    const map = MapAdapter?.map;
    if (map) {
      for (const entry of this.clipEntries || []) {
        if (map.getLayer(entry.layerId)) map.removeLayer(entry.layerId);
        if (map.getSource(entry.sourceId)) map.removeSource(entry.sourceId);
      }
    }
    this.clipEntries = [];
  },
};
