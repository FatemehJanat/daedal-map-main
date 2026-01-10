/**
 * Polygon Model - Renders area-based events with fill and stroke.
 * Used for: Wildfires, Floods, Ash Clouds, Drought Areas
 *
 * Display characteristics:
 * - Polygon/MultiPolygon fill with transparency
 * - Stroke outline for visibility
 * - Severity-based color coding
 * - Optional animation for active events
 */

import { CONFIG } from '../config.js';

// Dependencies set via setDependencies
let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

// Layer IDs for polygon events
const LAYERS = {
  source: 'polygon-events',
  fill: 'polygon-events-fill',
  stroke: 'polygon-events-stroke',
  label: 'polygon-events-label'
};

// Color schemes for different polygon event types
const COLORS = {
  wildfire: {
    fill: '#ff4400',
    fillOpacity: 0.4,
    stroke: '#ff6600',
    strokeWidth: 2,
    active: '#ff0000',      // Bright red for active fires
    contained: '#ff8800'    // Orange for contained fires
  },
  flood: {
    fill: '#0066cc',
    fillOpacity: 0.4,
    stroke: '#0088ff',
    strokeWidth: 2,
    active: '#0044aa',
    receding: '#0099ff'
  },
  ash_cloud: {
    fill: '#666666',
    fillOpacity: 0.5,
    stroke: '#888888',
    strokeWidth: 1,
    dense: '#444444',
    light: '#999999'
  },
  drought_area: {
    fill: '#cc8800',
    fillOpacity: 0.3,
    stroke: '#aa6600',
    strokeWidth: 1,
    severe: '#993300',
    moderate: '#cc9900'
  },
  default: {
    fill: '#ffcc00',
    fillOpacity: 0.35,
    stroke: '#ff9900',
    strokeWidth: 2
  }
};

