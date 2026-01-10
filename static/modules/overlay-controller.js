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
    list: '/api/earthquakes/geojson?min_magnitude=4.5',  // Default M4.5+, chat can adjust
    eventType: 'earthquake',
    yearField: 'year'  // Property name for year filtering
  },
  hurricanes: {
    list: '/api/hurricane/storms/geojson',
    eventType: 'hurricane',
    yearField: 'year'
  },
  volcanoes: {
    list: '/api/eruptions/geojson',  // Use eruptions (events) not static locations
    eventType: 'volcano',
    yearField: 'year'  // Filter eruptions by year
  },
  wildfires: {
    list: '/api/wildfires/geojson',
    eventType: 'wildfire',
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
      if (TimeSlider) {
        TimeSlider.setActiveScale('primary');
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

    // Clear normal earthquake display before starting sequence animation
    const model = ModelRegistry?.getModelForType('earthquake');
    if (model?.clear) {
      model.clear();
    }

    // Set up exit callback before starting
    SequenceAnimator.onExit(() => {
      console.log('OverlayController: Sequence exit callback triggered');
      // Remove the sequence scale from TimeSlider
      if (this.activeSequenceScaleId && TimeSlider) {
        TimeSlider.removeScale(this.activeSequenceScaleId);
        this.activeSequenceScaleId = null;
      }
      // Switch back to primary scale and reset to default time
      if (TimeSlider) {
        TimeSlider.setActiveScale('primary');
      }
      // Restore normal earthquake display for current year
      const currentYear = this.getCurrentYear();
      if (dataCache.earthquakes) {
        this.renderFilteredData('earthquakes', currentYear);
      }
    });

    // Start the sequence animator with the events
    SequenceAnimator.start(sequenceId, seqEvents, mainshock);

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
    if (SequenceAnimator.isActive() && time > 3000) {
      SequenceAnimator.setTime(time);
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
   * @param {number} time - Time value
   * @returns {number} Year
   */
  getYearFromTime(time) {
    if (!time) return null;
    // If it looks like a timestamp (> year 3000), convert
    if (time > 3000) {
      return new Date(time).getFullYear();
    }
    return time;
  },

  /**
   * Get current year from TimeSlider.
   * @returns {number|null}
   */
  getCurrentYear() {
    if (!TimeSlider?.currentTime) return null;

    // TimeSlider.currentTime can be a year (int) or timestamp (ms)
    if (TimeSlider.useTimestamps) {
      return new Date(TimeSlider.currentTime).getFullYear();
    } else {
      return TimeSlider.currentTime;
    }
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

    // Demographics controls choropleth visibility
    if (overlayId === 'demographics') {
      if (MapAdapter) {
        MapAdapter.setChoroplethVisible(isActive);
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

    this.loading.add(overlayId);

    try {
      // Fetch ALL data (no year filter - we filter client-side)
      const url = endpoint.list;
      console.log(`OverlayController: Fetching ${url}`);

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const geojson = await response.json();

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
          console.log(`OverlayController: TimeSlider range ${minYear}-${maxYear} (from data), ${sortedYears.length} years with data`);
        }
      }

      // Render filtered by current year (or all if no year filter)
      const currentYear = this.getCurrentYear();
      this.renderFilteredData(overlayId, currentYear);

    } catch (error) {
      console.error(`OverlayController: Failed to load ${overlayId}:`, error);
      this.showError(overlayId, error.message);
    } finally {
      this.loading.delete(overlayId);
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
      // Use == for type coercion (year might be string or number in data)
      const yearNum = parseInt(year);

      // Debug: sample first few features to see what year values look like
      if (cachedData.features.length > 0) {
        const sample = cachedData.features.slice(0, 3).map(f => f.properties[endpoint.yearField]);
        console.log(`OverlayController: Sample year values:`, sample, `filtering for ${yearNum}`);
      }

      const filtered = cachedData.features.filter(f => {
        const propYear = f.properties[endpoint.yearField];
        // Handle null/undefined
        if (propYear == null) return false;
        return parseInt(propYear) === yearNum;
      });
      filteredGeojson = {
        type: 'FeatureCollection',
        features: filtered
      };
      console.log(`OverlayController: Filtered ${cachedData.features.length} -> ${filtered.length} for year ${yearNum}`);
    } else {
      // No filtering - show all
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
   */
  handleEventClick(overlayId, props) {
    console.log(`OverlayController: Clicked ${overlayId} event:`, props);

    // For hurricanes, drill down into track
    if (overlayId === 'hurricanes' && props.storm_id) {
      this.drillDownHurricane(props.storm_id, props.name || props.storm_id);
    }
  },

  /**
   * Drill down into a hurricane track.
   * @param {string} stormId - Storm ID
   * @param {string} stormName - Storm name
   */
  async drillDownHurricane(stormId, stormName) {
    try {
      const response = await fetch(`/api/hurricane/track/${stormId}`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      // Build GeoJSON from positions
      const features = data.positions.map(pos => ({
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [pos.longitude, pos.latitude]
        },
        properties: {
          storm_id: stormId,
          timestamp: pos.timestamp,
          wind_kt: pos.wind_kt,
          pressure_mb: pos.pressure_mb,
          category: pos.category,
          status: pos.status
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
      }

      console.log(`OverlayController: Loaded track for ${stormName} (${data.position_count} positions)`);

    } catch (error) {
      console.error(`OverlayController: Failed to load hurricane track:`, error);
    }
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
