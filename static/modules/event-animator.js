/**
 * EventAnimator - Unified animation controller for time-based event visualization.
 *
 * Provides common infrastructure for animating different event types:
 * - TimeSlider multi-scale integration (addScale/setActiveScale/removeScale)
 * - Time stepping and playback control
 * - Exit/cleanup callbacks to restore normal display
 * - Layer lifecycle management
 *
 * Animation modes:
 * - ACCUMULATIVE: Events appear and stay visible (earthquakes, volcanoes)
 * - PROGRESSIVE: Track grows, current position highlighted (hurricanes)
 * - POLYGON: Areas expand/contract over time (wildfires, floods)
 *
 * Usage:
 *   EventAnimator.start({
 *     id: 'seq-abc123',
 *     label: 'M7.1 Jan 5',
 *     mode: 'accumulative',
 *     events: [...],           // GeoJSON features or position objects
 *     timeField: 'timestamp',  // Property containing time
 *     granularity: '6h',       // Time step size
 *     renderer: 'point-radius', // Which model renders
 *     onExit: () => {...}      // Cleanup callback
 *   });
 */

// Dependencies injected via setDependencies
let MapAdapter = null;
let TimeSlider = null;
let ModelRegistry = null;
let TIME_SYSTEM = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  TimeSlider = deps.TimeSlider;
  ModelRegistry = deps.ModelRegistry;
  TIME_SYSTEM = deps.TIME_SYSTEM;
}

// Animation modes
export const AnimationMode = {
  ACCUMULATIVE: 'accumulative',  // Events appear and stay (earthquakes)
  PROGRESSIVE: 'progressive',    // Track grows (hurricanes)
  POLYGON: 'polygon',            // Areas change over time (wildfires)
  RADIAL: 'radial'               // Source -> destinations by distance (tsunamis)
};

// Granularity to milliseconds
const GRANULARITY_MS = {
  '12m': 12 * 60 * 1000,            // 12 minutes (smooth tsunami animation)
  '1h': 1 * 60 * 60 * 1000,
  '2h': 2 * 60 * 60 * 1000,
  '6h': 6 * 60 * 60 * 1000,
  '12h': 12 * 60 * 60 * 1000,
  'daily': 24 * 60 * 60 * 1000,
  '2d': 2 * 24 * 60 * 60 * 1000,
  'weekly': 7 * 24 * 60 * 60 * 1000,
  'monthly': 30 * 24 * 60 * 60 * 1000,
  'yearly': 365 * 24 * 60 * 60 * 1000
};

// Rolling window duration based on granularity
// Events accumulate within this window, then fade out
const WINDOW_DURATIONS = {
  '12m': 2 * 60 * 60 * 1000,        // 2 hours (10 data points)
  '1h': 6 * 60 * 60 * 1000,         // 6 hours (6 data points)
  '2h': 12 * 60 * 60 * 1000,        // 12 hours
  '6h': 24 * 60 * 60 * 1000,        // 24 hours (4 data points)
  '12h': 48 * 60 * 60 * 1000,       // 48 hours
  'daily': 7 * 24 * 60 * 60 * 1000, // 7 days
  '2d': 14 * 24 * 60 * 60 * 1000,   // 14 days
  'weekly': 28 * 24 * 60 * 60 * 1000,  // 4 weeks
  'monthly': 90 * 24 * 60 * 60 * 1000, // ~3 months
  'yearly': 365 * 24 * 60 * 60 * 1000  // 1 year
};

// Inactivity multiplier: how many missed updates = event ended
// 4x the expected update interval means "probably over"
const INACTIVITY_MULTIPLIER = 4;

// Expected data update intervals per event type
// Used to calculate when continuous events are "ended"
const UPDATE_INTERVALS = {
  storm: 6 * 60 * 60 * 1000,      // 6h updates (IBTrACS)
  wildfire: 24 * 60 * 60 * 1000,  // Daily perimeter updates
  flood: 24 * 60 * 60 * 1000,     // Daily extent updates
  default: null                    // Use animation granularity
};

// Point-in-time events that don't have duration (instant events)
const INSTANT_EVENTS = ['earthquake', 'volcano', 'tornado', 'tsunami'];

// Tsunami wave propagation speed (approximate deep ocean speed)
// Used for radial mode to calculate arrival times
const TSUNAMI_SPEED_KMH = 700;  // ~700 km/h in deep ocean

/**
 * Calculate inactivity threshold for an event type.
 * Returns 0 for instant events, otherwise 4x the update interval.
 * @param {string} eventType - Event type (storm, earthquake, etc.)
 * @param {number} granularityMs - Animation granularity in ms (fallback)
 * @returns {number} Threshold in ms
 */
function getInactivityThreshold(eventType, granularityMs) {
  // Instant events never "end" - they're point-in-time
  if (INSTANT_EVENTS.includes(eventType)) {
    return 0;
  }

  // Get update interval for this event type, or use animation granularity
  const updateInterval = UPDATE_INTERVALS[eventType] || granularityMs;

  // Threshold = 4x the expected update interval
  return updateInterval * INACTIVITY_MULTIPLIER;
}

