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

// API endpoints for each overlay type (min_year=2020 for faster loading)
const OVERLAY_ENDPOINTS = {
  earthquakes: {
    list: '/api/earthquakes/geojson?min_magnitude=5.5&min_year=2020',
    eventType: 'earthquake',
    yearField: 'year'
  },
  hurricanes: {
    list: '/api/storms/tracks/geojson?min_year=2020',
    trackEndpoint: '/api/storms/{storm_id}/track',
    eventType: 'hurricane',
    yearField: 'year'
  },
  volcanoes: {
    list: '/api/eruptions/geojson?min_year=2020',
    eventType: 'volcano',
    yearField: 'year'
  },
  wildfires: {
    list: '/api/wildfires/geojson?min_year=2020',
    eventType: 'wildfire',
    yearField: 'year'
  },
  tsunamis: {
    list: '/api/tsunamis/geojson?min_year=2020',
    animationEndpoint: '/api/tsunamis/{event_id}/animation',
    eventType: 'tsunami',
    yearField: 'year'
  },
  tornadoes: {
    list: '/api/tornadoes/geojson?min_year=2020',
    detailEndpoint: '/api/tornadoes/{event_id}',
    eventType: 'tornado',
    yearField: 'year'
  },
  floods: {
    list: '/api/floods/geojson?min_year=2020',
    geometryEndpoint: '/api/floods/{event_id}/geometry',
    eventType: 'flood',
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

    // Setup track drill-down listener for hurricanes
    this.setupTrackDrillDownListener();

    console.log('OverlayController initialized');
  },

  /**
   * Setup listener for hurricane track drill-down.
   */
  setupTrackDrillDownListener() {
    document.addEventListener('track-drill-down', async (e) => {
      const { stormId, stormName, eventType, props } = e.detail;
      console.log(`OverlayController: Track drill-down for ${stormName} (${stormId})`);
      await this.handleHurricaneDrillDown(stormId, stormName, props);
    });
    console.log('OverlayController: Registered track drill-down listener');
  },

  /**
   * Setup listener for aftershock sequence selection.
   * When user clicks "View sequence" on an earthquake, adds a 6h granularity tab.
   */
  setupSequenceListener() {
    const model = ModelRegistry?.getModel('point-radius');
    if (model?.onSequenceChange) {
      model.onSequenceChange((sequenceId, eventId) => {
        this.handleSequenceChange(sequenceId, eventId);
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

    // Tornado -> Sequence: when user clicks a tornado that's part of a sequence
    if (model.onTornadoSequence) {
      model.onTornadoSequence((data) => {
        this.handleTornadoSequence(data);
      });
      console.log('OverlayController: Registered tornado sequence listener');
    }

    // Tornado -> Point Animation: for tornadoes without track data
    if (model.onTornadoPointAnimation) {
      model.onTornadoPointAnimation((data) => {
        this.handleTornadoPointAnimation(data);
      });
      console.log('OverlayController: Registered tornado point animation listener');
    }

    // Flood -> Animation: when user clicks "View flood" on a flood event
    if (model.onFloodAnimation) {
      model.onFloodAnimation((data) => {
        this.handleFloodAnimation(data);
      });
      console.log('OverlayController: Registered flood animation listener');
    }

    // Volcano -> Impact: when user clicks "Impact" on a volcano event
    if (model.onVolcanoImpact) {
      model.onVolcanoImpact((data) => {
        this.handleVolcanoImpact(data);
      });
      console.log('OverlayController: Registered volcano impact animation listener');
    }

    // Wildfire -> Impact: fallback when no progression data (area circle)
    if (model.onWildfireImpact) {
      model.onWildfireImpact((data) => {
        this.handleWildfireImpact(data);
      });
      console.log('OverlayController: Registered wildfire impact animation listener');
    }

    // Wildfire -> Perimeter: single shape fade-in (second preference)
    if (model.onWildfirePerimeter) {
      model.onWildfirePerimeter((data) => {
        this.handleWildfirePerimeter(data);
      });
      console.log('OverlayController: Registered wildfire perimeter animation listener');
    }

    // Flood -> Impact: fallback when no geometry data (area circle)
    if (model.onFloodImpact) {
      model.onFloodImpact((data) => {
        this.handleFloodImpact(data);
      });
      console.log('OverlayController: Registered flood impact animation listener');
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

    // Convert API features to GeoJSON format
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

    // Handle case where all events have same timestamp or no valid times
    let minTime = Infinity, maxTime = -Infinity;
    for (const event of seqEvents) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      if (!isNaN(t)) {
        if (t < minTime) minTime = t;
        if (t > maxTime) maxTime = t;
      }
    }

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

    // Stop any active animation
    if (EventAnimator.getIsActive()) {
      EventAnimator.stop();
    }

    // Clear normal earthquake display
    const model = ModelRegistry?.getModelForType('earthquake');
    if (model?.clear) {
      model.clear();
    }

    // Create mainshock at volcano location
    const volcanoMainshock = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [volcanoLon, volcanoLat] },
      properties: {
        ...mainshock.properties,
        is_volcano_origin: true,
        volcano_name: volcanoName
      }
    };

    // Determine granularity based on time range
    const timeRange = maxTime - minTime;
    const stepHours = Math.max(1, Math.ceil((timeRange / (60 * 60 * 1000)) / 200));
    let granularityLabel = '6h';
    if (stepHours < 2) granularityLabel = '1h';
    else if (stepHours < 4) granularityLabel = '2h';
    else if (stepHours < 8) granularityLabel = '6h';
    else if (stepHours < 16) granularityLabel = '12h';
    else if (stepHours < 36) granularityLabel = 'daily';
    else granularityLabel = '2d';

    // Start unified EventAnimator with earthquake mode
    EventAnimator.start({
      id: `volcano-${volcanoName.replace(/\s+/g, '-').substring(0, 12)}`,
      label: `${volcanoName} quakes`,
      mode: AnimationMode.EARTHQUAKE,
      events: seqEvents,
      mainshock: volcanoMainshock,
      eventType: 'earthquake',
      timeField: 'timestamp',
      granularity: granularityLabel,
      renderer: 'point-radius',
      onExit: () => {
        console.log('OverlayController: Volcano earthquake sequence exited');
        // Restore TimeSlider range from cached overlay year ranges
        this.recalculateTimeRange();
        if (TimeSlider) {
          if (TimeSlider.scales?.find(s => s.id === 'primary')) {
            TimeSlider.setActiveScale('primary');
          }
          if (Object.keys(yearRangeCache).length > 0) {
            TimeSlider.show();
          }
        }
        // Restore normal earthquake display for current year
        const currentYear = this.getCurrentYear();
        if (dataCache.earthquakes) {
          this.renderFilteredData('earthquakes', currentYear);
        }
      }
    });

    console.log(`OverlayController: Started volcano earthquake animation with ${seqEvents.length} events`);
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
   * Handle tornado sequence animation.
   * Uses EventAnimator with TORNADO_SEQUENCE mode for progressive track drawing.
   * @param {Object} data - { geojson, seedEventId, sequenceCount }
   */
  handleTornadoSequence(data) {
    const { geojson, seedEventId, sequenceCount } = data;
    console.log(`OverlayController: Starting tornado sequence animation for ${seedEventId} with ${sequenceCount} tornadoes`);

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      console.warn('OverlayController: No data for tornado sequence animation');
      return;
    }

    // For single tornadoes, only proceed if it has track geometry
    // (otherwise route to point animation)
    if (geojson.features.length === 1) {
      const feature = geojson.features[0];
      if (!feature.properties?.track) {
        console.log('OverlayController: Single tornado without track - routing to point animation');
        // Extract data and trigger point animation
        const props = feature.properties || {};
        this.handleTornadoPointAnimation({
          eventId: props.event_id || seedEventId,
          latitude: props.latitude,
          longitude: props.longitude,
          scale: props.tornado_scale || 'EF0',
          timestamp: props.timestamp || null
        });
        return;
      }
    }

    // Hide any popups
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Find the seed tornado to get initial center
    const seedTornado = geojson.features.find(f =>
      String(f.properties?.event_id) === String(seedEventId)
    ) || geojson.features[0];

    const centerLon = seedTornado.properties?.longitude;
    const centerLat = seedTornado.properties?.latitude;

    // Get time range for animation label
    let minTime = Infinity, maxTime = -Infinity;
    for (const f of geojson.features) {
      const t = new Date(f.properties?.timestamp).getTime();
      if (!isNaN(t)) {
        if (t < minTime) minTime = t;
        if (t > maxTime) maxTime = t;
      }
    }

    // Format label - different for single vs sequence
    const startDate = new Date(minTime);
    const isSingle = geojson.features.length === 1;
    const label = isSingle
      ? `Tornado ${startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
      : `Tornado Sequence ${startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;

    // Start tornado sequence animation using EventAnimator
    const animationId = `tornado-seq-${seedEventId}`;

    const started = EventAnimator.start({
      id: animationId,
      label: label,
      mode: AnimationMode.TORNADO_SEQUENCE,
      events: geojson.features,
      eventType: 'tornado',
      timeField: 'timestamp',
      granularity: '1h',
      renderer: 'point-radius',
      center: centerLat && centerLon ? { lat: centerLat, lon: centerLon } : null,
      zoom: 8,
      rendererOptions: {
        eventType: 'tornado'
      },
      onExit: () => {
        console.log('OverlayController: Tornado sequence animation exited');
        // Restore original tornado overlay
        const currentYear = this.getCurrentYear();
        if (dataCache.tornadoes) {
          this.renderFilteredData('tornadoes', currentYear);
        }
        // Recalculate time range for TimeSlider
        this.recalculateTimeRange();
        if (TimeSlider && Object.keys(yearRangeCache).length > 0) {
          TimeSlider.show();
        }
      }
    });

    if (started) {
      console.log(`OverlayController: Tornado sequence animation started with ${geojson.features.length} tornadoes`);
    } else {
      console.error('OverlayController: Failed to start tornado sequence animation');
      const currentYear = this.getCurrentYear();
      if (dataCache.tornadoes) {
        this.renderFilteredData('tornadoes', currentYear);
      }
    }
  },

  /**
   * Handle point-only tornado animation.
   * For tornadoes without track data - zooms in, shows circle based on EF scale,
   * with TimeSlider-driven animation showing the tornado's duration.
   * @param {Object} data - { eventId, latitude, longitude, scale, timestamp }
   */
  handleTornadoPointAnimation(data) {
    const { eventId, scale, timestamp } = data;
    // Parse coordinates as floats to ensure valid numbers
    const latitude = parseFloat(data.latitude);
    const longitude = parseFloat(data.longitude);
    console.log(`OverlayController: Starting point-only tornado animation for ${eventId} at [${longitude}, ${latitude}]`);

    if (isNaN(latitude) || isNaN(longitude)) {
      console.warn('OverlayController: Invalid coordinates for tornado point animation:', data);
      return;
    }

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Note: We keep the tornado overlay visible so the source point stays on screen
    // The animation circle will appear on top of the existing point

    // Get color and size based on scale
    const scaleColors = {
      'EF0': '#98fb98', 'F0': '#98fb98',
      'EF1': '#32cd32', 'F1': '#32cd32',
      'EF2': '#ffd700', 'F2': '#ffd700',
      'EF3': '#ff8c00', 'F3': '#ff8c00',
      'EF4': '#ff4500', 'F4': '#ff4500',
      'EF5': '#8b0000', 'F5': '#8b0000'
    };
    const scaleRadii = {
      'EF0': 500,   // meters
      'EF1': 800,
      'EF2': 1200,
      'EF3': 1800,
      'EF4': 2500,
      'EF5': 3500
    };

    // Estimated duration in minutes based on EF scale
    // Stronger tornadoes tend to last longer
    const scaleDurations = {
      'EF0': 3, 'F0': 3,     // ~3 minutes (weak, short-lived)
      'EF1': 5, 'F1': 5,     // ~5 minutes
      'EF2': 10, 'F2': 10,   // ~10 minutes
      'EF3': 15, 'F3': 15,   // ~15 minutes
      'EF4': 20, 'F4': 20,   // ~20 minutes
      'EF5': 30, 'F5': 30    // ~30 minutes (violent, long-lived)
    };

    const color = scaleColors[scale] || '#32cd32';
    const radius = scaleRadii[scale] || scaleRadii['EF0'] || 500;
    const durationMinutes = scaleDurations[scale] || 5;
    const layerId = 'tornado-point-animation';
    const sourceId = 'tornado-point-animation-source';

    // Calculate time range
    // Use timestamp if available, otherwise use a default time
    let startMs;
    if (timestamp) {
      startMs = new Date(timestamp).getTime();
    } else {
      // Fallback: use noon on Jan 1 of some year (arbitrary but valid)
      startMs = new Date('2020-01-01T12:00:00Z').getTime();
    }
    const endMs = startMs + (durationMinutes * 60 * 1000);

    // Create GeoJSON for the point
    const geojson = {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [longitude, latitude] },
        properties: { scale: scale, radius: radius }
      }]
    };

    // Zoom to location first
    const zoomLevel = 11;
    MapAdapter.flyTo([longitude, latitude], zoomLevel);

    // Wait for flyTo to complete, then setup TimeSlider and layers
    setTimeout(() => {
      const map = MapAdapter.map;
      if (!map) return;

      // Clean up any previous animation layers
      if (map.getLayer(layerId)) map.removeLayer(layerId);
      if (map.getLayer(layerId + '-outline')) map.removeLayer(layerId + '-outline');
      if (map.getSource(sourceId)) map.removeSource(sourceId);

      // Add source
      map.addSource(sourceId, {
        type: 'geojson',
        data: geojson
      });

      // Convert meters to pixels using proper geographic scaling
      // Note: ['zoom'] can only be used at top-level interpolate/step, so we use
      // interpolate with pre-calculated meters/pixel values at zoom stops:
      // Zoom 8: 611.5 m/px, Zoom 11: 76.44 m/px, Zoom 14: 9.55 m/px
      const metersToPixels = [
        'interpolate', ['exponential', 2], ['zoom'],
        8, ['/', ['get', 'radius'], 611.5],
        11, ['/', ['get', 'radius'], 76.44],
        14, ['/', ['get', 'radius'], 9.55]
      ];

      // Add fill circle layer (starts transparent)
      map.addLayer({
        id: layerId,
        type: 'circle',
        source: sourceId,
        paint: {
          'circle-radius': metersToPixels,
          'circle-color': color,
          'circle-opacity': 0
        }
      });

      // Add outline layer
      map.addLayer({
        id: layerId + '-outline',
        type: 'circle',
        source: sourceId,
        paint: {
          'circle-radius': metersToPixels,
          'circle-color': 'transparent',
          'circle-stroke-color': color,
          'circle-stroke-width': 3,
          'circle-stroke-opacity': 1
        }
      });

      // Setup TimeSlider for tornado animation
      const scaleId = `tornado-point-${eventId.substring(0, 12)}`;
      const tornadoDate = timestamp
        ? new Date(timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
        : `${scale} Tornado`;

      // Generate timestamps for each second (tornadoes are short events)
      const timestamps = [];
      const stepMs = 1000; // 1 second steps
      for (let t = startMs; t <= endMs; t += stepMs) {
        timestamps.push(t);
      }

      if (TimeSlider) {
        const added = TimeSlider.addScale({
          id: scaleId,
          label: `Tornado ${tornadoDate}`,
          granularity: 'seconds',
          useTimestamps: true,
          currentTime: startMs,
          timeRange: {
            min: startMs,
            max: endMs,
            available: timestamps
          },
          mapRenderer: 'tornado-point-animation'
        });

        if (added) {
          this.activeTornadoPointScaleId = scaleId;
          TimeSlider.setActiveScale(scaleId);

          // Enter event animation mode with auto-calculated speed
          if (TimeSlider.enterEventAnimation) {
            TimeSlider.enterEventAnimation(startMs, endMs);
          }
        }
      }

      // Store animation state
      this._tornadoPointAnimState = {
        sourceId,
        layerId,
        startMs,
        endMs,
        scaleId,
        color
      };

      // Listen for time changes to update opacity
      this._tornadoPointTimeHandler = (time, source) => {
        if (!this._tornadoPointAnimState) return;

        const { startMs, endMs, layerId } = this._tornadoPointAnimState;
        const progress = Math.max(0, Math.min(1, (time - startMs) / (endMs - startMs)));

        // Update fill opacity based on progress (0 -> 0.7 over duration)
        if (map.getLayer(layerId)) {
          map.setPaintProperty(layerId, 'circle-opacity', progress * 0.7);
        }
      };
      TimeSlider?.addChangeListener(this._tornadoPointTimeHandler);

      // Add exit button
      this._addTornadoPointExitButton(() => this._exitTornadoPointAnimation());

      console.log(`OverlayController: Tornado point animation ready, ${durationMinutes} minutes`);
    }, 1600); // Wait for flyTo to complete
  },

  /**
   * Exit tornado point animation and cleanup.
   * @private
   */
  _exitTornadoPointAnimation() {
    console.log('OverlayController: Exiting tornado point animation');

    const map = MapAdapter.map;

    // Remove layers
    if (this._tornadoPointAnimState) {
      const { sourceId, layerId, scaleId } = this._tornadoPointAnimState;

      if (map.getLayer(layerId)) map.removeLayer(layerId);
      if (map.getLayer(layerId + '-outline')) map.removeLayer(layerId + '-outline');
      if (map.getSource(sourceId)) map.removeSource(sourceId);

      // Remove TimeSlider scale
      if (TimeSlider && scaleId) {
        TimeSlider.removeScale(scaleId);
        if (TimeSlider.exitEventAnimation) {
          TimeSlider.exitEventAnimation();
        }
      }

      this._tornadoPointAnimState = null;
    }

    // Remove time listener
    if (this._tornadoPointTimeHandler && TimeSlider) {
      TimeSlider.removeChangeListener(this._tornadoPointTimeHandler);
      this._tornadoPointTimeHandler = null;
    }

    // Remove exit button
    const exitBtn = document.getElementById('tornado-point-exit-btn');
    if (exitBtn) exitBtn.remove();

    // Recalculate time range
    this.recalculateTimeRange();
  },

  /**
   * Add exit button for tornado point animation.
   * @private
   */
  _addTornadoPointExitButton(onExit) {
    // Remove existing
    const existing = document.getElementById('tornado-point-exit-btn');
    if (existing) existing.remove();

    const btn = document.createElement('button');
    btn.id = 'tornado-point-exit-btn';
    btn.textContent = 'Exit Tornado View';
    btn.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      padding: 10px 20px;
      background: #32cd32;
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
    btn.addEventListener('mouseenter', () => { btn.style.background = '#228b22'; });
    btn.addEventListener('mouseleave', () => { btn.style.background = '#32cd32'; });

    document.body.appendChild(btn);
  },

  /**
   * Handle flood animation - shows flood polygon with opacity fade over duration.
   * At flood start time, outline appears. Over the duration, opacity increases.
   * @param {Object} data - { geometry, eventId, durationDays, startTime, endTime, latitude, longitude, eventName }
   */
  handleFloodAnimation(data) {
    const { geometry, eventId, durationDays, startTime, endTime, latitude, longitude, eventName } = data;
    console.log(`OverlayController: Starting flood animation for ${eventId} (${durationDays} days)`);

    // Handle both Feature and FeatureCollection formats
    let geojsonData = geometry;
    if (!geometry) {
      console.warn('OverlayController: No geometry data for flood animation');
      return;
    }

    // If it's a FeatureCollection, use it directly; if it's a Feature, wrap it
    if (geometry.type === 'FeatureCollection') {
      geojsonData = geometry;
    } else if (geometry.type === 'Feature') {
      geojsonData = geometry;
    } else if (geometry.geometry) {
      // Already a Feature with geometry property
      geojsonData = geometry;
    } else {
      console.warn('OverlayController: Invalid geometry format for flood animation');
      return;
    }

    // Calculate time range
    const startMs = new Date(startTime).getTime();
    const endMs = new Date(endTime).getTime();
    const durationMs = endMs - startMs;

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Hide the flood overlay to focus on this flood
    this._hideFloodOverlay();

    // Calculate bounds from geometry for proper zoom that shows the whole area
    let bounds = null;

    // Helper to collect all coordinates from a geometry
    const collectCoords = (geom) => {
      const coords = [];
      if (!geom || !geom.coordinates) return coords;
      if (geom.type === 'Polygon') {
        coords.push(...geom.coordinates[0]);
      } else if (geom.type === 'MultiPolygon') {
        for (const poly of geom.coordinates) {
          coords.push(...poly[0]);
        }
      }
      return coords;
    };

    // Collect all coordinates from geometry
    let allCoords = [];
    if (geojsonData.type === 'FeatureCollection' && geojsonData.features) {
      for (const feature of geojsonData.features) {
        allCoords.push(...collectCoords(feature.geometry));
      }
    } else if (geojsonData.geometry) {
      allCoords = collectCoords(geojsonData.geometry);
    }

    // Calculate bounds from coordinates
    if (allCoords.length > 0) {
      bounds = this._getBoundsFromCoords(allCoords);
    }

    // Zoom to flood - use fitBounds if we have geometry, otherwise flyTo center
    if (bounds) {
      MapAdapter.map.fitBounds(bounds, {
        padding: 60,
        duration: 1500,
        maxZoom: 11
      });
    } else if (longitude && latitude) {
      MapAdapter.map.flyTo({
        center: [longitude, latitude],
        zoom: 8,
        duration: 1500
      });
    }

    // Create flood polygon layer
    const sourceId = 'flood-anim-polygon';
    const layerId = 'flood-anim-fill';
    const strokeId = 'flood-anim-stroke';

    // Remove existing layers
    if (MapAdapter.map.getLayer(layerId)) MapAdapter.map.removeLayer(layerId);
    if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
    if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

    // Add flood source
    MapAdapter.map.addSource(sourceId, {
      type: 'geojson',
      data: geojsonData
    });

    // Add stroke layer (appears immediately at animation start)
    MapAdapter.map.addLayer({
      id: strokeId,
      type: 'line',
      source: sourceId,
      paint: {
        'line-color': '#0066cc',
        'line-width': 2,
        'line-opacity': 0.8
      }
    });

    // Add fill layer (starts transparent, fades in over duration)
    MapAdapter.map.addLayer({
      id: layerId,
      type: 'fill',
      source: sourceId,
      paint: {
        'fill-color': '#3399ff',
        'fill-opacity': 0
      }
    });

    // Setup TimeSlider for flood animation
    const scaleId = `flood-${eventId.substring(0, 12)}`;
    const floodDate = new Date(startTime).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    // Generate timestamps for each day
    const timestamps = [];
    for (let t = startMs; t <= endMs; t += 24 * 60 * 60 * 1000) {
      timestamps.push(t);
    }

    if (TimeSlider) {
      const added = TimeSlider.addScale({
        id: scaleId,
        label: eventName ? `${eventName}` : `Flood ${floodDate}`,
        granularity: 'daily',
        useTimestamps: true,
        currentTime: startMs,
        timeRange: {
          min: startMs,
          max: endMs,
          available: timestamps
        },
        mapRenderer: 'flood-animation'
      });

      if (added) {
        this.activeFloodScaleId = scaleId;
        TimeSlider.setActiveScale(scaleId);

        // Enter event animation mode with auto-calculated speed
        if (TimeSlider.enterEventAnimation) {
          TimeSlider.enterEventAnimation(startMs, endMs);
        }
      }
    }

    // Store animation state
    this._floodAnimState = {
      sourceId,
      layerId,
      strokeId,
      startMs,
      endMs,
      scaleId
    };

    // Listen for time changes to update opacity
    this._floodTimeHandler = (time, source) => {
      if (!this._floodAnimState) return;

      const { startMs, endMs, layerId } = this._floodAnimState;
      const progress = Math.max(0, Math.min(1, (time - startMs) / (endMs - startMs)));

      // Update fill opacity based on progress (0 -> 0.6 over duration)
      if (MapAdapter.map.getLayer(layerId)) {
        MapAdapter.map.setPaintProperty(layerId, 'fill-opacity', progress * 0.6);
      }
    };
    TimeSlider?.addChangeListener(this._floodTimeHandler);

    // Add exit button
    this._addFloodExitButton(() => this._exitFloodAnimation());

    console.log(`OverlayController: Flood animation ready, ${durationDays} days starting ${floodDate}`);
  },

  /**
   * Handle volcano impact radius animation.
   * Shows felt and damage radii expanding from the volcano center.
   */
  handleVolcanoImpact(data) {
    const { eventId, volcanoName, latitude, longitude, feltRadius, damageRadius, VEI, timestamp } = data;
    console.log(`OverlayController: Starting volcano impact animation for ${volcanoName} (VEI ${VEI})`);

    if (!latitude || !longitude) {
      console.warn('OverlayController: No coordinates for volcano impact animation');
      return;
    }

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Zoom to volcano
    MapAdapter.map.flyTo({
      center: [longitude, latitude],
      zoom: 7,
      duration: 1500
    });

    // Create impact circle sources
    const feltSourceId = 'volcano-felt-radius';
    const damageSourceId = 'volcano-damage-radius';
    const feltLayerId = 'volcano-felt-fill';
    const damageLayerId = 'volcano-damage-fill';
    const feltStrokeId = 'volcano-felt-stroke';
    const damageStrokeId = 'volcano-damage-stroke';

    // Remove existing layers
    [feltLayerId, damageLayerId, feltStrokeId, damageStrokeId].forEach(id => {
      if (MapAdapter.map.getLayer(id)) MapAdapter.map.removeLayer(id);
    });
    [feltSourceId, damageSourceId].forEach(id => {
      if (MapAdapter.map.getSource(id)) MapAdapter.map.removeSource(id);
    });

    // Create circle GeoJSON (approximation using turf-style circle)
    const createCircle = (centerLon, centerLat, radiusKm, steps = 64) => {
      const coords = [];
      for (let i = 0; i <= steps; i++) {
        const angle = (i / steps) * 2 * Math.PI;
        // Approximate km to degrees (1 degree ~ 111km at equator)
        const latOffset = (radiusKm / 111) * Math.cos(angle);
        const lonOffset = (radiusKm / (111 * Math.cos(centerLat * Math.PI / 180))) * Math.sin(angle);
        coords.push([centerLon + lonOffset, centerLat + latOffset]);
      }
      return {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [coords]
        }
      };
    };

    // Add felt radius source and layers (larger, yellow/orange)
    if (feltRadius > 0) {
      MapAdapter.map.addSource(feltSourceId, {
        type: 'geojson',
        data: createCircle(longitude, latitude, feltRadius)
      });

      MapAdapter.map.addLayer({
        id: feltLayerId,
        type: 'fill',
        source: feltSourceId,
        paint: {
          'fill-color': '#ffc107',
          'fill-opacity': 0
        }
      });

      MapAdapter.map.addLayer({
        id: feltStrokeId,
        type: 'line',
        source: feltSourceId,
        paint: {
          'line-color': '#ff9800',
          'line-width': 2,
          'line-opacity': 0
        }
      });
    }

    // Add damage radius source and layers (smaller, red)
    if (damageRadius > 0) {
      MapAdapter.map.addSource(damageSourceId, {
        type: 'geojson',
        data: createCircle(longitude, latitude, damageRadius)
      });

      MapAdapter.map.addLayer({
        id: damageLayerId,
        type: 'fill',
        source: damageSourceId,
        paint: {
          'fill-color': '#f44336',
          'fill-opacity': 0
        }
      });

      MapAdapter.map.addLayer({
        id: damageStrokeId,
        type: 'line',
        source: damageSourceId,
        paint: {
          'line-color': '#d32f2f',
          'line-width': 3,
          'line-opacity': 0
        }
      });
    }

    // Animate the radii expanding (3 second animation)
    const animDuration = 3000;
    const startTime = performance.now();

    const animate = () => {
      const elapsed = performance.now() - startTime;
      const progress = Math.min(1, elapsed / animDuration);
      const easeProgress = 1 - Math.pow(1 - progress, 3); // Ease out cubic

      // Update felt radius opacity (fade in)
      if (feltRadius > 0 && MapAdapter.map.getLayer(feltLayerId)) {
        MapAdapter.map.setPaintProperty(feltLayerId, 'fill-opacity', easeProgress * 0.3);
        MapAdapter.map.setPaintProperty(feltStrokeId, 'line-opacity', easeProgress * 0.8);
      }

      // Update damage radius opacity (fade in slightly delayed)
      if (damageRadius > 0 && MapAdapter.map.getLayer(damageLayerId)) {
        const damageProgress = Math.max(0, (progress - 0.3) / 0.7); // Start at 30%
        const easeDamage = 1 - Math.pow(1 - damageProgress, 3);
        MapAdapter.map.setPaintProperty(damageLayerId, 'fill-opacity', easeDamage * 0.4);
        MapAdapter.map.setPaintProperty(damageStrokeId, 'line-opacity', easeDamage * 0.9);
      }

      if (progress < 1) {
        requestAnimationFrame(animate);
      }
    };

    // Start animation after flyTo completes
    setTimeout(animate, 1600);

    // Store state for cleanup
    this._volcanoImpactState = {
      feltSourceId,
      damageSourceId,
      feltLayerId,
      damageLayerId,
      feltStrokeId,
      damageStrokeId
    };

    // Add exit button
    this._addVolcanoExitButton(() => this._exitVolcanoImpact());

    console.log(`OverlayController: Volcano impact animation started (felt: ${feltRadius}km, damage: ${damageRadius}km)`);
  },

  /**
   * Exit volcano impact animation and cleanup.
   * @private
   */
  _exitVolcanoImpact() {
    console.log('OverlayController: Exiting volcano impact animation');

    if (this._volcanoImpactState) {
      const { feltSourceId, damageSourceId, feltLayerId, damageLayerId, feltStrokeId, damageStrokeId } = this._volcanoImpactState;

      // Remove layers
      [feltLayerId, damageLayerId, feltStrokeId, damageStrokeId].forEach(id => {
        if (MapAdapter.map.getLayer(id)) MapAdapter.map.removeLayer(id);
      });

      // Remove sources
      [feltSourceId, damageSourceId].forEach(id => {
        if (MapAdapter.map.getSource(id)) MapAdapter.map.removeSource(id);
      });

      this._volcanoImpactState = null;
    }

    // Remove exit button
    const exitBtn = document.getElementById('volcano-exit-btn');
    if (exitBtn) exitBtn.remove();
  },

  /**
   * Add exit button for volcano impact animation.
   * @private
   */
  _addVolcanoExitButton(onExit) {
    const existing = document.getElementById('volcano-exit-btn');
    if (existing) existing.remove();

    const btn = document.createElement('button');
    btn.id = 'volcano-exit-btn';
    btn.textContent = 'Exit Impact View';
    btn.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      padding: 10px 20px;
      background: #ff5722;
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
   * Handle wildfire impact animation (area circle fallback).
   * Shows a circle representing the burned area.
   */
  handleWildfireImpact(data) {
    const { eventId, fireName, latitude, longitude, areaKm2, radiusKm, timestamp } = data;
    console.log(`OverlayController: Starting wildfire impact animation for ${fireName} (${areaKm2} km2)`);

    if (!latitude || !longitude) {
      console.warn('OverlayController: No coordinates for wildfire impact animation');
      return;
    }

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Zoom to fire
    MapAdapter.map.flyTo({
      center: [longitude, latitude],
      zoom: 9,
      duration: 1500
    });

    // Create area circle
    const sourceId = 'wildfire-impact-radius';
    const fillId = 'wildfire-impact-fill';
    const strokeId = 'wildfire-impact-stroke';

    // Remove existing
    if (MapAdapter.map.getLayer(fillId)) MapAdapter.map.removeLayer(fillId);
    if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
    if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

    // Create circle GeoJSON
    const createCircle = (centerLon, centerLat, radiusKm, steps = 64) => {
      const coords = [];
      for (let i = 0; i <= steps; i++) {
        const angle = (i / steps) * 2 * Math.PI;
        const latOffset = (radiusKm / 111) * Math.cos(angle);
        const lonOffset = (radiusKm / (111 * Math.cos(centerLat * Math.PI / 180))) * Math.sin(angle);
        coords.push([centerLon + lonOffset, centerLat + latOffset]);
      }
      return {
        type: 'Feature',
        properties: {},
        geometry: { type: 'Polygon', coordinates: [coords] }
      };
    };

    MapAdapter.map.addSource(sourceId, {
      type: 'geojson',
      data: createCircle(longitude, latitude, radiusKm)
    });

    MapAdapter.map.addLayer({
      id: fillId,
      type: 'fill',
      source: sourceId,
      paint: { 'fill-color': '#ff5722', 'fill-opacity': 0 }
    });

    MapAdapter.map.addLayer({
      id: strokeId,
      type: 'line',
      source: sourceId,
      paint: { 'line-color': '#d84315', 'line-width': 3, 'line-opacity': 0 }
    });

    // Animate
    const animDuration = 2000;
    const startTime = performance.now();
    const animate = () => {
      const progress = Math.min(1, (performance.now() - startTime) / animDuration);
      const ease = 1 - Math.pow(1 - progress, 3);
      if (MapAdapter.map.getLayer(fillId)) {
        MapAdapter.map.setPaintProperty(fillId, 'fill-opacity', ease * 0.4);
        MapAdapter.map.setPaintProperty(strokeId, 'line-opacity', ease * 0.9);
      }
      if (progress < 1) requestAnimationFrame(animate);
    };
    setTimeout(animate, 1600);

    this._wildfireImpactState = { sourceId, fillId, strokeId };
    this._addGenericExitButton('wildfire-exit-btn', 'Exit Fire View', '#ff5722', () => this._exitWildfireImpact());
  },

  _exitWildfireImpact() {
    if (this._wildfireImpactState) {
      const { sourceId, fillId, strokeId } = this._wildfireImpactState;
      if (MapAdapter.map.getLayer(fillId)) MapAdapter.map.removeLayer(fillId);
      if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
      if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);
      this._wildfireImpactState = null;
    }
    document.getElementById('wildfire-exit-btn')?.remove();
  },

  /**
   * Handle wildfire perimeter animation (single shape fade-in).
   * Shows the fire perimeter polygon fading in.
   */
  handleWildfirePerimeter(data) {
    const { eventId, fireName, geometry, latitude, longitude, areaKm2, timestamp } = data;
    console.log(`OverlayController: Starting wildfire perimeter animation for ${fireName}`);

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Calculate bounds from geometry for proper zoom
    let bounds = null;
    if (geometry && geometry.geometry) {
      const coords = geometry.geometry.coordinates;
      if (geometry.geometry.type === 'Polygon') {
        bounds = this._getBoundsFromCoords(coords[0]);
      } else if (geometry.geometry.type === 'MultiPolygon') {
        // Flatten all outer rings
        const allCoords = coords.flatMap(poly => poly[0]);
        bounds = this._getBoundsFromCoords(allCoords);
      }
    }

    // Zoom to fire perimeter
    if (bounds) {
      MapAdapter.map.fitBounds(bounds, {
        padding: 50,
        duration: 1500,
        maxZoom: 12
      });
    } else if (latitude && longitude) {
      MapAdapter.map.flyTo({
        center: [longitude, latitude],
        zoom: 9,
        duration: 1500
      });
    }

    // Layer IDs
    const sourceId = 'wildfire-perimeter';
    const fillId = 'wildfire-perimeter-fill';
    const strokeId = 'wildfire-perimeter-stroke';

    // Remove existing
    if (MapAdapter.map.getLayer(fillId)) MapAdapter.map.removeLayer(fillId);
    if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
    if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

    // Add the perimeter geometry
    MapAdapter.map.addSource(sourceId, {
      type: 'geojson',
      data: geometry
    });

    MapAdapter.map.addLayer({
      id: fillId,
      type: 'fill',
      source: sourceId,
      paint: { 'fill-color': '#ff5722', 'fill-opacity': 0 }
    });

    MapAdapter.map.addLayer({
      id: strokeId,
      type: 'line',
      source: sourceId,
      paint: { 'line-color': '#d84315', 'line-width': 2, 'line-opacity': 0 }
    });

    // Animate fade-in
    const animDuration = 2500;
    const startTime = performance.now();
    const animate = () => {
      const progress = Math.min(1, (performance.now() - startTime) / animDuration);
      const ease = 1 - Math.pow(1 - progress, 3);
      if (MapAdapter.map.getLayer(fillId)) {
        MapAdapter.map.setPaintProperty(fillId, 'fill-opacity', ease * 0.5);
        MapAdapter.map.setPaintProperty(strokeId, 'line-opacity', ease * 0.9);
      }
      if (progress < 1) requestAnimationFrame(animate);
    };
    setTimeout(animate, 1600);

    this._wildfirePerimeterState = { sourceId, fillId, strokeId };
    this._addGenericExitButton('wildfire-perim-exit-btn', 'Exit Fire View', '#ff5722', () => this._exitWildfirePerimeter());
  },

  _exitWildfirePerimeter() {
    if (this._wildfirePerimeterState) {
      const { sourceId, fillId, strokeId } = this._wildfirePerimeterState;
      if (MapAdapter.map.getLayer(fillId)) MapAdapter.map.removeLayer(fillId);
      if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
      if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);
      this._wildfirePerimeterState = null;
    }
    document.getElementById('wildfire-perim-exit-btn')?.remove();
  },

  /**
   * Get bounding box from coordinate array.
   * @param {Array} coords - Array of [lng, lat] coordinates
   * @returns {Array} [[minLng, minLat], [maxLng, maxLat]]
   */
  _getBoundsFromCoords(coords) {
    if (!coords || coords.length === 0) return null;
    let minLng = Infinity, maxLng = -Infinity;
    let minLat = Infinity, maxLat = -Infinity;
    for (const [lng, lat] of coords) {
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
    return [[minLng, minLat], [maxLng, maxLat]];
  },

  /**
   * Handle flood impact animation (area circle fallback).
   * Shows a circle representing the flooded area.
   */
  handleFloodImpact(data) {
    const { eventId, eventName, latitude, longitude, areaKm2, radiusKm, durationDays, timestamp } = data;
    console.log(`OverlayController: Starting flood impact animation for ${eventName} (${areaKm2} km2)`);

    if (!latitude || !longitude) {
      console.warn('OverlayController: No coordinates for flood impact animation');
      return;
    }

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Zoom to flood
    MapAdapter.map.flyTo({
      center: [longitude, latitude],
      zoom: 8,
      duration: 1500
    });

    // Create area circle
    const sourceId = 'flood-impact-radius';
    const fillId = 'flood-impact-fill';
    const strokeId = 'flood-impact-stroke';

    // Remove existing
    if (MapAdapter.map.getLayer(fillId)) MapAdapter.map.removeLayer(fillId);
    if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
    if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);

    // Create circle GeoJSON
    const createCircle = (centerLon, centerLat, radiusKm, steps = 64) => {
      const coords = [];
      for (let i = 0; i <= steps; i++) {
        const angle = (i / steps) * 2 * Math.PI;
        const latOffset = (radiusKm / 111) * Math.cos(angle);
        const lonOffset = (radiusKm / (111 * Math.cos(centerLat * Math.PI / 180))) * Math.sin(angle);
        coords.push([centerLon + lonOffset, centerLat + latOffset]);
      }
      return {
        type: 'Feature',
        properties: {},
        geometry: { type: 'Polygon', coordinates: [coords] }
      };
    };

    MapAdapter.map.addSource(sourceId, {
      type: 'geojson',
      data: createCircle(longitude, latitude, radiusKm)
    });

    MapAdapter.map.addLayer({
      id: fillId,
      type: 'fill',
      source: sourceId,
      paint: { 'fill-color': '#2196f3', 'fill-opacity': 0 }
    });

    MapAdapter.map.addLayer({
      id: strokeId,
      type: 'line',
      source: sourceId,
      paint: { 'line-color': '#1565c0', 'line-width': 3, 'line-opacity': 0 }
    });

    // Animate
    const animDuration = 2000;
    const startTime = performance.now();
    const animate = () => {
      const progress = Math.min(1, (performance.now() - startTime) / animDuration);
      const ease = 1 - Math.pow(1 - progress, 3);
      if (MapAdapter.map.getLayer(fillId)) {
        MapAdapter.map.setPaintProperty(fillId, 'fill-opacity', ease * 0.4);
        MapAdapter.map.setPaintProperty(strokeId, 'line-opacity', ease * 0.9);
      }
      if (progress < 1) requestAnimationFrame(animate);
    };
    setTimeout(animate, 1600);

    this._floodImpactState = { sourceId, fillId, strokeId };
    this._addGenericExitButton('flood-impact-exit-btn', 'Exit Flood View', '#2196f3', () => this._exitFloodImpact());
  },

  _exitFloodImpact() {
    if (this._floodImpactState) {
      const { sourceId, fillId, strokeId } = this._floodImpactState;
      if (MapAdapter.map.getLayer(fillId)) MapAdapter.map.removeLayer(fillId);
      if (MapAdapter.map.getLayer(strokeId)) MapAdapter.map.removeLayer(strokeId);
      if (MapAdapter.map.getSource(sourceId)) MapAdapter.map.removeSource(sourceId);
      this._floodImpactState = null;
    }
    document.getElementById('flood-impact-exit-btn')?.remove();
  },

  /**
   * Generic exit button helper.
   * @private
   */
  _addGenericExitButton(id, text, color, onExit) {
    document.getElementById(id)?.remove();
    const btn = document.createElement('button');
    btn.id = id;
    btn.textContent = text;
    btn.style.cssText = `
      position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
      padding: 10px 20px; background: ${color}; color: white; border: none;
      border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500;
      z-index: 1000; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;
    btn.addEventListener('click', onExit);
    document.body.appendChild(btn);
  },

  /**
   * Exit flood animation and cleanup.
   * @private
   */
  _exitFloodAnimation() {
    console.log('OverlayController: Exiting flood animation');

    // Remove layers
    if (this._floodAnimState) {
      const { sourceId, layerId, strokeId, scaleId } = this._floodAnimState;

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

      this._floodAnimState = null;
    }

    // Remove time listener
    if (this._floodTimeHandler && TimeSlider) {
      TimeSlider.removeChangeListener(this._floodTimeHandler);
      this._floodTimeHandler = null;
    }

    // Remove exit button
    const exitBtn = document.getElementById('flood-exit-btn');
    if (exitBtn) exitBtn.remove();

    // Restore flood overlay
    this._restoreFloodOverlay();

    // Recalculate time range
    this.recalculateTimeRange();
  },

  /**
   * Add exit button for flood animation.
   * @private
   */
  _addFloodExitButton(onExit) {
    // Remove existing
    const existing = document.getElementById('flood-exit-btn');
    if (existing) existing.remove();

    const btn = document.createElement('button');
    btn.id = 'flood-exit-btn';
    btn.textContent = 'Exit Flood View';
    btn.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      padding: 10px 20px;
      background: #0066cc;
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
   * Hide flood overlay to focus on a single flood animation.
   * @private
   */
  _hideFloodOverlay() {
    const model = ModelRegistry?.getModelForType('flood');
    if (model?.clear) {
      model.clear();
    }
    console.log('OverlayController: Hid flood overlay for animation');
  },

  /**
   * Restore flood overlay after exiting flood animation.
   * @private
   */
  _restoreFloodOverlay() {
    const currentYear = this.getCurrentYear();
    if (dataCache.floods) {
      this.renderFilteredData('floods', currentYear);
      console.log('OverlayController: Restored flood overlay');
    }
  },

  /**
   * Handle wildfire animation - animates perimeter polygon opacity over fire duration.
   * Simple Option A: Fade in final perimeter from 0% to 100% over duration_days.
   */
  handleFireAnimation(data) {
    const { perimeter, eventId, durationDays, startTime, latitude, longitude } = data;
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

    // Hide the wildfire overlay to focus on this fire
    this._hideWildfireOverlay();

    // Get perimeter center for zoom (use provided coords or calculate from geometry)
    let centerLon = longitude || 0;
    let centerLat = latitude || 0;

    // Calculate center from geometry if not provided
    if (!longitude || !latitude) {
      let count = 0;
      centerLon = 0;
      centerLat = 0;
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
    }

    // Add ignition marker at the fire's starting point
    this._addIgnitionMarker(centerLon, centerLat);

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
   * @param {Object} data - {snapshots, eventId, totalDays, startTime, latitude, longitude}
   */
  handleFireProgression(data) {
    const { snapshots, eventId, totalDays, startTime, latitude, longitude } = data;
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

    // Hide the wildfire overlay to focus on this fire
    this._hideWildfireOverlay();

    // Get first snapshot for initial display
    const firstSnap = snapshots[0];

    // Get center from first snapshot for zoom (use provided coords or calculate)
    let centerLon = longitude || 0;
    let centerLat = latitude || 0;

    if (!longitude || !latitude) {
      let count = 0;
      centerLon = 0;
      centerLat = 0;
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
    }

    // Add ignition marker at the fire's starting point
    this._addIgnitionMarker(centerLon, centerLat);

    // Zoom to fire location
    MapAdapter.map.flyTo({
      center: [centerLon, centerLat],
      zoom: 9,
      duration: 1500
    });

    // Create two sets of fire perimeter layers for cross-fading
    // This enables smooth transitions between daily snapshots
    const sourceIdA = 'fire-prog-perimeter-a';
    const sourceIdB = 'fire-prog-perimeter-b';
    const layerIdA = 'fire-prog-fill-a';
    const layerIdB = 'fire-prog-fill-b';
    const strokeIdA = 'fire-prog-stroke-a';
    const strokeIdB = 'fire-prog-stroke-b';

    // Remove existing layers from both sets
    [layerIdA, layerIdB, strokeIdA, strokeIdB].forEach(id => {
      if (MapAdapter.map.getLayer(id)) MapAdapter.map.removeLayer(id);
    });
    [sourceIdA, sourceIdB].forEach(id => {
      if (MapAdapter.map.getSource(id)) MapAdapter.map.removeSource(id);
    });

    // Add two perimeter sources for cross-fading
    MapAdapter.map.addSource(sourceIdA, {
      type: 'geojson',
      data: { type: 'Feature', geometry: firstSnap.geometry, properties: { day: 1 } }
    });
    MapAdapter.map.addSource(sourceIdB, {
      type: 'geojson',
      data: { type: 'Feature', geometry: firstSnap.geometry, properties: { day: 1 } }
    });

    // Add fill layers (A starts visible, B starts hidden)
    MapAdapter.map.addLayer({
      id: layerIdA,
      type: 'fill',
      source: sourceIdA,
      paint: {
        'fill-color': '#ff4400',
        'fill-opacity': 0.5,
        'fill-opacity-transition': { duration: 300, delay: 0 }
      }
    });
    MapAdapter.map.addLayer({
      id: layerIdB,
      type: 'fill',
      source: sourceIdB,
      paint: {
        'fill-color': '#ff4400',
        'fill-opacity': 0,
        'fill-opacity-transition': { duration: 300, delay: 0 }
      }
    });

    // Add stroke layers (A starts visible, B starts hidden)
    MapAdapter.map.addLayer({
      id: strokeIdA,
      type: 'line',
      source: sourceIdA,
      paint: {
        'line-color': '#ff6600',
        'line-width': 2,
        'line-opacity': 0.9,
        'line-opacity-transition': { duration: 300, delay: 0 }
      }
    });
    MapAdapter.map.addLayer({
      id: strokeIdB,
      type: 'line',
      source: sourceIdB,
      paint: {
        'line-color': '#ff6600',
        'line-width': 2,
        'line-opacity': 0,
        'line-opacity-transition': { duration: 300, delay: 0 }
      }
    });

    // Legacy variable names for backward compatibility
    const sourceId = sourceIdA;
    const layerId = layerIdA;
    const strokeId = strokeIdA;

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

    // Store animation state with both layer sets for cross-fading
    this._fireAnimState = {
      sourceId,
      layerId,
      strokeId,
      sourceIdA,
      sourceIdB,
      layerIdA,
      layerIdB,
      strokeIdA,
      strokeIdB,
      startMs: minTime,
      endMs: maxTime,
      scaleId,
      snapshotMap,  // For progression: lookup by timestamp
      timestamps,   // For progression: sorted list
      currentLayer: 'A',  // Track which layer is currently visible
      lastSnapshotTime: minTime  // Track last snapshot to detect changes
    };

    // Listen for time changes to update geometry with cross-fade
    this._fireTimeHandler = (time, source) => {
      if (!this._fireAnimState || !this._fireAnimState.snapshotMap) return;

      const state = this._fireAnimState;
      const { snapshotMap, timestamps, lastSnapshotTime, currentLayer } = state;

      // Find closest snapshot <= current time
      let closestTime = timestamps[0];
      for (const t of timestamps) {
        if (t <= time) closestTime = t;
        else break;
      }

      // If snapshot hasn't changed, no need to update
      if (closestTime === lastSnapshotTime) return;

      const snap = snapshotMap.get(closestTime);
      if (!snap) return;

      // Cross-fade: update the hidden layer with new geometry, then swap visibility
      const newLayer = currentLayer === 'A' ? 'B' : 'A';
      const newSourceId = newLayer === 'A' ? state.sourceIdA : state.sourceIdB;
      const newFillId = newLayer === 'A' ? state.layerIdA : state.layerIdB;
      const newStrokeId = newLayer === 'A' ? state.strokeIdA : state.strokeIdB;
      const oldFillId = currentLayer === 'A' ? state.layerIdA : state.layerIdB;
      const oldStrokeId = currentLayer === 'A' ? state.strokeIdA : state.strokeIdB;

      // Update the hidden layer's geometry
      const newSource = MapAdapter.map.getSource(newSourceId);
      if (newSource) {
        newSource.setData({
          type: 'Feature',
          geometry: snap.geometry,
          properties: { day: snap.day_num, area_km2: snap.area_km2, date: snap.date }
        });
      }

      // Cross-fade: fade in the new layer, fade out the old
      if (MapAdapter.map.getLayer(newFillId)) {
        MapAdapter.map.setPaintProperty(newFillId, 'fill-opacity', 0.5);
      }
      if (MapAdapter.map.getLayer(newStrokeId)) {
        MapAdapter.map.setPaintProperty(newStrokeId, 'line-opacity', 0.9);
      }
      if (MapAdapter.map.getLayer(oldFillId)) {
        MapAdapter.map.setPaintProperty(oldFillId, 'fill-opacity', 0);
      }
      if (MapAdapter.map.getLayer(oldStrokeId)) {
        MapAdapter.map.setPaintProperty(oldStrokeId, 'line-opacity', 0);
      }

      // Update tracking state
      state.currentLayer = newLayer;
      state.lastSnapshotTime = closestTime;
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

    // Remove layers (both A and B layer sets for cross-fade)
    if (this._fireAnimState) {
      const {
        sourceIdA, sourceIdB,
        layerIdA, layerIdB,
        strokeIdA, strokeIdB,
        scaleId
      } = this._fireAnimState;

      // Remove all fill and stroke layers
      [layerIdA, layerIdB, strokeIdA, strokeIdB].forEach(id => {
        if (id && MapAdapter.map.getLayer(id)) MapAdapter.map.removeLayer(id);
      });

      // Remove all sources
      [sourceIdA, sourceIdB].forEach(id => {
        if (id && MapAdapter.map.getSource(id)) MapAdapter.map.removeSource(id);
      });

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

    // Remove ignition marker
    this._removeIgnitionMarker();

    // Restore wildfire overlay
    this._restoreWildfireOverlay();

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
   * Hide wildfire overlay to focus on a single fire animation.
   * Clears the map layers but preserves the cached data.
   * @private
   */
  _hideWildfireOverlay() {
    const model = ModelRegistry?.getModelForType('wildfire');
    if (model?.clear) {
      model.clear();
    }
    console.log('OverlayController: Hid wildfire overlay for animation');
  },

  /**
   * Restore wildfire overlay after exiting fire animation.
   * @private
   */
  _restoreWildfireOverlay() {
    const currentYear = this.getCurrentYear();
    if (dataCache.wildfires) {
      this.renderFilteredData('wildfires', currentYear);
      console.log('OverlayController: Restored wildfire overlay');
    }
  },

  /**
   * Add ignition marker for wildfire animation.
   * Shows a fire icon/marker at the ignition point.
   * @private
   */
  _addIgnitionMarker(lon, lat) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const sourceId = 'fire-ignition-marker';
    const layerId = 'fire-ignition-point';
    const glowId = 'fire-ignition-glow';

    // Remove existing marker
    this._removeIgnitionMarker();

    // Add marker source
    map.addSource(sourceId, {
      type: 'geojson',
      data: {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [lon, lat] },
        properties: { type: 'ignition' }
      }
    });

    // Add glow effect layer
    map.addLayer({
      id: glowId,
      type: 'circle',
      source: sourceId,
      paint: {
        'circle-radius': 16,
        'circle-color': '#ff4400',
        'circle-opacity': 0.4,
        'circle-blur': 0.8
      }
    });

    // Add main marker layer (fire symbol)
    map.addLayer({
      id: layerId,
      type: 'circle',
      source: sourceId,
      paint: {
        'circle-radius': 8,
        'circle-color': '#ff6600',
        'circle-stroke-color': '#ffcc00',
        'circle-stroke-width': 2
      }
    });

    console.log(`OverlayController: Added ignition marker at [${lon.toFixed(3)}, ${lat.toFixed(3)}]`);
  },

  /**
   * Remove ignition marker.
   * @private
   */
  _removeIgnitionMarker() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const sourceId = 'fire-ignition-marker';
    const layerId = 'fire-ignition-point';
    const glowId = 'fire-ignition-glow';

    if (map.getLayer(glowId)) map.removeLayer(glowId);
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  },

  /**
   * Hide hurricane overlay to focus on a single track animation.
   * Clears the track model layers but preserves the cached data.
   * @private
   */
  _hideHurricaneOverlay() {
    const model = ModelRegistry?.getModel('track');
    if (model?.clear) {
      model.clear();
    }
    console.log('OverlayController: Hid hurricane overlay for track drill-down');
  },

  /**
   * Restore hurricane overlay after exiting track drill-down.
   * @private
   */
  _restoreHurricaneOverlay() {
    const currentYear = this.getCurrentYear();
    if (dataCache.hurricanes) {
      this.renderFilteredData('hurricanes', currentYear);
      console.log('OverlayController: Restored hurricane overlay');
    }
  },

  /**
   * Handle hurricane track drill-down animation.
   * Fetches detailed track data and shows animated path.
   * @param {string} stormId - Storm ID
   * @param {string} stormName - Storm name
   * @param {Object} props - Storm properties
   */
  async handleHurricaneDrillDown(stormId, stormName, props) {
    console.log(`OverlayController: Starting hurricane drill-down for ${stormName} (${stormId})`);

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Fetch track data
    const trackUrl = OVERLAY_ENDPOINTS.hurricanes.trackEndpoint.replace('{storm_id}', stormId);
    try {
      const response = await fetch(trackUrl);
      const data = await response.json();

      if (!data || (!data.positions && !data.features)) {
        console.warn('OverlayController: No track data for storm', stormId);
        return;
      }

      // Normalize to positions array
      let positions = data.positions;
      if (!positions && data.features) {
        // FeatureCollection format
        positions = data.features.map(f => ({
          timestamp: f.properties.timestamp,
          latitude: f.geometry.coordinates[1],
          longitude: f.geometry.coordinates[0],
          wind_kt: f.properties.wind_kt,
          category: f.properties.category,
          ...f.properties
        }));
      }

      if (!positions || positions.length === 0) {
        console.warn('OverlayController: Empty track positions for storm', stormId);
        return;
      }

      // Hide hurricane overlay to focus on this track
      this._hideHurricaneOverlay();

      // Use TrackAnimator for proper animation with moving marker and wind radii
      TrackAnimator.start(stormId, positions, {
        stormName,
        onExit: () => {
          console.log('TrackAnimator: Animation exited');
          this._restoreHurricaneOverlay();
          this.recalculateTimeRange();
        }
      });

      // Add exit button (TrackAnimator handles its own TimeSlider setup)
      this._addGenericExitButton('track-exit-btn', 'Exit Track View', '#9c27b0', () => this._exitTrackDrillDown());

      console.log(`OverlayController: Hurricane track animation started (${positions.length} positions)`);
    } catch (err) {
      console.error('OverlayController: Error fetching hurricane track:', err);
    }
  },

  /**
   * Exit track drill-down and restore hurricane overlay.
   * @private
   */
  _exitTrackDrillDown() {
    console.log('OverlayController: Exiting track drill-down');

    // Stop TrackAnimator (handles all cleanup including TimeSlider scale)
    if (TrackAnimator.isActive) {
      TrackAnimator.stop();
    }

    // Also clear track model layers in case they were used
    const trackModel = ModelRegistry?.getModel('track');
    if (trackModel?.clear) {
      trackModel.clear();
    }

    // Exit event animation mode
    if (TimeSlider?.exitEventAnimation) {
      TimeSlider.exitEventAnimation();
    }

    // Remove exit button
    document.getElementById('track-exit-btn')?.remove();

    // Restore hurricane overlay
    this._restoreHurricaneOverlay();

    // Recalculate time range
    this.recalculateTimeRange();
  },

  /**
   * Handle aftershock sequence selection/deselection.
   * Fetches full sequence data from API (not filtered by magnitude).
   * Uses unified EventAnimator with EARTHQUAKE mode.
   * @param {string|null} sequenceId - Sequence ID or null to clear
   * @param {string|null} eventId - Optional mainshock event_id for accurate aftershock query
   */
  async handleSequenceChange(sequenceId, eventId = null) {
    console.log('OverlayController.handleSequenceChange called with:', sequenceId, eventId);

    // Stop any active animation
    if (EventAnimator.getIsActive()) {
      EventAnimator.stop();
    }

    // If no sequence selected, restore normal earthquake display and we're done
    if (!sequenceId && !eventId) {
      console.log('OverlayController: Cleared aftershock sequence');
      // Re-render all earthquakes for current year
      const currentYear = this.getCurrentYear();
      if (dataCache.earthquakes) {
        this.renderFilteredData('earthquakes', currentYear);
      }
      return;
    }

    // Fetch full sequence from API (includes ALL aftershocks regardless of magnitude filter)
    // Use eventId if provided for accurate aftershock query (handles nested sequences)
    const seqEvents = await this.fetchSequenceData(sequenceId, 'earthquake', eventId);

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

    // Determine granularity based on time range
    const timeRange = maxTime - minTime;
    const stepHours = Math.max(1, Math.ceil((timeRange / (60 * 60 * 1000)) / 200));
    let granularityLabel = '6h';
    if (stepHours < 2) granularityLabel = '1h';
    else if (stepHours < 4) granularityLabel = '2h';
    else if (stepHours < 8) granularityLabel = '6h';
    else if (stepHours < 16) granularityLabel = '12h';
    else if (stepHours < 36) granularityLabel = 'daily';
    else granularityLabel = '2d';

    // Format label
    const mainDate = new Date(mainTime);
    const label = `M${mainMag.toFixed(1)} ${mainDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;

    // Track which overlays are currently active (to restore on exit)
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
    const overlaysToRestore = activeOverlays.filter(id =>
      id !== 'demographics' && OVERLAY_ENDPOINTS[id]
    );

    // Clear normal earthquake display before starting sequence animation
    const model = ModelRegistry?.getModelForType('earthquake');
    if (model?.clear) {
      model.clear();
    }

    // Start unified EventAnimator with EARTHQUAKE mode
    EventAnimator.start({
      id: `seq-${sequenceId.substring(0, 8)}`,
      label: label,
      mode: AnimationMode.EARTHQUAKE,
      events: seqEvents,
      mainshock: mainshock,
      eventType: 'earthquake',
      timeField: 'timestamp',
      granularity: granularityLabel,
      renderer: 'point-radius',
      onExit: () => {
        console.log('OverlayController: Earthquake sequence exit callback triggered');
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
      }
    });

    const durationDays = (timeRange / (24 * 60 * 60 * 1000)).toFixed(1);
    console.log(`OverlayController: Started earthquake sequence ${sequenceId} with ${seqEvents.length} events (${durationDays} days)`);
  },

  /**
   * Fetch full sequence data from API.
   * Returns all events in the sequence regardless of magnitude filter.
   * Extensible for future cross-event linking (volcanoes, tsunamis, etc.)
   *
   * @param {string} sequenceId - Sequence ID to fetch
   * @param {string} eventType - Event type (default 'earthquake', future: 'volcano', 'tsunami')
   * @param {string} eventId - Optional event_id for mainshock-based query
   * @returns {Promise<Array>} Array of GeoJSON features
   */
  async fetchSequenceData(sequenceId, eventType = 'earthquake', eventId = null) {
    try {
      // Build API endpoint based on event type
      let endpoint;
      if (eventType === 'earthquake') {
        // Use aftershocks endpoint if eventId is provided (more accurate for nested sequences)
        // Otherwise fall back to sequence_id query
        if (eventId) {
          endpoint = `/api/earthquakes/aftershocks/${encodeURIComponent(eventId)}`;
        } else {
          endpoint = `/api/earthquakes/sequence/${encodeURIComponent(sequenceId)}`;
        }
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
    // If EventAnimator is active, forward timestamp to it
    // Note: Don't check time value - pre-1970 events have negative timestamps
    if (EventAnimator.getIsActive()) {
      EventAnimator.setTime(time);
      return;  // Don't do normal year-based filtering
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
      // Hide the hurricane overlay to focus on this single track
      this._hideHurricaneOverlay();

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

    // Restore hurricane overlay to show yearly overview
    this._restoreHurricaneOverlay();

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
