/**
 * Sequence Animator - Orchestrates aftershock sequence visualization.
 * Creates "ripples in a pond" + "growing spiderweb" animation effect.
 *
 * Features:
 * - Time-filtered rendering (events appear as time advances)
 * - Circle growth animation (epicenters grow from 0 to full size)
 * - Connection lines from mainshock to aftershocks
 * - Viewport animation (slowly zoom out as sequence expands)
 */

// Dependencies set via setDependencies
let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

// Animation constants
const ANIMATION = {
  CIRCLE_GROW_DURATION: 800,     // ms for circle to grow to full size
  LINE_DRAW_DURATION: 400,       // ms for line to draw
  VIEWPORT_PADDING: 40,          // px padding around bounds
  VIEWPORT_DURATION: 800,        // ms for viewport transitions
  FADE_DURATION: 300,            // ms for fade in
  MIN_ZOOM: 3,                   // Don't zoom out further than this
  MAX_ZOOM: 10                   // Max zoom for damage radius view
};

// Layer IDs for sequence animation
const LAYERS = {
  CONNECTIONS: 'sequence-connections',       // Lines from mainshock to aftershocks
  CIRCLES_GROWING: 'sequence-circles-grow',  // Animated growing circles
  CIRCLES_GLOW: 'sequence-circles-glow',     // Glow behind circles
  MAINSHOCK_PULSE: 'sequence-mainshock-pulse', // Pulsing ring on mainshock
  FELT_RADIUS: 'sequence-felt-radius',       // Geographic felt radius circles
  DAMAGE_RADIUS: 'sequence-damage-radius',   // Geographic damage radius circles
  SOURCE: 'sequence-animation-source',
  LINES_SOURCE: 'sequence-lines-source',
  RELATED_SOURCE: 'sequence-related-source', // Related events (volcanoes, tsunamis)
  RELATED_CIRCLES: 'sequence-related-circles',
  RELATED_GLOW: 'sequence-related-glow'
};

// Helper: convert km to pixels at current zoom (geographic circles)
// Formula: pixels = km * 2^zoom / 156.5
// Using exponential interpolation with base 2 for smooth scaling
// NOTE: MapLibre requires zoom expressions at top level, so we pre-scale km values
// in _updateDisplay and use this simpler expression
const kmToPixelsExpr = (kmProp) => [
  'interpolate', ['exponential', 2], ['zoom'],
  0, ['/', ['get', kmProp], 156.5],    // At zoom 0: very small
  5, ['/', ['get', kmProp], 4.9],      // 2^5 / 156.5 = 0.204
  10, ['*', ['get', kmProp], 6.54],    // 2^10 / 156.5 = 6.54
  15, ['*', ['get', kmProp], 209]      // 2^15 / 156.5 = 209
];

