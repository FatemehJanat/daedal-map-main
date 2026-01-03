/**
 * Time Slider - Controls year selection for multi-year data.
 * Handles playback animation and year-based data filtering.
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
  yearData: null,      // {year: {loc_id: {metric: value}}} - original data
  yearDataFilled: null, // {year: {loc_id: {metric, data_year}}} - with gaps filled
  baseGeojson: null,   // Geometry without year-specific values
  metricKey: null,     // Which property to color by
  currentYear: null,
  minYear: null,
  maxYear: null,
  availableYears: [],  // Years that actually have data
  sortedYears: [],     // Sorted array for navigation
  isPlaying: false,
  playInterval: null,
  playSpeed: 1,        // 1 = normal, 3 = fast
  playDirection: 1,    // 1 = forward, -1 = rewind
  listenersSetup: false,  // Track if event listeners have been added

  /**
   * Initialize time slider with multi-year data
   */
  init(yearRange, yearData, baseGeojson, metricKey) {
    this.yearData = yearData;
    this.baseGeojson = baseGeojson;
    this.metricKey = metricKey;
    this.minYear = yearRange.min;
    this.maxYear = yearRange.max;
    this.availableYears = yearRange.available_years || [];
    // Sort available years for navigation (skip years with no data for ANY location)
    this.sortedYears = [...this.availableYears].sort((a, b) => a - b);
    this.currentYear = yearRange.max;  // Start at latest year
    this.playSpeed = 1;

    // Pre-compute gap-filled data (carry forward last known values)
    this.yearDataFilled = this.buildFilledYearData();

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

    // Configure slider
    this.slider.min = this.minYear;
    this.slider.max = this.maxYear;
    this.slider.value = this.currentYear;
    this.minLabel.textContent = this.minYear;
    this.maxLabel.textContent = this.maxYear;
    this.titleLabel.textContent = metricKey || 'Year';

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
    ChoroplethManager?.init(metricKey, yearData, this.availableYears);

    // Load geometry ONCE with initial year data (full loadGeoJSON)
    const initialGeojson = this.buildYearGeojson(this.currentYear);
    MapAdapter?.loadGeoJSON(initialGeojson);
    ChoroplethManager?.update(initialGeojson, this.metricKey);

    // Update labels
    this.yearLabel.textContent = this.currentYear;
  },

  /**
   * Setup event listeners (called once)
   */
  setupEventListeners() {
    // Slider input (fires while dragging)
    this.slider.addEventListener('input', (e) => {
      const year = parseInt(e.target.value);
      this.setYear(year);
    });

    // Play button
    this.playBtn.addEventListener('click', () => {
      if (this.isPlaying) {
        this.pause();
      } else {
        this.play();
      }
    });

    // Step buttons - single step to next/prev available year
    this.stepBackBtn?.addEventListener('click', () => {
      this.pause();
      this.stepToPrevYear();
    });

    this.stepFwdBtn?.addEventListener('click', () => {
      this.pause();
      this.stepToNextYear();
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
   * Get the next available year (skips years with no data)
   */
  getNextAvailableYear(fromYear) {
    // Find next year in sortedYears that is > fromYear
    for (const year of this.sortedYears) {
      if (year > fromYear) return year;
    }
    // Wrap to start
    return this.sortedYears[0] || this.minYear;
  },

  /**
   * Get the previous available year (skips years with no data)
   */
  getPrevAvailableYear(fromYear) {
    // Find prev year in sortedYears that is < fromYear
    for (let i = this.sortedYears.length - 1; i >= 0; i--) {
      if (this.sortedYears[i] < fromYear) return this.sortedYears[i];
    }
    // Wrap to end
    return this.sortedYears[this.sortedYears.length - 1] || this.maxYear;
  },

  /**
   * Step to next available year
   */
  stepToNextYear() {
    const nextYear = this.getNextAvailableYear(this.currentYear);
    this.setYear(nextYear);
  },

  /**
   * Step to previous available year
   */
  stepToPrevYear() {
    const prevYear = this.getPrevAvailableYear(this.currentYear);
    this.setYear(prevYear);
  },

  /**
   * Set current year and update display
   */
  setYear(year) {
    this.currentYear = year;
    this.yearLabel.textContent = year;
    this.slider.value = year;

    // Build GeoJSON for this year and update source data (fast, no layer recreation)
    // The interpolate expression automatically re-evaluates when source data changes
    const geojson = this.buildYearGeojson(year);
    MapAdapter?.updateSourceData(geojson);
  },

  /**
   * Pre-compute gap-filled year data (called once at init).
   * For each year, carries forward the last known value for each location.
   * Returns {year: {loc_id: {metric, data_year}}}
   */
  buildFilledYearData() {
    const filled = {};
    const lastKnown = {};  // {loc_id: {data, data_year}}

    // Get all location IDs from the base geometry
    const allLocIds = this.baseGeojson.features.map(f => f.properties.loc_id);

    // Process years in order (min to max)
    for (let year = this.minYear; year <= this.maxYear; year++) {
      filled[year] = {};
      const yearValues = this.yearData[year] || {};

      for (const locId of allLocIds) {
        // Check if this year has data for this location
        if (yearValues[locId] && Object.keys(yearValues[locId]).length > 0) {
          // New data - update last known
          lastKnown[locId] = {
            data: yearValues[locId],
            data_year: year
          };
        }

        // Use last known value (or empty if none yet)
        if (lastKnown[locId]) {
          filled[year][locId] = {
            ...lastKnown[locId].data,
            data_year: lastKnown[locId].data_year
          };
        }
      }
    }

    return filled;
  },

  /**
   * Build GeoJSON with year-specific values injected.
   * Uses pre-computed gap-filled data for O(1) lookup per location.
   */
  buildYearGeojson(year) {
    const yearValues = this.yearDataFilled[year] || {};

    return {
      type: 'FeatureCollection',
      features: this.baseGeojson.features.map(f => {
        const locId = f.properties.loc_id;
        const locData = yearValues[locId] || {};

        return {
          ...f,
          properties: {
            ...f.properties,
            ...locData,
            year: year  // Slider position (data_year already in locData if exists)
          }
        };
      })
    };
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

    // Calculate interval: 600ms normal, 200ms fast
    const interval = this.playSpeed === 3 ? 200 : 600;

    this.playInterval = setInterval(() => {
      let nextYear;
      if (this.playDirection === 1) {
        nextYear = this.getNextAvailableYear(this.currentYear);
        // Check for wrap-around (looped back to start)
        if (nextYear <= this.currentYear && this.sortedYears.length > 1) {
          nextYear = this.sortedYears[0];
        }
      } else {
        nextYear = this.getPrevAvailableYear(this.currentYear);
        // Check for wrap-around (looped back to end)
        if (nextYear >= this.currentYear && this.sortedYears.length > 1) {
          nextYear = this.sortedYears[this.sortedYears.length - 1];
        }
      }
      this.setYear(nextYear);
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
    this.yearData = null;
    this.yearDataFilled = null;
    this.baseGeojson = null;
    this.metricKey = null;
    this.sortedYears = [];
    this.playSpeed = 1;
    this.playDirection = 1;
  }
};
