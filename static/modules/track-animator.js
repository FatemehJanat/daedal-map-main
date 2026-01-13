/**
 * Track Animator - Animates storm tracks with progressive drawing and wind radii.
 *
 * Features:
 * - Progressive track line drawing (grows as animation progresses)
 * - Current position marker with pulsing animation
 * - Wind radii circles (r34/r50/r64) when data available
 * - 6-hourly position stepping
 * - Integration with TimeSlider for playback controls
 *
 * Usage:
 *   TrackAnimator.start(stormId, positions);
 *   TrackAnimator.stop();
 */

import { CONFIG } from './config.js';

// Dependencies set via setDependencies
let MapAdapter = null;
let TimeSlider = null;
let TrackModel = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  TimeSlider = deps.TimeSlider;
  TrackModel = deps.TrackModel;
}

// Layer IDs for track animation
const LAYERS = {
  trackLine: 'track-anim-line',
  trackLineSource: 'track-anim-line-source',
  trackDots: 'track-anim-dots',
  trackDotsSource: 'track-anim-dots-source',
  currentMarker: 'track-anim-current',
  currentMarkerSource: 'track-anim-current-source',
  currentGlow: 'track-anim-current-glow',
  windR34: 'track-anim-wind-r34',
  windR50: 'track-anim-wind-r50',
  windR64: 'track-anim-wind-r64',
  windSource: 'track-anim-wind-source'
};

