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
    } else if (eventType === 'tsunami') {
      this._addTsunamiLayer(options);
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

            // Setup click handler for "View runups" link (tsunami cross-link)
            const runupLinks = popupEl.querySelectorAll('.view-runups-link');
            runupLinks.forEach(link => {
              link.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const eventId = link.dataset.event;

                // Update link to show loading state
                link.textContent = 'Loading runups...';
                link.style.pointerEvents = 'none';

                try {
                  // Fetch animation data (source + runups combined)
                  const url = `/api/tsunamis/${eventId}/animation`;
                  const response = await fetch(url);
                  const data = await response.json();

                  if (data.features && data.features.length > 1) {
                    // Found runups - update display
                    const runupCount = data.metadata?.runup_count || (data.features.length - 1);
                    link.textContent = `Showing ${runupCount} runups`;
                    link.style.color = '#81c784';

                    // Notify listeners to display the runups
                    this._notifyTsunamiRunups(data, eventId);
                  } else {
                    link.textContent = 'No runups recorded';
                    link.style.color = '#999';
                  }
                } catch (err) {
                  console.error('Error fetching tsunami runups:', err);
                  link.textContent = 'Error loading';
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

    // Recency-based effects for animation
    // _recency: 1.5 = brand new (flash), 1.0 = recent, 0.0 = fading out
    // Use coalesce to default to 1.0 if _recency not present (normal display)
    const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];

    // Opacity: cap at 1.0 (recency can be > 1.0 for flash effect)
    const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];

    // Size boost for new events: when recency > 1.0, add extra size
    // At recency 1.5: adds 50% extra size. At recency 1.0 or below: no boost.
    const sizeBoostExpr = (baseSize) => [
      '*', baseSize,
      ['max', 1.0, recencyExpr]  // Multiplier is 1.0-1.5 for flash, 1.0 otherwise
    ];

    // 3. EPICENTER GLOW - subtle glow behind the marker
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(['+', epicenterSize, 4]),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.3),  // Fade with recency, cap at 1.0
        'circle-blur': 1
      }
    });

    // 4. EPICENTER MARKER - small solid circle at exact location
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(epicenterSize),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.9),  // Fade with recency, cap at 1.0
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

    // Recency-based effects for animation
    // _recency: 1.5 = brand new (flash), 1.0 = recent, 0.0 = fading out
    const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];
    const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];
    const sizeBoostExpr = (baseSize) => ['*', baseSize, ['max', 1.0, recencyExpr]];

    // 3. EPICENTER GLOW
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(['+', epicenterSize, 4]),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.3),  // Fade with recency, cap at 1.0
        'circle-blur': 1
      }
    });

    // 4. EPICENTER MARKER
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(epicenterSize),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.85),  // Fade with recency, cap at 1.0
        'circle-stroke-color': '#333333',
        'circle-stroke-width': 1
      }
    });
  },

  /**
   * Add tsunami-specific layers.
   * Handles both source epicenters (cyan) and coastal runup points (teal).
   * Uses is_source property to distinguish source from runup points.
   * Includes impact radius rings scaled by runup_count (log scale).
   * @private
   */
  _addTsunamiLayer(options = {}) {
    const map = MapAdapter.map;

    // Recency-based effects for animation
    const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];
    const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];
    const sizeBoostExpr = (baseSize) => ['*', baseSize, ['max', 1.0, recencyExpr]];

    // Colors: Source = cyan, Runup = teal/green
    // Use coalesce to handle boolean or truthy check
    const isSourceExpr = ['coalesce', ['get', 'is_source'], false];
    const colorExpr = [
      'case',
      ['==', isSourceExpr, true], '#00bcd4',  // Cyan for source
      '#26a69a'  // Teal-green for runups
    ];

    // Size based on runup_count (for sources) or water_height_m (for runups)
    // Log scale for runup count: 1->4, 10->7, 100->10, 1000->13, 5000->16
    // Increased range for more visible size difference
    const sizeExpr = [
      'case',
      ['==', isSourceExpr, true],
      // Source: size by runup_count (log scale for wide range 0-6000+)
      [
        'interpolate', ['linear'],
        ['log10', ['max', 1, ['coalesce', ['get', 'runup_count'], 1]]],
        0, 4,      // 1 runup = 4px
        1, 7,      // 10 runups = 7px
        2, 10,     // 100 runups = 10px
        3, 14,     // 1000 runups = 14px
        3.7, 18    // 5000+ runups = 18px (largest)
      ],
      // Runup: size by water height
      [
        'interpolate', ['linear'], ['coalesce', ['get', 'water_height_m'], 1],
        0, 4,
        5, 8,
        10, 12,
        20, 16
      ]
    ];

    // Helper: convert km to pixels at current zoom (same as earthquakes)
    // Formula: pixels = km * 2^zoom / 156.5
    const kmToPixels = (kmExpr) => [
      'interpolate', ['exponential', 2], ['zoom'],
      0, ['/', kmExpr, 156.5],
      5, ['/', kmExpr, 4.9],
      10, ['*', kmExpr, 6.54],
      15, ['*', kmExpr, 209]
    ];

    // Impact radius in km based on runup_count (log scale)
    // More runups = wider impact = larger ring
    // 1 runup = 30km, 10 = 100km, 100 = 300km, 1000 = 800km, 5000+ = 1500km
    const impactRadiusKm = [
      'interpolate', ['linear'],
      ['log10', ['max', 1, ['coalesce', ['get', 'runup_count'], 1]]],
      0, 30,       // 1 runup = 30km
      1, 100,      // 10 runups = 100km
      2, 300,      // 100 runups = 300km
      3, 800,      // 1000 runups = 800km
      3.7, 1500    // 5000+ runups = 1500km
    ];

    // 1. CONNECTION LINES (source to runups) - optional
    if (options.showConnections !== false) {
      map.addLayer({
        id: CONFIG.layers.eventSource + '-connections',
        type: 'line',
        source: CONFIG.layers.eventSource,
        filter: ['==', ['geometry-type'], 'LineString'],
        paint: {
          'line-color': '#26c6da',
          'line-width': 1.5,
          'line-opacity': opacityExpr(0.4),
          'line-dasharray': [2, 2]
        }
      });
    }

    // 2. IMPACT RADIUS RING - shows tsunami reach based on runup_count
    // Only for source events (is_source: true)
    map.addLayer({
      id: CONFIG.layers.eventRadiusOuter,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['all',
        ['==', ['geometry-type'], 'Point'],
        ['==', ['get', 'is_source'], true],
        ['>', ['coalesce', ['get', 'runup_count'], 0], 0]
      ],
      paint: {
        'circle-radius': kmToPixels(impactRadiusKm),
        'circle-color': 'transparent',
        'circle-stroke-color': '#00bcd4',  // Cyan ring
        'circle-stroke-width': 1.5,
        'circle-stroke-opacity': opacityExpr(0.35)
      }
    });

    // 3. INNER IMPACT RING - smaller ring for high-impact events (100+ runups)
    map.addLayer({
      id: CONFIG.layers.eventRadiusInner,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['all',
        ['==', ['geometry-type'], 'Point'],
        ['==', ['get', 'is_source'], true],
        ['>=', ['coalesce', ['get', 'runup_count'], 0], 100]
      ],
      paint: {
        'circle-radius': kmToPixels(['/', impactRadiusKm, 3]),  // 1/3 of outer
        'circle-color': 'transparent',
        'circle-stroke-color': '#00bcd4',
        'circle-stroke-width': 2.5,
        'circle-stroke-opacity': opacityExpr(0.6)
      }
    });

    // 4. SELECTED EVENT LAYERS - filled circles for clicked event
    map.addLayer({
      id: CONFIG.layers.eventRadiusOuter + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],  // Initially matches nothing
      paint: {
        'circle-radius': kmToPixels(impactRadiusKm),
        'circle-color': '#00bcd4',
        'circle-opacity': 0.12,
        'circle-stroke-color': '#00bcd4',
        'circle-stroke-width': 2,
        'circle-stroke-opacity': 0.5
      }
    });

    map.addLayer({
      id: CONFIG.layers.eventRadiusInner + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],
      paint: {
        'circle-radius': kmToPixels(['/', impactRadiusKm, 3]),
        'circle-color': '#00bcd4',
        'circle-opacity': 0.2,
        'circle-stroke-color': '#00bcd4',
        'circle-stroke-width': 3,
        'circle-stroke-opacity': 0.7
      }
    });

    // 5. WAVE FRONT CIRCLE - animated growing circle during radial animation
    // Uses _waveRadiusKm property set by EventAnimator
    map.addLayer({
      id: CONFIG.layers.eventSource + '-wavefront',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['all',
        ['==', ['geometry-type'], 'Point'],
        ['==', ['get', 'is_source'], true],
        ['has', '_waveRadiusKm'],
        ['>', ['get', '_waveRadiusKm'], 0]
      ],
      paint: {
        'circle-radius': kmToPixels(['get', '_waveRadiusKm']),
        'circle-color': 'transparent',
        'circle-stroke-color': '#4dd0e1',  // Teal wave front
        'circle-stroke-width': 3,
        'circle-stroke-opacity': 0.7,
        'circle-pitch-alignment': 'map'
      }
    });

    // 6. WAVE FRONT GLOW - subtle glow around wave front
    map.addLayer({
      id: CONFIG.layers.eventSource + '-wavefront-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['all',
        ['==', ['geometry-type'], 'Point'],
        ['==', ['get', 'is_source'], true],
        ['has', '_waveRadiusKm'],
        ['>', ['get', '_waveRadiusKm'], 0]
      ],
      paint: {
        'circle-radius': kmToPixels(['+', ['get', '_waveRadiusKm'], 20]),
        'circle-color': '#4dd0e1',
        'circle-opacity': 0.08,
        'circle-blur': 0.8
      }
    });

    // 7. GLOW layer
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': sizeBoostExpr(['+', sizeExpr, 4]),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.3),
        'circle-blur': 1
      }
    });

    // 8. MAIN CIRCLE layer
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': sizeBoostExpr(sizeExpr),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.9),
        'circle-stroke-color': [
          'case',
          ['==', isSourceExpr, true], '#004d40',  // Dark teal stroke for source
          '#006064'  // Slightly different for runups
        ],
        'circle-stroke-width': [
          'case',
          ['==', isSourceExpr, true], 2,  // Thicker stroke for source
          1
        ]
      }
    });
  },

  /**
   * Add generic event layer for other event types.
   * @private
   */
  _addGenericEventLayer(eventType, options = {}) {
    const map = MapAdapter.map;

    // Recency-based effects for animation
    // _recency: 1.5 = brand new (flash), 1.0 = recent, 0.0 = fading out
    const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];
    const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];
    const sizeBoostExpr = (baseSize) => ['*', baseSize, ['max', 1.0, recencyExpr]];

    // Default yellow/orange coloring
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(12),
        'circle-color': '#ffcc00',
        'circle-opacity': opacityExpr(0.3),  // Fade with recency, cap at 1.0
        'circle-blur': 1
      }
    });

    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(6),
        'circle-color': '#ffcc00',
        'circle-opacity': opacityExpr(0.85),  // Fade with recency, cap at 1.0
        'circle-stroke-color': '#333333',
        'circle-stroke-width': 1
      }
    });
  },

  /**
   * Update existing source data or create layers if needed.
   * Used for time-based filtering and animation updates.
   * @param {Object} geojson - GeoJSON FeatureCollection
   * @param {Object} options - Options including eventType for layer creation
   */
  update(geojson, options = {}) {
    if (!MapAdapter?.map) return;

    const source = MapAdapter.map.getSource(CONFIG.layers.eventSource);
    if (source) {
      source.setData(geojson);
    } else {
      // Source doesn't exist, need to render with proper event type
      const eventType = options.eventType || this.activeType || 'generic_event';
      this.render(geojson, eventType, options);
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

    // Remove layers (including selection, sequence highlight, and tsunami layers)
    const layerIds = [
      CONFIG.layers.eventCircle,
      CONFIG.layers.eventCircle + '-glow',
      CONFIG.layers.eventCircle + '-sequence',  // Green sequence highlight
      CONFIG.layers.eventLabel,
      CONFIG.layers.eventRadiusOuter,
      CONFIG.layers.eventRadiusInner,
      CONFIG.layers.eventRadiusOuter + '-selected',
      CONFIG.layers.eventRadiusInner + '-selected',
      CONFIG.layers.eventSource + '-connections',  // Tsunami connection lines
      CONFIG.layers.eventSource + '-wavefront',     // Tsunami wave front
      CONFIG.layers.eventSource + '-wavefront-glow' // Wave front glow
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

    // Clean up runups mode state
    this._inRunupsMode = false;
    this._originalTsunamiData = null;
    this._hideRunupsExitControl();

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
   * Notify about tsunami runups loaded for an event.
   * @param {Object} data - GeoJSON with source + runups from animation endpoint
   * @param {string} eventId - Tsunami event ID
   */
  _notifyTsunamiRunups(data, eventId) {
    console.log(`PointRadiusModel: Loaded ${data.features?.length - 1 || 0} runups for ${eventId}`);

    if (this.tsunamiRunupsCallback) {
      this.tsunamiRunupsCallback({
        geojson: data,
        eventId: eventId,
        runupCount: data.metadata?.runup_count || 0
      });
    } else {
      // Default behavior: update the map source directly with combined data
      this._displayTsunamiRunups(data);
    }
  },

  /**
   * Display tsunami runups on the map (default behavior).
   * Stores original data so user can exit back to normal view.
   * @param {Object} geojson - GeoJSON with source + runups
   */
  _displayTsunamiRunups(geojson) {
    if (!MapAdapter?.map) return;

    const source = MapAdapter.map.getSource(CONFIG.layers.eventSource);
    if (source) {
      // Store original data if not already in runups mode
      if (!this._inRunupsMode && source._data) {
        this._originalTsunamiData = source._data;
        this._inRunupsMode = true;
      }

      // Update the source data with combined features
      source.setData(geojson);

      // Fit bounds to show all points
      this.fitBounds(geojson);

      // Show exit button in popup or add to map
      this._showRunupsExitControl();

      console.log(`PointRadiusModel: Displaying ${geojson.features?.length || 0} tsunami features (runups mode)`);
    }
  },

  /**
   * Exit runups view and restore original tsunami data.
   */
  exitRunupsMode() {
    if (!this._inRunupsMode || !this._originalTsunamiData) {
      console.log('PointRadiusModel: Not in runups mode, nothing to exit');
      return;
    }

    const source = MapAdapter?.map?.getSource(CONFIG.layers.eventSource);
    if (source) {
      source.setData(this._originalTsunamiData);
      console.log('PointRadiusModel: Restored original tsunami data');
    }

    // Clean up
    this._inRunupsMode = false;
    this._originalTsunamiData = null;
    this._hideRunupsExitControl();

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;
  },

  /**
   * Show an exit control for runups mode.
   * @private
   */
  _showRunupsExitControl() {
    // Remove any existing control
    this._hideRunupsExitControl();

    // Create a floating button on the map
    const exitBtn = document.createElement('button');
    exitBtn.id = 'runups-exit-btn';
    exitBtn.textContent = 'Exit Runups View';
    exitBtn.style.cssText = `
      position: absolute;
      top: 70px;
      right: 10px;
      z-index: 100;
      padding: 8px 16px;
      background: #004d40;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    `;
    exitBtn.addEventListener('click', () => {
      this.exitRunupsMode();
    });

    // Add to map container
    const mapContainer = MapAdapter?.map?.getContainer();
    if (mapContainer) {
      mapContainer.appendChild(exitBtn);
    }
  },

  /**
   * Hide the runups exit control.
   * @private
   */
  _hideRunupsExitControl() {
    const existing = document.getElementById('runups-exit-btn');
    if (existing) {
      existing.remove();
    }
  },

  /**
   * Register callback for tsunami runups.
   * @param {Function} callback - Callback function
   */
  onTsunamiRunups(callback) {
    this.tsunamiRunupsCallback = callback;
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
    } else if (eventType === 'tsunami') {
      // Tsunami - different display for source vs runup
      // Check both is_source (API) and _isSource (animation enriched)
      if (props.is_source || props._isSource) {
        // Source epicenter
        lines.push('<strong>Tsunami Source</strong>');
        if (props.cause) lines.push(`Cause: ${props.cause}`);
        if (props.eq_magnitude) lines.push(`Magnitude: M${props.eq_magnitude.toFixed(1)}`);
        if (props.max_water_height_m != null) {
          lines.push(`Max wave height: ${props.max_water_height_m.toFixed(1)} m`);
        }
        if (props.timestamp) {
          const date = new Date(props.timestamp);
          lines.push(date.toLocaleString());
        } else if (props.year) {
          const yearStr = props.year < 0 ? `${Math.abs(props.year)} BCE` : props.year;
          lines.push(`Year: ${yearStr}`);
        }
        // Casualties
        if (props.deaths != null && props.deaths > 0) {
          lines.push(`<span style="color:#ef5350">Deaths: ${props.deaths.toLocaleString()}</span>`);
        }
        if (props.injuries != null && props.injuries > 0) {
          lines.push(`Injuries: ${props.injuries.toLocaleString()}`);
        }
        // Runup count
        if (props.runup_count != null && props.runup_count > 0) {
          lines.push(`<span style="color:#4dd0e1">Runups recorded: ${props.runup_count}</span>`);
          if (props.event_id) {
            lines.push(`<a href="#" class="view-runups-link" data-event="${props.event_id}" style="color:#81c784;text-decoration:underline;cursor:pointer">View runups</a>`);
          }
        }
      } else {
        // Coastal runup observation
        lines.push('<strong>Coastal Runup</strong>');
        if (props.location_name) lines.push(props.location_name);
        if (props.country) lines.push(props.country);
        if (props.water_height_m != null) {
          lines.push(`Wave height: ${props.water_height_m.toFixed(1)} m`);
        }
        if (props.dist_from_source_km != null) {
          lines.push(`Distance from source: ${Math.round(props.dist_from_source_km)} km`);
        }
        // Travel time
        if (props.travel_time_hours != null) {
          const hours = props.travel_time_hours;
          if (hours < 1) {
            lines.push(`Travel time: ${Math.round(hours * 60)} min`);
          } else {
            lines.push(`Travel time: ${hours.toFixed(1)} hours`);
          }
        }
        // Runup casualties
        if (props.deaths != null && props.deaths > 0) {
          lines.push(`<span style="color:#ef5350">Deaths: ${props.deaths.toLocaleString()}</span>`);
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
