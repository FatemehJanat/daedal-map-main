/**
 * Ocean Raster Model - animated SST basin raster overlays.
 *
 * Loads a per-basin "clip bundle" (one msgpack per ocean basin, with the whole
 * monthly time series stacked as frames) from /api/raster/<source>/clip-bundle/<basin>,
 * and animates it on the time slider. Reuses the scene-raster rendering pattern
 * (Float32 pixels -> colormap LUT -> canvas -> MapLibre image source at bounds),
 * adds frame swapping over time, and treats NaN as nodata (0 C is a valid SST).
 *
 * Antimeridian basins (Pacific) just carry a wide -180..180 bbox with the other
 * oceans as a transparent gap; no special longitude frame.
 * See county-map-private/docs/CLIMATE_DISPLAY.md (Ocean SST Grid Animation).
 */

let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

const DEFAULT_OPACITY = 0.4;

function hexToRgb(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return m
    ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) }
    : { r: 128, g: 128, b: 128 };
}

/** Build a 256-entry RGBA LUT from {min, max, stops:[[value,hex],...]}. */
function buildColorLUT(scale) {
  const stops = scale?.stops || [[-2, '#2b2c7f'], [36, '#7f0000']];
  const min = scale?.min ?? stops[0][0];
  const max = scale?.max ?? stops[stops.length - 1][0];
  const range = max - min || 1;
  const lut = new Array(256);
  for (let i = 0; i < 256; i += 1) {
    const value = min + (i / 255) * range;
    let lo = stops[0];
    let hi = stops[stops.length - 1];
    for (let j = 0; j < stops.length - 1; j += 1) {
      if (value >= stops[j][0] && value <= stops[j + 1][0]) {
        lo = stops[j]; hi = stops[j + 1]; break;
      }
    }
    const t = hi[0] === lo[0] ? 0 : (value - lo[0]) / (hi[0] - lo[0]);
    const lc = hexToRgb(lo[1]);
    const hc = hexToRgb(hi[1]);
    lut[i] = [
      Math.round(lc.r + t * (hc.r - lc.r)),
      Math.round(lc.g + t * (hc.g - lc.g)),
      Math.round(lc.b + t * (hc.b - lc.b)),
    ];
  }
  return { lut, min, max };
}

function bytesToFloat32(bytes) {
  // msgpack bin -> aligned Float32Array
  const aligned = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  return new Float32Array(aligned);
}

class OceanBasinLayer {
  constructor(overlayId, locId, index) {
    this.locId = locId;
    this.sourceId = `ocean-raster-${overlayId}-${locId}`;
    this.layerId = `ocean-raster-layer-${overlayId}-${locId}`;
    this.width = 0;
    this.height = 0;
    this.bounds = null;
    this.timestamps = [];
    this.framesByVar = {};   // { sst_c: [Float32Array, ...] }
    this.colorScales = {};
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d');
    this.added = false;
    this.lastFrameIndex = -1;
  }
}

