/**
 * Point+Radius Model - Renders point events with optional radius circles.
 * Used for: Earthquakes, Volcanoes, Tornadoes, Tsunamis
 *
 * Display characteristics:
 * - Circle markers sized by magnitude/intensity
 * - Color coding by severity scale
 * - Optional felt/damage radius circles
 * - Glow effect for visibility on dark backgrounds
 */

import { CONFIG } from '../config.js';

// Dependencies set via setDependencies
let MapAdapter = null;
let TimeSlider = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  if (deps.TimeSlider) {
    TimeSlider = deps.TimeSlider;
  }
}

export const PointRadiusModel = {
  // Currently active event type
  activeType: null,

  // Click handler references for cleanup
  clickHandler: null,
  _mapClickHandler: null,

  // Selected event tracking
  selectedEventId: null,

  // Aftershock sequence tracking
  activeSequenceId: null,
  sequenceChangeCallback: null,  // Called when sequence selection changes

  /**
   * Render point events on the map.
   * @param {Object} geojson - GeoJSON FeatureCollection with Point features
   * @param {string} eventType - 'earthquake', 'volcano', 'tornado', etc.
   * @param {Object} options - {showFeltRadius, showDamageRadius, onEventClick}
   */
  render(geojson, eventType = 'earthquake', options = {}) {
    if (!MapAdapter?.map) {
      console.warn('PointRadiusModel: MapAdapter not available');
      return;
    }

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      console.log('PointRadiusModel: No features to display');
      return;
    }

    // Clear existing layers
    this.clear();

    // Store active type
    this.activeType = eventType;

    // Add event source
    MapAdapter.map.addSource(CONFIG.layers.eventSource, {
      type: 'geojson',
      data: geojson
    });

    // Build layers based on event type
    if (eventType === 'earthquake') {
      this._addEarthquakeLayer(options);
    } else if (eventType === 'volcano') {
      this._addVolcanoLayer(options);
    } else {
      this._addGenericEventLayer(eventType, options);
    }

    // Setup click handler - locks popup on click and fills radius circles
    this.clickHandler = (e) => {
      // Don't show popups during animation playback
      if (TimeSlider?.isPlaying) return;

      if (e.features.length > 0) {
        const props = e.features[0].properties;
        const html = this.buildPopupHtml(props, eventType);

        // Show popup and lock it
        MapAdapter.showPopup([e.lngLat.lng, e.lngLat.lat], html);
        MapAdapter.popupLocked = true;

        // Select this event - fills in the radius circles
        this._selectEvent(props.event_id);

        // Setup click handler for "View sequence" links in popup
        setTimeout(() => {
          const popupEl = document.querySelector('.maplibregl-popup-content');
          if (popupEl) {
            const seqLinks = popupEl.querySelectorAll('.view-sequence-link');
            seqLinks.forEach(link => {
              link.addEventListener('click', (evt) => {
                evt.preventDefault();
                const seqId = link.dataset.sequence;
                if (seqId) {
                  // Notify sequence change listeners (SequenceAnimator handles viewport/display)
                  // Don't highlight or zoom here - let the animation reveal events
                  this._notifySequenceChange(seqId);
                }
              });
            });

            // Setup click handler for "Find related earthquakes" link (volcano cross-link)
            const eqLinks = popupEl.querySelectorAll('.find-earthquakes-link');
            eqLinks.forEach(link => {
              link.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const lat = parseFloat(link.dataset.lat);
                const lon = parseFloat(link.dataset.lon);
                const timestamp = link.dataset.timestamp;
                const year = parseInt(link.dataset.year);
                const volcanoName = link.dataset.volcano;

                // Update link to show loading state
                link.textContent = 'Searching...';
                link.style.pointerEvents = 'none';

                try {
                  // Build query URL - search 30 days before AND 60 days after eruption
                  let url = `/api/events/nearby-earthquakes?lat=${lat}&lon=${lon}&radius_km=150&min_magnitude=3.0`;
                  if (timestamp && timestamp !== 'null' && timestamp !== '') {
                    url += `&timestamp=${encodeURIComponent(timestamp)}&days_before=30&days_after=60`;
                  } else if (year) {
                    url += `&year=${year}`;
                  }

                  const response = await fetch(url);
                  const data = await response.json();

                  if (data.count > 0) {
                    // Found earthquakes - display them
                    link.textContent = `Found ${data.count} earthquakes`;
                    link.style.color = '#81c784';

                    // Notify listeners to display the earthquakes
                    // Use the volcano-triggered sequence ID pattern
                    const volcanoSeqId = `volcano-${volcanoName}-${year}`;
                    this._notifyVolcanoEarthquakes(data.features, volcanoSeqId, volcanoName, lat, lon);
                  } else {
                    link.textContent = 'No earthquakes found nearby';
                    link.style.color = '#999';
                  }
                } catch (err) {
                  console.error('Error fetching nearby earthquakes:', err);
                  link.textContent = 'Error searching';
                  link.style.color = '#f44336';
                }

                // Re-enable after delay
                setTimeout(() => {
                  link.style.pointerEvents = 'auto';
                }, 2000);
              });
            });

            // Setup click handler for "Find related volcanoes" link (earthquake cross-link)
            const volLinks = popupEl.querySelectorAll('.find-volcanoes-link');
            volLinks.forEach(link => {
              link.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const lat = parseFloat(link.dataset.lat);
                const lon = parseFloat(link.dataset.lon);
                const timestamp = link.dataset.timestamp;
                const year = parseInt(link.dataset.year);

                // Update link to show loading state
                link.textContent = 'Searching...';
                link.style.pointerEvents = 'none';

                try {
                  // Build query URL - look for eruptions BEFORE the earthquake
                  let url = `/api/events/nearby-volcanoes?lat=${lat}&lon=${lon}&radius_km=150`;
                  if (timestamp && timestamp !== 'null' && timestamp !== '') {
                    url += `&timestamp=${encodeURIComponent(timestamp)}&days_before=60`;
                  } else if (year) {
                    url += `&year=${year}`;
                  }

                  const response = await fetch(url);
                  const data = await response.json();

                  if (data.count > 0) {
                    // Found volcanoes - display summary
                    const names = [...new Set(data.features.map(f => f.properties.volcano_name))];
                    const summary = names.length > 2
                      ? `${names.slice(0, 2).join(', ')} +${names.length - 2} more`
                      : names.join(', ');
                    link.textContent = `Found: ${summary}`;
                    link.style.color = '#81c784';

                    // Notify listeners to display the volcanoes
                    this._notifyNearbyVolcanoes(data.features, lat, lon);
                  } else {
                    link.textContent = 'No volcanoes found nearby';
                    link.style.color = '#999';
                  }
                } catch (err) {
                  console.error('Error fetching nearby volcanoes:', err);
                  link.textContent = 'Error searching';
                  link.style.color = '#f44336';
                }

                // Re-enable after delay
                setTimeout(() => {
                  link.style.pointerEvents = 'auto';
                }, 2000);
              });
            });
          }
        }, 50);

        // Call optional click callback
        if (options.onEventClick) {
          options.onEventClick(props);
        }
      }
    };
    MapAdapter.map.on('click', CONFIG.layers.eventCircle, this.clickHandler);

    // Click elsewhere to unlock popup and deselect
    this._mapClickHandler = (e) => {
      // Check if click was on an event feature
      const features = MapAdapter.map.queryRenderedFeatures(e.point, {
        layers: [CONFIG.layers.eventCircle]
      });
      if (features.length === 0 && MapAdapter.popupLocked) {
        MapAdapter.popupLocked = false;
        MapAdapter.hidePopup();
        this._selectEvent(null);  // Clear selection
        this.highlightSequence(null);  // Clear sequence highlight
      }
    };
    MapAdapter.map.on('click', this._mapClickHandler);

    // Hover cursor
    MapAdapter.map.on('mouseenter', CONFIG.layers.eventCircle, () => {
      MapAdapter.map.getCanvas().style.cursor = 'pointer';
    });
    MapAdapter.map.on('mouseleave', CONFIG.layers.eventCircle, () => {
      MapAdapter.map.getCanvas().style.cursor = '';
    });

    // Hover popup (only when not locked and not playing animation)
    MapAdapter.map.on('mousemove', CONFIG.layers.eventCircle, (e) => {
      // Don't show hover popups during animation playback
      if (TimeSlider?.isPlaying) return;

      if (e.features.length > 0 && !MapAdapter.popupLocked) {
        const props = e.features[0].properties;
        const html = this.buildPopupHtml(props, eventType);
        MapAdapter.showPopup([e.lngLat.lng, e.lngLat.lat], html);
      }
    });
    MapAdapter.map.on('mouseleave', CONFIG.layers.eventCircle, () => {
      if (!MapAdapter.popupLocked) {
        MapAdapter.hidePopup();
      }
    });

    console.log(`PointRadiusModel: Loaded ${geojson.features.length} ${eventType} events`);
  },

  /**
   * Add earthquake-specific layers (point + radius circles).
   *
   * Radii are pre-calculated in the data pipeline using empirical formulas:
   * - felt_radius_km: distance where shaking is noticeable (MMI II-III)
   * - damage_radius_km: distance with potential structural damage (MMI VI+)
   *
   * km-to-pixel conversion: pixels = km * 2^zoom / 156.5 (at equator)
   * @private
   */
  _addEarthquakeLayer(options = {}) {
    const colors = CONFIG.earthquakeColors;
    const map = MapAdapter.map;

    // Color expression based on magnitude
    const colorExpr = [
      'interpolate', ['linear'], ['get', 'magnitude'],
      3.0, colors.minor,
      4.0, colors.light,
      5.0, colors.moderate,
      6.0, colors.strong,
      7.0, colors.major
    ];

    // Epicenter marker size - small fixed size (not geographic)
    const epicenterSize = [
      'interpolate', ['linear'], ['get', 'magnitude'],
      3.0, 3,
      5.0, 5,
      7.0, 8,
      8.0, 10
    ];

    // Helper: convert km to pixels at current zoom
    // Formula: pixels = km * 2^zoom / 156.5
    // Using exponential interpolation with base 2 for smooth scaling
    const kmToPixels = (kmExpr) => [
      'interpolate', ['exponential', 2], ['zoom'],
      0, ['/', kmExpr, 156.5],      // At zoom 0: very small
      5, ['/', kmExpr, 4.9],        // 2^5 / 156.5 = 0.204, so km/4.9
      10, ['*', kmExpr, 6.54],      // 2^10 / 156.5 = 6.54
      15, ['*', kmExpr, 209]        // 2^15 / 156.5 = 209
    ];

    // 1. FELT RADIUS - outer circle (thinner, less opaque)
    // Shows how far the earthquake could be felt
    if (options.showFeltRadius !== false) {
      map.addLayer({
        id: CONFIG.layers.eventRadiusOuter,
        type: 'circle',
        source: CONFIG.layers.eventSource,
        filter: ['>', ['get', 'felt_radius_km'], 0],
        paint: {
          'circle-radius': kmToPixels(['get', 'felt_radius_km']),
          'circle-color': 'transparent',
          'circle-stroke-color': colorExpr,  // Same color as magnitude
          'circle-stroke-width': 1.5,
          'circle-stroke-opacity': 0.35
        }
      });
    }

    // 2. DAMAGE RADIUS - inner circle (thicker, more opaque)
    // Shows potential structural damage zone (only M5+)
    if (options.showDamageRadius !== false) {
      map.addLayer({
        id: CONFIG.layers.eventRadiusInner,
        type: 'circle',
        source: CONFIG.layers.eventSource,
        filter: ['>', ['get', 'damage_radius_km'], 0],
        paint: {
          'circle-radius': kmToPixels(['get', 'damage_radius_km']),
          'circle-color': 'transparent',
          'circle-stroke-color': colorExpr,  // Same color as magnitude
          'circle-stroke-width': 2.5,
          'circle-stroke-opacity': 0.7
        }
      });
    }

    // SELECTED EVENT LAYERS - filled circles for the selected event
    // These layers have a filter that initially matches nothing,
    // updated by _selectEvent() when an event is clicked

    // Selected felt radius - filled
    map.addLayer({
      id: CONFIG.layers.eventRadiusOuter + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],  // Initially matches nothing
      paint: {
        'circle-radius': kmToPixels(['get', 'felt_radius_km']),
        'circle-color': colorExpr,
        'circle-opacity': 0.15,
        'circle-stroke-color': colorExpr,
        'circle-stroke-width': 2,
        'circle-stroke-opacity': 0.6
      }
    });

    // Selected damage radius - filled
    map.addLayer({
      id: CONFIG.layers.eventRadiusInner + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],  // Initially matches nothing
      paint: {
        'circle-radius': kmToPixels(['get', 'damage_radius_km']),
        'circle-color': colorExpr,
        'circle-opacity': 0.25,
        'circle-stroke-color': colorExpr,
        'circle-stroke-width': 3,
        'circle-stroke-opacity': 0.9
      }
    });

    // 3. EPICENTER GLOW - subtle glow behind the marker
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': ['+', epicenterSize, 4],
        'circle-color': colorExpr,
        'circle-opacity': 0.3,
        'circle-blur': 1
      }
    });

    // 4. EPICENTER MARKER - small solid circle at exact location
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': epicenterSize,
        'circle-color': colorExpr,
        'circle-opacity': 0.9,
        'circle-stroke-color': '#222222',
        'circle-stroke-width': 1
      }
    });
  },

  /**
   * Add volcano-specific layers.
   * Uses VEI for color, felt_radius_km/damage_radius_km for radius circles.
   * @private
   */
  _addVolcanoLayer(options = {}) {
    const map = MapAdapter.map;

    // Color by VEI (Volcanic Explosivity Index)
    // Pale yellow (weakest) to dark red (strongest) - visible on dark maps
    // Must check VEI is not null - ['has', 'VEI'] returns true for null values
    const hasValidVEI = ['all', ['has', 'VEI'], ['!=', ['get', 'VEI'], null]];
    const colorExpr = [
      'case',
      hasValidVEI, [
        'interpolate', ['linear'], ['get', 'VEI'],
        0, '#ffffcc',   // Non-explosive - pale yellow
        1, '#ffeda0',   // Gentle - light yellow
        2, '#fed976',   // Explosive - yellow
        3, '#feb24c',   // Severe - orange
        4, '#fd8d3c',   // Cataclysmic - dark orange
        5, '#f03b20',   // Paroxysmal - red
        6, '#bd0026',   // Colossal - dark red
        7, '#800026'    // Super-colossal - maroon
      ],
      // No VEI or null VEI - bright green (clearly marks unknown/unrated eruptions)
      '#44ff44'
    ];

    // Epicenter marker size based on VEI
    const epicenterSize = [
      'case',
      hasValidVEI, [
        'interpolate', ['linear'], ['get', 'VEI'],
        0, 4,
        3, 6,
        5, 9,
        7, 12
      ],
      6  // Default size for unknown VEI
    ];

    // Helper: convert km to pixels at current zoom (same as earthquakes)
    const kmToPixels = (kmExpr) => [
      'interpolate', ['exponential', 2], ['zoom'],
      0, ['/', kmExpr, 156.5],
      5, ['/', kmExpr, 4.9],
      10, ['*', kmExpr, 6.54],
      15, ['*', kmExpr, 209]
    ];

    // 1. FELT RADIUS - outer circle (thinner, less opaque)
    // Shows ash fall and noticeable effects zone
    if (options.showFeltRadius !== false) {
      map.addLayer({
        id: CONFIG.layers.eventRadiusOuter,
        type: 'circle',
        source: CONFIG.layers.eventSource,
        filter: ['>', ['get', 'felt_radius_km'], 0],
        paint: {
          'circle-radius': kmToPixels(['get', 'felt_radius_km']),
          'circle-color': 'transparent',
          'circle-stroke-color': colorExpr,
          'circle-stroke-width': 1.5,
          'circle-stroke-opacity': 0.35
        }
      });
    }

    // 2. DAMAGE RADIUS - inner circle (thicker, more opaque)
    // Shows pyroclastic flow / heavy ashfall danger zone
    if (options.showDamageRadius !== false) {
      map.addLayer({
        id: CONFIG.layers.eventRadiusInner,
        type: 'circle',
        source: CONFIG.layers.eventSource,
        filter: ['>', ['get', 'damage_radius_km'], 0],
        paint: {
          'circle-radius': kmToPixels(['get', 'damage_radius_km']),
          'circle-color': 'transparent',
          'circle-stroke-color': colorExpr,
          'circle-stroke-width': 2.5,
          'circle-stroke-opacity': 0.7
        }
      });
    }

    // SELECTED EVENT LAYERS - filled circles for the selected event
    // Selected felt radius - filled
    map.addLayer({
      id: CONFIG.layers.eventRadiusOuter + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],  // Initially matches nothing
      paint: {
        'circle-radius': kmToPixels(['get', 'felt_radius_km']),
        'circle-color': colorExpr,
        'circle-opacity': 0.15,
        'circle-stroke-color': colorExpr,
        'circle-stroke-width': 2,
        'circle-stroke-opacity': 0.6
      }
    });

    // Selected damage radius - filled
    map.addLayer({
      id: CONFIG.layers.eventRadiusInner + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],  // Initially matches nothing
      paint: {
        'circle-radius': kmToPixels(['get', 'damage_radius_km']),
        'circle-color': colorExpr,
        'circle-opacity': 0.25,
        'circle-stroke-color': colorExpr,
        'circle-stroke-width': 3,
        'circle-stroke-opacity': 0.9
      }
    });

    // 3. EPICENTER GLOW
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': ['+', epicenterSize, 4],
        'circle-color': colorExpr,
        'circle-opacity': 0.3,
        'circle-blur': 1
      }
    });

    // 4. EPICENTER MARKER
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': epicenterSize,
        'circle-color': colorExpr,
        'circle-opacity': 0.85,
        'circle-stroke-color': '#333333',
        'circle-stroke-width': 1
      }
    });
  },

  /**
   * Add generic event layer for other event types.
   * @private
   */
  _addGenericEventLayer(eventType, options = {}) {
    const map = MapAdapter.map;

    // Default yellow/orange coloring
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': 12,
        'circle-color': '#ffcc00',
        'circle-opacity': 0.3,
        'circle-blur': 1
      }
    });

    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': 6,
        'circle-color': '#ffcc00',
        'circle-opacity': 0.85,
        'circle-stroke-color': '#333333',
        'circle-stroke-width': 1
      }
    });
  },

  /**
   * Update event layer data (for time-based filtering).
   * @param {Object} geojson - Filtered GeoJSON FeatureCollection
   */
  update(geojson) {
    if (!MapAdapter?.map) return;

    const source = MapAdapter.map.getSource(CONFIG.layers.eventSource);
    if (source) {
      source.setData(geojson);
    }
  },

  /**
   * Clear all event layers.
   */
  clear() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    // Remove click handlers
    if (this.clickHandler) {
      map.off('click', CONFIG.layers.eventCircle, this.clickHandler);
      this.clickHandler = null;
    }
    if (this._mapClickHandler) {
      map.off('click', this._mapClickHandler);
      this._mapClickHandler = null;
    }

    // Unlock popup
    MapAdapter.popupLocked = false;

    // Remove layers (including selection and sequence highlight layers)
    const layerIds = [
      CONFIG.layers.eventCircle,
      CONFIG.layers.eventCircle + '-glow',
      CONFIG.layers.eventCircle + '-sequence',  // Green sequence highlight
      CONFIG.layers.eventLabel,
      CONFIG.layers.eventRadiusOuter,
      CONFIG.layers.eventRadiusInner,
      CONFIG.layers.eventRadiusOuter + '-selected',
      CONFIG.layers.eventRadiusInner + '-selected'
    ];

    for (const layerId of layerIds) {
      if (map.getLayer(layerId)) {
        map.removeLayer(layerId);
      }
    }

    // Remove source
    if (map.getSource(CONFIG.layers.eventSource)) {
      map.removeSource(CONFIG.layers.eventSource);
    }

    this.activeType = null;
    this.selectedEventId = null;
    this.activeSequenceId = null;
  },

  /**
   * Select an event to highlight with filled radius circles.
   * @param {string|null} eventId - Event ID to select, or null to deselect
   * @private
   */
  _selectEvent(eventId) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    this.selectedEventId = eventId;

    // Update filters on selection layers
    const filter = eventId
      ? ['==', ['get', 'event_id'], eventId]
      : ['==', ['get', 'event_id'], ''];  // Matches nothing

    const outerLayer = CONFIG.layers.eventRadiusOuter + '-selected';
    const innerLayer = CONFIG.layers.eventRadiusInner + '-selected';

    if (map.getLayer(outerLayer)) {
      map.setFilter(outerLayer, filter);
    }
    if (map.getLayer(innerLayer)) {
      map.setFilter(innerLayer, filter);
    }
  },

  /**
   * Highlight an aftershock sequence on the map.
   * Shows all events in the sequence with enhanced visibility.
   * @param {string|null} sequenceId - Sequence ID to highlight, or null to clear
   */
  highlightSequence(sequenceId) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const prevSequence = this.activeSequenceId;
    this.activeSequenceId = sequenceId;

    // Add sequence highlight layer if it doesn't exist
    const seqLayerId = CONFIG.layers.eventCircle + '-sequence';
    if (!map.getLayer(seqLayerId) && map.getSource(CONFIG.layers.eventSource)) {
      // Add a highlight ring around sequence events
      map.addLayer({
        id: seqLayerId,
        type: 'circle',
        source: CONFIG.layers.eventSource,
        filter: ['==', ['get', 'sequence_id'], ''],  // Initially matches nothing
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['get', 'magnitude'],
            3.0, 8,
            5.0, 12,
            7.0, 18,
            9.0, 24
          ],
          'circle-color': 'transparent',
          'circle-stroke-color': '#76ff03',  // Bright green highlight
          'circle-stroke-width': 3,
          'circle-stroke-opacity': 0.9
        }
      }, CONFIG.layers.eventCircle);  // Place below epicenters
    }

    // Update filter
    if (map.getLayer(seqLayerId)) {
      const filter = sequenceId
        ? ['==', ['get', 'sequence_id'], sequenceId]
        : ['==', ['get', 'sequence_id'], ''];
      map.setFilter(seqLayerId, filter);
    }

    // Notify callback if sequence changed
    if (this.sequenceChangeCallback && sequenceId !== prevSequence) {
      this.sequenceChangeCallback(sequenceId);
    }

    if (sequenceId) {
      console.log(`PointRadiusModel: Highlighting sequence ${sequenceId}`);
    }
  },

  /**
   * Set callback for sequence changes (used by TimeSlider integration).
   * @param {Function} callback - Called with (sequenceId) when sequence changes
   */
  onSequenceChange(callback) {
    this.sequenceChangeCallback = callback;
  },

  /**
   * Notify sequence change listeners without highlighting.
   * Used when starting animation - SequenceAnimator handles display.
   * @param {string} sequenceId - Sequence ID
   * @private
   */
  _notifySequenceChange(sequenceId) {
    if (this.sequenceChangeCallback) {
      this.sequenceChangeCallback(sequenceId);
    }
  },

  /**
   * Notify about earthquakes found near a volcano.
   * @param {Array} features - Earthquake features from API
   * @param {string} volcanoSeqId - Generated sequence ID for this volcano's earthquakes
   * @param {string} volcanoName - Name of the volcano
   * @param {number} lat - Volcano latitude
   * @param {number} lon - Volcano longitude
   */
  _notifyVolcanoEarthquakes(features, volcanoSeqId, volcanoName, lat, lon) {
    console.log(`PointRadiusModel: Found ${features.length} earthquakes near ${volcanoName}`);

    if (this.volcanoEarthquakesCallback) {
      this.volcanoEarthquakesCallback({
        features,
        volcanoSeqId,
        volcanoName,
        volcanoLat: lat,
        volcanoLon: lon
      });
    }
  },

  /**
   * Notify about volcanoes found near an earthquake.
   * @param {Array} features - Volcano features from API
   * @param {number} lat - Earthquake latitude
   * @param {number} lon - Earthquake longitude
   */
  _notifyNearbyVolcanoes(features, lat, lon) {
    console.log(`PointRadiusModel: Found ${features.length} volcanoes near (${lat}, ${lon})`);

    if (this.nearbyVolcanoesCallback) {
      this.nearbyVolcanoesCallback({
        features,
        earthquakeLat: lat,
        earthquakeLon: lon
      });
    }
  },

  /**
   * Register callback for volcano-triggered earthquakes.
   * @param {Function} callback - Callback function
   */
  onVolcanoEarthquakes(callback) {
    this.volcanoEarthquakesCallback = callback;
  },

  /**
   * Register callback for nearby volcanoes.
   * @param {Function} callback - Callback function
   */
  onNearbyVolcanoes(callback) {
    this.nearbyVolcanoesCallback = callback;
  },

  /**
   * Get events in a sequence.
   * @param {string} sequenceId - Sequence ID
   * @returns {Array} Array of features in the sequence
   */
  getSequenceEvents(sequenceId) {
    if (!MapAdapter?.map) return [];

    const source = MapAdapter.map.getSource(CONFIG.layers.eventSource);
    if (!source || !source._data) return [];

    return source._data.features.filter(f =>
      f.properties.sequence_id === sequenceId
    );
  },

  /**
   * Fit map to event bounds.
   * @param {Object} geojson - Event GeoJSON
   */
  fitBounds(geojson) {
    if (!MapAdapter?.map || !geojson || !geojson.features || geojson.features.length === 0) {
      return;
    }

    const bounds = new maplibregl.LngLatBounds();

    for (const feature of geojson.features) {
      if (feature.geometry && feature.geometry.type === 'Point') {
        bounds.extend(feature.geometry.coordinates);
      }
    }

    if (!bounds.isEmpty()) {
      MapAdapter.map.fitBounds(bounds, {
        padding: 50,
        duration: 1000,
        maxZoom: 10
      });
    }
  },

  /**
   * Build HTML popup content for event.
   * @param {Object} props - Feature properties
   * @param {string} eventType - Event type
   * @returns {string} HTML string
   */
  buildPopupHtml(props, eventType) {
    const lines = [];

    if (eventType === 'earthquake') {
      const mag = props.magnitude?.toFixed(1) || 'N/A';
      lines.push(`<strong>M${mag} Earthquake</strong>`);
      if (props.place) lines.push(props.place);
      if (props.depth_km != null) lines.push(`Depth: ${props.depth_km.toFixed(1)} km`);
      if (props.timestamp) {
        const date = new Date(props.timestamp);
        lines.push(date.toLocaleString());
      } else if (props.time) {
        const date = new Date(props.time);
        lines.push(date.toLocaleString());
      }
      // Show impact radii
      if (props.damage_radius_km > 0) {
        lines.push(`Damage radius: ${props.damage_radius_km.toFixed(0)} km`);
      }
      if (props.felt_radius_km > 0) {
        lines.push(`Felt radius: ${props.felt_radius_km.toFixed(0)} km`);
      }
      // Aftershock sequence info
      if (props.is_mainshock && props.aftershock_count > 0) {
        lines.push(`<span style="color:#4fc3f7">Aftershocks: ${props.aftershock_count.toLocaleString()}</span>`);
        lines.push(`<a href="#" class="view-sequence-link" data-sequence="${props.sequence_id}" style="color:#81c784;text-decoration:underline;cursor:pointer">View sequence</a>`);
      } else if (props.mainshock_id) {
        lines.push(`<span style="color:#ffb74d">Aftershock of larger event</span>`);
        if (props.sequence_id) {
          lines.push(`<a href="#" class="view-sequence-link" data-sequence="${props.sequence_id}" style="color:#81c784;text-decoration:underline;cursor:pointer">View sequence</a>`);
        }
      }
      // Cross-link to volcanoes: look for eruptions that may have triggered this earthquake
      // Only for modern earthquakes where volcano data overlaps (1900+)
      if (props.year >= 1900 || (props.timestamp && new Date(props.timestamp).getFullYear() >= 1900)) {
        const lat = props.latitude || props.lat;
        const lon = props.longitude || props.lng || props.lon;
        if (lat != null && lon != null) {
          const ts = props.timestamp || props.time || '';
          const yr = props.year || (props.timestamp ? new Date(props.timestamp).getFullYear() : null);
          lines.push(`<a href="#" class="find-volcanoes-link" data-lat="${lat}" data-lon="${lon}" data-timestamp="${ts}" data-year="${yr}" style="color:#feb24c;text-decoration:underline;cursor:pointer">Find related volcanoes</a>`);
        }
      }
    } else if (eventType === 'volcano') {
      lines.push(`<strong>${props.volcano_name || 'Volcanic Eruption'}</strong>`);
      // Show VEI or Unknown (unknown = green marker)
      lines.push(`VEI: ${props.VEI != null ? props.VEI : 'Unknown'}`);
      if (props.activity_type) lines.push(`Type: ${props.activity_type}`);
      // Show activity area if available (e.g., "East rift zone")
      if (props.activity_area) lines.push(`Area: ${props.activity_area}`);
      // Display year/date range with duration for long eruptions
      if (props.year != null) {
        const startYear = props.year < 0 ? `${Math.abs(props.year)} BCE` : props.year;
        // Check if this is a multi-year eruption (has end_year different from start)
        if (props.end_year != null && !isNaN(props.end_year) && props.end_year !== props.year) {
          // Multi-year eruption - show range
          const endYear = props.is_ongoing ? 'ongoing' : props.end_year;
          lines.push(`Years: ${startYear} - ${endYear}`);
          // Show duration in appropriate units
          if (props.duration_days != null && !isNaN(props.duration_days) && props.duration_days > 0) {
            const years = props.duration_days / 365.25;
            if (years >= 1) {
              lines.push(`Duration: ${years.toFixed(1)} years`);
            } else {
              lines.push(`Duration: ${Math.round(props.duration_days)} days`);
            }
          }
        } else {
          // Single year or short eruption
          lines.push(`Year: ${startYear}`);
          // Show specific date if available
          if (props.timestamp) {
            const date = new Date(props.timestamp);
            if (!isNaN(date.getTime())) {
              lines.push(date.toLocaleDateString());
            }
          }
        }
      }
      // Show ongoing status prominently
      if (props.is_ongoing === true || props.is_ongoing === 'true') {
        lines.push(`<span style="color:#ff9800">ONGOING</span>`);
      }
      // Show impact radii
      if (props.damage_radius_km > 0) {
        lines.push(`Damage radius: ${Math.round(props.damage_radius_km)} km`);
      }
      if (props.felt_radius_km > 0) {
        lines.push(`Felt radius: ${Math.round(props.felt_radius_km)} km`);
      }
      // Cross-link to earthquakes: only for modern eruptions (1900+) where earthquake data exists
      if (props.year != null && props.year >= 1900) {
        // Store coordinates as data attributes for the fetch
        const lat = props.latitude || props.lat;
        const lon = props.longitude || props.lng || props.lon;
        if (lat != null && lon != null) {
          const ts = props.timestamp || '';
          lines.push(`<a href="#" class="find-earthquakes-link" data-lat="${lat}" data-lon="${lon}" data-timestamp="${ts}" data-year="${props.year}" data-volcano="${props.volcano_name || 'volcano'}" style="color:#4fc3f7;text-decoration:underline;cursor:pointer">Find related earthquakes</a>`);
        }
      }
    } else {
      // Generic popup
      lines.push(`<strong>${eventType} Event</strong>`);
      if (props.event_id) lines.push(`ID: ${props.event_id}`);
    }

    return lines.join('<br>');
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