export const PolygonModel = {
  // Currently active event type
  activeType: null,

  // Click handler reference for cleanup
  clickHandler: null,

  /**
   * Get color scheme for an event type.
   * @private
   * @param {string} eventType - Event type
   * @returns {Object} Color configuration
   */
  _getColors(eventType) {
    return COLORS[eventType] || COLORS.default;
  },

  /**
   * Build fill color expression based on event properties.
   * @private
   * @param {string} eventType - Event type
   * @returns {Array|string} MapLibre paint expression or color string
   */
  _buildFillColorExpr(eventType) {
    const colors = this._getColors(eventType);

    if (eventType === 'wildfire') {
      // Color by containment status
      return [
        'case',
        ['==', ['get', 'status'], 'active'], colors.active,
        ['==', ['get', 'status'], 'contained'], colors.contained,
        ['has', 'percent_contained'],
        [
          'interpolate', ['linear'], ['get', 'percent_contained'],
          0, colors.active,
          50, colors.fill,
          100, colors.contained
        ],
        colors.fill
      ];
    }

    if (eventType === 'flood') {
      return [
        'case',
        ['==', ['get', 'status'], 'active'], colors.active,
        ['==', ['get', 'status'], 'receding'], colors.receding,
        colors.fill
      ];
    }

    if (eventType === 'drought_area') {
      return [
        'match', ['get', 'severity'],
        'severe', colors.severe,
        'moderate', colors.moderate,
        colors.fill
      ];
    }

    return colors.fill;
  },

  /**
   * Render polygon events on the map.
   * @param {Object} geojson - GeoJSON FeatureCollection with Polygon/MultiPolygon features
   * @param {string} eventType - 'wildfire', 'flood', 'ash_cloud', etc.
   * @param {Object} options - {onEventClick, showLabels}
   */
  render(geojson, eventType = 'wildfire', options = {}) {
    if (!MapAdapter?.map) {
      console.warn('PolygonModel: MapAdapter not available');
      return;
    }

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      console.log('PolygonModel: No features to display');
      return;
    }

    // Clear existing layers
    this.clear();

    // Store active type
    this.activeType = eventType;

    const map = MapAdapter.map;
    const colors = this._getColors(eventType);

    // Add source
    map.addSource(LAYERS.source, {
      type: 'geojson',
      data: geojson
    });

    // Add fill layer
    map.addLayer({
      id: LAYERS.fill,
      type: 'fill',
      source: LAYERS.source,
      paint: {
        'fill-color': this._buildFillColorExpr(eventType),
        'fill-opacity': colors.fillOpacity
      }
    });

    // Add stroke layer
    map.addLayer({
      id: LAYERS.stroke,
      type: 'line',
      source: LAYERS.source,
      paint: {
        'line-color': colors.stroke,
        'line-width': colors.strokeWidth,
        'line-opacity': 0.8
      }
    });

    // Add labels if requested
    if (options.showLabels !== false) {
      map.addLayer({
        id: LAYERS.label,
        type: 'symbol',
        source: LAYERS.source,
        minzoom: 6,
        layout: {
          'text-field': ['coalesce', ['get', 'name'], ['get', 'event_name'], ''],
          'text-size': 11,
          'text-anchor': 'center',
          'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold']
        },
        paint: {
          'text-color': '#ffffff',
          'text-halo-color': 'rgba(0, 0, 0, 0.8)',
          'text-halo-width': 2
        }
      });
    }

    // Setup click handler
    if (options.onEventClick) {
      this.clickHandler = (e) => {
        if (e.features.length > 0) {
          const props = e.features[0].properties;
          options.onEventClick(props);
        }
      };
      map.on('click', LAYERS.fill, this.clickHandler);
    }

    // Hover cursor
    map.on('mouseenter', LAYERS.fill, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', LAYERS.fill, () => {
      map.getCanvas().style.cursor = '';
    });

    // Hover popup
    map.on('mousemove', LAYERS.fill, (e) => {
      if (e.features.length > 0 && !MapAdapter.popupLocked) {
        const props = e.features[0].properties;
        const html = this.buildPopupHtml(props, eventType);
        MapAdapter.showPopup([e.lngLat.lng, e.lngLat.lat], html);
      }
    });
    map.on('mouseleave', LAYERS.fill, () => {
      if (!MapAdapter.popupLocked) {
        MapAdapter.hidePopup();
      }
    });

    console.log(`PolygonModel: Loaded ${geojson.features.length} ${eventType} features`);
  },

  /**
   * Update polygon layer data (for time-based filtering).
   * @param {Object} geojson - Filtered GeoJSON FeatureCollection
   */
  update(geojson) {
    if (!MapAdapter?.map) return;

    const source = MapAdapter.map.getSource(LAYERS.source);
    if (source) {
      source.setData(geojson);
    }
  },

  /**
   * Clear all polygon layers.
   */
  clear() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Remove click handler
    if (this.clickHandler) {
      map.off('click', LAYERS.fill, this.clickHandler);
      this.clickHandler = null;
    }

    // Remove layers
    const layerIds = [LAYERS.label, LAYERS.stroke, LAYERS.fill];
    for (const layerId of layerIds) {
      if (map.getLayer(layerId)) {
        map.removeLayer(layerId);
      }
    }

    // Remove source
    if (map.getSource(LAYERS.source)) {
      map.removeSource(LAYERS.source);
    }

    this.activeType = null;
  },

  /**
   * Fit map to polygon bounds.
   * @param {Object} geojson - Polygon GeoJSON
   */
  fitBounds(geojson) {
    if (!MapAdapter?.map || !geojson || !geojson.features || geojson.features.length === 0) {
      return;
    }

    const bounds = new maplibregl.LngLatBounds();

    for (const feature of geojson.features) {
      if (feature.geometry) {
        this._extendBoundsWithGeometry(bounds, feature.geometry);
      }
    }

    if (!bounds.isEmpty()) {
      MapAdapter.map.fitBounds(bounds, {
        padding: 50,
        duration: 1000,
        maxZoom: 12
      });
    }
  },

  /**
   * Extend bounds with geometry coordinates.
   * @private
   */
  _extendBoundsWithGeometry(bounds, geometry) {
    if (geometry.type === 'Polygon') {
      // Outer ring is first element
      for (const coord of geometry.coordinates[0]) {
        bounds.extend(coord);
      }
    } else if (geometry.type === 'MultiPolygon') {
      for (const polygon of geometry.coordinates) {
        for (const coord of polygon[0]) {
          bounds.extend(coord);
        }
      }
    } else if (geometry.type === 'Point') {
      bounds.extend(geometry.coordinates);
    }
  },

  /**
   * Build popup HTML for a polygon event.
   * @param {Object} props - Feature properties
   * @param {string} eventType - Event type
   * @returns {string} HTML string
   */
  buildPopupHtml(props, eventType) {
    const lines = [];

    if (eventType === 'wildfire') {
      const name = props.name || props.fire_name || 'Wildfire';
      lines.push(`<strong>${name}</strong>`);
      if (props.status) lines.push(`Status: ${props.status}`);
      if (props.acres != null) lines.push(`Area: ${this._formatNumber(props.acres)} acres`);
      if (props.percent_contained != null) {
        lines.push(`Contained: ${props.percent_contained}%`);
      }
      if (props.start_date) lines.push(`Started: ${props.start_date}`);
    } else if (eventType === 'flood') {
      const name = props.name || 'Flood Area';
      lines.push(`<strong>${name}</strong>`);
      if (props.status) lines.push(`Status: ${props.status}`);
      if (props.severity) lines.push(`Severity: ${props.severity}`);
      if (props.area_sq_km) lines.push(`Area: ${this._formatNumber(props.area_sq_km)} sq km`);
    } else if (eventType === 'ash_cloud') {
      lines.push(`<strong>Volcanic Ash Cloud</strong>`);
      if (props.volcano_name) lines.push(`Source: ${props.volcano_name}`);
      if (props.altitude_ft) lines.push(`Altitude: ${this._formatNumber(props.altitude_ft)} ft`);
      if (props.density) lines.push(`Density: ${props.density}`);
    } else if (eventType === 'drought_area') {
      lines.push(`<strong>Drought Area</strong>`);
      if (props.severity) lines.push(`Severity: ${props.severity}`);
      if (props.duration_weeks) lines.push(`Duration: ${props.duration_weeks} weeks`);
    } else {
      // Generic popup
      lines.push(`<strong>${eventType} Event</strong>`);
      if (props.name) lines.push(props.name);
      if (props.event_id) lines.push(`ID: ${props.event_id}`);
    }

    return lines.join('<br>');
  },

  /**
   * Format a number with commas.
   * @private
   */
  _formatNumber(num) {
    if (num == null) return 'N/A';
    return num.toLocaleString();
  },

  /**
   * Check if this model is currently active.
   * @returns {boolean}
   */
  isActive() {
    return this.activeType !== null;
  },

  /**
   * Get the currently active event type.
   * @returns {string|null}
   */
  getActiveType() {
    return this.activeType;
  }
};
