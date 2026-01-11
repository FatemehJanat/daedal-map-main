/**
 * Overlay Controller - Orchestrates overlay data loading and rendering.
 * Listens to OverlaySelector changes and fetches/displays data using models.
 *
 * Data flow:
 * 1. Toggle overlay ON -> fetch ALL events from API
 * 2. Cache full dataset
 * 3. Filter by current TimeSlider year and render
 * 4. When TimeSlider changes -> filter cached data and update display
 */

import { SequenceAnimator, setDependencies as setSequenceAnimatorDeps } from './sequence-animator.js';
import { TrackAnimator, setDependencies as setTrackAnimatorDeps } from './track-animator.js';
import EventAnimator, { AnimationMode, setDependencies as setEventAnimatorDeps } from './event-animator.js';
import { TIME_SYSTEM } from './time-slider.js';
import { CONFIG } from './config.js';

// Dependencies set via setDependencies
let MapAdapter = null;
let ModelRegistry = null;
let OverlaySelector = null;
let TimeSlider = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  ModelRegistry = deps.ModelRegistry;
  OverlaySelector = deps.OverlaySelector;
  TimeSlider = deps.TimeSlider;

  // Wire dependencies to SequenceAnimator
  setSequenceAnimatorDeps({
    MapAdapter: deps.MapAdapter
  });

  // Wire dependencies to TrackAnimator
  setTrackAnimatorDeps({
    MapAdapter: deps.MapAdapter,
    TimeSlider: deps.TimeSlider,
    TrackModel: deps.ModelRegistry?.getModel?.('track')
  });

  // Wire dependencies to EventAnimator
  setEventAnimatorDeps({
    MapAdapter: deps.MapAdapter,
    TimeSlider: deps.TimeSlider,
    ModelRegistry: deps.ModelRegistry,
    TIME_SYSTEM: TIME_SYSTEM
  });
}

/**
 * Gardner-Knopoff window calculation for aftershocks.
 * Returns time window in days based on mainshock magnitude.
 * Formula: 10^(0.5*M - 1.5) days
 * @param {number} magnitude - Mainshock magnitude
 * @returns {number} Time window in days
 */
function gardnerKnopoffTimeWindow(magnitude) {
  return Math.pow(10, 0.5 * magnitude - 1.5);
}

// API endpoints for each overlay type
const OVERLAY_ENDPOINTS = {
  earthquakes: {
    list: '/api/earthquakes/geojson?min_magnitude=5.5',  // Default M5.5+ for faster testing
    eventType: 'earthquake',
    yearField: 'year'  // Property name for year filtering
  },
  hurricanes: {
    list: '/api/storms/tracks/geojson?min_year=1950',  // Global IBTrACS storm tracks
    trackEndpoint: '/api/storms/{storm_id}/track',     // Track drill-down endpoint
    eventType: 'hurricane',
    yearField: 'year'
  },
  volcanoes: {
    list: '/api/eruptions/geojson',  // Use eruptions (events) not static locations
    eventType: 'volcano',
    yearField: 'year'  // Filter eruptions by year
  },
  wildfires: {
    list: '/api/wildfires/geojson?include_perimeter=true',
    eventType: 'wildfire',
    yearField: 'year'
  },
  tsunamis: {
    list: '/api/tsunamis/geojson?min_year=1900',  // NOAA global tsunami database
    animationEndpoint: '/api/tsunamis/{event_id}/animation',  // Radial animation data
    eventType: 'tsunami',
    yearField: 'year'
  }
};

// Cache for loaded overlay data (full unfiltered datasets)
const dataCache = {};

// Track current displayed year per overlay
const displayedYear = {};

// Cache year ranges per overlay (for recalculating combined range when overlays change)
const yearRangeCache = {};

