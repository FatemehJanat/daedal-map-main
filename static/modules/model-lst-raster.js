/**
 * LST Raster Model - Renders Fairfax land surface temperature as a raster image layer.
 *
 * Same canvas-to-MapLibre-image-source pattern as model-weather-grid.js, but
 * scoped to a county bounding box instead of global bounds.
 *
 * Data flow:
 *   1. Fetch pixel array + bounds from /api/fairfax/raster/{period}
 *   2. Build a 256-entry color LUT from configurable min/max Fahrenheit range
 *   3. Render float32 pixels to an HTML canvas using the LUT (nodata=0 -> transparent)
 *   4. Add canvas as a MapLibre image source using the county bounds
 *   5. On colormap change: rebuild LUT and re-render (no network request)
 *   6. On scene change: fetch new period, re-render
 */

let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

const SOURCE_ID = 'fairfax-lst-raster-source';
const LAYER_ID  = 'fairfax-lst-raster-layer';

// Default color stops (value in Fahrenheit -> hex color)
// Runs from cool blue at 85F through yellow/orange to dark red at 135F+
const DEFAULT_COLOR_STOPS = [
  [85,  '#313695'],
  [93,  '#4575b4'],
  [98,  '#74add1'],
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

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

function hexToRgb(hex) {
  const r = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return r ? { r: parseInt(r[1], 16), g: parseInt(r[2], 16), b: parseInt(r[3], 16) }
           : { r: 128, g: 128, b: 128 };
}

function buildColorLUT(minF, maxF, stops) {
  const range = maxF - minF;
  const lut = new Array(256);

  for (let i = 0; i < 256; i++) {
    const value = minF + (i / 255) * range;

    let low  = stops[0];
    let high = stops[stops.length - 1];
    for (let j = 0; j < stops.length - 1; j++) {
      if (value >= stops[j][0] && value <= stops[j + 1][0]) {
        low  = stops[j];
        high = stops[j + 1];
        break;
      }
    }

    const t  = high[0] === low[0] ? 0 : (value - low[0]) / (high[0] - low[0]);
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

// -------------------------------------------------------------------------
// LstRasterModel
// -------------------------------------------------------------------------

export const LstRasterModel = {
  // Raw data (kept in memory so colormap changes don't need a re-fetch)
  pixels:  null,   // Float32Array
  width:   0,
  height:  0,
  bounds:  null,   // { west, south, east, north }
  period:  null,

  // Render state
  minF:    DEFAULT_MIN_F,
  maxF:    DEFAULT_MAX_F,
  opacity: DEFAULT_OPACITY,
  colorStops: DEFAULT_COLOR_STOPS,
  colorLUT: null,

  canvas:  null,
  ctx:     null,
  isVisible: false,

  // -----------------------------------------------------------------------
  // Load a scene from the backend
  // -----------------------------------------------------------------------

  async load(period) {
    const { fetchMsgpack } = await import('./utils/fetch.js');

    console.log(`LstRasterModel: loading period ${period}`);

    let data;
    try {
      data = await fetchMsgpack(`/api/fairfax/raster/${encodeURIComponent(period)}`);
    } catch (err) {
      console.error('LstRasterModel: fetch failed', err);
      return false;
    }

    if (!data || !data.pixels) {
      console.error('LstRasterModel: empty response');
      return false;
    }

    // msgpack bytes field arrives as Uint8Array - reinterpret as Float32Array.
    // slice() creates an aligned copy so the Float32Array constructor does not
    // throw a RangeError when the Uint8Array view has a non-4-byte byteOffset.
    const raw = data.pixels;
    const aligned = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
    this.pixels = new Float32Array(aligned);
    this.width  = data.width;
    this.height = data.height;
    this.bounds = data.bounds;
    this.period = data.period;

    console.log(`LstRasterModel: loaded ${this.width}x${this.height} pixels for ${period}`);

    this._ensureCanvas();
    this._rebuildLUT();
    this._render();
    this._updateMapSource();

    return true;
  },

  // -----------------------------------------------------------------------
  // Color range control - re-render without re-fetching
  // -----------------------------------------------------------------------

  setColorRange(minF, maxF) {
    this.minF = minF;
    this.maxF = maxF;
    if (this.pixels) {
      this._rebuildLUT();
      this._render();
      this._updateMapSource();
    }
  },

  setOpacity(opacity) {
    this.opacity = opacity;
    if (MapAdapter?.map?.getLayer(LAYER_ID)) {
      MapAdapter.map.setPaintProperty(LAYER_ID, 'raster-opacity', opacity);
    }
  },

  // -----------------------------------------------------------------------
  // Show / hide
  // -----------------------------------------------------------------------

  show() {
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
    this.isVisible = false;
  },

  cleanup() {
    const map = MapAdapter?.map;
    if (map) {
      if (map.getLayer(LAYER_ID))  map.removeLayer(LAYER_ID);
      if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID);
    }
    this.pixels  = null;
    this.canvas  = null;
    this.ctx     = null;
    this.isVisible = false;
    console.log('LstRasterModel: cleaned up');
  },

  // -----------------------------------------------------------------------
  // Internal
  // -----------------------------------------------------------------------

  _ensureCanvas() {
    if (!this.canvas || this.canvas.width !== this.width || this.canvas.height !== this.height) {
      this.canvas = document.createElement('canvas');
      this.canvas.width  = this.width;
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

    for (let i = 0; i < this.pixels.length; i++) {
      const val = this.pixels[i];
      const idx = i * 4;

      if (!val || val === 0) {
        // nodata - transparent
        px[idx] = px[idx+1] = px[idx+2] = px[idx+3] = 0;
        continue;
      }

      const norm   = Math.max(0, Math.min(1, (val - minF) / range));
      const lutIdx = Math.round(norm * 255);
      const color  = lut[lutIdx];

      px[idx]   = color[0];
      px[idx+1] = color[1];
      px[idx+2] = color[2];
      px[idx+3] = color[3];
    }

    this.ctx.putImageData(imageData, 0, 0);
  },

  _updateMapSource() {
    const map = MapAdapter?.map;
    if (!map || !this.bounds || !this.canvas) return;

    const { west, south, east, north } = this.bounds;
    const coordinates = [
      [west,  north],
      [east,  north],
      [east,  south],
      [west,  south],
    ];

    const dataUrl = this.canvas.toDataURL('image/png');
    const existing = map.getSource(SOURCE_ID);

    if (existing) {
      existing.updateImage({ url: dataUrl, coordinates });
    } else {
      map.addSource(SOURCE_ID, { type: 'image', url: dataUrl, coordinates });

      // Insert below the first symbol/label layer so labels stay on top
      let labelLayerId;
      for (const layer of map.getStyle().layers) {
        if (layer.type === 'symbol' && layer.layout?.['text-field']) {
          labelLayerId = layer.id;
          break;
        }
      }

      map.addLayer({
        id:     LAYER_ID,
        type:   'raster',
        source: SOURCE_ID,
        paint: {
          'raster-opacity':       this.opacity,
          'raster-fade-duration': 0,
        },
      }, labelLayerId);

      this.isVisible = true;
      console.log('LstRasterModel: map layer created');
    }
  },
};