export const SequenceAnimator = {
  // Current sequence state
  active: false,
  sequenceId: null,
  sequenceEvents: [],           // All events in sequence
  mainshock: null,              // Mainshock feature
  visibleEvents: [],            // Events visible at current time
  currentTime: null,            // Current animation time (ms timestamp)
  relatedEvents: [],            // Related events (volcanoes, tsunamis) from enabled overlays

  // Time range for interpolation
  minTime: null,                // Sequence start time (mainshock)
  maxTime: null,                // Sequence end time (last aftershock)

  // Animation state
  circleScales: {},             // event_id -> current scale (0-1)
  animationFrameId: null,
  lastFrameTime: null,

  // Viewport tracking - radius-based bounds for smooth interpolation
  initialBounds: null,          // Based on mainshock damage radius
  finalBounds: null,            // Based on max felt radius of all events
  lastViewportProgress: -1,     // Last interpolation progress (0-1)

  // Exit callback
  onExitCallback: null,

  /**
   * Start sequence animation for a given sequence.
   * @param {string} sequenceId - Sequence ID
   * @param {Array} events - Array of GeoJSON features in the sequence
   * @param {Object} mainshock - The mainshock feature
   * @param {Array} relatedEvents - Optional related events (volcanoes, tsunamis) to display
   */
  start(sequenceId, events, mainshock, relatedEvents = []) {
    console.log(`SequenceAnimator: Starting sequence ${sequenceId} with ${events.length} events`);
    if (relatedEvents.length > 0) {
      console.log(`SequenceAnimator: Including ${relatedEvents.length} related events`);
    }

    if (!MapAdapter?.map) {
      console.warn('SequenceAnimator: MapAdapter not available');
      return;
    }

    // Stop any existing animation
    this.stop();

    // Hide any existing popup (popups are disabled during playback)
    if (MapAdapter.hidePopup) {
      MapAdapter.hidePopup();
      MapAdapter.popupLocked = false;
    }

    // Store sequence data
    this.active = true;
    this.sequenceId = sequenceId;
    this.sequenceEvents = events;
    this.mainshock = mainshock;
    this.visibleEvents = [];
    this.circleScales = {};
    this.lastViewportProgress = -1;
    this.relatedEvents = relatedEvents || [];

    // Get mainshock coordinates and time
    const mainCoords = mainshock.geometry.coordinates;
    const mainTime = new Date(mainshock.properties.timestamp || mainshock.properties.time).getTime();
    this.currentTime = mainTime;
    this.minTime = mainTime;

    // Calculate max time from all events
    let maxTime = mainTime;
    for (const event of events) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      if (t > maxTime) maxTime = t;
    }
    this.maxTime = maxTime;

    // Initialize circle scales (all start at 0, except mainshock)
    for (const event of events) {
      const eventId = event.properties.event_id;
      // Mainshock starts fully visible, others start at 0
      this.circleScales[eventId] = (eventId === mainshock.properties.event_id) ? 1 : 0;
    }

    // Mainshock is always visible from the start
    this.visibleEvents = [mainshock];

    // Setup map layers
    this._setupLayers();

    // Create exit button UI
    this._createExitButton();

    // Calculate radius-based bounds for viewport interpolation
    // Initial: mainshock damage radius (tight view of impact area)
    const damageRadiusKm = mainshock.properties.damage_radius_km || 50;
    this.initialBounds = this._boundsFromCenterRadius(mainCoords, damageRadiusKm);

    // Final: max of mainshock felt radius OR all events' felt radii combined
    const mainFeltRadiusKm = mainshock.properties.felt_radius_km || 200;
    this.finalBounds = this._boundsFromCenterRadius(mainCoords, mainFeltRadiusKm);

    // Extend final bounds to include all aftershocks' felt radii
    // Handle date line crossing by adjusting coordinates
    for (const event of events) {
      if (event.properties.event_id === mainshock.properties.event_id) continue;
      let eventCoords = [...event.geometry.coordinates];

      // Handle international date line crossing
      const lngDiff = eventCoords[0] - mainCoords[0];
      if (Math.abs(lngDiff) > 180) {
        // Adjust event longitude to be on same side as mainshock
        if (lngDiff > 0) {
          eventCoords[0] -= 360;
        } else {
          eventCoords[0] += 360;
        }
      }

      const eventFeltKm = event.properties.felt_radius_km || 30;
      const eventBounds = this._boundsFromCenterRadius(eventCoords, eventFeltKm);
      this.finalBounds.extend(eventBounds.getNorthEast());
      this.finalBounds.extend(eventBounds.getSouthWest());
    }

    console.log(`SequenceAnimator: Initial bounds (damage ${damageRadiusKm}km), Final bounds (felt ${mainFeltRadiusKm}km + aftershocks)`);

    // Zoom to initial bounds (mainshock damage radius)
    MapAdapter.map.fitBounds(this.initialBounds, {
      padding: ANIMATION.VIEWPORT_PADDING,
      duration: ANIMATION.VIEWPORT_DURATION,
      maxZoom: ANIMATION.MAX_ZOOM,
      essential: true
    });

    // Render mainshock immediately so it's visible from the start
    this._updateDisplay();

    // Start animation loop
    this._startAnimationLoop();

    console.log(`SequenceAnimator: Starting at mainshock ${mainCoords}, time range ${new Date(this.minTime).toISOString()} to ${new Date(this.maxTime).toISOString()}`);
  },

  /**
   * Set callback for when user exits sequence view.
   * @param {Function} callback - Called when exit is triggered
   */
  onExit(callback) {
    this.onExitCallback = callback;
  },

  /**
   * Create the exit button UI element.
   * @private
   */
  _createExitButton() {
    // Remove existing button if any
    this._removeExitButton();

    // Create button container
    const container = document.createElement('div');
    container.id = 'sequence-exit-container';
    container.style.cssText = `
      position: absolute;
      top: 10px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 1000;
      display: flex;
      gap: 10px;
      align-items: center;
      background: rgba(30, 30, 30, 0.95);
      padding: 8px 16px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.2);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
    `;

    // Label showing sequence info
    const label = document.createElement('span');
    label.style.cssText = 'color: #fff; font-size: 13px; font-weight: 500;';
    const mag = this.mainshock?.properties?.magnitude?.toFixed(1) || '?';
    const count = this.sequenceEvents.length;
    label.textContent = `Aftershock Sequence: M${mag} (${count} events)`;
    container.appendChild(label);

    // Exit button
    const exitBtn = document.createElement('button');
    exitBtn.textContent = 'Exit Sequence View';
    exitBtn.style.cssText = `
      background: #e53935;
      color: white;
      border: none;
      padding: 6px 14px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      transition: background 0.2s;
    `;
    exitBtn.onmouseenter = () => exitBtn.style.background = '#f44336';
    exitBtn.onmouseleave = () => exitBtn.style.background = '#e53935';
    exitBtn.onclick = () => this._handleExit();
    container.appendChild(exitBtn);

    // Add to map container
    const mapContainer = document.getElementById('map');
    if (mapContainer) {
      mapContainer.appendChild(container);
    }
  },

  /**
   * Remove the exit button UI.
   * @private
   */
  _removeExitButton() {
    const existing = document.getElementById('sequence-exit-container');
    if (existing) {
      existing.remove();
    }
  },

  /**
   * Handle exit button click.
   * @private
   */
  _handleExit() {
    console.log('SequenceAnimator: Exit requested');
    this.stop();
    if (this.onExitCallback) {
      this.onExitCallback();
    }
  },

  /**
   * Stop sequence animation and cleanup.
   */
  stop() {
    if (!this.active) return;

    console.log('SequenceAnimator: Stopping');

    // Stop animation loop
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }

    // Remove layers
    this._removeLayers();

    // Remove exit button
    this._removeExitButton();

    // Reset state
    this.active = false;
    this.sequenceId = null;
    this.sequenceEvents = [];
    this.mainshock = null;
    this.visibleEvents = [];
    this.circleScales = {};
    this.minTime = null;
    this.maxTime = null;
    this.initialBounds = null;
    this.finalBounds = null;
    this.lastViewportProgress = -1;
    this.relatedEvents = [];
  },

  /**
   * Update animation to a specific time.
   * Called by TimeSlider as it animates through the sequence.
   * @param {number} time - Timestamp in ms
   */
  setTime(time) {
    if (!this.active) return;

    this.currentTime = time;

    // Calculate time progress (0-1) for viewport interpolation
    const timeRange = this.maxTime - this.minTime;
    const progress = timeRange > 0 ? Math.max(0, Math.min(1, (time - this.minTime) / timeRange)) : 0;

    // Update viewport based on time progress (smooth zoom out)
    this._updateViewportForProgress(progress);

    // Find which events should be visible at this time
    const newVisible = [];
    const newlyAppeared = [];
    const mainshockId = this.mainshock?.properties?.event_id;

    for (const event of this.sequenceEvents) {
      const eventTime = new Date(event.properties.timestamp || event.properties.time).getTime();
      const eventId = event.properties.event_id;

      // Mainshock is ALWAYS visible, others appear when their time is reached
      if (eventId === mainshockId || eventTime <= time) {
        const wasVisible = this.visibleEvents.some(e => e.properties.event_id === eventId);

        newVisible.push(event);

        if (!wasVisible && eventId !== mainshockId) {
          newlyAppeared.push(event);
          // Start circle growth animation (but not for mainshock which is always at 1)
          this.circleScales[eventId] = 0.01; // Start small but visible
        }
      }
    }

    this.visibleEvents = newVisible;

    // Trigger re-render
    this._updateDisplay();

    if (newlyAppeared.length > 0) {
      console.log(`SequenceAnimator: ${newlyAppeared.length} new events at progress ${(progress * 100).toFixed(1)}%`);
    }
  },

  /**
   * Setup map layers for sequence animation.
   * @private
   */
  _setupLayers() {
    const map = MapAdapter.map;

    // Remove existing layers first
    this._removeLayers();

    // Add source for event points
    map.addSource(LAYERS.SOURCE, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Add source for connection lines
    map.addSource(LAYERS.LINES_SOURCE, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Connection lines layer (spiderweb effect)
    map.addLayer({
      id: LAYERS.CONNECTIONS,
      type: 'line',
      source: LAYERS.LINES_SOURCE,
      paint: {
        'line-color': ['get', 'color'],
        'line-width': ['get', 'width'],
        'line-opacity': ['get', 'opacity'],
        'line-dasharray': [2, 2]  // Dashed lines
      }
    });

    // GEOGRAPHIC RADIUS LAYERS - actual km circles that scale with map
    // These show real impact areas that users can see overlap
    // NOTE: We pre-scale the km values by animation scale in _updateDisplay
    // because MapLibre doesn't allow zoom expressions nested in multiplication

    // 1. FELT RADIUS - outer geographic circle (how far shaking was noticeable)
    map.addLayer({
      id: LAYERS.FELT_RADIUS,
      type: 'circle',
      source: LAYERS.SOURCE,
      filter: ['>', ['get', 'felt_radius_scaled'], 0],
      paint: {
        // Uses pre-scaled km value (felt_radius_km * scale)
        'circle-radius': kmToPixelsExpr('felt_radius_scaled'),
        'circle-color': ['get', 'color'],
        'circle-opacity': ['*', ['get', 'opacity'], 0.12],
        'circle-stroke-color': ['get', 'color'],
        'circle-stroke-width': 1.5,
        'circle-stroke-opacity': ['*', ['get', 'opacity'], 0.35]
      }
    });

    // 2. DAMAGE RADIUS - inner geographic circle (structural damage zone)
    map.addLayer({
      id: LAYERS.DAMAGE_RADIUS,
      type: 'circle',
      source: LAYERS.SOURCE,
      filter: ['>', ['get', 'damage_radius_scaled'], 0],
      paint: {
        // Uses pre-scaled km value (damage_radius_km * scale)
        'circle-radius': kmToPixelsExpr('damage_radius_scaled'),
        'circle-color': ['get', 'color'],
        'circle-opacity': ['*', ['get', 'opacity'], 0.2],
        'circle-stroke-color': ['get', 'color'],
        'circle-stroke-width': 2,
        'circle-stroke-opacity': ['*', ['get', 'opacity'], 0.6]
      }
    });

    // Glow layer behind epicenter markers
    map.addLayer({
      id: LAYERS.CIRCLES_GLOW,
      type: 'circle',
      source: LAYERS.SOURCE,
      paint: {
        'circle-radius': ['get', 'glowRadius'],
        'circle-color': ['get', 'color'],
        'circle-opacity': ['*', ['get', 'opacity'], 0.4],
        'circle-blur': 1
      }
    });

    // Epicenter markers - small fixed-size dots at exact earthquake location
    map.addLayer({
      id: LAYERS.CIRCLES_GROWING,
      type: 'circle',
      source: LAYERS.SOURCE,
      paint: {
        'circle-radius': ['get', 'radius'],
        'circle-color': ['get', 'color'],
        'circle-opacity': ['get', 'opacity'],
        'circle-stroke-color': '#222222',
        'circle-stroke-width': 1
      }
    });

    // Mainshock pulse layer - pulsing ring around mainshock epicenter
    map.addLayer({
      id: LAYERS.MAINSHOCK_PULSE,
      type: 'circle',
      source: LAYERS.SOURCE,
      filter: ['==', ['get', 'isMainshock'], true],
      paint: {
        'circle-radius': ['get', 'pulseRadius'],
        'circle-color': 'transparent',
        'circle-stroke-color': ['get', 'color'],
        'circle-stroke-width': 3,
        'circle-stroke-opacity': ['get', 'pulseOpacity']
      }
    });

    // Related events layers (volcanoes, tsunamis from enabled overlays)
    if (this.relatedEvents.length > 0) {
      map.addSource(LAYERS.RELATED_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: this.relatedEvents }
      });

      // Glow layer for related events
      map.addLayer({
        id: LAYERS.RELATED_GLOW,
        type: 'circle',
        source: LAYERS.RELATED_SOURCE,
        paint: {
          'circle-radius': 14,
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.4,
          'circle-blur': 1
        }
      });

      // Main circle layer for related events
      map.addLayer({
        id: LAYERS.RELATED_CIRCLES,
        type: 'circle',
        source: LAYERS.RELATED_SOURCE,
        paint: {
          'circle-radius': 8,
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.9,
          'circle-stroke-color': '#222222',
          'circle-stroke-width': 2
        }
      });

      // Pre-process related events with colors
      this._updateRelatedEventsData();
    }

    console.log('SequenceAnimator: Layers setup complete');
  },

  /**
   * Remove all sequence animation layers.
   * @private
   */
  _removeLayers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Remove layers (order matters - remove in reverse of add order)
    const layerIds = [
      LAYERS.RELATED_CIRCLES,
      LAYERS.RELATED_GLOW,
      LAYERS.MAINSHOCK_PULSE,
      LAYERS.CIRCLES_GROWING,
      LAYERS.CIRCLES_GLOW,
      LAYERS.DAMAGE_RADIUS,
      LAYERS.FELT_RADIUS,
      LAYERS.CONNECTIONS
    ];

    for (const id of layerIds) {
      if (map.getLayer(id)) {
        map.removeLayer(id);
      }
    }

    // Remove sources
    if (map.getSource(LAYERS.SOURCE)) {
      map.removeSource(LAYERS.SOURCE);
    }
    if (map.getSource(LAYERS.LINES_SOURCE)) {
      map.removeSource(LAYERS.LINES_SOURCE);
    }
    if (map.getSource(LAYERS.RELATED_SOURCE)) {
      map.removeSource(LAYERS.RELATED_SOURCE);
    }
  },

  /**
   * Start the animation loop for smooth transitions.
   * @private
   */
  _startAnimationLoop() {
    this.lastFrameTime = performance.now();

    const animate = (timestamp) => {
      if (!this.active) return;

      const deltaTime = timestamp - this.lastFrameTime;
      this.lastFrameTime = timestamp;

      // Update circle growth animations
      const needsUpdate = this._updateCircleGrowth(deltaTime);

      // Re-render if any circles are still growing
      if (needsUpdate) {
        this._updateDisplay();
      }

      // Continue animation loop
      this.animationFrameId = requestAnimationFrame(animate);
    };

    this.animationFrameId = requestAnimationFrame(animate);
  },

  /**
   * Update circle growth animations.
   * @param {number} deltaTime - Time since last frame in ms
   * @returns {boolean} True if any circles are still growing
   * @private
   */
  _updateCircleGrowth(deltaTime) {
    let stillGrowing = false;
    const growthPerFrame = deltaTime / ANIMATION.CIRCLE_GROW_DURATION;

    for (const event of this.visibleEvents) {
      const eventId = event.properties.event_id;
      const currentScale = this.circleScales[eventId] || 0;

      if (currentScale < 1) {
        // Ease-out growth curve
        const newScale = Math.min(1, currentScale + growthPerFrame * (1.5 - currentScale));
        this.circleScales[eventId] = newScale;
        stillGrowing = true;
      }
    }

    return stillGrowing;
  },

  /**
   * Create bounds from a center point and radius in km.
   * @param {Array} coords - [lng, lat] coordinates
   * @param {number} radiusKm - Radius in kilometers
   * @returns {maplibregl.LngLatBounds}
   * @private
   */
  _boundsFromCenterRadius(coords, radiusKm) {
    const [lng, lat] = coords;

    // Convert km to approximate degrees
    // Latitude: 1 degree ~ 111 km
    // Longitude: 1 degree ~ 111 * cos(lat) km
    const latDelta = radiusKm / 111;
    const lngDelta = radiusKm / (111 * Math.cos(lat * Math.PI / 180));

    const sw = [lng - lngDelta, lat - latDelta];
    const ne = [lng + lngDelta, lat + latDelta];

    return new maplibregl.LngLatBounds(sw, ne);
  },

  /**
   * Interpolate between two bounds based on progress (0-1).
   * @param {maplibregl.LngLatBounds} start - Starting bounds
   * @param {maplibregl.LngLatBounds} end - Ending bounds
   * @param {number} t - Progress 0-1
   * @returns {maplibregl.LngLatBounds}
   * @private
   */
  _interpolateBounds(start, end, t) {
    // Ease-out curve for smoother feel
    const eased = 1 - Math.pow(1 - t, 2);

    const startSW = start.getSouthWest();
    const startNE = start.getNorthEast();
    const endSW = end.getSouthWest();
    const endNE = end.getNorthEast();

    const sw = [
      startSW.lng + (endSW.lng - startSW.lng) * eased,
      startSW.lat + (endSW.lat - startSW.lat) * eased
    ];
    const ne = [
      startNE.lng + (endNE.lng - startNE.lng) * eased,
      startNE.lat + (endNE.lat - startNE.lat) * eased
    ];

    return new maplibregl.LngLatBounds(sw, ne);
  },

  /**
   * Update viewport based on time progress.
   * Smoothly interpolates from initial bounds (damage radius) to final bounds (felt radius).
   * @param {number} progress - Time progress 0-1
   * @private
   */
  _updateViewportForProgress(progress) {
    if (!this.initialBounds || !this.finalBounds) return;

    // Only update if progress has changed significantly (avoid jitter)
    const progressDelta = Math.abs(progress - this.lastViewportProgress);
    if (progressDelta < 0.005) return;  // Smaller threshold for smoother updates

    this.lastViewportProgress = progress;

    // Interpolate bounds
    const currentBounds = this._interpolateBounds(this.initialBounds, this.finalBounds, progress);

    // Apply to map INSTANTLY - no animation duration to prevent pulsing
    // The smoothness comes from frequent small updates, not from fitBounds animation
    MapAdapter.map.fitBounds(currentBounds, {
      padding: ANIMATION.VIEWPORT_PADDING,
      duration: 0,  // Instant - prevents overlapping animations causing pulsing
      maxZoom: ANIMATION.MAX_ZOOM,
      minZoom: ANIMATION.MIN_ZOOM,
      linear: true
    });
  },

  /**
   * Update the display with current animation state.
   * @private
   */
  _updateDisplay() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Build features with animation properties
    const features = this.visibleEvents.map(event => {
      const props = event.properties;
      const eventId = props.event_id;
      const scale = this.circleScales[eventId] || 1;
      const isMainshock = props.event_id === this.mainshock?.properties?.event_id;

      // Base radius from magnitude - small fixed-size epicenter marker
      const magnitude = props.magnitude || 4;
      const baseRadius = this._magnitudeToRadius(magnitude);

      // Color from magnitude
      const color = this._magnitudeToColor(magnitude);

      // Calculate opacity (fade in effect)
      const opacity = Math.min(1, scale * 1.5);

      // Pulse effect for mainshock
      const pulsePhase = (Date.now() % 2000) / 2000;
      const pulseRadius = baseRadius + 10 + Math.sin(pulsePhase * Math.PI * 2) * 5;
      const pulseOpacity = 0.8 - pulsePhase * 0.6;

      // Geographic radius values from the event data (in km)
      // Pre-scale by animation scale since MapLibre can't nest zoom in multiplication
      const feltRadiusKm = props.felt_radius_km || 0;
      const damageRadiusKm = props.damage_radius_km || 0;

      return {
        type: 'Feature',
        geometry: event.geometry,
        properties: {
          event_id: eventId,
          radius: baseRadius * scale,
          glowRadius: (baseRadius + 6) * scale,
          color: color,
          opacity: opacity,
          // Pre-scaled km values for geographic radius circles (km * scale)
          felt_radius_scaled: feltRadiusKm * scale,
          damage_radius_scaled: damageRadiusKm * scale,
          isMainshock: isMainshock,
          pulseRadius: pulseRadius,
          pulseOpacity: isMainshock ? pulseOpacity : 0
        }
      };
    });

    // Update points source
    const source = map.getSource(LAYERS.SOURCE);
    if (source) {
      source.setData({
        type: 'FeatureCollection',
        features: features
      });
    }

    // Build connection lines (spiderweb)
    const lines = this._buildConnectionLines();
    const linesSource = map.getSource(LAYERS.LINES_SOURCE);
    if (linesSource) {
      linesSource.setData({
        type: 'FeatureCollection',
        features: lines
      });
    }
  },

  /**
   * Build connection lines from mainshock to visible aftershocks.
   * Lines "draw" themselves by interpolating the endpoint based on growth scale.
   * @returns {Array} Array of GeoJSON line features
   * @private
   */
  _buildConnectionLines() {
    if (!this.mainshock) return [];

    const mainCoords = this.mainshock.geometry.coordinates;
    const mainId = this.mainshock.properties.event_id;
    const lines = [];

    for (const event of this.visibleEvents) {
      const eventId = event.properties.event_id;

      // Don't draw line to self
      if (eventId === mainId) continue;

      const scale = this.circleScales[eventId] || 0;

      // Start drawing line early (when circle starts growing)
      if (scale > 0.05) {
        let eventCoords = [...event.geometry.coordinates];
        const magnitude = event.properties.magnitude || 4;
        const color = this._magnitudeToColor(magnitude);

        // Handle international date line crossing
        // If longitude difference > 180, adjust to take the short path
        let lngDiff = eventCoords[0] - mainCoords[0];
        if (Math.abs(lngDiff) > 180) {
          // Adjust event longitude to be on same side as mainshock
          if (lngDiff > 0) {
            eventCoords[0] -= 360;
          } else {
            eventCoords[0] += 360;
          }
        }

        // Line "draws" itself: interpolate endpoint based on scale
        // Use eased scale for smoother line drawing
        const drawProgress = Math.min(1, scale * 1.2);  // Line completes slightly before circle
        const currentEndCoords = [
          mainCoords[0] + (eventCoords[0] - mainCoords[0]) * drawProgress,
          mainCoords[1] + (eventCoords[1] - mainCoords[1]) * drawProgress
        ];

        // Line opacity increases as it draws
        const lineOpacity = Math.min(0.6, drawProgress * 0.7);
        const lineWidth = 1 + (magnitude - 3) * 0.3;

        lines.push({
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [mainCoords, currentEndCoords]
          },
          properties: {
            color: color,
            opacity: lineOpacity,
            width: lineWidth
          }
        });
      }
    }

    return lines;
  },

  /**
   * Convert magnitude to epicenter marker radius.
   * Small fixed-size markers - the geographic radius circles show actual impact.
   * @param {number} magnitude - Earthquake magnitude
   * @returns {number} Radius in pixels
   * @private
   */
  _magnitudeToRadius(magnitude) {
    // Small epicenter dots - geographic circles show real impact area
    // M3: 3px, M5: 5px, M7: 8px, M9: 10px
    if (magnitude < 4) return 3;
    if (magnitude < 5) return 4;
    if (magnitude < 6) return 5;
    if (magnitude < 7) return 7;
    if (magnitude < 8) return 9;
    return 10;
  },

  /**
   * Convert magnitude to color.
   * @param {number} magnitude - Earthquake magnitude
   * @returns {string} Color hex
   * @private
   */
  _magnitudeToColor(magnitude) {
    // Match CONFIG.earthquakeColors (yellow-orange-red scale)
    if (magnitude < 4) return '#ffeda0';      // minor - pale yellow
    if (magnitude < 5) return '#fed976';      // light - yellow
    if (magnitude < 6) return '#feb24c';      // moderate - orange
    if (magnitude < 7) return '#fd8d3c';      // strong - dark orange
    return '#f03b20';                          // major - red
  },

  /**
   * Update related events data with proper colors based on type.
   * @private
   */
  _updateRelatedEventsData() {
    if (!MapAdapter?.map || this.relatedEvents.length === 0) return;

    const source = MapAdapter.map.getSource(LAYERS.RELATED_SOURCE);
    if (!source) return;

    // Add color property based on event type
    const coloredFeatures = this.relatedEvents.map(feature => {
      const props = feature.properties || {};
      const relatedType = props._relatedType;

      let color;
      if (relatedType === 'volcano') {
        // Volcano: orange-red based on VEI
        const vei = props.VEI || props.vei || 0;
        if (vei >= 5) color = '#f03b20';       // High VEI - red
        else if (vei >= 3) color = '#fd8d3c';  // Medium VEI - orange
        else color = '#feb24c';                 // Low VEI - yellow-orange
      } else if (relatedType === 'tsunami') {
        // Tsunami: cyan-teal
        color = '#00bcd4';
      } else {
        // Unknown type - gray
        color = '#9e9e9e';
      }

      return {
        ...feature,
        properties: {
          ...props,
          color: color
        }
      };
    });

    source.setData({
      type: 'FeatureCollection',
      features: coloredFeatures
    });

    console.log(`SequenceAnimator: Updated ${coloredFeatures.length} related events with colors`);
  },

  /**
   * Check if animator is currently active.
   * @returns {boolean}
   */
  isActive() {
    return this.active;
  },

  /**
   * Get current sequence ID.
   * @returns {string|null}
   */
  getSequenceId() {
    return this.sequenceId;
  }
};