export const OceanRasterModel = {
  instances: new Map(),   // overlayId -> { variable, opacity, basins: [OceanBasinLayer], timestamps }

  hasInstance(overlayId) {
    return this.instances.has(overlayId);
  },

  getTimestampRange(overlayId) {
    const inst = this.instances.get(overlayId);
    if (!inst || !inst.timestamps.length) return null;
    return { min: inst.timestamps[0], max: inst.timestamps[inst.timestamps.length - 1] };
  },

  getTimestamps(overlayId) {
    return this.instances.get(overlayId)?.timestamps || [];
  },

  getVariable(overlayId) {
    return this.instances.get(overlayId)?.variable || null;
  },

  getOpacity(overlayId) {
    return this.instances.get(overlayId)?.opacity ?? DEFAULT_OPACITY;
  },

  getVariables(overlayId) {
    const inst = this.instances.get(overlayId);
    if (!inst) return [];
    const set = new Set();
    for (const layer of inst.basins) {
      for (const v of Object.keys(layer.framesByVar)) set.add(v);
    }
    return Array.from(set);
  },

  getColorScale(overlayId, variable) {
    const inst = this.instances.get(overlayId);
    if (!inst) return null;
    const v = variable || inst.variable;
    for (const layer of inst.basins) {
      if (layer.colorScales?.[v]) return layer.colorScales[v];
    }
    return null;
  },

  /**
   * Load one or more basin bundles for an overlay and render the latest frame.
   * @param {string} overlayId
   * @param {string} sourceId - e.g. "ocean_sst"
   * @param {string[]} basinIds - e.g. ["XOP"]
   * @param {string} variable - "sst_c" | "sst_anom_c"
   */
  async load(overlayId, sourceId, basinIds, variable = 'sst_c') {
    const { fetchMsgpack } = await import('../utils/fetch.js');
    const inst = { variable, opacity: DEFAULT_OPACITY, basins: [], timestamps: [] };

    for (let i = 0; i < basinIds.length; i += 1) {
      const locId = basinIds[i];
      let bundle;
      try {
        bundle = await fetchMsgpack(`/api/raster/${encodeURIComponent(sourceId)}/clip-bundle/${encodeURIComponent(locId)}`);
      } catch (err) {
        console.warn('OceanRasterModel: bundle fetch failed', locId, err);
        continue;
      }
      if (!bundle || !bundle.frames || !bundle.timestamps) continue;

      const layer = new OceanBasinLayer(overlayId, locId, i);
      layer.width = bundle.width;
      layer.height = bundle.height;
      layer.bounds = bundle.bounds;
      layer.timestamps = bundle.timestamps;
      layer.colorScales = bundle.color_scales || {};
      layer.canvas.width = bundle.width;
      layer.canvas.height = bundle.height;
      const vars = bundle.variables || [variable];
      for (const v of vars) {
        const blobs = bundle.frames[v];
        if (Array.isArray(blobs)) {
          layer.framesByVar[v] = blobs.map(bytesToFloat32);
        }
      }
      inst.basins.push(layer);
      if (layer.timestamps.length > inst.timestamps.length) {
        inst.timestamps = layer.timestamps;
      }
    }

    if (!inst.basins.length) {
      console.error('OceanRasterModel: no basins loaded for', overlayId);
      return false;
    }

    this.instances.set(overlayId, inst);
    // Render the most recent frame by default.
    this.renderAtTimestamp(overlayId, inst.timestamps[inst.timestamps.length - 1]);
    return true;
  },

  _frameIndexForTime(layer, timeMs) {
    const ts = layer.timestamps;
    if (!ts.length) return -1;
    if (timeMs <= ts[0]) return 0;
    if (timeMs >= ts[ts.length - 1]) return ts.length - 1;
    // largest index with ts[i] <= timeMs
    let lo = 0;
    let hi = ts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (ts[mid] <= timeMs) lo = mid; else hi = mid - 1;
    }
    return lo;
  },

  renderAtTimestamp(overlayId, timeMs) {
    const inst = this.instances.get(overlayId);
    if (!inst) return;
    for (const layer of inst.basins) {
      const idx = this._frameIndexForTime(layer, timeMs);
      if (idx < 0) continue;
      const frames = layer.framesByVar[inst.variable];
      if (!frames || !frames[idx]) continue;
      if (idx === layer.lastFrameIndex) continue;
      layer.lastFrameIndex = idx;
      this._renderFrame(layer, frames[idx], inst);
      this._placeLayer(layer, inst.opacity);
    }
  },

  _renderFrame(layer, pixels, inst) {
    const scale = layer.colorScales[inst.variable];
    const { lut, min, max } = buildColorLUT(scale);
    const range = (max - min) || 1;
    const img = layer.ctx.createImageData(layer.width, layer.height);
    const px = img.data;
    for (let i = 0; i < pixels.length; i += 1) {
      const v = pixels[i];
      const idx = i * 4;
      if (Number.isNaN(v)) {
        px[idx] = px[idx + 1] = px[idx + 2] = px[idx + 3] = 0;
        continue;
      }
      const norm = Math.max(0, Math.min(1, (v - min) / range));
      const c = lut[Math.round(norm * 255)];
      // Opaque pixels; the MapLibre raster-opacity (set per overlay) controls the
      // overall blend so the opacity slider works cleanly.
      px[idx] = c[0]; px[idx + 1] = c[1]; px[idx + 2] = c[2]; px[idx + 3] = 255;
    }
    layer.ctx.putImageData(img, 0, 0);
  },

  _placeLayer(layer, opacity) {
    const map = MapAdapter?.map;
    if (!map || !layer.bounds) return;
    const { west, south, east, north } = layer.bounds;
    const coordinates = [[west, north], [east, north], [east, south], [west, south]];
    const dataUrl = layer.canvas.toDataURL('image/png');
    const existing = map.getSource(layer.sourceId);
    if (existing) {
      existing.updateImage({ url: dataUrl, coordinates });
      return;
    }
    let labelLayerId;
    for (const l of map.getStyle().layers) {
      if (l.type === 'symbol' && l.layout?.['text-field']) { labelLayerId = l.id; break; }
    }
    map.addSource(layer.sourceId, { type: 'image', url: dataUrl, coordinates });
    map.addLayer({
      id: layer.layerId,
      type: 'raster',
      source: layer.sourceId,
      paint: { 'raster-opacity': opacity, 'raster-fade-duration': 0, 'raster-resampling': 'linear' },
    }, labelLayerId);
    layer.added = true;
  },

  setVariable(overlayId, variable) {
    const inst = this.instances.get(overlayId);
    if (!inst || inst.variable === variable) return;
    inst.variable = variable;
    for (const layer of inst.basins) layer.lastFrameIndex = -1;
  },

  setOpacity(overlayId, opacity) {
    const inst = this.instances.get(overlayId);
    if (!inst) return;
    inst.opacity = opacity;
    const map = MapAdapter?.map;
    for (const layer of inst.basins) {
      if (map?.getLayer(layer.layerId)) map.setPaintProperty(layer.layerId, 'raster-opacity', opacity);
    }
  },

  show(overlayId) {
    const map = MapAdapter?.map;
    const inst = this.instances.get(overlayId);
    if (!map || !inst) return;
    for (const layer of inst.basins) {
      if (map.getLayer(layer.layerId)) map.setLayoutProperty(layer.layerId, 'visibility', 'visible');
    }
  },

  hide(overlayId) {
    const map = MapAdapter?.map;
    const inst = this.instances.get(overlayId);
    if (!map || !inst) return;
    for (const layer of inst.basins) {
      if (map.getLayer(layer.layerId)) map.setLayoutProperty(layer.layerId, 'visibility', 'none');
    }
  },

  cleanup(overlayId) {
    const map = MapAdapter?.map;
    const inst = this.instances.get(overlayId);
    if (inst && map) {
      for (const layer of inst.basins) {
        if (map.getLayer(layer.layerId)) map.removeLayer(layer.layerId);
        if (map.getSource(layer.sourceId)) map.removeSource(layer.sourceId);
      }
    }
    this.instances.delete(overlayId);
  },
};
