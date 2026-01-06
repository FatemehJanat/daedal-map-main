/**
 * Time Slider - Controls time selection for temporal data.
 * Supports multiple granularities: 6h, daily, weekly, monthly, yearly, 5y, 10y.
 * Handles playback animation and time-based data filtering.
 *
 * For sub-yearly data (6h, daily, weekly, monthly):
 *   - Uses timestamps (ms since epoch) as keys
 *   - init() with {granularity: '6h', useTimestamps: true}
 *
 * For yearly+ data (yearly, 5y, 10y):
 *   - Uses integer years as keys (backward compatible)
 *   - init() with {granularity: 'yearly'} or omit for default
 */

// Dependencies set via setDependencies to avoid circular imports
let MapAdapter = null;
let ChoroplethManager = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  ChoroplethManager = deps.ChoroplethManager;
}

// ============================================================================
// TIME SLIDER - Controls year selection for multi-year data
// ============================================================================

export const TimeSlider = {
  container: null,
  slider: null,
  yearLabel: null,
  playBtn: null,
  stepBackBtn: null,
  stepFwdBtn: null,
  rewindBtn: null,
  fastFwdBtn: null,
  minLabel: null,
  maxLabel: null,
  titleLabel: null,

  // Data state
  timeData: null,      // {time: {loc_id: {metric: value}}} - original data (time = year or timestamp)
  timeDataFilled: null, // {time: {loc_id: {metric, data_time}}} - with gaps filled
  baseGeojson: null,   // Geometry without time-specific values
  metricKey: null,     // Which property to color by
  currentTime: null,   // Current year (int) or timestamp (ms)
  minTime: null,
  maxTime: null,
  availableTimes: [],  // Times that actually have data
  sortedTimes: [],     // Sorted array for navigation
  isPlaying: false,
  playInterval: null,
  playSpeed: 1,        // 1 = normal, 3 = fast
  playDirection: 1,    // 1 = forward, -1 = rewind
  listenersSetup: false,  // Track if event listeners have been added

  // Granularity support
  granularity: 'yearly',  // '6h', 'daily', 'weekly', 'monthly', 'yearly', '5y', '10y'
  useTimestamps: false,   // true for sub-yearly (6h, daily, weekly, monthly), false for yearly+
  stepMs: null,           // Step size in milliseconds (for sub-yearly)

  // Multi-scale support (Phase 3)
  scales: [],             // Array of scale objects
  activeScaleId: null,    // Currently active scale ID
  tabContainer: null,     // Tab bar DOM element
  MAX_SCALES: 3,          // Maximum allowed scales

  /**
   * Calculate step size in milliseconds for a given granularity
   */
  calculateStepMs(granularity) {
    const HOUR = 3600000;
    const DAY = 86400000;
    switch (granularity) {
      case '6h': return HOUR * 6;
      case 'daily': return DAY;
      case 'weekly': return DAY * 7;
      case 'monthly': return DAY * 30;  // Approximate
      case 'yearly': return DAY * 365;
      case '5y': return DAY * 365 * 5;
      case '10y': return DAY * 365 * 10;
      default: return DAY * 365;
    }
  },

  /**
   * Format time label based on current granularity
   */
  formatTimeLabel(time) {
    // For yearly+ granularity with integer years
    if (!this.useTimestamps) {
      const year = typeof time === 'number' ? time : parseInt(time);
      switch (this.granularity) {
        case '5y':
          return `${year}-${year + 4}`;
        case '10y':
          return `${year}-${year + 9}`;
        default:
          return year.toString();
      }
    }

    // For sub-yearly with timestamps
    const date = new Date(time);
    switch (this.granularity) {
      case '6h':
        return date.toLocaleString('en-US', {
          month: 'short', day: 'numeric', year: 'numeric',
          hour: '2-digit', minute: '2-digit'
        });
      case 'daily':
        return date.toLocaleDateString('en-US', {
          month: 'short', day: 'numeric', year: 'numeric'
        });
      case 'weekly':
        return `Week of ${date.toLocaleDateString('en-US', {
          month: 'short', day: 'numeric'
        })}`;
      case 'monthly':
        return date.toLocaleDateString('en-US', {
          month: 'short', year: 'numeric'
        });
      default:
        return date.getFullYear().toString();
    }
  },

  /**
   * Get playback interval based on granularity (faster for finer granularity)
   */
  getPlaybackInterval() {
    const baseIntervals = {
      '6h': 150,      // Fast for smooth animation
      'daily': 200,
      'weekly': 300,
      'monthly': 400,
      'yearly': 600,
      '5y': 800,
      '10y': 1000
    };
    const base = baseIntervals[this.granularity] || 600;
    return this.playSpeed === 3 ? Math.floor(base / 3) : base;
  },

  /**
   * Initialize time slider with time range data
   * @param {Object} timeRange - {min, max, available_years|available, granularity?, useTimestamps?}
   * @param {Object} timeData - {time: {loc_id: {metric: value}}}
   * @param {Object} baseGeojson - Base geometry
   * @param {string} metricKey - Metric to display
   */
  init(timeRange, timeData, baseGeojson, metricKey) {
    this.timeData = timeData;
    this.baseGeojson = baseGeojson;
    this.metricKey = metricKey;
    this.minTime = timeRange.min;
    this.maxTime = timeRange.max;

    // Granularity support - detect from timeRange or default to yearly
    this.granularity = timeRange.granularity || 'yearly';
    this.useTimestamps = timeRange.useTimestamps ||
      ['6h', 'daily', 'weekly', 'monthly'].includes(this.granularity);
    this.stepMs = this.calculateStepMs(this.granularity);

    // Support both old (available_years) and new (available) property names
    this.availableTimes = timeRange.available || timeRange.available_years || [];
    // Sort available times for navigation
    this.sortedTimes = [...this.availableTimes].sort((a, b) => a - b);
    this.currentTime = timeRange.max;  // Start at latest time
    this.playSpeed = 1;

    // Pre-compute gap-filled data (carry forward last known values)
    this.timeDataFilled = this.buildFilledTimeData();

    // Cache DOM elements
    this.container = document.getElementById('timeSliderContainer');
    this.slider = document.getElementById('timeSlider');
    this.yearLabel = document.getElementById('currentYearLabel');
    this.playBtn = document.getElementById('playBtn');
    this.stepBackBtn = document.getElementById('stepBackBtn');
    this.stepFwdBtn = document.getElementById('stepFwdBtn');
    this.rewindBtn = document.getElementById('rewindBtn');
    this.fastFwdBtn = document.getElementById('fastFwdBtn');
    this.minLabel = document.getElementById('minYearLabel');
    this.maxLabel = document.getElementById('maxYearLabel');
    this.titleLabel = document.getElementById('sliderTitle');
    this.tabContainer = document.getElementById('timeSliderTabs');

    // Configure slider
    this.slider.min = this.minTime;
    this.slider.max = this.maxTime;
    this.slider.value = this.currentTime;
    this.minLabel.textContent = this.formatTimeLabel(this.minTime);
    this.maxLabel.textContent = this.formatTimeLabel(this.maxTime);
    this.titleLabel.textContent = metricKey || 'Time';

    // Setup event listeners (only once)
    if (!this.listenersSetup) {
      this.setupEventListeners();
      this.listenersSetup = true;
    }

    // Reset play button state
    this.playBtn.textContent = '|>';
    this.playBtn.title = 'Play';

    // Show slider
    this.show();

    // Initialize choropleth with full data range (before first render)
    ChoroplethManager?.init(metricKey, timeData, this.availableTimes);

    // Load geometry ONCE with initial time data (full loadGeoJSON)
    const initialGeojson = this.buildTimeGeojson(this.currentTime);
    MapAdapter?.loadGeoJSON(initialGeojson);
    ChoroplethManager?.update(initialGeojson, this.metricKey);

    // Update label with formatted time
    this.yearLabel.textContent = this.formatTimeLabel(this.currentTime);

    // Initialize as primary scale for multi-scale support
    this.initAsPrimaryScale();
  },

  /**
   * Setup event listeners (called once)
   */
  setupEventListeners() {
    // Slider input (fires while dragging)
    this.slider.addEventListener('input', (e) => {
      const time = this.useTimestamps ? parseFloat(e.target.value) : parseInt(e.target.value);
      this.setTime(time);
    });

    // Play button
    this.playBtn.addEventListener('click', () => {
      if (this.isPlaying) {
        this.pause();
      } else {
        this.play();
      }
    });

    // Step buttons - single step to next/prev available time
    this.stepBackBtn?.addEventListener('click', () => {
      this.pause();
      this.stepToPrev();
    });

    this.stepFwdBtn?.addEventListener('click', () => {
      this.pause();
      this.stepToNext();
    });

    // Fast forward/rewind buttons - toggle fast mode
    this.rewindBtn?.addEventListener('click', () => {
      if (this.isPlaying && this.playSpeed === 3 && this.playDirection === -1) {
        this.pause();
      } else {
        this.playFast(-1);  // Rewind at 3x
      }
    });

    this.fastFwdBtn?.addEventListener('click', () => {
      if (this.isPlaying && this.playSpeed === 3 && this.playDirection === 1) {
        this.pause();
      } else {
        this.playFast(1);  // Fast forward at 3x
      }
    });
  },

  /**
   * Get the next available time (skips times with no data)
   */
  getNextAvailableTime(fromTime) {
    // Find next time in sortedTimes that is > fromTime
    for (const time of this.sortedTimes) {
      if (time > fromTime) return time;
    }
    // Wrap to start
    return this.sortedTimes[0] || this.minTime;
  },

  /**
   * Get the previous available time (skips times with no data)
   */
  getPrevAvailableTime(fromTime) {
    // Find prev time in sortedTimes that is < fromTime
    for (let i = this.sortedTimes.length - 1; i >= 0; i--) {
      if (this.sortedTimes[i] < fromTime) return this.sortedTimes[i];
    }
    // Wrap to end
    return this.sortedTimes[this.sortedTimes.length - 1] || this.maxTime;
  },

  /**
   * Step to next available time
   */
  stepToNext() {
    const nextTime = this.getNextAvailableTime(this.currentTime);
    this.setTime(nextTime);
  },

  /**
   * Step to previous available time
   */
  stepToPrev() {
    const prevTime = this.getPrevAvailableTime(this.currentTime);
    this.setTime(prevTime);
  },

  /**
   * Set current time and update display
   */
  setTime(time) {
    this.currentTime = time;
    this.yearLabel.textContent = this.formatTimeLabel(time);
    this.slider.value = time;

    // Build GeoJSON for this time and update source data (fast, no layer recreation)
    // The interpolate expression automatically re-evaluates when source data changes
    const geojson = this.buildTimeGeojson(time);
    MapAdapter?.updateSourceData(geojson);
  },

  /**
   * Pre-compute gap-filled time data (called once at init).
   * For yearly mode: fills gaps between years.
   * For timestamp mode: only uses actual data points (no interpolation).
   * Returns {time: {loc_id: {metric, data_time}}}
   */
  buildFilledTimeData() {
    const filled = {};
    const lastKnown = {};  // {loc_id: {data, data_time}}

    // Get all location IDs from the base geometry
    const allLocIds = this.baseGeojson.features.map(f => f.properties.loc_id);

    if (this.useTimestamps) {
      // For timestamp mode, only fill for actual data points (no gap filling)
      for (const time of this.sortedTimes) {
        filled[time] = {};
        const timeValues = this.timeData[time] || {};

        for (const locId of allLocIds) {
          if (timeValues[locId] && Object.keys(timeValues[locId]).length > 0) {
            filled[time][locId] = {
              ...timeValues[locId],
              data_time: time
            };
          }
        }
      }
    } else {
      // For year mode, process all years and carry forward values
      for (let year = this.minTime; year <= this.maxTime; year++) {
        filled[year] = {};
        const yearValues = this.timeData[year] || {};

        for (const locId of allLocIds) {
          // Check if this year has data for this location
          if (yearValues[locId] && Object.keys(yearValues[locId]).length > 0) {
            // New data - update last known
            lastKnown[locId] = {
              data: yearValues[locId],
              data_time: year
            };
          }

          // Use last known value (or empty if none yet)
          if (lastKnown[locId]) {
            filled[year][locId] = {
              ...lastKnown[locId].data,
              data_time: lastKnown[locId].data_time
            };
          }
        }
      }
    }

    return filled;
  },

  /**
   * Build GeoJSON with time-specific values injected.
   * Uses pre-computed gap-filled data for O(1) lookup per location.
   */
  buildTimeGeojson(time) {
    const timeValues = this.timeDataFilled[time] || {};

    return {
      type: 'FeatureCollection',
      features: this.baseGeojson.features.map(f => {
        const locId = f.properties.loc_id;
        const locData = timeValues[locId] || {};

        return {
          ...f,
          properties: {
            ...f.properties,
            ...locData,
            // Include both 'time' and 'year' for compatibility
            time: time,
            year: this.useTimestamps ? new Date(time).getFullYear() : time
          }
        };
      })
    };
  },

  // ============================================================================
  // MULTI-SCALE MANAGEMENT (Phase 3)
  // ============================================================================

  /**
   * Add a new scale (tab) to the time slider.
   * @param {Object} scaleConfig - {id, label, granularity, timeRange, timeData, mapRenderer?}
   * @returns {boolean} - true if added, false if at max or duplicate ID
   */
  addScale(scaleConfig) {
    // Check for duplicate ID
    if (this.scales.find(s => s.id === scaleConfig.id)) {
      console.warn(`Scale with ID "${scaleConfig.id}" already exists`);
      return false;
    }

    // Check max scales
    if (this.scales.length >= this.MAX_SCALES) {
      console.warn(`Maximum of ${this.MAX_SCALES} scales reached`);
      // Could emit event or show UI warning here
      return false;
    }

    // Build scale object
    const scale = {
      id: scaleConfig.id,
      label: scaleConfig.label || scaleConfig.id,
      granularity: scaleConfig.granularity || 'yearly',
      useTimestamps: scaleConfig.useTimestamps ||
        ['6h', 'daily', 'weekly', 'monthly'].includes(scaleConfig.granularity),
      timeRange: scaleConfig.timeRange,
      timeData: scaleConfig.timeData,
      baseGeojson: scaleConfig.baseGeojson || this.baseGeojson,
      metricKey: scaleConfig.metricKey || this.metricKey,
      mapRenderer: scaleConfig.mapRenderer || 'choropleth',
      currentTime: scaleConfig.timeRange?.max || scaleConfig.timeRange?.min
    };

    this.scales.push(scale);
    this.renderTabs();

    return true;
  },

  /**
   * Remove a scale by ID.
   * @param {string} scaleId - Scale ID to remove
   */
  removeScale(scaleId) {
    const index = this.scales.findIndex(s => s.id === scaleId);
    if (index === -1) return;

    // Don't remove the primary scale
    if (scaleId === 'primary') {
      console.warn('Cannot remove primary scale');
      return;
    }

    this.scales.splice(index, 1);

    // If we removed the active scale, switch to primary
    if (this.activeScaleId === scaleId) {
      this.setActiveScale('primary');
    } else {
      this.renderTabs();
    }
  },

  /**
   * Switch to a different scale.
   * @param {string} scaleId - Scale ID to activate
   */
  setActiveScale(scaleId) {
    const scale = this.scales.find(s => s.id === scaleId);
    if (!scale) {
      console.warn(`Scale "${scaleId}" not found`);
      return;
    }

    // Save current time position to outgoing scale
    const currentScale = this.getActiveScale();
    if (currentScale) {
      currentScale.currentTime = this.currentTime;
    }

    // Switch to new scale
    this.activeScaleId = scaleId;
    this.granularity = scale.granularity;
    this.useTimestamps = scale.useTimestamps;
    this.stepMs = this.calculateStepMs(scale.granularity);

    // Load scale's data
    this.timeData = scale.timeData;
    this.baseGeojson = scale.baseGeojson;
    this.metricKey = scale.metricKey;
    this.minTime = scale.timeRange.min;
    this.maxTime = scale.timeRange.max;
    this.availableTimes = scale.timeRange.available || scale.timeRange.available_years || [];
    this.sortedTimes = [...this.availableTimes].sort((a, b) => a - b);
    this.currentTime = scale.currentTime || scale.timeRange.max;

    // Rebuild filled data for new scale
    this.timeDataFilled = this.buildFilledTimeData();

    // Update slider range
    this.slider.min = this.minTime;
    this.slider.max = this.maxTime;
    this.slider.value = this.currentTime;
    this.minLabel.textContent = this.formatTimeLabel(this.minTime);
    this.maxLabel.textContent = this.formatTimeLabel(this.maxTime);

    // Update display
    this.yearLabel.textContent = this.formatTimeLabel(this.currentTime);

    // Update map
    const geojson = this.buildTimeGeojson(this.currentTime);
    MapAdapter?.updateSourceData(geojson);

    // Re-render tabs to update active state
    this.renderTabs();
  },

  /**
   * Get the currently active scale object.
   * @returns {Object|null} - Active scale or null
   */
  getActiveScale() {
    return this.scales.find(s => s.id === this.activeScaleId) || null;
  },

  /**
   * Render the tab bar UI.
   */
  renderTabs() {
    if (!this.tabContainer) {
      this.tabContainer = document.getElementById('timeSliderTabs');
    }
    if (!this.tabContainer) return;

    // Only show tabs if we have more than one scale
    if (this.scales.length <= 1) {
      this.tabContainer.style.display = 'none';
      return;
    }

    this.tabContainer.style.display = 'flex';
    this.tabContainer.innerHTML = '';

    for (const scale of this.scales) {
      const tab = document.createElement('button');
      tab.className = 'time-slider-tab' + (scale.id === this.activeScaleId ? ' active' : '');
      tab.dataset.scaleId = scale.id;

      // Label with granularity badge
      const labelSpan = document.createElement('span');
      labelSpan.className = 'tab-label';
      labelSpan.textContent = scale.label;
      tab.appendChild(labelSpan);

      const granBadge = document.createElement('span');
      granBadge.className = 'tab-granularity';
      granBadge.textContent = this.formatGranularityLabel(scale.granularity);
      tab.appendChild(granBadge);

      // Close button for non-primary tabs
      if (scale.id !== 'primary') {
        const closeBtn = document.createElement('span');
        closeBtn.className = 'tab-close';
        closeBtn.textContent = 'x';
        closeBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.removeScale(scale.id);
        });
        tab.appendChild(closeBtn);
      }

      // Tab click switches scale
      tab.addEventListener('click', () => {
        if (scale.id !== this.activeScaleId) {
          this.setActiveScale(scale.id);
        }
      });

      this.tabContainer.appendChild(tab);
    }
  },

  /**
   * Format granularity for display in tab badge.
   */
  formatGranularityLabel(granularity) {
    const labels = {
      '6h': '6hr',
      'daily': 'day',
      'weekly': 'wk',
      'monthly': 'mo',
      'yearly': 'yr',
      '5y': '5yr',
      '10y': '10yr'
    };
    return labels[granularity] || granularity;
  },

  /**
   * Initialize as primary scale (called from init).
   * Creates the first scale from init parameters.
   */
  initAsPrimaryScale() {
    // Clear existing scales
    this.scales = [];

    // Create primary scale from current state
    const primaryScale = {
      id: 'primary',
      label: this.metricKey || 'All Data',
      granularity: this.granularity,
      useTimestamps: this.useTimestamps,
      timeRange: {
        min: this.minTime,
        max: this.maxTime,
        available: this.availableTimes
      },
      timeData: this.timeData,
      baseGeojson: this.baseGeojson,
      metricKey: this.metricKey,
      mapRenderer: 'choropleth',
      currentTime: this.currentTime
    };

    this.scales.push(primaryScale);
    this.activeScaleId = 'primary';
    this.renderTabs();
  },

  /**
   * Start playback animation (normal speed, forward)
   */
  play() {
    this.playSpeed = 1;
    this.playDirection = 1;
    this.startPlayback();
  },

  /**
   * Start fast playback in given direction
   * @param {number} direction - 1 for forward, -1 for rewind
   */
  playFast(direction) {
    this.playSpeed = 3;
    this.playDirection = direction;
    this.startPlayback();
  },

  /**
   * Internal: start the playback interval
   */
  startPlayback() {
    // Clear any existing interval
    if (this.playInterval) {
      clearInterval(this.playInterval);
    }

    this.isPlaying = true;
    this.updateButtonStates();

    // Use granularity-aware interval
    const interval = this.getPlaybackInterval();

    this.playInterval = setInterval(() => {
      let nextTime;
      if (this.playDirection === 1) {
        nextTime = this.getNextAvailableTime(this.currentTime);
        // Check for wrap-around (looped back to start)
        if (nextTime <= this.currentTime && this.sortedTimes.length > 1) {
          nextTime = this.sortedTimes[0];
        }
      } else {
        nextTime = this.getPrevAvailableTime(this.currentTime);
        // Check for wrap-around (looped back to end)
        if (nextTime >= this.currentTime && this.sortedTimes.length > 1) {
          nextTime = this.sortedTimes[this.sortedTimes.length - 1];
        }
      }
      this.setTime(nextTime);
    }, interval);
  },

  /**
   * Update button visual states
   */
  updateButtonStates() {
    // Guard against null elements (reset called before init)
    if (!this.playBtn) return;

    // Reset all buttons
    this.rewindBtn?.classList.remove('active');
    this.fastFwdBtn?.classList.remove('active');

    if (this.isPlaying) {
      this.playBtn.textContent = '||';
      this.playBtn.title = 'Pause';

      // Highlight fast buttons when in fast mode
      if (this.playSpeed === 3) {
        if (this.playDirection === -1) {
          this.rewindBtn?.classList.add('active');
        } else {
          this.fastFwdBtn?.classList.add('active');
        }
      }
    } else {
      this.playBtn.textContent = '|>';
      this.playBtn.title = 'Play';
    }
  },

  /**
   * Pause playback
   */
  pause() {
    this.isPlaying = false;
    this.playSpeed = 1;

    if (this.playInterval) {
      clearInterval(this.playInterval);
      this.playInterval = null;
    }

    this.updateButtonStates();
  },

  /**
   * Show the time slider
   */
  show() {
    if (this.container) {
      this.container.classList.add('visible');
    }
  },

  /**
   * Hide the time slider
   */
  hide() {
    this.pause();  // Stop playing when hiding
    if (this.container) {
      this.container.classList.remove('visible');
    }
  },

  /**
   * Reset/clear time slider
   */
  reset() {
    this.hide();
    this.timeData = null;
    this.timeDataFilled = null;
    this.baseGeojson = null;
    this.metricKey = null;
    this.sortedTimes = [];
    this.availableTimes = [];
    this.playSpeed = 1;
    this.playDirection = 1;
    this.granularity = 'yearly';
    this.useTimestamps = false;
    this.stepMs = null;

    // Clear multi-scale state
    this.scales = [];
    this.activeScaleId = null;
    if (this.tabContainer) {
      this.tabContainer.style.display = 'none';
      this.tabContainer.innerHTML = '';
    }
  }
};