export const TrackAnimator = {
  // Current animation state
  isActive: false,
  rollingMode: false,  // True when driven by global TimeSlider (no zoom, no scale takeover)
  stormId: null,
  stormName: null,
  positions: [],
  currentIndex: 0,

  // Track line coordinates (grows during animation)
  trackCoords: [],

  // Time range
  startTime: null,
  endTime: null,

  // Exit callback
  onExit: null,

  /**
   * Start track animation for a storm.
   * @param {string} stormId - Storm identifier
   * @param {Array} positions - Array of position objects with timestamp, lat, lon, wind_kt, etc.
   * @param {Object} options - {stormName, onExit}
   */
  async start(stormId, positions, options = {}) {
    if (!MapAdapter?.map) {
      console.warn('TrackAnimator: MapAdapter not available');
      return;
    }

    if (!positions || positions.length === 0) {
      console.warn('TrackAnimator: No positions provided');
      return;
    }

    // Sort positions by timestamp
    this.positions = [...positions].sort((a, b) =>
      new Date(a.timestamp) - new Date(b.timestamp)
    );

    this.stormId = stormId;
    this.stormName = options.stormName || stormId;
    this.onExit = options.onExit;
    this.currentIndex = 0;
    this.trackCoords = [];

    // Calculate time range
    this.startTime = new Date(this.positions[0].timestamp).getTime();
    this.endTime = new Date(this.positions[this.positions.length - 1].timestamp).getTime();

    console.log(`TrackAnimator: Starting ${this.stormName} with ${this.positions.length} positions`);
    console.log(`  Time range: ${new Date(this.startTime).toISOString()} to ${new Date(this.endTime).toISOString()}`);

    // Clear existing track layers
    this.clearLayers();

    // Initialize layers
    this.initializeLayers();

    // Fit map to track
    this.fitToTrack();

    // Setup TimeSlider for track animation
    this.setupTimeSlider();

    // Show first position
    this.setPosition(0);

    this.isActive = true;
  },

  /**
   * Start track animation in rolling mode (driven by global TimeSlider).
   * Skips auto-zoom and TimeSlider scale creation.
   * Called when a storm enters its active period during rolling time playback.
   * @param {string} stormId - Storm identifier
   * @param {Array} positions - Array of position objects with timestamp, lat, lon, wind_kt, etc.
   * @param {Object} options - {stormName}
   */
  startRolling(stormId, positions, options = {}) {
    if (!MapAdapter?.map) {
      console.warn('TrackAnimator: MapAdapter not available');
      return;
    }

    if (!positions || positions.length === 0) {
      console.warn('TrackAnimator: No positions provided');
      return;
    }

    // Sort positions by timestamp
    this.positions = [...positions].sort((a, b) =>
      new Date(a.timestamp) - new Date(b.timestamp)
    );

    this.stormId = stormId;
    this.stormName = options.stormName || stormId;
    this.rollingMode = true;
    this.currentIndex = 0;
    this.trackCoords = [];

    // Calculate time range
    this.startTime = new Date(this.positions[0].timestamp).getTime();
    this.endTime = new Date(this.positions[this.positions.length - 1].timestamp).getTime();

    console.log(`TrackAnimator: Starting rolling mode for ${this.stormName} with ${this.positions.length} positions`);

    // Clear existing track layers
    this.clearLayers();

    // Initialize layers
    this.initializeLayers();

    // NO fitToTrack() - don't zoom
    // NO setupTimeSlider() - use global TimeSlider

    this.isActive = true;

    // Set initial position based on current global time
    if (TimeSlider?.currentTime) {
      this.setTimestamp(TimeSlider.currentTime);
    }
  },

  /**
   * Initialize map layers for track animation.
   */
  initializeLayers() {
    const map = MapAdapter.map;

    // Track line source (grows during animation)
    map.addSource(LAYERS.trackLineSource, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Track line layer
    map.addLayer({
      id: LAYERS.trackLine,
      type: 'line',
      source: LAYERS.trackLineSource,
      paint: {
        'line-color': '#ffffff',
        'line-width': 3,
        'line-opacity': 0.8
      }
    });

    // Track dots source (past positions)
    map.addSource(LAYERS.trackDotsSource, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Track dots layer
    map.addLayer({
      id: LAYERS.trackDots,
      type: 'circle',
      source: LAYERS.trackDotsSource,
      paint: {
        'circle-radius': 4,
        'circle-color': this._buildCategoryColorExpr(),
        'circle-opacity': 0.7
      }
    });

    // Wind radii source
    map.addSource(LAYERS.windSource, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Wind radii layers (64kt innermost, 34kt outermost)
    map.addLayer({
      id: LAYERS.windR34,
      type: 'fill',
      source: LAYERS.windSource,
      filter: ['==', ['get', 'windLevel'], 'r34'],
      paint: {
        'fill-color': '#3498db',
        'fill-opacity': 0.15
      }
    });

    map.addLayer({
      id: LAYERS.windR50,
      type: 'fill',
      source: LAYERS.windSource,
      filter: ['==', ['get', 'windLevel'], 'r50'],
      paint: {
        'fill-color': '#f39c12',
        'fill-opacity': 0.2
      }
    });

    map.addLayer({
      id: LAYERS.windR64,
      type: 'fill',
      source: LAYERS.windSource,
      filter: ['==', ['get', 'windLevel'], 'r64'],
      paint: {
        'fill-color': '#e74c3c',
        'fill-opacity': 0.25
      }
    });

    // Current position source
    map.addSource(LAYERS.currentMarkerSource, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Current position glow
    map.addLayer({
      id: LAYERS.currentGlow,
      type: 'circle',
      source: LAYERS.currentMarkerSource,
      paint: {
        'circle-radius': 20,
        'circle-color': this._buildCategoryColorExpr(),
        'circle-opacity': 0.4,
        'circle-blur': 1
      }
    });

    // Current position marker
    map.addLayer({
      id: LAYERS.currentMarker,
      type: 'circle',
      source: LAYERS.currentMarkerSource,
      paint: {
        'circle-radius': 10,
        'circle-color': this._buildCategoryColorExpr(),
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 3
      }
    });
  },

  /**
   * Build category color expression.
   */
  _buildCategoryColorExpr() {
    return [
      'match',
      ['get', 'category'],
      'TD', CONFIG.hurricaneColors?.TD || '#6ec1e4',
      'TS', CONFIG.hurricaneColors?.TS || '#4aa1d2',
      'Cat1', CONFIG.hurricaneColors?.['1'] || '#74c476',
      'Cat2', CONFIG.hurricaneColors?.['2'] || '#ffffb2',
      'Cat3', CONFIG.hurricaneColors?.['3'] || '#fd8d3c',
      'Cat4', CONFIG.hurricaneColors?.['4'] || '#f03b20',
      'Cat5', CONFIG.hurricaneColors?.['5'] || '#bd0026',
      '1', CONFIG.hurricaneColors?.['1'] || '#74c476',
      '2', CONFIG.hurricaneColors?.['2'] || '#ffffb2',
      '3', CONFIG.hurricaneColors?.['3'] || '#fd8d3c',
      '4', CONFIG.hurricaneColors?.['4'] || '#f03b20',
      '5', CONFIG.hurricaneColors?.['5'] || '#bd0026',
      '#666666'
    ];
  },

  /**
   * Set animation to a specific position index.
   * @param {number} index - Position index
   */
  setPosition(index) {
    if (index < 0 || index >= this.positions.length) return;

    this.currentIndex = index;
    const pos = this.positions[index];
    const map = MapAdapter.map;

    // Build track line up to current position
    this.trackCoords = this.positions.slice(0, index + 1).map(p => [p.longitude, p.latitude]);

    // Update track line
    const lineSource = map.getSource(LAYERS.trackLineSource);
    if (lineSource) {
      lineSource.setData({
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates: this.trackCoords
        }
      });
    }

    // Update track dots (past positions)
    const dotsSource = map.getSource(LAYERS.trackDotsSource);
    if (dotsSource) {
      dotsSource.setData({
        type: 'FeatureCollection',
        features: this.positions.slice(0, index).map(p => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [p.longitude, p.latitude] },
          properties: { category: p.category }
        }))
      });
    }

    // Update current position marker
    const currentSource = map.getSource(LAYERS.currentMarkerSource);
    if (currentSource) {
      currentSource.setData({
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [pos.longitude, pos.latitude] },
          properties: { category: pos.category, wind_kt: pos.wind_kt }
        }]
      });
    }

    // Update wind radii
    this.updateWindRadii(pos);

    // Update TimeSlider display
    const timestamp = new Date(pos.timestamp).getTime();
    if (TimeSlider?.updateLabel) {
      TimeSlider.updateLabel(timestamp);
    }
  },

  /**
   * Set animation to a specific timestamp.
   * @param {number} timestamp - Unix timestamp in ms
   */
  setTimestamp(timestamp) {
    // Find closest position to timestamp
    let closestIndex = 0;
    let closestDiff = Infinity;

    for (let i = 0; i < this.positions.length; i++) {
      const posTime = new Date(this.positions[i].timestamp).getTime();
      const diff = Math.abs(posTime - timestamp);
      if (diff < closestDiff) {
        closestDiff = diff;
        closestIndex = i;
      }
    }

    this.setPosition(closestIndex);
  },

  /**
   * Update wind radii circles for a position.
   * @param {Object} pos - Position with r34/r50/r64 quadrant data
   */
  updateWindRadii(pos) {
    const map = MapAdapter.map;
    const windSource = map.getSource(LAYERS.windSource);
    if (!windSource) return;

    const features = [];
    const center = [pos.longitude, pos.latitude];

    // Build wind radii polygons for each level
    for (const level of ['r64', 'r50', 'r34']) {
      const ne = pos[`${level}_ne`];
      const se = pos[`${level}_se`];
      const sw = pos[`${level}_sw`];
      const nw = pos[`${level}_nw`];

      // Only draw if we have data
      if (ne || se || sw || nw) {
        const polygon = this._buildWindPolygon(center, ne || 0, se || 0, sw || 0, nw || 0);
        features.push({
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [polygon] },
          properties: { windLevel: level }
        });
      }
    }

    windSource.setData({
      type: 'FeatureCollection',
      features
    });
  },

  /**
   * Build a 4-quadrant wind radius polygon.
   * @param {Array} center - [lon, lat]
   * @param {number} ne - NE quadrant radius in nautical miles
   * @param {number} se - SE quadrant radius in nautical miles
   * @param {number} sw - SW quadrant radius in nautical miles
   * @param {number} nw - NW quadrant radius in nautical miles
   * @returns {Array} Polygon coordinates
   */
  _buildWindPolygon(center, ne, se, sw, nw) {
    const coords = [];
    const [lon, lat] = center;
    const nmToKm = 1.852;
    const kmPerDegLat = 111;

    // Generate points around the circle, using quadrant-specific radii
    for (let angle = 0; angle <= 360; angle += 10) {
      let radiusNm;
      if (angle <= 90) {
        // NE quadrant
        radiusNm = ne;
      } else if (angle <= 180) {
        // SE quadrant
        radiusNm = se;
      } else if (angle <= 270) {
        // SW quadrant
        radiusNm = sw;
      } else {
        // NW quadrant
        radiusNm = nw;
      }

      const radiusKm = radiusNm * nmToKm;
      const latOffset = (radiusKm / kmPerDegLat) * Math.cos(angle * Math.PI / 180);
      const lonOffset = (radiusKm / (kmPerDegLat * Math.cos(lat * Math.PI / 180))) * Math.sin(angle * Math.PI / 180);

      coords.push([lon + lonOffset, lat + latOffset]);
    }

    // Close the polygon
    coords.push(coords[0]);

    return coords;
  },

  /**
   * Setup TimeSlider for track animation.
   * Uses multi-scale API to add a track-specific time scale.
   */
  setupTimeSlider() {
    if (!TimeSlider) {
      console.warn('TrackAnimator: TimeSlider not available');
      return;
    }

    // Build timestamp array from positions
    const timestamps = this.positions.map(p => new Date(p.timestamp).getTime());

    // Build timeData structure for TimeSlider (position index keyed by timestamp)
    const timeData = {};
    for (let i = 0; i < this.positions.length; i++) {
      const ts = new Date(this.positions[i].timestamp).getTime();
      timeData[ts] = { positionIndex: i };
    }

    // Create scale ID for this track
    this.scaleId = `track-${this.stormId.substring(0, 8)}`;

    // Add scale to TimeSlider using multi-scale API
    const added = TimeSlider.addScale({
      id: this.scaleId,
      label: this.stormName,
      granularity: '6h',
      useTimestamps: true,
      currentTime: this.startTime,
      timeRange: {
        min: this.startTime,
        max: this.endTime,
        available: timestamps
      },
      timeData: timeData,
      mapRenderer: 'track-animation'
    });

    if (added) {
      TimeSlider.setActiveScale(this.scaleId);

      // Enter event animation mode with auto-calculated speed for ~10 second playback
      if (TimeSlider.enterEventAnimation) {
        TimeSlider.enterEventAnimation(this.startTime, this.endTime);
      }

      console.log(`TrackAnimator: Added TimeSlider scale ${this.scaleId}`);

      // Listen for time changes from TimeSlider
      this._timeChangeHandler = (time, source) => {
        if (source !== 'track-animator' && time > 3000) {
          this.setTimestamp(time);
        }
      };
      TimeSlider.addChangeListener(this._timeChangeHandler);
    }

    // Add exit button
    this.addExitButton();
  },

  /**
   * Add exit button to return to storm list.
   */
  addExitButton() {
    // Remove existing exit button if any
    const existing = document.getElementById('track-exit-btn');
    if (existing) existing.remove();

    const btn = document.createElement('button');
    btn.id = 'track-exit-btn';
    btn.textContent = 'Exit Track View';
    btn.className = 'track-exit-button';
    btn.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      padding: 10px 20px;
      background: #e74c3c;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      z-index: 1000;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;

    btn.addEventListener('click', () => this.stop());
    document.body.appendChild(btn);
  },

  /**
   * Fit map to the full track extent.
   */
  fitToTrack() {
    if (!MapAdapter?.map || this.positions.length === 0) return;

    const maplibre = window.maplibregl || maplibregl;
    const bounds = new maplibre.LngLatBounds();

    for (const pos of this.positions) {
      bounds.extend([pos.longitude, pos.latitude]);
    }

    MapAdapter.map.fitBounds(bounds, {
      padding: 80,
      duration: 1500,
      maxZoom: 8,
      minZoom: 2  // Allow zooming out for large ocean-crossing tracks
    });
  },

  /**
   * Stop track animation and cleanup.
   */
  stop() {
    console.log(`TrackAnimator: Stopping${this.rollingMode ? ' (rolling mode)' : ''}`);

    this.clearLayers();

    // Only do TimeSlider cleanup if NOT in rolling mode (focused mode created its own scale)
    if (!this.rollingMode) {
      // Remove exit button
      const exitBtn = document.getElementById('track-exit-btn');
      if (exitBtn) exitBtn.remove();

      // Remove TimeSlider scale and listener
      if (TimeSlider) {
        // Exit event animation mode - restore yearly overview speed
        if (TimeSlider.exitEventAnimation) {
          TimeSlider.exitEventAnimation();
        }

        if (this._timeChangeHandler) {
          TimeSlider.removeChangeListener(this._timeChangeHandler);
          this._timeChangeHandler = null;
        }
        if (this.scaleId) {
          TimeSlider.removeScale(this.scaleId);
          // Only switch to primary if it exists (may not exist if only overlays are displayed)
          if (TimeSlider.scales?.find(s => s.id === 'primary')) {
            TimeSlider.setActiveScale('primary');
          } else if (TimeSlider.scales?.length === 0) {
            // No scales left, hide the time slider
            TimeSlider.hide();
          }
          this.scaleId = null;
        }
      }

      // Call exit callback (only for focused mode)
      if (this.onExit) {
        this.onExit();
      }
    }

    this.isActive = false;
    this.rollingMode = false;
    this.stormId = null;
    this.positions = [];
    this.trackCoords = [];
  },

  /**
   * Clear all animation layers.
   */
  clearLayers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Remove layers
    for (const layerId of Object.values(LAYERS)) {
      if (!layerId.includes('Source') && map.getLayer(layerId)) {
        map.removeLayer(layerId);
      }
    }

    // Remove sources
    for (const sourceId of [LAYERS.trackLineSource, LAYERS.trackDotsSource, LAYERS.currentMarkerSource, LAYERS.windSource]) {
      if (map.getSource(sourceId)) {
        map.removeSource(sourceId);
      }
    }
  }
};
