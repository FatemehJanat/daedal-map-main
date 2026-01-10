/**
 * Track Model - Renders storm tracks with line paths and position markers.
 * Used for: Hurricanes, Typhoons, Cyclones
 *
 * Display characteristics:
 * - Line paths showing storm trajectory
 * - Point markers at track positions
 * - Category-based color coding (Saffir-Simpson)
 * - Optional animated current position marker
 * - Storm name labels
 */

import { CONFIG } from '../config.js';

// Dependencies set via setDependencies
let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

export const TrackModel = {
  // Currently active track ID
  activeTrackId: null,

  // Click handler reference for cleanup
  clickHandler: null,

  /**
   * Build category color expression for MapLibre.
   * @private
   * @returns {Array} MapLibre match expression
   */
  _buildCategoryColorExpr() {
    return [
      'match',
      ['coalesce', ['get', 'category'], ['get', 'max_category']],
      'TD', CONFIG.hurricaneColors.TD,
      'TS', CONFIG.hurricaneColors.TS,
      '1', CONFIG.hurricaneColors['1'],
      '2', CONFIG.hurricaneColors['2'],
      '3', CONFIG.hurricaneColors['3'],
      '4', CONFIG.hurricaneColors['4'],
      '5', CONFIG.hurricaneColors['5'],
      1, CONFIG.hurricaneColors['1'],
      2, CONFIG.hurricaneColors['2'],
      3, CONFIG.hurricaneColors['3'],
      4, CONFIG.hurricaneColors['4'],
      5, CONFIG.hurricaneColors['5'],
      CONFIG.hurricaneColors.default
    ];
  },

  /**
   * Render hurricane/storm point markers onto the map.
   * Used for overview display of multiple storms.
   * @param {Object} geojson - GeoJSON FeatureCollection with Point features
   * @param {string} eventType - 'hurricane', 'typhoon', 'cyclone'
   * @param {Object} options - {onStormClick: callback(stormId, stormName)}
   */
  render(geojson, eventType = 'hurricane', options = {}) {
    if (!MapAdapter?.map) {
      console.warn('TrackModel: MapAdapter not available');
      return;
    }

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      console.log('TrackModel: No features to display');
      return;
    }

    // Clear existing layers
    this.clearMarkers();

    const map = MapAdapter.map;
    const categoryColorExpr = this._buildCategoryColorExpr();

    // Add hurricane source
    map.addSource(CONFIG.layers.hurricaneSource, {
      type: 'geojson',
      data: geojson
    });

    // Add outer glow
    map.addLayer({
      id: CONFIG.layers.hurricaneCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.hurricaneSource,
      paint: {
        'circle-radius': 14,
        'circle-color': categoryColorExpr,
        'circle-opacity': 0.3,
        'circle-blur': 1
      }
    });

    // Add main circle
    map.addLayer({
      id: CONFIG.layers.hurricaneCircle,
      type: 'circle',
      source: CONFIG.layers.hurricaneSource,
      paint: {
        'circle-radius': 8,
        'circle-color': categoryColorExpr,
        'circle-opacity': 0.9,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 2
      }
    });

    // Add labels for storm names
    map.addLayer({
      id: CONFIG.layers.hurricaneLabel,
      type: 'symbol',
      source: CONFIG.layers.hurricaneSource,
      minzoom: 4,
      layout: {
        'text-field': ['coalesce', ['get', 'name'], ['get', 'storm_name']],
        'text-size': 11,
        'text-offset': [0, 1.8],
        'text-anchor': 'top',
        'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold']
      },
      paint: {
        'text-color': '#ffffff',
        'text-halo-color': 'rgba(0, 0, 0, 0.8)',
        'text-halo-width': 2
      }
    });

    // Setup click handler
    if (options.onStormClick) {
      this.clickHandler = (e) => {
        if (e.features.length > 0) {
          const props = e.features[0].properties;
          const stormId = props.storm_id || props.id;
          const stormName = props.name || props.storm_name || stormId;
          options.onStormClick(stormId, stormName);
        }
      };
      map.on('click', CONFIG.layers.hurricaneCircle, this.clickHandler);
    }

    // Hover cursor
    map.on('mouseenter', CONFIG.layers.hurricaneCircle, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', CONFIG.layers.hurricaneCircle, () => {
      map.getCanvas().style.cursor = '';
    });

    console.log(`TrackModel: Loaded ${geojson.features.length} ${eventType} markers`);
  },

  /**
   * Render a storm track (line path + position dots).
   * Used for drill-down into a specific storm.
   * @param {Object} trackGeojson - GeoJSON with track point features
   * @param {Object} lineGeojson - Optional GeoJSON LineString for track path
   * @param {Object} currentPosition - Optional {longitude, latitude, category}
   */
  renderTrack(trackGeojson, lineGeojson = null, currentPosition = null) {
    if (!MapAdapter?.map) {
      console.warn('TrackModel: MapAdapter not available');
      return;
    }

    // Clear existing track
    this.clearTrack();

    const map = MapAdapter.map;

    // Build line from points if not provided
    if (!lineGeojson && trackGeojson && trackGeojson.features) {
      const coords = trackGeojson.features.map(f => f.geometry.coordinates);
      lineGeojson = {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: coords
          },
          properties: {}
        }]
      };
    }

    // Add track line source and layer
    if (lineGeojson) {
      map.addSource(CONFIG.layers.hurricaneTrackSource, {
        type: 'geojson',
        data: lineGeojson
      });

      map.addLayer({
        id: CONFIG.layers.hurricaneTrackLine,
        type: 'line',
        source: CONFIG.layers.hurricaneTrackSource,
        paint: {
          'line-color': '#ffffff',
          'line-width': 3,
          'line-opacity': 0.7,
          'line-dasharray': [2, 2]
        }
      });
    }

    // Add track points (small dots along path)
    if (trackGeojson) {
      map.addSource(CONFIG.layers.hurricaneSource + '-track', {
        type: 'geojson',
        data: trackGeojson
      });

      const categoryColorExpr = [
        'match',
        ['get', 'category'],
        'TD', CONFIG.hurricaneColors.TD,
        'TS', CONFIG.hurricaneColors.TS,
        '1', CONFIG.hurricaneColors['1'],
        '2', CONFIG.hurricaneColors['2'],
        '3', CONFIG.hurricaneColors['3'],
        '4', CONFIG.hurricaneColors['4'],
        '5', CONFIG.hurricaneColors['5'],
        1, CONFIG.hurricaneColors['1'],
        2, CONFIG.hurricaneColors['2'],
        3, CONFIG.hurricaneColors['3'],
        4, CONFIG.hurricaneColors['4'],
        5, CONFIG.hurricaneColors['5'],
        CONFIG.hurricaneColors.default
      ];

      map.addLayer({
        id: CONFIG.layers.hurricaneCircle + '-track-dots',
        type: 'circle',
        source: CONFIG.layers.hurricaneSource + '-track',
        paint: {
          'circle-radius': 4,
          'circle-color': categoryColorExpr,
          'circle-opacity': 0.8
        }
      });
    }

    console.log('TrackModel: Track loaded');
  },

  /**
   * Update the current position marker on a track (for animation).
   * @param {number} longitude
   * @param {number} latitude
   * @param {string} category - Storm category for color
   */
  updatePosition(longitude, latitude, category) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const posSource = map.getSource(CONFIG.layers.hurricaneSource + '-current');

    if (posSource) {
      posSource.setData({
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: {
            type: 'Point',
            coordinates: [longitude, latitude]
          },
          properties: { category }
        }]
      });
    }
  },

  /**
   * Update track data (for time-based filtering).
   * @param {Object} geojson - Filtered GeoJSON FeatureCollection
   */
  update(geojson) {
    if (!MapAdapter?.map) return;

    const source = MapAdapter.map.getSource(CONFIG.layers.hurricaneSource);
    if (source) {
      source.setData(geojson);
    }
  },

  /**
   * Clear all storm markers.
   */
  clearMarkers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Remove click handler
    if (this.clickHandler) {
      map.off('click', CONFIG.layers.hurricaneCircle, this.clickHandler);
      this.clickHandler = null;
    }

    // Remove layers
    if (map.getLayer(CONFIG.layers.hurricaneLabel)) {
      map.removeLayer(CONFIG.layers.hurricaneLabel);
    }
    if (map.getLayer(CONFIG.layers.hurricaneCircle)) {
      map.removeLayer(CONFIG.layers.hurricaneCircle);
    }
    if (map.getLayer(CONFIG.layers.hurricaneCircle + '-glow')) {
      map.removeLayer(CONFIG.layers.hurricaneCircle + '-glow');
    }
    if (map.getSource(CONFIG.layers.hurricaneSource)) {
      map.removeSource(CONFIG.layers.hurricaneSource);
    }
  },

  /**
   * Clear storm track layers.
   */
  clearTrack() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Track line
    if (map.getLayer(CONFIG.layers.hurricaneTrackLine)) {
      map.removeLayer(CONFIG.layers.hurricaneTrackLine);
    }
    if (map.getSource(CONFIG.layers.hurricaneTrackSource)) {
      map.removeSource(CONFIG.layers.hurricaneTrackSource);
    }

    // Track dots
    if (map.getLayer(CONFIG.layers.hurricaneCircle + '-track-dots')) {
      map.removeLayer(CONFIG.layers.hurricaneCircle + '-track-dots');
    }
    if (map.getSource(CONFIG.layers.hurricaneSource + '-track')) {
      map.removeSource(CONFIG.layers.hurricaneSource + '-track');
    }

    // Current position marker
    if (map.getLayer(CONFIG.layers.hurricaneCircle + '-current')) {
      map.removeLayer(CONFIG.layers.hurricaneCircle + '-current');
    }
    if (map.getSource(CONFIG.layers.hurricaneSource + '-current')) {
      map.removeSource(CONFIG.layers.hurricaneSource + '-current');
    }

    this.activeTrackId = null;
  },

  /**
   * Clear all layers (markers and track).
   */
  clear() {
    this.clearMarkers();
    this.clearTrack();
  },

  /**
   * Fit map to track bounds.
   * @param {Object} geojson - Track GeoJSON
   */
  fitBounds(geojson) {
    if (!MapAdapter?.map || !geojson || !geojson.features || geojson.features.length === 0) {
      return;
    }

    const bounds = new maplibregl.LngLatBounds();

    for (const feature of geojson.features) {
      if (feature.geometry) {
        if (feature.geometry.type === 'Point') {
          bounds.extend(feature.geometry.coordinates);
        } else if (feature.geometry.type === 'LineString') {
          for (const coord of feature.geometry.coordinates) {
            bounds.extend(coord);
          }
        }
      }
    }

    if (!bounds.isEmpty()) {
      MapAdapter.map.fitBounds(bounds, {
        padding: 50,
        duration: 1000,
        maxZoom: 8
      });
    }
  },

  /**
   * Build popup HTML for a storm.
   * @param {Object} props - Feature properties
   * @param {string} eventType - Event type
   * @returns {string} HTML string
   */
  buildPopupHtml(props, eventType = 'hurricane') {
    const lines = [];
    const name = props.name || props.storm_name || 'Unknown Storm';
    const category = props.category || props.max_category || 'N/A';

    lines.push(`<strong>${name}</strong>`);
    lines.push(`Category: ${category}`);

    if (props.wind_kt) {
      lines.push(`Wind: ${props.wind_kt} kt`);
    }
    if (props.pressure_mb) {
      lines.push(`Pressure: ${props.pressure_mb} mb`);
    }
    if (props.timestamp) {
      const date = new Date(props.timestamp);
      lines.push(date.toLocaleString());
    }

    return lines.join('<br>');
  },

  /**
   * Check if this model is currently active.
   * @returns {boolean}
   */
  isActive() {
    return this.activeTrackId !== null || this.clickHandler !== null;
  },

  /**
   * Get the currently active track ID.
   * @returns {string|null}
   */
  getActiveTrackId() {
    return this.activeTrackId;
  }
};