export const EventAnimator = {
  // Current animation state
  isActive: false,
  scaleId: null,
  mode: null,
  events: [],
  timestamps: [],
  currentIndex: 0,

  // Configuration
  config: null,
  onExitCallback: null,
  _timeChangeHandler: null,

  // Renderer reference (model-point-radius, model-track, model-polygon)
  renderer: null,

  // Smooth wave animation state (radial mode only)
  // Decouples visual wave circle from discrete time slider steps
  _smoothWaveLoopId: null,      // requestAnimationFrame ID
  _smoothWaveStartWall: null,   // Wall-clock time when playback started (ms)
  _smoothWaveStartSim: null,    // Simulation time when playback started (ms)
  _smoothWaveLastSim: null,     // Last rendered simulation time (for pause resume)
  _smoothWavePlaying: false,    // Tracks if we're in smooth playback mode

  /**
   * Start an animation sequence.
   * @param {Object} options Animation configuration
   * @param {string} options.id - Unique animation ID (used for TimeSlider scale)
   * @param {string} options.label - Display label for TimeSlider tab
   * @param {string} options.mode - Animation mode: 'accumulative', 'progressive', 'polygon'
   * @param {Array} options.events - Array of events/positions to animate
   * @param {string} options.timeField - Property name containing timestamp (default: 'timestamp')
   * @param {string} options.granularity - Time step: '1h', '6h', 'daily', etc.
   * @param {string} options.renderer - Model to use: 'point-radius', 'track', 'polygon'
   * @param {Object} options.rendererOptions - Options passed to renderer
   * @param {Function} options.onExit - Callback when animation exits
   * @param {Object} options.center - Optional {lat, lon} to center map
   * @param {number} options.zoom - Optional zoom level
   */
  start(options) {
    if (this.isActive) {
      console.warn('EventAnimator: Already active, stopping previous animation');
      this.stop();
    }

    console.log(`EventAnimator: Starting ${options.mode} animation for ${options.id}`);

    // Validate required options
    if (!options.id || !options.events || options.events.length === 0) {
      console.error('EventAnimator: Missing required options (id, events)');
      return false;
    }

    // Store configuration
    const granularity = options.granularity || '6h';
    const eventType = options.eventType || 'default';
    this.config = {
      id: options.id,
      label: options.label || options.id,
      mode: options.mode || AnimationMode.ACCUMULATIVE,
      timeField: options.timeField || 'timestamp',
      granularity: granularity,
      rendererName: options.renderer || 'point-radius',
      // Merge eventType into rendererOptions for layer creation
      rendererOptions: { eventType, ...(options.rendererOptions || {}) },
      center: options.center,
      zoom: options.zoom,
      // Rolling window configuration
      windowMs: options.windowMs || WINDOW_DURATIONS[granularity] || WINDOW_DURATIONS['daily'],
      eventType: eventType,
      // Whether to use fade effect (can be disabled)
      useFade: options.useFade !== false
    };

    this.mode = this.config.mode;
    this.events = options.events;
    this.onExitCallback = options.onExit;
    this.isActive = true;

    // Get renderer from ModelRegistry
    this.renderer = ModelRegistry?.getModel(this.config.rendererName);
    if (!this.renderer) {
      console.error(`EventAnimator: Renderer '${this.config.rendererName}' not found`);
      this.stop();
      return false;
    }

    // Extract and sort timestamps
    this._buildTimestamps();

    if (this.timestamps.length === 0) {
      console.error('EventAnimator: No valid timestamps found in events');
      this.stop();
      return false;
    }

    // Setup TimeSlider scale
    this._setupTimeSlider();

    // Center map if requested
    if (this.config.center) {
      this._centerMap();
    }

    // Add exit button
    this._addExitButton();

    // Render initial state (start of animation)
    this.currentIndex = 0;
    this._renderAtTime(this.timestamps[0]);

    // Start smooth wave animation loop for radial mode (tsunamis)
    // This provides 60 FPS wave circle updates independent of TimeSlider ticks
    if (this.mode === AnimationMode.RADIAL) {
      this._startSmoothWaveLoop();
    }

    console.log(`EventAnimator: Started with ${this.events.length} events, ${this.timestamps.length} time steps`);
    return true;
  },

  /**
   * Stop animation and cleanup.
   */
  stop() {
    if (!this.isActive) return;

    console.log('EventAnimator: Stopping');

    // Stop smooth wave animation loop (radial mode)
    this._stopSmoothWaveLoop();

    // Remove TimeSlider scale and listener
    if (TimeSlider) {
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

    // Clear renderer
    if (this.renderer?.clear) {
      this.renderer.clear();
    }

    // Remove exit button container
    const controls = document.getElementById('event-animator-controls');
    if (controls) controls.remove();

    // Call exit callback
    if (this.onExitCallback) {
      try {
        this.onExitCallback();
      } catch (e) {
        console.error('EventAnimator: Error in onExit callback:', e);
      }
    }

    // Reset state
    this.isActive = false;
    this.config = null;
    this.events = [];
    this.timestamps = [];
    this.currentIndex = 0;
    this.renderer = null;
    this.onExitCallback = null;
  },

  /**
   * Set animation to specific timestamp.
   * @param {number} timestamp - Target timestamp (ms)
   */
  setTime(timestamp) {
    if (!this.isActive) return;

    // Find closest timestamp index
    const index = this._findClosestIndex(timestamp);
    if (index === this.currentIndex) return;

    this.currentIndex = index;
    this._renderAtTime(this.timestamps[index]);

    // Sync smooth wave loop to new position (radial mode)
    // This ensures wave radius matches after user seeks
    if (this.mode === AnimationMode.RADIAL) {
      this._smoothWaveLastSim = this.timestamps[index];
      // If currently playing, reset start times for smooth continuation
      if (this._smoothWavePlaying) {
        this._smoothWaveStartWall = performance.now();
        this._smoothWaveStartSim = this.timestamps[index];
      }
    }
  },

  /**
   * Check if animator is currently active.
   * @returns {boolean}
   */
  getIsActive() {
    return this.isActive;
  },

  // ========================================================================
  // PRIVATE METHODS
  // ========================================================================

  /**
   * Build sorted timestamp array from events.
   * For radial mode (tsunamis), generates synthetic timestamps based on wave propagation.
   * @private
   */
  _buildTimestamps() {
    const timeField = this.config.timeField;
    const granularityMs = GRANULARITY_MS[this.config.granularity] || GRANULARITY_MS['6h'];

    // For radial mode, generate timestamps based on wave propagation
    if (this.mode === AnimationMode.RADIAL) {
      this._buildRadialTimestamps(granularityMs);
      return;
    }

    // Extract all timestamps for other modes
    const rawTimestamps = new Set();
    for (const event of this.events) {
      const props = event.properties || event;
      const timeVal = props[timeField];
      if (timeVal) {
        const ts = new Date(timeVal).getTime();
        if (!isNaN(ts)) {
          // Bucket to granularity
          const bucket = Math.floor(ts / granularityMs) * granularityMs;
          rawTimestamps.add(bucket);
        }
      }
    }

    // Sort timestamps
    this.timestamps = Array.from(rawTimestamps).sort((a, b) => a - b);

    // Also bucket events by timestamp for efficient lookup
    this._eventsByTime = {};
    for (const event of this.events) {
      const props = event.properties || event;
      const timeVal = props[timeField];
      if (timeVal) {
        const ts = new Date(timeVal).getTime();
        const bucket = Math.floor(ts / granularityMs) * granularityMs;
        if (!this._eventsByTime[bucket]) {
          this._eventsByTime[bucket] = [];
        }
        this._eventsByTime[bucket].push(event);
      }
    }
  },

  /**
   * Build timestamps for radial mode (tsunami wave propagation).
   * Generates synthetic timestamps based on source time and wave travel distance.
   * Animation duration scales with farthest runup: 1 second = 1 hour at normal playback.
   * @private
   */
  _buildRadialTimestamps(granularityMs) {
    const timeField = this.config.timeField;

    // Find source event and its timestamp
    const sourceEvent = this.events.find(e => {
      const props = e.properties || e;
      return props.is_source === true;
    });

    if (!sourceEvent) {
      console.warn('EventAnimator: No source event found for radial mode');
      this.timestamps = [];
      return;
    }

    const sourceProps = sourceEvent.properties || sourceEvent;
    const sourceTime = new Date(sourceProps[timeField]).getTime();

    if (isNaN(sourceTime)) {
      console.warn('EventAnimator: Source event has no valid timestamp');
      this.timestamps = [];
      return;
    }

    // Find maximum distance to any runup
    // Check multiple possible property names for distance
    let maxDistanceKm = 0;
    let farthestRunup = null;
    let runupsWithDistance = 0;
    let runupsWithoutDistance = 0;

    for (const event of this.events) {
      const props = event.properties || event;
      if (props.is_source) continue;

      // Check all possible distance property names
      // Use Number() to handle string values properly
      const rawDist = props.dist_from_source_km ??
                      props.distance_km ??
                      props.distance_from_source_km ??
                      props.distanceKm ??
                      props.distance;

      const distKm = rawDist != null ? Number(rawDist) : 0;

      if (distKm > 0) {
        runupsWithDistance++;
        if (distKm > maxDistanceKm) {
          maxDistanceKm = distKm;
          farthestRunup = props.location_name || props.name || props.country || 'unknown';
        }
      } else {
        runupsWithoutDistance++;
      }
    }

    // Log diagnostic info
    console.log(`EventAnimator: Radial mode analysis - ${runupsWithDistance} runups have distance, ${runupsWithoutDistance} missing distance`);

    // Calculate animation duration based on wave travel time
    // Wave travels at TSUNAMI_SPEED_KMH (700 km/h)
    // Add 10% buffer to ensure animation completes after wave reaches farthest point
    const travelHours = (maxDistanceKm / TSUNAMI_SPEED_KMH) * 1.1;
    const travelMs = travelHours * 60 * 60 * 1000;

    // Minimum 2 hours of animation even for close runups
    const minAnimationMs = 2 * 60 * 60 * 1000;
    const animationDurationMs = Math.max(travelMs, minAnimationMs);

    // Generate timestamps from source time to source time + travel duration
    this.timestamps = [];
    const endTime = sourceTime + animationDurationMs;

    for (let t = sourceTime; t <= endTime; t += granularityMs) {
      this.timestamps.push(t);
    }

    // Store source time for radial calculations
    this._radialSourceTime = sourceTime;
    this._radialMaxDistance = maxDistanceKm;

    // Initialize empty eventsByTime (radial mode calculates visibility differently)
    this._eventsByTime = {};

    console.log(`EventAnimator: Radial mode - ${this.timestamps.length} time steps, ` +
                `${maxDistanceKm.toFixed(0)}km max distance (farthest: ${farthestRunup}), ` +
                `${travelHours.toFixed(1)}h animation (~${Math.ceil(travelHours)} sec at 1x speed)`);
  },

  /**
   * Setup TimeSlider for animation.
   * @private
   */
  _setupTimeSlider() {
    if (!TimeSlider) {
      console.warn('EventAnimator: TimeSlider not available');
      return;
    }

    this.scaleId = `anim-${this.config.id.substring(0, 12)}`;

    // Build timeData structure for TimeSlider
    const timeData = {};
    for (const ts of this.timestamps) {
      timeData[ts] = { eventCount: (this._eventsByTime[ts] || []).length };
    }

    const minTime = this.timestamps[0];
    const maxTime = this.timestamps[this.timestamps.length - 1];

    // Add scale
    const added = TimeSlider.addScale({
      id: this.scaleId,
      label: this.config.label,
      granularity: this.config.granularity,
      useTimestamps: true,
      currentTime: minTime,
      timeRange: {
        min: minTime,
        max: maxTime,
        available: this.timestamps
      },
      timeData: timeData,
      mapRenderer: 'event-animation'
    });

    if (added) {
      TimeSlider.setActiveScale(this.scaleId);

      // Enter event animation mode with auto-calculated speed for ~10 second playback
      if (TimeSlider.enterEventAnimation) {
        TimeSlider.enterEventAnimation(minTime, maxTime);
      }

      // Listen for time changes
      this._timeChangeHandler = (time, source) => {
        if (source !== 'event-animator' && time > 3000) {
          this.setTime(time);
        }
      };
      TimeSlider.addChangeListener(this._timeChangeHandler);

      console.log(`EventAnimator: Added TimeSlider scale ${this.scaleId}`);
    }
  },

  /**
   * Center map on animation area.
   * @private
   */
  _centerMap() {
    if (!MapAdapter?.map) return;

    const { center, zoom } = this.config;
    if (center?.lat && center?.lon) {
      MapAdapter.map.flyTo({
        center: [center.lon, center.lat],
        zoom: zoom || 6,
        duration: 1500
      });
    }
  },

  /**
   * Start smooth wave animation loop for radial mode.
   * Runs at 60 FPS independently of TimeSlider discrete steps.
   * Wave circle grows smoothly while runups still appear at discrete times.
   * @private
   */
  _startSmoothWaveLoop() {
    if (this.mode !== AnimationMode.RADIAL) return;
    if (!MapAdapter?.map) return;

    // Initialize last simulation time to source time
    this._smoothWaveLastSim = this._radialSourceTime || this.timestamps[0];

    // Monitor TimeSlider playback state
    const checkPlaybackAndRender = () => {
      if (!this.isActive || this.mode !== AnimationMode.RADIAL) {
        this._smoothWaveLoopId = null;
        return;
      }

      const nowPlaying = TimeSlider?.isPlaying || false;

      // Detect play start
      if (nowPlaying && !this._smoothWavePlaying) {
        this._smoothWaveStartWall = performance.now();
        this._smoothWaveStartSim = this._smoothWaveLastSim;
        this._smoothWavePlaying = true;
      }

      // Detect pause
      if (!nowPlaying && this._smoothWavePlaying) {
        this._smoothWavePlaying = false;
        // Preserve current simulation time for resume
      }

      // If playing, calculate smooth simulation time
      if (this._smoothWavePlaying && TimeSlider && TIME_SYSTEM) {
        const wallElapsed = performance.now() - this._smoothWaveStartWall;

        // Calculate speed: stepsPerFrame * BASE_STEP_MS per frame, at TIME_SYSTEM.MAX_FPS
        // speedMultiplier = how many simulation ms pass per real ms
        // When MAX_FPS increases from 15 to 60, speed stays correct because
        // TimeSlider adjusts stepsPerFrame accordingly
        const stepsPerFrame = TimeSlider.stepsPerFrame || 1;
        const baseStepMs = TIME_SYSTEM.BASE_STEP_MS;  // 6 hours in ms
        const fps = TIME_SYSTEM.MAX_FPS;  // Currently 15, will be 60 later
        const speedMultiplier = (stepsPerFrame * baseStepMs * fps) / 1000;

        // Smooth simulation time
        const smoothSimTime = this._smoothWaveStartSim + (wallElapsed * speedMultiplier);

        // Clamp to animation range
        const minTime = this.timestamps[0];
        const maxTime = this.timestamps[this.timestamps.length - 1];
        const clampedSimTime = Math.max(minTime, Math.min(maxTime, smoothSimTime));

        // Update wave radius only (not full render)
        this._updateWaveRadiusSmooth(clampedSimTime);

        // Save for resume
        this._smoothWaveLastSim = clampedSimTime;

        // Check if animation completed
        if (smoothSimTime >= maxTime) {
          // Animation finished - let TimeSlider handle loop/pause
        }
      }

      // Continue loop
      this._smoothWaveLoopId = requestAnimationFrame(checkPlaybackAndRender);
    };

    // Start the loop
    this._smoothWaveLoopId = requestAnimationFrame(checkPlaybackAndRender);
    console.log('EventAnimator: Started smooth wave animation loop');
  },

  /**
   * Update only the wave circle radius without re-rendering all features.
   * Uses direct source data update for smooth 60 FPS animation.
   * @private
   */
  _updateWaveRadiusSmooth(simTime) {
    if (!MapAdapter?.map) return;

    const sourceTime = this._radialSourceTime;
    if (!sourceTime) return;

    // Calculate wave distance at this simulation time
    const elapsedMs = Math.max(0, simTime - sourceTime);
    const elapsedHours = elapsedMs / (1000 * 60 * 60);
    const waveRadiusKm = elapsedHours * TSUNAMI_SPEED_KMH;

    // Find the source in the map layer and update its properties
    const map = MapAdapter.map;
    const sourceId = 'events-point-radius';  // From model-point-radius CONFIG

    // Get current source data
    const source = map.getSource(sourceId);
    if (!source) return;

    // Get source's current data and update the source event's wave radius
    const currentData = source._data;
    if (!currentData || !currentData.features) return;

    // Find and update source event
    let updated = false;
    for (const feature of currentData.features) {
      if (feature.properties?.is_source === true) {
        feature.properties._waveRadiusKm = waveRadiusKm;
        feature.properties._elapsedHours = elapsedHours;
        updated = true;
        break;
      }
    }

    if (updated) {
      // Trigger re-render with updated data
      source.setData(currentData);
    }
  },

  /**
   * Stop smooth wave animation loop.
   * @private
   */
  _stopSmoothWaveLoop() {
    if (this._smoothWaveLoopId) {
      cancelAnimationFrame(this._smoothWaveLoopId);
      this._smoothWaveLoopId = null;
    }
    this._smoothWaveStartWall = null;
    this._smoothWaveStartSim = null;
    this._smoothWaveLastSim = null;
    this._smoothWavePlaying = false;
  },

  /**
   * Add exit button to UI.
   * Positioned at top center to match track controls style.
   * @private
   */
  _addExitButton() {
    // Remove existing container if any
    const existing = document.getElementById('event-animator-controls');
    if (existing) existing.remove();

    // Create container at top center (matching track controls)
    const container = document.createElement('div');
    container.id = 'event-animator-controls';
    container.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      gap: 12px;
      z-index: 1000;
    `;

    // Exit button (gray to match "Back to..." style)
    const exitBtn = document.createElement('button');
    exitBtn.id = 'event-animator-exit-btn';
    exitBtn.textContent = 'Exit Animation';
    exitBtn.style.cssText = `
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

    exitBtn.addEventListener('click', () => this.stop());
    container.appendChild(exitBtn);
    document.body.appendChild(container);
  },

  /**
   * Find closest timestamp index for a given time.
   * @private
   */
  _findClosestIndex(timestamp) {
    let closest = 0;
    let minDiff = Math.abs(this.timestamps[0] - timestamp);

    for (let i = 1; i < this.timestamps.length; i++) {
      const diff = Math.abs(this.timestamps[i] - timestamp);
      if (diff < minDiff) {
        minDiff = diff;
        closest = i;
      }
    }

    return closest;
  },

  /**
   * Render events at a specific time based on animation mode.
   * @private
   */
  _renderAtTime(timestamp) {
    if (!this.renderer) return;

    let displayEvents;

    switch (this.mode) {
      case AnimationMode.ACCUMULATIVE:
        // Show all events up to and including this time
        displayEvents = this._getEventsUpTo(timestamp);
        break;

      case AnimationMode.PROGRESSIVE:
        // Show track up to this point, highlight current position
        displayEvents = this._getProgressiveState(timestamp);
        break;

      case AnimationMode.POLYGON:
        // Show polygon state at this exact time
        displayEvents = this._getPolygonState(timestamp);
        break;

      case AnimationMode.RADIAL:
        // Show source event + runups based on wave travel time
        displayEvents = this._getRadialState(timestamp);
        break;

      default:
        displayEvents = this._getEventsUpTo(timestamp);
    }

    // Build GeoJSON and render
    const geojson = this._buildDisplayGeojson(displayEvents);

    if (this.renderer.update) {
      this.renderer.update(geojson, this.config.rendererOptions);
    } else if (this.renderer.render) {
      this.renderer.render(geojson, 'animation', this.config.rendererOptions);
    }

    // Progressive zoom for radial mode (tsunamis)
    if (this.mode === AnimationMode.RADIAL && displayEvents.source) {
      this._updateRadialZoom(displayEvents);
    }
  },

  /**
   * Update map zoom level during radial animation.
   * Starts zoomed in on source, progressively zooms out as wave expands.
   * @private
   */
  _updateRadialZoom(radialState) {
    if (!MapAdapter?.map) return;

    const { source, maxDistanceKm } = radialState;
    if (!source || maxDistanceKm === undefined) return;

    // Get source coordinates for centering
    const sourceProps = source.properties || source;
    const sourceLon = source.geometry?.coordinates?.[0] ||
                      sourceProps.longitude || sourceProps.lon;
    const sourceLat = source.geometry?.coordinates?.[1] ||
                      sourceProps.latitude || sourceProps.lat;

    if (sourceLon === undefined || sourceLat === undefined) return;

    // Calculate zoom level based on wave distance
    // Start at zoom 7 (close), progressively zoom out to show wider area
    // At 0 km: zoom 7 (very close to source)
    // At 500 km: zoom 5
    // At 2000 km: zoom 3
    // At 5000+ km: zoom 2 (global view)
    const targetZoom = this._calculateZoomForDistance(maxDistanceKm);

    // Only update if zoom changed significantly (>0.3 levels) to avoid jitter
    const currentZoom = MapAdapter.map.getZoom();
    if (Math.abs(currentZoom - targetZoom) > 0.3) {
      // Use flyTo for smooth transition, but keep duration short for animation
      MapAdapter.map.flyTo({
        center: [sourceLon, sourceLat],
        zoom: targetZoom,
        duration: 800,  // Fast but smooth
        essential: true // Don't skip this animation
      });
    }
  },

  /**
   * Calculate appropriate zoom level for a given wave distance.
   * Uses logarithmic scale for smooth zoom out.
   * @private
   */
  _calculateZoomForDistance(distanceKm) {
    // Clamp distance to reasonable range
    const dist = Math.max(10, Math.min(distanceKm, 10000));

    // Logarithmic interpolation
    // log10(10) = 1 -> zoom 7
    // log10(100) = 2 -> zoom 6
    // log10(500) = 2.7 -> zoom 5
    // log10(2000) = 3.3 -> zoom 4
    // log10(5000) = 3.7 -> zoom 3
    // log10(10000) = 4 -> zoom 2
    const logDist = Math.log10(dist);

    // Map log10(10..10000) i.e. (1..4) to zoom (7..2)
    // zoom = 7 - (logDist - 1) * (5/3)
    const zoom = 7 - (logDist - 1) * (5 / 3);

    return Math.max(2, Math.min(7, zoom));
  },

  /**
   * Calculate recency for an event within the rolling window.
   * Returns values 0.0 to 1.5:
   *   1.5 = just happened (flash/pulse effect)
   *   1.0 = recent but not brand new
   *   0.0 = at edge of window (about to fade out)
   *
   * The "flash" period is the first 10% of the window duration.
   * @private
   */
  _calculateRecency(eventTime, currentTime, windowMs) {
    const age = currentTime - eventTime;
    if (age < 0) return 1.5;  // Future event (shouldn't happen, but treat as new)
    if (age >= windowMs) return 0.0;  // Beyond window

    // Flash period: first 10% of window gets brightness boost
    const flashWindow = windowMs * 0.1;
    if (age <= flashWindow) {
      // Interpolate from 1.5 (brand new) to 1.0 (end of flash period)
      return 1.5 - (0.5 * (age / flashWindow));
    }

    // Normal fade: remaining 90% of window fades from 1.0 to 0.0
    const remainingAge = age - flashWindow;
    const remainingWindow = windowMs - flashWindow;
    return 1.0 - (remainingAge / remainingWindow);
  },

  /**
   * Check if a continuous event has "ended" based on inactivity.
   * Uses 4x the expected update interval as threshold.
   * For instant events (earthquakes): always returns false.
   * @private
   */
  _isEventEnded(event, timestamp, granularityMs) {
    const eventType = this.config.eventType || 'default';
    const threshold = getInactivityThreshold(eventType, granularityMs);

    if (threshold === 0) return false;  // Instant events never "end"

    // For continuous events, check if there's a later update within threshold
    const timeField = this.config.timeField;
    const eventTime = new Date((event.properties || event)[timeField]).getTime();

    // If this event has an explicit end time, use that
    const endTime = (event.properties || event).end_time || (event.properties || event).endTime;
    if (endTime) {
      return new Date(endTime).getTime() < timestamp;
    }

    // Otherwise, check if this is the last observation within threshold window
    const timeSinceEvent = timestamp - eventTime;
    return timeSinceEvent > threshold;
  },

  /**
   * Get all events up to and including timestamp (accumulative mode).
   * Uses rolling window to limit how far back events are shown.
   * Adds recency property for opacity fading.
   * @private
   */
  _getEventsUpTo(timestamp) {
    const timeField = this.config.timeField;
    const windowMs = this.config.windowMs;
    const useFade = this.config.useFade;
    const granularityMs = GRANULARITY_MS[this.config.granularity] || GRANULARITY_MS['6h'];

    // Window start time (how far back to show events)
    const windowStart = timestamp - windowMs;

    return this.events
      .filter(event => {
        const props = event.properties || event;
        const t = new Date(props[timeField]).getTime();

        // Event must be before or at current time
        if (t > timestamp) return false;

        // Event must be within rolling window
        if (t < windowStart) return false;

        // Check if continuous events have "ended" (no recent updates)
        // Note: We still show them in window but mark as ended for potential styling
        return true;
      })
      .map(event => {
        const props = event.properties || event;
        const eventTime = new Date(props[timeField]).getTime();

        // Calculate recency for opacity
        const recency = useFade ? this._calculateRecency(eventTime, timestamp, windowMs) : 1.0;

        // Check if event is considered "ended"
        const isEnded = this._isEventEnded(event, timestamp, granularityMs);

        // Return enriched event with animation properties
        if (event.type === 'Feature') {
          return {
            ...event,
            properties: {
              ...event.properties,
              _recency: recency,
              _isEnded: isEnded
            }
          };
        } else {
          return {
            ...event,
            _recency: recency,
            _isEnded: isEnded
          };
        }
      });
  },

  /**
   * Get progressive state (track mode).
   * Returns { track: [...], current: event, past: [...] }
   * Past positions include recency for trail fade effect.
   * @private
   */
  _getProgressiveState(timestamp) {
    const timeField = this.config.timeField;
    const windowMs = this.config.windowMs;
    const useFade = this.config.useFade;

    const sorted = [...this.events].sort((a, b) => {
      const ta = new Date((a.properties || a)[timeField]).getTime();
      const tb = new Date((b.properties || b)[timeField]).getTime();
      return ta - tb;
    });

    // Find index of current position
    let currentIdx = 0;
    for (let i = 0; i < sorted.length; i++) {
      const t = new Date((sorted[i].properties || sorted[i])[timeField]).getTime();
      if (t <= timestamp) {
        currentIdx = i;
      } else {
        break;
      }
    }

    // Window start for trail effect
    const windowStart = timestamp - windowMs;

    // Enrich past positions with recency for trail fade
    const enrichedTrack = sorted.slice(0, currentIdx + 1).map((event, idx) => {
      const props = event.properties || event;
      const eventTime = new Date(props[timeField]).getTime();

      // Only calculate recency for positions within window
      let recency = 1.0;
      if (useFade && eventTime < windowStart) {
        recency = 0.0;  // Beyond window
      } else if (useFade && idx < currentIdx) {
        // Within window but not current - fade based on position age
        recency = this._calculateRecency(eventTime, timestamp, windowMs);
      }

      if (event.type === 'Feature') {
        return {
          ...event,
          properties: {
            ...event.properties,
            _recency: recency,
            _isCurrent: idx === currentIdx
          }
        };
      } else {
        return {
          ...event,
          _recency: recency,
          _isCurrent: idx === currentIdx
        };
      }
    });

    return {
      track: enrichedTrack,
      current: enrichedTrack[currentIdx],
      past: enrichedTrack.slice(0, currentIdx),
      currentIndex: currentIdx,
      totalPositions: sorted.length,
      windowStart: windowStart
    };
  },

  /**
   * Get polygon state at timestamp.
   * For wildfires: find the polygon closest to this time.
   * @private
   */
  _getPolygonState(timestamp) {
    const granularityMs = GRANULARITY_MS[this.config.granularity] || GRANULARITY_MS['daily'];

    // Find events within this time bucket
    const bucket = Math.floor(timestamp / granularityMs) * granularityMs;
    return this._eventsByTime[bucket] || [];
  },

  /**
   * Get radial propagation state for tsunamis.
   * Source event appears immediately, runups appear based on wave travel time.
   *
   * Events should have:
   * - is_source: true for the source epicenter
   * - dist_from_source_km: distance from source (for runups)
   *
   * @private
   */
  _getRadialState(timestamp) {
    const timeField = this.config.timeField;
    const windowMs = this.config.windowMs;
    const useFade = this.config.useFade;

    // Find source event (epicenter)
    const sourceEvent = this.events.find(e => {
      const props = e.properties || e;
      return props.is_source === true;
    });

    if (!sourceEvent) {
      console.warn('EventAnimator: Radial mode requires a source event (is_source: true)');
      return { source: null, runups: [], connections: [] };
    }

    // Get source time
    const sourceProps = sourceEvent.properties || sourceEvent;
    const sourceTime = new Date(sourceProps[timeField]).getTime();

    // Source not yet visible
    if (timestamp < sourceTime) {
      return { source: null, runups: [], connections: [] };
    }

    // Time elapsed since source event
    const elapsedMs = timestamp - sourceTime;
    const elapsedHours = elapsedMs / (1000 * 60 * 60);

    // Distance the wave could have traveled (capped at farthest runup)
    const theoreticalDistanceKm = elapsedHours * TSUNAMI_SPEED_KMH;
    const maxDistanceKm = Math.min(theoreticalDistanceKm, this._radialMaxDistance || theoreticalDistanceKm);

    // Filter runups that would have been reached by wave
    const visibleRunups = [];
    const connections = [];

    for (const event of this.events) {
      const props = event.properties || event;

      // Skip source event
      if (props.is_source === true) continue;

      // Get distance from source (check multiple property names)
      // Use ?? to handle 0 values correctly, then Number() for string conversion
      const rawDist = props.dist_from_source_km ??
                      props.distance_km ??
                      props.distance_from_source_km ??
                      props.distanceKm ??
                      props.distance;
      const distKm = rawDist != null ? Number(rawDist) : 0;

      // Runup is visible if wave has passed it
      // Add 5% buffer so runups appear slightly after the wave front reaches them
      // This compensates for visual mismatch between circle rendering and geographic distance
      const visibilityBuffer = distKm * 0.05;  // 5% of runup distance
      if ((distKm + visibilityBuffer) <= maxDistanceKm) {
        // Calculate when wave arrived at this runup
        const arrivalHours = distKm / TSUNAMI_SPEED_KMH;
        const arrivalMs = arrivalHours * 60 * 60 * 1000;
        const arrivalTime = sourceTime + arrivalMs;

        // Calculate recency based on time since arrival (not source time)
        const recency = useFade
          ? this._calculateRecency(arrivalTime, timestamp, windowMs)
          : 1.0;

        // Enrich event with animation properties
        const enrichedEvent = event.type === 'Feature' ? {
          ...event,
          properties: {
            ...event.properties,
            _recency: recency,
            _arrivalTime: arrivalTime,
            _distanceKm: distKm
          }
        } : {
          ...event,
          _recency: recency,
          _arrivalTime: arrivalTime,
          _distanceKm: distKm
        };

        visibleRunups.push(enrichedEvent);

        // Build connection line from source to runup
        const sourceCoords = sourceEvent.geometry?.coordinates ||
                            [sourceProps.longitude || sourceProps.lon, sourceProps.latitude || sourceProps.lat];
        let runupCoords = event.geometry?.coordinates ||
                           [props.longitude || props.lon, props.latitude || props.lat];

        if (sourceCoords && runupCoords) {
          // Handle international date line crossing
          // If longitude difference > 180, adjust runup coords to take short path
          runupCoords = [...runupCoords];  // Copy to avoid mutating original
          const lngDiff = runupCoords[0] - sourceCoords[0];
          if (Math.abs(lngDiff) > 180) {
            if (lngDiff > 0) {
              runupCoords[0] -= 360;
            } else {
              runupCoords[0] += 360;
            }
          }

          connections.push({
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: [sourceCoords, runupCoords]
            },
            properties: {
              _recency: recency,
              _distanceKm: distKm,
              runup_id: props.runup_id || props.id
            }
          });
        }
      }
    }

    // Enrich source event with wave propagation data
    const enrichedSource = sourceEvent.type === 'Feature' ? {
      ...sourceEvent,
      properties: {
        ...sourceEvent.properties,
        _recency: 1.0,
        _isSource: true,
        _waveRadiusKm: maxDistanceKm,  // Current wave front distance
        _elapsedHours: elapsedHours
      }
    } : {
      ...sourceEvent,
      _recency: 1.0,
      _isSource: true,
      _waveRadiusKm: maxDistanceKm,
      _elapsedHours: elapsedHours
    };

    return {
      source: enrichedSource,
      runups: visibleRunups,
      connections: connections,
      elapsedHours: elapsedHours,
      maxDistanceKm: maxDistanceKm,
      sourceTime: sourceTime
    };
  },

  /**
   * Build GeoJSON from display events.
   * Ensures recency and animation properties are preserved.
   * @private
   */
  _buildDisplayGeojson(eventsOrState) {
    // Handle progressive mode which returns an object
    if (eventsOrState && eventsOrState.track) {
      // Progressive mode - renderer handles the structure
      // Track positions already have _recency from _getProgressiveState
      return eventsOrState;
    }

    // Handle radial mode which returns { source, runups, connections }
    if (eventsOrState && (eventsOrState.source !== undefined || eventsOrState.runups)) {
      // Radial mode - convert to GeoJSON FeatureCollection
      const features = [];

      // Add source event
      if (eventsOrState.source) {
        features.push(eventsOrState.source);
      }

      // Add runup events
      if (eventsOrState.runups && eventsOrState.runups.length > 0) {
        features.push(...eventsOrState.runups);
      }

      // Add connection lines
      if (eventsOrState.connections && eventsOrState.connections.length > 0) {
        features.push(...eventsOrState.connections);
      }

      return {
        type: 'FeatureCollection',
        features,
        // Preserve metadata for potential use
        metadata: {
          elapsedHours: eventsOrState.elapsedHours,
          maxDistanceKm: eventsOrState.maxDistanceKm,
          sourceTime: eventsOrState.sourceTime
        }
      };
    }

    // Standard event array
    const features = (eventsOrState || []).map(event => {
      if (event.type === 'Feature') {
        // Already a GeoJSON feature with enriched properties
        return event;
      }

      // Convert position object to GeoJSON feature
      // Preserve animation properties (_recency, _isEnded)
      const { _recency, _isEnded, longitude, latitude, lon, lat, ...otherProps } = event;
      const lng = longitude || lon;
      const latVal = latitude || lat;

      return {
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [lng, latVal]
        },
        properties: {
          ...otherProps,
          _recency: _recency !== undefined ? _recency : 1.0,
          _isEnded: _isEnded || false
        }
      };
    });

    return {
      type: 'FeatureCollection',
      features
    };
  }
};

export default EventAnimator;