export const OverlayController = {
  // Currently loading overlays (prevent duplicate requests)
  loading: new Set(),

  // AbortControllers for in-flight fetch requests (overlayId -> AbortController)
  abortControllers: new Map(),

  // Last known TimeSlider year (for change detection)
  lastTimeSliderYear: null,

  // Bound listener function (for cleanup if needed)
  _timeChangeListener: null,

  // Active aftershock sequence scale ID
  activeSequenceScaleId: null,

  /**
   * Initialize the overlay controller.
   * Registers as listener to OverlaySelector and TimeSlider.
   */
  init() {
    if (!OverlaySelector) {
      console.warn('OverlayController: OverlaySelector not available');
      return;
    }

    // Listen for overlay toggle events
    OverlaySelector.addListener((overlayId, isActive) => {
      this.handleOverlayChange(overlayId, isActive);
    });

    // Listen for TimeSlider changes (decoupled via listener pattern)
    if (TimeSlider) {
      this._timeChangeListener = (time, source) => {
        this.handleTimeChange(time, source);
      };
      TimeSlider.addChangeListener(this._timeChangeListener);
      console.log('OverlayController: Registered TimeSlider listener');
    }

    // Setup aftershock sequence listener
    this.setupSequenceListener();

    // Setup cross-event linking (volcano<->earthquake)
    this.setupCrossLinkListeners();

    console.log('OverlayController initialized');
  },

  /**
   * Setup listener for aftershock sequence selection.
   * When user clicks "View sequence" on an earthquake, adds a 6h granularity tab.
   */
  setupSequenceListener() {
    const model = ModelRegistry?.getModel('point-radius');
    if (model?.onSequenceChange) {
      model.onSequenceChange((sequenceId) => {
        this.handleSequenceChange(sequenceId);
      });
      console.log('OverlayController: Registered sequence change listener');
    }
  },

  /**
   * Setup listeners for cross-event linking (volcano<->earthquake).
   */
  setupCrossLinkListeners() {
    const model = ModelRegistry?.getModel('point-radius');
    if (!model) return;

    // Volcano -> Earthquakes: when user searches from a volcano popup
    if (model.onVolcanoEarthquakes) {
      model.onVolcanoEarthquakes((data) => {
        this.handleVolcanoEarthquakes(data);
      });
      console.log('OverlayController: Registered volcano->earthquake cross-link listener');
    }

    // Earthquake -> Volcanoes: when user searches from an earthquake popup
    if (model.onNearbyVolcanoes) {
      model.onNearbyVolcanoes((data) => {
        this.handleNearbyVolcanoes(data);
      });
      console.log('OverlayController: Registered earthquake->volcano cross-link listener');
    }

    // Tsunami -> Runups: when user clicks "View runups" on a tsunami
    if (model.onTsunamiRunups) {
      model.onTsunamiRunups((data) => {
        this.handleTsunamiRunups(data);
      });
      console.log('OverlayController: Registered tsunami runups animation listener');
    }

    // Wildfire -> Animation: when user clicks "View fire progression"
    if (model.onFireAnimation) {
      model.onFireAnimation((data) => {
        this.handleFireAnimation(data);
      });
      console.log('OverlayController: Registered fire animation listener');
    }

    // Wildfire -> Progression: when daily progression data is available
    if (model.onFireProgression) {
      model.onFireProgression((data) => {
        this.handleFireProgression(data);
      });
      console.log('OverlayController: Registered fire progression listener');
    }
  },

  /**
   * Handle earthquakes found near a volcano.
   * Uses the same animation system as aftershock sequences.
   */
  handleVolcanoEarthquakes(data) {
    const { features, volcanoName, volcanoLat, volcanoLon } = data;
    console.log(`OverlayController: Displaying ${features.length} earthquakes triggered by ${volcanoName}`);

    if (features.length === 0) return;

    // Convert API features to GeoJSON format expected by SequenceAnimator
    const seqEvents = features.map(f => ({
      type: 'Feature',
      geometry: f.geometry,
      properties: f.properties
    }));

    // Find the largest earthquake to use as "mainshock" for animation centering
    let mainshock = seqEvents[0];
    for (const event of seqEvents) {
      if ((event.properties.magnitude || 0) > (mainshock.properties.magnitude || 0)) {
        mainshock = event;
      }
    }

    // Find min/max timestamps
    let minTime = Infinity;
    let maxTime = -Infinity;
    for (const event of seqEvents) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      if (!isNaN(t)) {
        if (t < minTime) minTime = t;
        if (t > maxTime) maxTime = t;
      }
    }

    // Handle case where all events have same timestamp or no valid times
    if (minTime === Infinity || maxTime === -Infinity || minTime === maxTime) {
      // Just display statically without animation
      const geojson = { type: 'FeatureCollection', features: seqEvents };
      const model = ModelRegistry?.getModel('point-radius');
      if (model) {
        model.update(geojson);
        const maplibre = window.maplibregl || maplibregl;
        const bounds = new maplibre.LngLatBounds();
        bounds.extend([volcanoLon, volcanoLat]);
        for (const f of seqEvents) {
          if (f.geometry?.coordinates) bounds.extend(f.geometry.coordinates);
        }
        if (!bounds.isEmpty()) {
          MapAdapter.map.fitBounds(bounds, { padding: 50, maxZoom: 10 });
        }
      }
      console.log(`OverlayController: Showing ${seqEvents.length} earthquakes statically (no time range)`);
      return;
    }

    // Adaptive time stepping (same as aftershock sequences)
    const MAX_STEPS = 200;
    const MIN_STEP_MS = 1 * 60 * 60 * 1000;  // 1 hour minimum
    const timeRange = maxTime - minTime;
    const adaptiveStepMs = Math.max(MIN_STEP_MS, Math.ceil(timeRange / MAX_STEPS));

    const availableTimes = [];
    for (let t = minTime; t <= maxTime; t += adaptiveStepMs) {
      availableTimes.push(t);
    }

    // Build time data structure
    const timeData = {};
    for (const t of availableTimes) {
      timeData[t] = {};
    }
    for (const event of seqEvents) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      if (!isNaN(t)) {
        const bucket = Math.floor((t - minTime) / adaptiveStepMs) * adaptiveStepMs + minTime;
        const eventId = event.properties.event_id;
        if (timeData[bucket]) {
          timeData[bucket][eventId] = event.properties;
        }
      }
    }

    // Create scale ID for this volcano-triggered sequence
    const scaleId = `volcano-${volcanoName.replace(/\s+/g, '-').substring(0, 12)}`;

    // Format label
    const label = `${volcanoName} quakes`;

    // Remove existing sequence scale if any
    if (this.activeSequenceScaleId && TimeSlider) {
      TimeSlider.removeScale(this.activeSequenceScaleId);
    }

    // Stop any active sequence animation
    if (SequenceAnimator.isActive()) {
      SequenceAnimator.stop();
    }

    // Clear normal earthquake display
    const model = ModelRegistry?.getModelForType('earthquake');
    if (model?.clear) {
      model.clear();
    }

    // Set up exit callback
    SequenceAnimator.onExit(() => {
      console.log('OverlayController: Volcano sequence exit callback triggered');
      if (this.activeSequenceScaleId && TimeSlider) {
        TimeSlider.removeScale(this.activeSequenceScaleId);
        this.activeSequenceScaleId = null;
      }
      // Exit event animation mode - restore yearly overview speed
      if (TimeSlider && TimeSlider.exitEventAnimation) {
        TimeSlider.exitEventAnimation();
      }
      // Restore TimeSlider range from cached overlay year ranges
      this.recalculateTimeRange();
      if (TimeSlider) {
        // Only switch to primary if it exists
        if (TimeSlider.scales?.find(s => s.id === 'primary')) {
          TimeSlider.setActiveScale('primary');
        }
        // Show TimeSlider if we have year data
        if (Object.keys(yearRangeCache).length > 0) {
          TimeSlider.show();
        }
      }
      // Restore normal earthquake display for current year
      const currentYear = this.getCurrentYear();
      if (dataCache.earthquakes) {
        this.renderFilteredData('earthquakes', currentYear);
      }
    });

    // Start the sequence animator - create a virtual "mainshock" at volcano location
    const volcanoMainshock = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [volcanoLon, volcanoLat] },
      properties: {
        ...mainshock.properties,
        is_volcano_origin: true,
        volcano_name: volcanoName
      }
    };
    SequenceAnimator.start(scaleId, seqEvents, volcanoMainshock);

    // Determine granularity label
    const stepHours = adaptiveStepMs / (60 * 60 * 1000);
    let granularityLabel = '6h';
    if (stepHours < 2) granularityLabel = '1h';
    else if (stepHours < 4) granularityLabel = '2h';
    else if (stepHours < 8) granularityLabel = '6h';
    else if (stepHours < 16) granularityLabel = '12h';
    else if (stepHours < 36) granularityLabel = 'daily';
    else granularityLabel = '2d';

    // Add scale to TimeSlider
    if (TimeSlider) {
      const added = TimeSlider.addScale({
        id: scaleId,
        label: label,
        granularity: granularityLabel,
        useTimestamps: true,
        currentTime: minTime,
        timeRange: {
          min: minTime,
          max: maxTime,
          available: availableTimes
        },
        timeData: timeData,
        mapRenderer: 'sequence-animation'
      });

      if (added) {
        this.activeSequenceScaleId = scaleId;
        TimeSlider.setActiveScale(scaleId);

        // Enter event animation mode with auto-calculated speed for ~10 second playback
        if (TimeSlider.enterEventAnimation) {
          TimeSlider.enterEventAnimation(minTime, maxTime);
        }

        const durationDays = (timeRange / (24 * 60 * 60 * 1000)).toFixed(1);
        console.log(`OverlayController: Started volcano-triggered sequence for ${volcanoName} with ${seqEvents.length} earthquakes, ${availableTimes.length} time steps (${durationDays} days)`);
      }
    }
  },

  /**
   * Handle volcanoes found near an earthquake.
   * Shows volcano markers temporarily on the map.
   */
  handleNearbyVolcanoes(data) {
    const { features, earthquakeLat, earthquakeLon } = data;
    console.log(`OverlayController: Displaying ${features.length} nearby volcanoes`);

    if (features.length === 0) {
      console.log('OverlayController: No volcanoes to display');
      return;
    }

    // Log found volcanoes - the popup already displays names
    const names = features.map(f => f.properties.volcano_name).join(', ');
    console.log(`OverlayController: Found volcanoes: ${names}`);
    console.log(`OverlayController: Earthquake at [${earthquakeLon}, ${earthquakeLat}]`);

    // Fit map to show the earthquake and nearby volcanoes
    // Use window.maplibregl for ES module compatibility
    const maplibre = window.maplibregl || maplibregl;
    const bounds = new maplibre.LngLatBounds();
    bounds.extend([earthquakeLon, earthquakeLat]);

    for (const f of features) {
      const coords = f.geometry?.coordinates;
      if (coords && coords.length >= 2) {
        console.log(`OverlayController: Adding volcano at [${coords[0]}, ${coords[1]}]`);
        bounds.extend(coords);
      }
    }

    if (!bounds.isEmpty()) {
      console.log(`OverlayController: Fitting bounds`, bounds.toArray());
      MapAdapter.map.fitBounds(bounds, { padding: 80, maxZoom: 8, duration: 1500 });
    } else {
      console.warn('OverlayController: Bounds are empty, cannot zoom');
    }
  },

  /**
   * Handle tsunami runups animation.
   * Uses EventAnimator with RADIAL mode to show wave propagation.
   * Similar to earthquake sequences: zoom to center, start animation,
   * slowly zoom out with expanding wave radius, reveal runups progressively.
   * @param {Object} data - { geojson, eventId, runupCount }
   */
  handleTsunamiRunups(data) {
    const { geojson, eventId, runupCount } = data;
    console.log(`OverlayController: Starting tsunami runups animation for ${eventId} with ${runupCount} runups`);

    if (!geojson || !geojson.features || geojson.features.length < 2) {
      console.warn('OverlayController: Not enough data for tsunami animation');
      return;
    }

    // Find source event (is_source: true)
    const sourceEvent = geojson.features.find(f => f.properties?.is_source === true);
    if (!sourceEvent) {
      console.warn('OverlayController: No source event found in tsunami data');
      return;
    }

    // Get source coordinates for centering
    const sourceCoords = sourceEvent.geometry?.coordinates;
    if (!sourceCoords) {
      console.warn('OverlayController: Source event has no coordinates');
      return;
    }

    // Hide any popups
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Zoom to source location first (like earthquake sequences)
    MapAdapter.map.flyTo({
      center: sourceCoords,
      zoom: 7,
      duration: 1500
    });

    // Start radial animation using EventAnimator
    const animationId = `tsunami-${eventId}`;
    const sourceYear = sourceEvent.properties?.year || new Date().getFullYear();
    const sourceDate = sourceEvent.properties?.timestamp
      ? new Date(sourceEvent.properties.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : sourceYear;

    const started = EventAnimator.start({
      id: animationId,
      label: `Tsunami ${sourceDate}`,
      mode: AnimationMode.RADIAL,
      events: geojson.features,
      eventType: 'tsunami',
      timeField: 'timestamp',
      granularity: '12m',  // 12-minute steps for smooth wave animation (5 steps per hour)
      renderer: 'point-radius',
      // Don't auto-center - we already did flyTo above
      rendererOptions: {
        eventType: 'tsunami'  // Tell renderer to use tsunami styling
      },
      onExit: () => {
        console.log('OverlayController: Tsunami animation exited');
        // Restore original tsunami overlay
        const currentYear = this.getCurrentYear();
        if (dataCache.tsunamis) {
          this.renderFilteredData('tsunamis', currentYear);
        }
        // Recalculate time range for TimeSlider
        this.recalculateTimeRange();
        if (TimeSlider && Object.keys(yearRangeCache).length > 0) {
          TimeSlider.show();
        }
      }
    });

    if (started) {
      console.log(`OverlayController: Tsunami animation started with ${geojson.features.length} features`);
    } else {
      console.error('OverlayController: Failed to start tsunami animation');
      // Try to restore the overlay
      const currentYear = this.getCurrentYear();
      if (dataCache.tsunamis) {
        this.renderFilteredData('tsunamis', currentYear);
      }
    }
  },

  /**
   * Handle wildfire animation - animates perimeter polygon opacity over fire duration.
   * Simple Option A: Fade in final perimeter from 0% to 100% over duration_days.
   */
  handleFireAnimation(data) {
    const { perimeter, eventId, durationDays, startTime } = data;
    console.log(`OverlayController: Starting fire animation for ${eventId} (${durationDays} days)`);

    if (!perimeter || !perimeter.geometry) {
      console.warn('OverlayController: No perimeter data for fire animation');
      return;
    }

    // Calculate time range
    const startMs = new Date(startTime).getTime();
    const durationMs = durationDays * 24 * 60 * 60 * 1000;
    const endMs = startMs + durationMs;

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Get perimeter center for zoom
    let centerLon = 0, centerLat = 0, count = 0;
    const coords = perimeter.geometry.coordinates;
    if (perimeter.geometry.type === 'Polygon') {
      for (const pt of coords[0]) {
        centerLon += pt[0];
        centerLat += pt[1];
        count++;
      }
    } else if (perimeter.geometry.type === 'MultiPolygon') {
      for (const poly of coords) {
        for (const pt of poly[0]) {
          centerLon += pt[0];
          centerLat += pt[1];
          count++;
        }
      }
    }
    if (count > 0) {
      centerLon /= count;
      centerLat /= count;
    }

    // Zoom to fire location
    MapAdapter.map.flyTo({
      center: [centerLon, centerLat],
      zoom: 9,
      duration: 1500
    });

    // Create fire perimeter layer
    const sourceId = 'fire-anim-perimeter';
    const layerId = 'fire-anim-fill';
    const strokeId = 'fire-anim-stroke';

    // Remove existing layers
    if (MapAdapter.map.getLayer(layerId)) MapAdapter.map.removeLayer(layerId);
    if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
    if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

    // Add perimeter source
    MapAdapter.map.addSource(sourceId, {
      type: 'geojson',
      data: perimeter
    });

    // Add fill layer (starts transparent)
    MapAdapter.map.addLayer({
      id: layerId,
      type: 'fill',
      source: sourceId,
      paint: {
        'fill-color': '#ff4400',
        'fill-opacity': 0
      }
    });

    // Add stroke layer
    MapAdapter.map.addLayer({
      id: strokeId,
      type: 'line',
      source: sourceId,
      paint: {
        'line-color': '#ff6600',
        'line-width': 2,
        'line-opacity': 0
      }
    });

    // Setup TimeSlider for fire animation
    const scaleId = `fire-${eventId.substring(0, 12)}`;
    const fireDate = new Date(startTime).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    // Generate timestamps for each day
    const timestamps = [];
    for (let t = startMs; t <= endMs; t += 24 * 60 * 60 * 1000) {
      timestamps.push(t);
    }

    if (TimeSlider) {
      const added = TimeSlider.addScale({
        id: scaleId,
        label: `Fire ${fireDate}`,
        granularity: 'daily',
        useTimestamps: true,
        currentTime: startMs,
        timeRange: {
          min: startMs,
          max: endMs,
          available: timestamps
        },
        mapRenderer: 'fire-animation'
      });

      if (added) {
        this.activeFireScaleId = scaleId;
        TimeSlider.setActiveScale(scaleId);

        // Enter event animation mode with auto-calculated speed
        if (TimeSlider.enterEventAnimation) {
          TimeSlider.enterEventAnimation(startMs, endMs);
        }
      }
    }

    // Store animation state
    this._fireAnimState = {
      sourceId,
      layerId,
      strokeId,
      startMs,
      endMs,
      scaleId
    };

    // Listen for time changes to update opacity
    this._fireTimeHandler = (time, source) => {
      if (!this._fireAnimState) return;

      const { startMs, endMs, layerId, strokeId } = this._fireAnimState;
      const progress = Math.max(0, Math.min(1, (time - startMs) / (endMs - startMs)));

      // Update fill and stroke opacity based on progress
      if (MapAdapter.map.getLayer(layerId)) {
        MapAdapter.map.setPaintProperty(layerId, 'fill-opacity', progress * 0.6);
      }
      if (MapAdapter.map.getLayer(strokeId)) {
        MapAdapter.map.setPaintProperty(strokeId, 'line-opacity', progress * 0.9);
      }
    };
    TimeSlider?.addChangeListener(this._fireTimeHandler);

    // Add exit button
    this._addFireExitButton(() => this._exitFireAnimation());

    console.log(`OverlayController: Fire animation ready, ${durationDays} days starting ${fireDate}`);
  },

  /**
   * Handle fire progression animation with daily snapshots.
   * Shows actual fire spread day-by-day using pre-computed perimeters.
   * @param {Object} data - {snapshots, eventId, totalDays, startTime}
   */
  handleFireProgression(data) {
    const { snapshots, eventId, totalDays, startTime } = data;
    console.log(`OverlayController: Starting fire progression for ${eventId} (${totalDays} daily snapshots)`);

    if (!snapshots || snapshots.length === 0) {
      console.warn('OverlayController: No snapshots for fire progression');
      return;
    }

    // Build timestamp -> snapshot lookup
    const snapshotMap = new Map();
    const timestamps = [];
    let minTime = Infinity, maxTime = -Infinity;

    for (const snap of snapshots) {
      const t = new Date(snap.date + 'T00:00:00Z').getTime();
      snapshotMap.set(t, snap);
      timestamps.push(t);
      if (t < minTime) minTime = t;
      if (t > maxTime) maxTime = t;
    }
    timestamps.sort((a, b) => a - b);

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Get center from first snapshot for zoom
    const firstSnap = snapshots[0];
    let centerLon = 0, centerLat = 0, count = 0;
    const geom = firstSnap.geometry;
    if (geom.type === 'Polygon') {
      for (const pt of geom.coordinates[0]) {
        centerLon += pt[0];
        centerLat += pt[1];
        count++;
      }
    } else if (geom.type === 'MultiPolygon') {
      for (const poly of geom.coordinates) {
        for (const pt of poly[0]) {
          centerLon += pt[0];
          centerLat += pt[1];
          count++;
        }
      }
    }
    if (count > 0) {
      centerLon /= count;
      centerLat /= count;
    }

    // Zoom to fire location
    MapAdapter.map.flyTo({
      center: [centerLon, centerLat],
      zoom: 9,
      duration: 1500
    });

    // Create fire perimeter layer
    const sourceId = 'fire-prog-perimeter';
    const layerId = 'fire-prog-fill';
    const strokeId = 'fire-prog-stroke';

    // Remove existing layers
    if (MapAdapter.map.getLayer(layerId)) MapAdapter.map.removeLayer(layerId);
    if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
    if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

    // Add perimeter source with first snapshot
    MapAdapter.map.addSource(sourceId, {
      type: 'geojson',
      data: { type: 'Feature', geometry: firstSnap.geometry, properties: { day: 1 } }
    });

    // Add fill layer
    MapAdapter.map.addLayer({
      id: layerId,
      type: 'fill',
      source: sourceId,
      paint: {
        'fill-color': '#ff4400',
        'fill-opacity': 0.5
      }
    });

    // Add stroke layer
    MapAdapter.map.addLayer({
      id: strokeId,
      type: 'line',
      source: sourceId,
      paint: {
        'line-color': '#ff6600',
        'line-width': 2,
        'line-opacity': 0.9
      }
    });

    // Setup TimeSlider
    const scaleId = `fireprog-${eventId.substring(0, 10)}`;
    const fireDate = new Date(minTime).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    if (TimeSlider) {
      const added = TimeSlider.addScale({
        id: scaleId,
        label: `Fire ${fireDate} (${totalDays}d)`,
        granularity: 'daily',
        useTimestamps: true,
        currentTime: minTime,
        timeRange: {
          min: minTime,
          max: maxTime,
          available: timestamps
        },
        mapRenderer: 'fire-progression'
      });

      if (added) {
        this.activeFireScaleId = scaleId;
        TimeSlider.setActiveScale(scaleId);

        // Enter event animation mode
        if (TimeSlider.enterEventAnimation) {
          TimeSlider.enterEventAnimation(minTime, maxTime);
        }
      }
    }

    // Store animation state
    this._fireAnimState = {
      sourceId,
      layerId,
      strokeId,
      startMs: minTime,
      endMs: maxTime,
      scaleId,
      snapshotMap,  // For progression: lookup by timestamp
      timestamps    // For progression: sorted list
    };

    // Listen for time changes to update geometry
    this._fireTimeHandler = (time, source) => {
      if (!this._fireAnimState || !this._fireAnimState.snapshotMap) return;

      const { sourceId, snapshotMap, timestamps } = this._fireAnimState;

      // Find closest snapshot <= current time
      let closestTime = timestamps[0];
      for (const t of timestamps) {
        if (t <= time) closestTime = t;
        else break;
      }

      const snap = snapshotMap.get(closestTime);
      if (snap && MapAdapter.map.getSource(sourceId)) {
        MapAdapter.map.getSource(sourceId).setData({
          type: 'Feature',
          geometry: snap.geometry,
          properties: { day: snap.day_num, area_km2: snap.area_km2, date: snap.date }
        });
      }
    };
    TimeSlider?.addChangeListener(this._fireTimeHandler);

    // Add exit button
    this._addFireExitButton(() => this._exitFireAnimation());

    console.log(`OverlayController: Fire progression ready, ${totalDays} days starting ${fireDate}`);
  },

  /**
   * Exit fire animation and cleanup.
   * @private
   */
  _exitFireAnimation() {
    console.log('OverlayController: Exiting fire animation');

    // Remove layers
    if (this._fireAnimState) {
      const { sourceId, layerId, strokeId, scaleId } = this._fireAnimState;
      if (MapAdapter.map.getLayer(layerId)) MapAdapter.map.removeLayer(layerId);
      if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
      if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

      // Remove TimeSlider scale
      if (TimeSlider && scaleId) {
        TimeSlider.removeScale(scaleId);
        if (TimeSlider.exitEventAnimation) {
          TimeSlider.exitEventAnimation();
        }
      }

      this._fireAnimState = null;
    }

    // Remove time listener
    if (this._fireTimeHandler && TimeSlider) {
      TimeSlider.removeChangeListener(this._fireTimeHandler);
      this._fireTimeHandler = null;
    }

    // Remove exit button
    const exitBtn = document.getElementById('fire-exit-btn');
    if (exitBtn) exitBtn.remove();

    // Restore wildfire overlay
    const currentYear = this.getCurrentYear();
    if (dataCache.wildfires) {
      this.renderFilteredData('wildfires', currentYear);
    }

    // Recalculate time range
    this.recalculateTimeRange();
  },

  /**
   * Add exit button for fire animation.
   * @private
   */
  _addFireExitButton(onExit) {
    // Remove existing
    const existing = document.getElementById('fire-exit-btn');
    if (existing) existing.remove();

    const btn = document.createElement('button');
    btn.id = 'fire-exit-btn';
    btn.textContent = 'Exit Fire View';
    btn.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      padding: 10px 20px;
      background: #ff6600;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      z-index: 1000;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;

    btn.addEventListener('click', onExit);
    document.body.appendChild(btn);
  },

  /**
   * Handle aftershock sequence selection/deselection.
   * Fetches full sequence data from API (not filtered by magnitude).
   * @param {string|null} sequenceId - Sequence ID or null to clear
   */
  async handleSequenceChange(sequenceId) {
    console.log('OverlayController.handleSequenceChange called with:', sequenceId);

    // Remove existing sequence scale if any
    if (this.activeSequenceScaleId && TimeSlider) {
      TimeSlider.removeScale(this.activeSequenceScaleId);
      this.activeSequenceScaleId = null;
    }

    // Stop any active sequence animation
    if (SequenceAnimator.isActive()) {
      SequenceAnimator.stop();
    }

    // If no sequence selected, restore normal earthquake display and we're done
    if (!sequenceId) {
      console.log('OverlayController: Cleared aftershock sequence');
      // Re-render all earthquakes for current year
      const currentYear = this.getCurrentYear();
      if (dataCache.earthquakes) {
        this.renderFilteredData('earthquakes', currentYear);
      }
      return;
    }

    // Fetch full sequence from API (includes ALL aftershocks regardless of magnitude filter)
    // This is extensible for future cross-event linking (volcanoes triggering earthquakes,
    // earthquakes triggering tsunamis, etc.)
    const seqEvents = await this.fetchSequenceData(sequenceId);

    if (!seqEvents || seqEvents.length === 0) {
      console.warn(`OverlayController: No events found for sequence ${sequenceId}`);
      return;
    }

    console.log(`OverlayController: Loaded ${seqEvents.length} events for sequence ${sequenceId}`);

    // Find mainshock (largest magnitude or flagged is_mainshock)
    let mainshock = seqEvents.find(f => f.properties.is_mainshock);
    if (!mainshock) {
      // Fallback: largest magnitude
      mainshock = seqEvents.reduce((max, f) =>
        (f.properties.magnitude || 0) > (max.properties.magnitude || 0) ? f : max
      );
    }

    const mainMag = mainshock.properties.magnitude || 5.5;
    const mainTime = new Date(mainshock.properties.timestamp || mainshock.properties.time).getTime();

    // Calculate aftershock window end using Gardner-Knopoff
    const windowDays = gardnerKnopoffTimeWindow(mainMag);
    const windowMs = windowDays * 24 * 60 * 60 * 1000;
    const windowEnd = mainTime + windowMs;

    // Find actual min/max timestamps in sequence
    let minTime = mainTime;
    let maxTime = mainTime;
    for (const event of seqEvents) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      if (t < minTime) minTime = t;
      if (t > maxTime) maxTime = t;
    }

    // Extend max to theoretical window end if needed
    maxTime = Math.max(maxTime, windowEnd);

    // Adaptive time stepping: target ~200 steps max for smooth animation
    // This scales the step size based on sequence duration
    const MAX_STEPS = 200;
    const MIN_STEP_MS = 1 * 60 * 60 * 1000;   // Minimum 1 hour per step
    const timeRange = maxTime - minTime;

    // Calculate adaptive step size (but never smaller than MIN_STEP)
    const adaptiveStepMs = Math.max(MIN_STEP_MS, Math.ceil(timeRange / MAX_STEPS));

    const availableTimes = [];
    for (let t = minTime; t <= maxTime; t += adaptiveStepMs) {
      availableTimes.push(t);
    }

    // Build time data: { timestamp: { event_id: props } }
    // For point events, we don't need loc_id structure - just time filtering
    const timeData = {};
    for (const t of availableTimes) {
      timeData[t] = {};
    }
    // Assign each event to nearest bucket (using adaptive step size)
    for (const event of seqEvents) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      // Find nearest bucket
      const bucket = Math.floor((t - minTime) / adaptiveStepMs) * adaptiveStepMs + minTime;
      const eventId = event.properties.event_id;
      if (timeData[bucket]) {
        timeData[bucket][eventId] = event.properties;
      }
    }

    // Create scale ID
    const scaleId = `seq-${sequenceId.substring(0, 8)}`;

    // Format label
    const mainDate = new Date(mainTime);
    const label = `M${mainMag.toFixed(1)} ${mainDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;

    // Track which overlays are currently active (to restore on exit)
    // SequenceAnimator uses separate layers, so we don't need to clear the model
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
    const overlaysToRestore = activeOverlays.filter(id =>
      id !== 'demographics' && OVERLAY_ENDPOINTS[id]
    );

    // Clear normal earthquake display before starting sequence animation
    // Note: This clears ALL point overlays since they share the model.
    // We'll restore volcano/tsunami on exit if they were enabled.
    const model = ModelRegistry?.getModelForType('earthquake');
    if (model?.clear) {
      model.clear();
    }

    // Overlay-aware animation: If volcano or tsunami overlays are enabled,
    // fetch related events and include them in the animation display
    const relatedEvents = [];
    const mainLat = mainshock.geometry?.coordinates?.[1];
    const mainLon = mainshock.geometry?.coordinates?.[0];
    const mainYear = new Date(mainTime).getFullYear();

    // Check for enabled overlays and fetch related events
    if (mainLat && mainLon) {
      if (activeOverlays.includes('volcanoes')) {
        try {
          const volcanoUrl = `/api/events/nearby-volcanoes?lat=${mainLat}&lon=${mainLon}&radius_km=200&year=${mainYear}`;
          const resp = await fetch(volcanoUrl);
          if (resp.ok) {
            const data = await resp.json();
            if (data.features && data.features.length > 0) {
              relatedEvents.push(...data.features.map(f => ({
                ...f,
                properties: { ...f.properties, _relatedType: 'volcano' }
              })));
              console.log(`OverlayController: Found ${data.features.length} related volcanoes`);
            }
          }
        } catch (err) {
          console.warn('Failed to fetch related volcanoes:', err);
        }
      }

      if (activeOverlays.includes('tsunamis')) {
        try {
          // Tsunamis caused by the earthquake - check for same year/location
          const tsunamiUrl = `/api/events/nearby-tsunamis?lat=${mainLat}&lon=${mainLon}&radius_km=300&year=${mainYear}`;
          const resp = await fetch(tsunamiUrl);
          if (resp.ok) {
            const data = await resp.json();
            if (data.features && data.features.length > 0) {
              relatedEvents.push(...data.features.map(f => ({
                ...f,
                properties: { ...f.properties, _relatedType: 'tsunami' }
              })));
              console.log(`OverlayController: Found ${data.features.length} related tsunamis`);
            }
          }
        } catch (err) {
          console.warn('Failed to fetch related tsunamis:', err);
        }
      }
    }

    // Set up exit callback before starting
    SequenceAnimator.onExit(() => {
      console.log('OverlayController: Sequence exit callback triggered');
      // Remove the sequence scale from TimeSlider
      if (this.activeSequenceScaleId && TimeSlider) {
        TimeSlider.removeScale(this.activeSequenceScaleId);
        this.activeSequenceScaleId = null;
      }
      // Exit event animation mode - restore yearly overview speed
      if (TimeSlider && TimeSlider.exitEventAnimation) {
        TimeSlider.exitEventAnimation();
      }
      // Restore TimeSlider range from cached overlay year ranges
      this.recalculateTimeRange();
      // Switch back to primary scale if it exists
      if (TimeSlider) {
        if (TimeSlider.scales?.find(s => s.id === 'primary')) {
          TimeSlider.setActiveScale('primary');
        }
        // Show TimeSlider if we have year data
        if (Object.keys(yearRangeCache).length > 0) {
          TimeSlider.show();
        }
      }
      // Restore all overlays that were active before animation
      const currentYear = this.getCurrentYear();
      for (const overlayId of overlaysToRestore) {
        if (dataCache[overlayId]) {
          this.renderFilteredData(overlayId, currentYear);
          console.log(`OverlayController: Restored ${overlayId} overlay`);
        }
      }
    });

    // Start the sequence animator with the events and any related events
    SequenceAnimator.start(sequenceId, seqEvents, mainshock, relatedEvents);

    // Determine granularity label based on adaptive step size
    const stepHours = adaptiveStepMs / (60 * 60 * 1000);
    let granularityLabel = '6h';  // Default
    if (stepHours < 2) granularityLabel = '1h';
    else if (stepHours < 4) granularityLabel = '2h';
    else if (stepHours < 8) granularityLabel = '6h';
    else if (stepHours < 16) granularityLabel = '12h';
    else if (stepHours < 36) granularityLabel = 'daily';
    else granularityLabel = '2d';

    // Add scale to TimeSlider - start at minTime (mainshock), not maxTime
    if (TimeSlider) {
      const added = TimeSlider.addScale({
        id: scaleId,
        label: label,
        granularity: granularityLabel,
        useTimestamps: true,
        currentTime: minTime,  // Start at mainshock time, not end of sequence
        timeRange: {
          min: minTime,
          max: maxTime,
          available: availableTimes
        },
        timeData: timeData,
        mapRenderer: 'sequence-animation'  // Handled by SequenceAnimator
      });

      if (added) {
        this.activeSequenceScaleId = scaleId;
        TimeSlider.setActiveScale(scaleId);

        // Enter event animation mode with auto-calculated speed for ~10 second playback
        if (TimeSlider.enterEventAnimation) {
          TimeSlider.enterEventAnimation(minTime, maxTime);
        }

        const stepHours = (adaptiveStepMs / (60 * 60 * 1000)).toFixed(1);
        const durationDays = (timeRange / (24 * 60 * 60 * 1000)).toFixed(1);
        console.log(`OverlayController: Added sequence scale ${scaleId} with ${seqEvents.length} events, ${availableTimes.length} time steps (${stepHours}h/step, ${durationDays} days)`);
      }
    }
  },

  /**
   * Fetch full sequence data from API.
   * Returns all events in the sequence regardless of magnitude filter.
   * Extensible for future cross-event linking (volcanoes, tsunamis, etc.)
   *
   * @param {string} sequenceId - Sequence ID to fetch
   * @param {string} eventType - Event type (default 'earthquake', future: 'volcano', 'tsunami')
   * @returns {Promise<Array>} Array of GeoJSON features
   */
  async fetchSequenceData(sequenceId, eventType = 'earthquake') {
    try {
      // Build API endpoint based on event type
      // Currently only earthquakes have sequences, but this is extensible
      let endpoint;
      if (eventType === 'earthquake') {
        endpoint = `/api/earthquakes/sequence/${encodeURIComponent(sequenceId)}`;
      } else {
        // Future: add endpoints for cross-event sequences
        // e.g., /api/events/sequence/{id} for cross-type sequences
        console.warn(`OverlayController: Sequence fetch not yet supported for ${eventType}`);
        return [];
      }

      console.log(`OverlayController: Fetching sequence from ${endpoint}`);
      const response = await fetch(endpoint);

      if (!response.ok) {
        console.error(`OverlayController: Failed to fetch sequence: ${response.status}`);
        return [];
      }

      const data = await response.json();

      if (!data.features || data.features.length === 0) {
        console.warn(`OverlayController: No features in sequence response`);
        return [];
      }

      return data.features;

    } catch (error) {
      console.error('OverlayController: Error fetching sequence data:', error);
      return [];
    }
  },

  /**
   * Handle TimeSlider change event from listener.
   * @param {number} time - Current time (year or timestamp)
   * @param {string} source - What triggered: 'slider' | 'playback' | 'api'
   */
  handleTimeChange(time, source) {
    // If sequence animation is active, forward timestamp to it
    // Note: Don't check time value - pre-1970 events have negative timestamps
    if (SequenceAnimator.isActive()) {
      SequenceAnimator.setTime(time);
      return;  // Don't do normal year-based filtering
    }

    // If EventAnimator is active, forward timestamp to it
    if (EventAnimator.getIsActive()) {
      EventAnimator.setTime(time);
      return;
    }

    const year = this.getYearFromTime(time);
    if (year !== this.lastTimeSliderYear) {
      this.lastTimeSliderYear = year;
      this.onTimeChange(year);
    }
  },

  /**
   * Convert time to year (handles both year int and timestamp ms).
   * Uses same detection as TimeSlider: |value| < 50000 = year, else timestamp.
   * @param {number} time - Time value
   * @returns {number} Year
   */
  getYearFromTime(time) {
    if (!time && time !== 0) return null;
    // If absolute value is small, it's a year (-50000 to 50000)
    // Otherwise it's a timestamp (handles both positive and negative)
    if (Math.abs(time) < 50000) {
      return time;
    }
    // It's a timestamp - convert to year
    return new Date(time).getUTCFullYear();
  },

  /**
   * Get current year from TimeSlider.
   * TimeSlider.currentTime is always stored as timestamp (ms) internally.
   * @returns {number|null}
   */
  getCurrentYear() {
    if (!TimeSlider?.currentTime) return null;

    // currentTime is always a timestamp since Phase 8 unification
    // Use TimeSlider's helper if available, otherwise convert directly
    if (TimeSlider.timestampToYear) {
      return TimeSlider.timestampToYear(TimeSlider.currentTime);
    }
    return new Date(TimeSlider.currentTime).getFullYear();
  },

  /**
   * Handle TimeSlider year change - update all active overlays.
   * @param {number} year - New year
   */
  onTimeChange(year) {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];

    for (const overlayId of activeOverlays) {
      if (overlayId === 'demographics') continue;

      const endpoint = OVERLAY_ENDPOINTS[overlayId];
      if (!endpoint || !endpoint.yearField) continue;

      // Only update if we have cached data and year changed
      if (dataCache[overlayId] && displayedYear[overlayId] !== year) {
        this.renderFilteredData(overlayId, year);
      }
    }
  },

  /**
   * Handle overlay toggle event.
   * @param {string} overlayId - Overlay ID (e.g., 'earthquakes')
   * @param {boolean} isActive - Whether overlay is now active
   */
  async handleOverlayChange(overlayId, isActive) {
    console.log(`OverlayController: ${overlayId} ${isActive ? 'ON' : 'OFF'}`);

    // Demographics controls choropleth visibility AND loads countries
    if (overlayId === 'demographics') {
      if (isActive) {
        // Load countries if not already loaded (lazy load on first demographics enable)
        const App = window.App;  // Get App reference
        if (App && typeof App.loadCountries === 'function') {
          // Check if countries are already loaded by checking if there's geojson data
          if (!App.currentData?.geojson) {
            console.log('OverlayController: Loading countries for demographics overlay');
            await App.loadCountries();
          }
        }
        if (MapAdapter) {
          MapAdapter.setChoroplethVisible(true);
        }
      } else {
        if (MapAdapter) {
          MapAdapter.setChoroplethVisible(false);
        }
      }
      return;
    }

    if (isActive) {
      await this.loadOverlay(overlayId);
    } else {
      this.clearOverlay(overlayId);
    }
  },

  /**
   * Load and display an overlay.
   * Fetches ALL data, caches it, then filters by current year for display.
   * @param {string} overlayId - Overlay ID
   */
  async loadOverlay(overlayId) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    if (!endpoint) {
      console.warn(`OverlayController: No endpoint for overlay: ${overlayId}`);
      return;
    }

    // Prevent duplicate loads
    if (this.loading.has(overlayId)) {
      console.log(`OverlayController: Already loading ${overlayId}`);
      return;
    }

    // Abort any existing request for this overlay
    if (this.abortControllers.has(overlayId)) {
      this.abortControllers.get(overlayId).abort();
    }

    // Create new AbortController for this request
    const abortController = new AbortController();
    this.abortControllers.set(overlayId, abortController);

    this.loading.add(overlayId);

    try {
      // Fetch ALL data (no year filter - we filter client-side)
      const url = endpoint.list;
      console.log(`OverlayController: Fetching ${url}`);

      const response = await fetch(url, { signal: abortController.signal });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const geojson = await response.json();

      // Check if overlay was disabled while we were fetching
      const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
      if (!activeOverlays.includes(overlayId)) {
        console.log(`OverlayController: ${overlayId} was disabled during fetch, discarding data`);
        return;
      }

      // Cache the full dataset
      dataCache[overlayId] = geojson;

      console.log(`OverlayController: Cached ${geojson.features?.length || 0} ${overlayId} features`);

      // Update TimeSlider range if this overlay has year filtering
      if (endpoint.yearField && TimeSlider) {
        // Extract unique years from actual data (not hardcoded config)
        const availableYears = new Set();
        for (const feature of geojson.features) {
          const year = feature.properties[endpoint.yearField];
          if (year != null) {
            availableYears.add(parseInt(year));
          }
        }
        const sortedYears = Array.from(availableYears).sort((a, b) => a - b);

        if (sortedYears.length > 0) {
          // Derive min/max from actual data, not hardcoded config
          const minYear = sortedYears[0];
          const maxYear = sortedYears[sortedYears.length - 1];

          // Cache year range for this overlay (for recalculating when overlays change)
          yearRangeCache[overlayId] = {
            min: minYear,
            max: maxYear,
            available: sortedYears
          };

          TimeSlider.setTimeRange({
            min: minYear,
            max: maxYear,
            granularity: 'yearly',
            available: sortedYears  // Only step to years with data
          });
          TimeSlider.show();  // Show TimeSlider when overlay with year data loads
          console.log(`OverlayController: TimeSlider range ${minYear}-${maxYear} (from data), ${sortedYears.length} years with data`);
        }
      }

      // Render filtered by current year (or all if no year filter)
      const currentYear = this.getCurrentYear();
      this.renderFilteredData(overlayId, currentYear);

    } catch (error) {
      // Don't log abort errors - they're expected when user disables overlay
      if (error.name === 'AbortError') {
        console.log(`OverlayController: Fetch aborted for ${overlayId}`);
        return;
      }
      console.error(`OverlayController: Failed to load ${overlayId}:`, error);
      this.showError(overlayId, error.message);
    } finally {
      this.loading.delete(overlayId);
      this.abortControllers.delete(overlayId);
    }
  },

  /**
   * Filter cached data by year and render.
   * @param {string} overlayId - Overlay ID
   * @param {number|null} year - Year to filter by, or null for all
   */
  renderFilteredData(overlayId, year) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    const cachedData = dataCache[overlayId];

    if (!endpoint || !cachedData) return;

    let filteredGeojson;

    // Filter by year if overlay supports it and year is set
    if (endpoint.yearField && year) {
      const yearNum = parseInt(year);
      const filtered = cachedData.features.filter(f => {
        const propYear = f.properties[endpoint.yearField];
        if (propYear == null) return false;
        return parseInt(propYear) === yearNum;
      });
      filteredGeojson = {
        type: 'FeatureCollection',
        features: filtered
      };
      console.log(`OverlayController: Filtered ${cachedData.features.length} -> ${filtered.length} for year ${yearNum}`);
    } else {
      filteredGeojson = cachedData;
    }

    // Track displayed year
    displayedYear[overlayId] = year;

    // Render using appropriate model
    const rendered = ModelRegistry?.render(filteredGeojson, endpoint.eventType, {
      onEventClick: (props) => this.handleEventClick(overlayId, props)
    });

    if (rendered) {
      const yearStr = year ? ` for ${year}` : ' (all years)';
      console.log(`OverlayController: Rendered ${filteredGeojson.features?.length || 0} ${overlayId}${yearStr}`);
    }
  },

  /**
   * Clear an overlay from the map.
   * @param {string} overlayId - Overlay ID
   */
  clearOverlay(overlayId) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    if (!endpoint) return;

    // Abort any in-flight fetch request for this overlay
    if (this.abortControllers.has(overlayId)) {
      this.abortControllers.get(overlayId).abort();
      this.abortControllers.delete(overlayId);
      console.log(`OverlayController: Aborted pending fetch for ${overlayId}`);
    }

    // Get the model and clear it
    const model = ModelRegistry?.getModelForType(endpoint.eventType);
    if (model?.clear) {
      model.clear();
    }

    // Clear caches
    delete dataCache[overlayId];
    delete yearRangeCache[overlayId];

    // Recalculate TimeSlider range from remaining active overlays
    this.recalculateTimeRange();

    console.log(`OverlayController: Cleared ${overlayId}`);
  },

  /**
   * Recalculate TimeSlider range from all active overlays.
   * Called when an overlay is disabled to contract the range.
   */
  recalculateTimeRange() {
    if (!TimeSlider) return;

    // Get remaining cached year ranges
    const activeRanges = Object.values(yearRangeCache);

    if (activeRanges.length === 0) {
      // No active overlays with year data - hide slider or reset to default
      console.log('OverlayController: No active overlays, TimeSlider range unchanged');
      return;
    }

    // Calculate combined range (union of all active overlays)
    let combinedMin = Infinity;
    let combinedMax = -Infinity;
    const allYears = new Set();

    for (const range of activeRanges) {
      if (range.min < combinedMin) combinedMin = range.min;
      if (range.max > combinedMax) combinedMax = range.max;
      for (const year of range.available) {
        allYears.add(year);
      }
    }

    const sortedYears = Array.from(allYears).sort((a, b) => a - b);

    // Update TimeSlider with REPLACE mode (contract range if needed)
    TimeSlider.setTimeRange({
      min: combinedMin,
      max: combinedMax,
      granularity: 'yearly',
      available: sortedYears,
      replace: true  // Allow contracting the range
    });

    console.log(`OverlayController: Recalculated TimeSlider range ${combinedMin}-${combinedMax} from ${activeRanges.length} overlays`);
  },

  /**
   * Handle click on an event feature.
   * @param {string} overlayId - Overlay ID
   * @param {Object} props - Feature properties
   * @param {Array} coords - Optional coordinates [lng, lat] for popup placement
   */
  handleEventClick(overlayId, props, coords = null) {
    console.log(`OverlayController: Clicked ${overlayId} event:`, props);

    // For hurricanes, show popup with View Track button
    if (overlayId === 'hurricanes' && props.storm_id) {
      this._showHurricanePopup(props, coords);
    }
  },

  /**
   * Show popup for hurricane track with View Track button.
   * @private
   */
  _showHurricanePopup(props, coords) {
    const map = MapAdapter?.map;
    if (!map) return;

    const stormId = props.storm_id;
    const stormName = props.name || stormId;

    // Build popup content
    const lines = [`<strong>${stormName}</strong>`];
    if (props.year) lines.push(`Year: ${props.year}`);
    if (props.basin) lines.push(`Basin: ${props.basin}`);
    if (props.max_category) lines.push(`Max Category: ${props.max_category}`);
    if (props.max_wind_kt) lines.push(`Max Wind: ${props.max_wind_kt} kt`);
    if (props.min_pressure_mb) lines.push(`Min Pressure: ${props.min_pressure_mb} mb`);
    if (props.start_date && props.end_date) {
      lines.push(`Dates: ${props.start_date.split('T')[0]} to ${props.end_date.split('T')[0]}`);
    }
    if (props.made_landfall) lines.push('<em>Made landfall</em>');

    // Add View Track button
    const buttonId = `view-track-${stormId.replace(/[^a-zA-Z0-9]/g, '-')}`;
    lines.push(`<br><button id="${buttonId}" style="background:#3b82f6;color:white;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;margin-top:8px;">View Track</button>`);

    // Determine popup position - use center of track if no coords provided
    let popupCoords = coords;
    if (!popupCoords) {
      // Try to get coords from the feature geometry center (approximate)
      popupCoords = [-80, 25]; // Default to Atlantic
    }

    // Create popup
    const popup = new maplibregl.Popup({ closeOnClick: true, maxWidth: '280px' })
      .setLngLat(popupCoords)
      .setHTML(lines.join('<br>'))
      .addTo(map);

    // Setup button click handler after popup is added to DOM
    setTimeout(() => {
      const button = document.getElementById(buttonId);
      if (button) {
        button.addEventListener('click', () => {
          popup.remove();
          this.drillDownHurricane(stormId, stormName);
        });
      }
    }, 0);
  },

  /**
   * Drill down into a hurricane track for animation.
   * Uses global IBTrACS API endpoint.
   * @param {string} stormId - Storm ID (e.g., "2005236N23285" for Katrina)
   * @param {string} stormName - Storm name
   */
  async drillDownHurricane(stormId, stormName) {
    try {
      // Use global tropical storms API
      const response = await fetch(`/api/storms/${encodeURIComponent(stormId)}/track`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      if (!data.positions || data.positions.length === 0) {
        console.warn(`OverlayController: No positions found for storm ${stormId}`);
        return;
      }

      // Build GeoJSON from positions
      const features = data.positions.map((pos, idx) => ({
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [pos.longitude, pos.latitude]
        },
        properties: {
          storm_id: stormId,
          name: data.name || stormName,
          timestamp: pos.timestamp,
          wind_kt: pos.wind_kt,
          pressure_mb: pos.pressure_mb,
          category: pos.category,
          status: pos.status,
          // Wind radii (may be null for older storms)
          r34_ne: pos.r34_ne,
          r34_se: pos.r34_se,
          r34_sw: pos.r34_sw,
          r34_nw: pos.r34_nw,
          r50_ne: pos.r50_ne,
          r50_se: pos.r50_se,
          r50_sw: pos.r50_sw,
          r50_nw: pos.r50_nw,
          r64_ne: pos.r64_ne,
          r64_se: pos.r64_se,
          r64_sw: pos.r64_sw,
          r64_nw: pos.r64_nw,
          position_index: idx
        }
      }));

      const trackGeojson = {
        type: 'FeatureCollection',
        features: features
      };

      // Get TrackModel and render track
      const trackModel = ModelRegistry?.getModel('track');
      if (trackModel) {
        trackModel.renderTrack(trackGeojson);
        trackModel.fitBounds(trackGeojson);

        // Store track data for click handling
        this._currentTrackData = {
          stormId,
          stormName,
          positions: features
        };

        // Add click handler for track position dots to show wind radii
        this._setupTrackPositionClickHandler(trackModel);
      }

      console.log(`OverlayController: Loaded track for ${stormName} (${data.count} positions)`);

      // Add "Animate Track" button for 6-hour animation mode
      this._addAnimateTrackButton(stormId, stormName, data.positions);

    } catch (error) {
      console.error(`OverlayController: Failed to load hurricane track:`, error);
    }
  },

  /**
   * Add track control buttons (Animate Track + Back to Storms).
   * Positioned at top center to avoid overlapping TimeSlider.
   * @private
   */
  _addAnimateTrackButton(stormId, stormName, positions) {
    // Remove existing buttons if any
    const existing = document.getElementById('track-controls-container');
    if (existing) existing.remove();

    // Create container for both buttons - positioned at top center
    const container = document.createElement('div');
    container.id = 'track-controls-container';
    container.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      gap: 12px;
      z-index: 1000;
    `;

    // Animate Track button
    const animateBtn = document.createElement('button');
    animateBtn.id = 'animate-track-btn';
    animateBtn.textContent = 'Animate Track';
    animateBtn.style.cssText = `
      padding: 10px 20px;
      background: #3b82f6;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;

    animateBtn.addEventListener('click', () => {
      container.remove();
      this._startTrackAnimation(stormId, stormName, positions);
    });

    // Back to Storms button
    const backBtn = document.createElement('button');
    backBtn.id = 'back-to-storms-btn';
    backBtn.textContent = 'Back to Storms';
    backBtn.style.cssText = `
      padding: 10px 20px;
      background: #6b7280;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;

    backBtn.addEventListener('click', () => {
      container.remove();
      this._exitTrackView();
    });

    container.appendChild(animateBtn);
    container.appendChild(backBtn);
    document.body.appendChild(container);
  },

  /**
   * Exit track view and return to yearly storm overview.
   * @private
   */
  _exitTrackView() {
    // Clear track display
    const trackModel = ModelRegistry?.getModel('track');
    if (trackModel) {
      trackModel.clearTrack();
      trackModel.clearWindRadii();
    }

    // Clear track data
    this._currentTrackData = null;

    // Refresh hurricanes overlay to show yearly overview
    if (activeOverlays.hurricanes) {
      this._displayOverlayData('hurricanes', TimeSlider?.currentTime);
    }

    console.log('OverlayController: Returned to storms overview');
  },

  /**
   * Start track animation using TrackAnimator.
   * @private
   */
  _startTrackAnimation(stormId, stormName, positions) {
    // Clear the static track display first
    const trackModel = ModelRegistry?.getModel('track');
    if (trackModel) {
      trackModel.clearTrack();
      trackModel.clearWindRadii();
    }

    // Start TrackAnimator
    TrackAnimator.start(stormId, positions, {
      stormName,
      onExit: () => {
        // When animation exits, reload the static track view
        console.log('TrackAnimator: Exited, reloading static track');
        this.drillDownHurricane(stormId, stormName);
      }
    });
  },

  /**
   * Setup click handler for track position dots.
   * Shows wind radii and popup when clicking on a position.
   * @private
   */
  _setupTrackPositionClickHandler(trackModel) {
    const map = MapAdapter?.map;
    if (!map) return;

    // Remove existing handler if any
    if (this._trackPositionClickHandler) {
      map.off('click', CONFIG.layers.hurricaneCircle + '-track-dots', this._trackPositionClickHandler);
    }

    this._trackPositionClickHandler = (e) => {
      if (!e.features || e.features.length === 0) return;

      const feature = e.features[0];
      const props = feature.properties;
      const coords = feature.geometry.coordinates;

      // Show wind radii if available
      const hasWindRadii = props.r34_ne || props.r34_se || props.r34_sw || props.r34_nw;
      if (hasWindRadii) {
        trackModel.renderWindRadii({
          longitude: coords[0],
          latitude: coords[1],
          properties: props
        });
      } else {
        trackModel.clearWindRadii();
      }

      // Build popup content
      const lines = [`<strong>${props.name || 'Storm Position'}</strong>`];
      if (props.timestamp) {
        const date = new Date(props.timestamp);
        lines.push(date.toLocaleString());
      }
      if (props.category) lines.push(`Category: ${props.category}`);
      if (props.wind_kt) lines.push(`Wind: ${props.wind_kt} kt`);
      if (props.pressure_mb) lines.push(`Pressure: ${props.pressure_mb} mb`);
      if (props.status) lines.push(`Status: ${props.status}`);

      // Wind radii info
      if (hasWindRadii) {
        lines.push('<br><em>Wind Radii (nm):</em>');
        if (props.r34_ne) lines.push(`34kt: NE=${props.r34_ne} SE=${props.r34_se} SW=${props.r34_sw} NW=${props.r34_nw}`);
        if (props.r50_ne) lines.push(`50kt: NE=${props.r50_ne} SE=${props.r50_se} SW=${props.r50_sw} NW=${props.r50_nw}`);
        if (props.r64_ne) lines.push(`64kt: NE=${props.r64_ne} SE=${props.r64_se} SW=${props.r64_sw} NW=${props.r64_nw}`);
      } else {
        lines.push('<em>(No wind radii data for this position)</em>');
      }

      // Show popup
      new maplibregl.Popup({ closeOnClick: true })
        .setLngLat(coords)
        .setHTML(lines.join('<br>'))
        .addTo(map);
    };

    map.on('click', CONFIG.layers.hurricaneCircle + '-track-dots', this._trackPositionClickHandler);

    // Hover cursor
    map.on('mouseenter', CONFIG.layers.hurricaneCircle + '-track-dots', () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', CONFIG.layers.hurricaneCircle + '-track-dots', () => {
      map.getCanvas().style.cursor = '';
    });
  },

  /**
   * Refresh all active overlays (e.g., when time changes).
   */
  async refreshActive() {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];

    for (const overlayId of activeOverlays) {
      if (overlayId !== 'demographics' && OVERLAY_ENDPOINTS[overlayId]) {
        await this.loadOverlay(overlayId);
      }
    }
  },

  /**
   * Show error notification for failed overlay load.
   * @param {string} overlayId - Overlay ID
   * @param {string} message - Error message
   */
  showError(overlayId, message) {
    // For now, just console error
    // TODO: Add toast notification UI
    console.error(`Failed to load ${overlayId}: ${message}`);
  },

  /**
   * Get cached data for an overlay.
   * @param {string} overlayId - Overlay ID
   * @returns {Object|null} Cached GeoJSON or null
   */
  getCachedData(overlayId) {
    return dataCache[overlayId] || null;
  },

  /**
   * Clear all overlay caches.
   */
  clearCache() {
    for (const key in dataCache) {
      delete dataCache[key];
    }
  }
};
