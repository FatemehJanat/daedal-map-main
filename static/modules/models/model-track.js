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
import { DisasterPopup } from '../disaster-popup.js';

// Dependencies set via setDependencies
let MapAdapter = null;
let TimeSlider = null;

export function setDependencies(deps) {
  if (deps.MapAdapter) MapAdapter = deps.MapAdapter;
  if (deps.TimeSlider) TimeSlider = deps.TimeSlider;
}

export const TrackModel = {
  // Currently active track ID
  activeTrackId: null,

  // Click handler reference for cleanup
  clickHandler: null,

  // Drill-down callback for popup sequence button
  _drillDownCallback: null,

  // Event listener reference for cleanup
  _sequenceListener: null,

  /**
   * Build category color expression for MapLibre.
   * Handles multiple category formats: 'Cat1', '1', 1, 'TD', 'TS'
   * @private
   * @returns {Array} MapLibre match expression
   */
  _buildCategoryColorExpr() {
    return [
      'match',
      ['coalesce', ['get', 'category'], ['get', 'max_category']],
      // String formats from IBTrACS (Cat1, Cat2, etc.)
      'TD', CONFIG.hurricaneColors.TD,
      'TS', CONFIG.hurricaneColors.TS,
      'Cat1', CONFIG.hurricaneColors['1'],
      'Cat2', CONFIG.hurricaneColors['2'],
      'Cat3', CONFIG.hurricaneColors['3'],
      'Cat4', CONFIG.hurricaneColors['4'],
      'Cat5', CONFIG.hurricaneColors['5'],
      // Legacy formats (string numbers)
      '1', CONFIG.hurricaneColors['1'],
      '2', CONFIG.hurricaneColors['2'],
      '3', CONFIG.hurricaneColors['3'],
      '4', CONFIG.hurricaneColors['4'],
      '5', CONFIG.hurricaneColors['5'],
      // Default fallback (must be a string color)
      CONFIG.hurricaneColors.default || '#888888'
    ];
  },

  /**
   * Render hurricane/storm features onto the map.
   * Supports both Point (max intensity markers) and LineString (track lines) features.
   * @param {Object} geojson - GeoJSON FeatureCollection with Point or LineString features
   * @param {string} eventType - 'hurricane', 'typhoon', 'cyclone'
   * @param {Object} options - {onStormClick: callback(stormId, stormName)}
   */
  render(geojson, eventType = 'hurricane', options = {}) {
    if (!MapAdapter?.map) {
      console.warn('TrackModel: MapAdapter not available');
      return;
    }

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      console.log('TrackModel: No features to display, clearing existing layers');
      this.clear();
      return;
    }

    const map = MapAdapter.map;

    // Check if source already exists - if so, just update data (no flash)
    const existingSource = map.getSource(CONFIG.layers.hurricaneSource);
    if (existingSource) {
      // Source exists - just update data, don't recreate layers
      existingSource.setData(geojson);
      return true;
    }

    // First time render - create source and layers
    const categoryColorExpr = this._buildCategoryColorExpr();

    // Detect geometry type from first feature
    const firstFeature = geojson.features[0];
    const isLineString = firstFeature.geometry?.type === 'LineString';

    // Add hurricane source
    map.addSource(CONFIG.layers.hurricaneSource, {
      type: 'geojson',
      data: geojson
    });

    if (isLineString) {
      // Render track lines for yearly overview
      this._renderTrackLines(map, categoryColorExpr, options);
    } else {
      // Render point markers (legacy behavior)
      this._renderPointMarkers(map, categoryColorExpr, options);
    }

    // Set up popup event listeners for sequence button
    this._setupPopupEventListeners();

    console.log(`TrackModel: Loaded ${geojson.features.length} ${eventType} ${isLineString ? 'tracks' : 'markers'}`);
  },

  /**
   * Render storm track lines for yearly overview.
   * Supports lifecycle opacity via _opacity property for rolling time animation.
   * @private
   */
  _renderTrackLines(map, categoryColorExpr, options) {
    // Lifecycle opacity expression: uses _opacity property or defaults to 1.0
    const lifecycleOpacity = ['coalesce', ['get', '_opacity'], 1.0];

    // Add track line layer (colored by max category)
    map.addLayer({
      id: CONFIG.layers.hurricaneCircle + '-lines',
      type: 'line',
      source: CONFIG.layers.hurricaneSource,
      paint: {
        'line-color': categoryColorExpr,
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          2, 1.5,
          5, 3,
          8, 4
        ],
        'line-opacity': ['*', 0.8, lifecycleOpacity]
      }
    });

    // Add glow effect for lines
    map.addLayer({
      id: CONFIG.layers.hurricaneCircle + '-glow',
      type: 'line',
      source: CONFIG.layers.hurricaneSource,
      paint: {
        'line-color': categoryColorExpr,
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          2, 4,
          5, 8,
          8, 12
        ],
        'line-opacity': ['*', 0.2, lifecycleOpacity],
        'line-blur': 3
      }
    }, CONFIG.layers.hurricaneCircle + '-lines');  // Below main line

    // Add labels at track endpoints (use symbol layer with placement)
    map.addLayer({
      id: CONFIG.layers.hurricaneLabel,
      type: 'symbol',
      source: CONFIG.layers.hurricaneSource,
      minzoom: 3,
      layout: {
        'symbol-placement': 'line',
        'text-field': ['coalesce', ['get', 'name'], ''],
        'text-size': [
          'interpolate', ['linear'], ['zoom'],
          3, 9,
          6, 11
        ],
        'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
        'text-max-angle': 30,
        'text-anchor': 'center'
      },
      paint: {
        'text-color': '#ffffff',
        'text-halo-color': 'rgba(0, 0, 0, 0.9)',
        'text-halo-width': 2
      }
    });

    // Store drill-down callback for popup sequence button
    this._drillDownCallback = options.onEventClick || options.onStormClick;

    // Click handler for track lines - show unified popup
    this.clickHandler = (e) => {
      if (TimeSlider?.isPlaying) return;
      if (e.features.length > 0) {
        const feature = e.features[0];
        const props = feature.properties;
        // Use click location for popup position (not genesis point)
        const coords = e.lngLat ? [e.lngLat.lng, e.lngLat.lat] : null;
        // Show unified disaster popup
        if (coords) {
          DisasterPopup.show(coords, props, 'hurricane');
        }
      }
    };
    map.on('click', CONFIG.layers.hurricaneCircle + '-lines', this.clickHandler);

    // Hover cursor for lines
    map.on('mouseenter', CONFIG.layers.hurricaneCircle + '-lines', () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', CONFIG.layers.hurricaneCircle + '-lines', () => {
      map.getCanvas().style.cursor = '';
      if (!MapAdapter.popupLocked) {
        MapAdapter.hidePopup();
      }
    });

    // Hover popup for lines - use unified DisasterPopup hover system
    map.on('mousemove', CONFIG.layers.hurricaneCircle + '-lines', (e) => {
      if (TimeSlider?.isPlaying) return;
      if (e.features.length > 0 && !MapAdapter.popupLocked) {
        const props = e.features[0].properties;
        const html = DisasterPopup.buildHoverHtml(props, 'hurricane');
        MapAdapter.showPopup([e.lngLat.lng, e.lngLat.lat], html);
      }
    });
  },

  /**
   * Render storm point markers (legacy behavior).
   * @private
   */
  _renderPointMarkers(map, categoryColorExpr, options) {
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

    // Store drill-down callback for popup sequence button (if not already set)
    if (!this._drillDownCallback) {
      this._drillDownCallback = options.onEventClick || options.onStormClick;
    }

    // Click handler for point markers - show unified popup
    this.clickHandler = (e) => {
      if (TimeSlider?.isPlaying) return;
      if (e.features.length > 0) {
        const feature = e.features[0];
        const props = feature.properties;
        // Use exact feature geometry for popup position
        const coords = feature.geometry?.coordinates ||
          (e.lngLat ? [e.lngLat.lng, e.lngLat.lat] : null);
        // Show unified disaster popup
        if (coords) {
          DisasterPopup.show(coords, props, 'hurricane');
        }
      }
    };
    map.on('click', CONFIG.layers.hurricaneCircle, this.clickHandler);

    // Hover cursor
    map.on('mouseenter', CONFIG.layers.hurricaneCircle, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', CONFIG.layers.hurricaneCircle, () => {
      map.getCanvas().style.cursor = '';
      if (!MapAdapter.popupLocked) {
        MapAdapter.hidePopup();
      }
    });

    // Hover popup for points - use unified DisasterPopup hover system
    map.on('mousemove', CONFIG.layers.hurricaneCircle, (e) => {
      if (TimeSlider?.isPlaying) return;
      if (e.features.length > 0 && !MapAdapter.popupLocked) {
        const props = e.features[0].properties;
        const html = DisasterPopup.buildHoverHtml(props, 'hurricane');
        MapAdapter.showPopup([e.lngLat.lng, e.lngLat.lat], html);
      }
    });
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

      // Use coalesce to handle both string and numeric category values
      // Convert category to string for consistent matching
      const categoryColorExpr = [
        'match',
        ['to-string', ['get', 'category']],
        'TD', CONFIG.hurricaneColors.TD || '#5ebaff',
        'TS', CONFIG.hurricaneColors.TS || '#00faf4',
        'Cat1', CONFIG.hurricaneColors['1'] || '#ffffcc',
        'Cat2', CONFIG.hurricaneColors['2'] || '#ffe775',
        'Cat3', CONFIG.hurricaneColors['3'] || '#ffc140',
        'Cat4', CONFIG.hurricaneColors['4'] || '#ff8f20',
        'Cat5', CONFIG.hurricaneColors['5'] || '#ff6060',
        '1', CONFIG.hurricaneColors['1'] || '#ffffcc',
        '2', CONFIG.hurricaneColors['2'] || '#ffe775',
        '3', CONFIG.hurricaneColors['3'] || '#ffc140',
        '4', CONFIG.hurricaneColors['4'] || '#ff8f20',
        '5', CONFIG.hurricaneColors['5'] || '#ff6060',
        CONFIG.hurricaneColors.default || '#aaaaaa'
      ];

      // Recency-based effects for animation trail
      // _recency: 1.5 = brand new (flash), 1.0 = recent, 0.0 = fading out
      const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];

      // Opacity: cap at 1.0 (recency can be > 1.0 for flash effect)
      const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];

      // Size boost for current position when it just arrived (flash effect)
      // Current position: base 8px, boosted up to 12px when new
      // Past positions: base 4px, no boost (they fade, not flash)
      const currentSizeExpr = ['*', 8, ['max', 1.0, recencyExpr]];

      map.addLayer({
        id: CONFIG.layers.hurricaneCircle + '-track-dots',
        type: 'circle',
        source: CONFIG.layers.hurricaneSource + '-track',
        paint: {
          'circle-radius': [
            'case',
            ['==', ['get', '_isCurrent'], true], currentSizeExpr,  // Larger + flash for current
            4  // Normal for past positions (fade only, no size boost)
          ],
          'circle-color': categoryColorExpr,
          'circle-opacity': opacityExpr(0.8),  // Fade with recency, cap at 1.0
          'circle-stroke-color': [
            'case',
            ['==', ['get', '_isCurrent'], true], '#ffffff',  // White ring for current
            'transparent'
          ],
          'circle-stroke-width': 2
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
   * Clear all storm markers (points or lines).
   */
  clearMarkers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Clean up popup event listeners
    this._cleanupPopupEventListeners();

    // Remove click handlers (for both points and lines)
    if (this.clickHandler) {
      map.off('click', CONFIG.layers.hurricaneCircle, this.clickHandler);
      map.off('click', CONFIG.layers.hurricaneCircle + '-lines', this.clickHandler);
      this.clickHandler = null;
    }

    // Remove layers (both point and line variants)
    const layersToRemove = [
      CONFIG.layers.hurricaneLabel,
      CONFIG.layers.hurricaneCircle,
      CONFIG.layers.hurricaneCircle + '-glow',
      CONFIG.layers.hurricaneCircle + '-lines'
    ];

    for (const layerId of layersToRemove) {
      if (map.getLayer(layerId)) {
        map.removeLayer(layerId);
      }
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
  },

  /**
   * Build a wind radii polygon from quadrant values.
   * Creates an asymmetric shape representing wind extent in each direction.
   * @private
   * @param {number} centerLon - Center longitude
   * @param {number} centerLat - Center latitude
   * @param {Object} radii - {ne, se, sw, nw} in nautical miles
   * @returns {Array} Polygon coordinates array
   */
  _buildWindRadiiPolygon(centerLon, centerLat, radii) {
    if (!radii.ne && !radii.se && !radii.sw && !radii.nw) {
      return null;
    }

    // Convert nautical miles to degrees (approximate)
    // 1 nm = 1.852 km, 1 degree lat = 111.32 km
    const nmToDegLat = 1.852 / 111.32;
    const nmToDegLon = 1.852 / (111.32 * Math.cos(centerLat * Math.PI / 180));

    const coords = [];
    const segments = 16; // Points per quadrant

    // Build polygon clockwise from North
    // NE quadrant (0 to 90 degrees)
    const rNE = (radii.ne || 0) * nmToDegLat;
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * (Math.PI / 2); // 0 to 90 deg
      const lon = centerLon + rNE * Math.sin(angle) * (nmToDegLon / nmToDegLat);
      const lat = centerLat + rNE * Math.cos(angle);
      coords.push([lon, lat]);
    }

    // SE quadrant (90 to 180 degrees)
    const rSE = (radii.se || 0) * nmToDegLat;
    for (let i = 1; i <= segments; i++) {
      const angle = (Math.PI / 2) + (i / segments) * (Math.PI / 2);
      const lon = centerLon + rSE * Math.sin(angle) * (nmToDegLon / nmToDegLat);
      const lat = centerLat + rSE * Math.cos(angle);
      coords.push([lon, lat]);
    }

    // SW quadrant (180 to 270 degrees)
    const rSW = (radii.sw || 0) * nmToDegLat;
    for (let i = 1; i <= segments; i++) {
      const angle = Math.PI + (i / segments) * (Math.PI / 2);
      const lon = centerLon + rSW * Math.sin(angle) * (nmToDegLon / nmToDegLat);
      const lat = centerLat + rSW * Math.cos(angle);
      coords.push([lon, lat]);
    }

    // NW quadrant (270 to 360 degrees)
    const rNW = (radii.nw || 0) * nmToDegLat;
    for (let i = 1; i <= segments; i++) {
      const angle = (3 * Math.PI / 2) + (i / segments) * (Math.PI / 2);
      const lon = centerLon + rNW * Math.sin(angle) * (nmToDegLon / nmToDegLat);
      const lat = centerLat + rNW * Math.cos(angle);
      coords.push([lon, lat]);
    }

    // Close the polygon
    coords.push(coords[0]);

    return [coords]; // GeoJSON polygon format
  },

  /**
   * Render wind radii circles for a storm position.
   * Shows concentric asymmetric shapes for 34kt, 50kt, and 64kt wind extent.
   * @param {Object} position - Position with wind radii properties
   */
  renderWindRadii(position) {
    if (!MapAdapter?.map) return;

    // Clear existing wind radii
    this.clearWindRadii();

    const map = MapAdapter.map;
    const lon = position.longitude || position.geometry?.coordinates?.[0];
    const lat = position.latitude || position.geometry?.coordinates?.[1];
    const props = position.properties || position;

    if (!lon || !lat) {
      console.warn('TrackModel: Invalid position for wind radii');
      return;
    }

    const features = [];

    // Build polygons for each wind threshold (largest first for proper layering)
    const r34 = this._buildWindRadiiPolygon(lon, lat, {
      ne: props.r34_ne, se: props.r34_se, sw: props.r34_sw, nw: props.r34_nw
    });
    const r50 = this._buildWindRadiiPolygon(lon, lat, {
      ne: props.r50_ne, se: props.r50_se, sw: props.r50_sw, nw: props.r50_nw
    });
    const r64 = this._buildWindRadiiPolygon(lon, lat, {
      ne: props.r64_ne, se: props.r64_se, sw: props.r64_sw, nw: props.r64_nw
    });

    // Add features with wind level property
    if (r34) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: r34 },
        properties: { windLevel: 34 }
      });
    }
    if (r50) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: r50 },
        properties: { windLevel: 50 }
      });
    }
    if (r64) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: r64 },
        properties: { windLevel: 64 }
      });
    }

    if (features.length === 0) {
      console.log('TrackModel: No wind radii data for this position');
      return;
    }

    const geojson = {
      type: 'FeatureCollection',
      features: features
    };

    // Add source
    map.addSource(CONFIG.layers.windRadiiSource, {
      type: 'geojson',
      data: geojson
    });

    // Add fill layers (34kt first/bottom, then 50kt, then 64kt on top)
    map.addLayer({
      id: CONFIG.layers.windRadii34,
      type: 'fill',
      source: CONFIG.layers.windRadiiSource,
      filter: ['==', ['get', 'windLevel'], 34],
      paint: {
        'fill-color': CONFIG.windRadiiColors.r34,
        'fill-outline-color': CONFIG.windRadiiColors.stroke34
      }
    });

    map.addLayer({
      id: CONFIG.layers.windRadii50,
      type: 'fill',
      source: CONFIG.layers.windRadiiSource,
      filter: ['==', ['get', 'windLevel'], 50],
      paint: {
        'fill-color': CONFIG.windRadiiColors.r50,
        'fill-outline-color': CONFIG.windRadiiColors.stroke50
      }
    });

    map.addLayer({
      id: CONFIG.layers.windRadii64,
      type: 'fill',
      source: CONFIG.layers.windRadiiSource,
      filter: ['==', ['get', 'windLevel'], 64],
      paint: {
        'fill-color': CONFIG.windRadiiColors.r64,
        'fill-outline-color': CONFIG.windRadiiColors.stroke64
      }
    });

    console.log(`TrackModel: Rendered ${features.length} wind radii layers`);
  },

  /**
   * Clear wind radii layers.
   */
  clearWindRadii() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const layers = [
      CONFIG.layers.windRadii64,
      CONFIG.layers.windRadii50,
      CONFIG.layers.windRadii34
    ];

    for (const layerId of layers) {
      if (map.getLayer(layerId)) {
        map.removeLayer(layerId);
      }
    }

    if (map.getSource(CONFIG.layers.windRadiiSource)) {
      map.removeSource(CONFIG.layers.windRadiiSource);
    }
  },

  /**
   * Update wind radii for animation (moves to new position).
   * @param {Object} position - New position with wind radii properties
   */
  updateWindRadii(position) {
    // For now, just re-render (could optimize to update source data)
    this.renderWindRadii(position);
  },

  /**
   * Handle sequence animation request from central dispatcher.
   * Called by ModelRegistry when disaster-sequence-request event fires.
   * @param {string} eventId - Event ID
   * @param {string} eventType - Event type (hurricane, typhoon, cyclone)
   * @param {Object} props - Event properties from the clicked feature
   */
  async handleSequence(eventId, eventType, props) {
    // Extract storm info
    const stormId = props.storm_id || eventId;
    const stormName = props.name || 'Unknown Storm';

    console.log(`TrackModel: Hurricane sequence request: ${stormId} (${stormName})`);

    // Dispatch custom event for drill-down (preferred method)
    // This allows any listener to handle the drill-down animation
    document.dispatchEvent(new CustomEvent('track-drill-down', {
      detail: { stormId, stormName, eventType, props }
    }));
  },

  /**
   * Set up event listeners for popup buttons.
   * NOTE: disaster-sequence-request is now handled by ModelRegistry central dispatcher
   * which routes to this model's handleSequence() method.
   * This method is kept for backwards compatibility but no longer adds listeners.
   */
  _setupPopupEventListeners() {
    // No-op: Sequence requests now handled by ModelRegistry.setupSequenceDispatcher()
    // which calls this.handleSequence() for hurricane/typhoon/cyclone types
  },

  /**
   * Clean up popup event listeners and callbacks.
   */
  _cleanupPopupEventListeners() {
    // NOTE: Sequence listener cleanup now handled by ModelRegistry.cleanup()
    this._drillDownCallback = null;
  }
};
