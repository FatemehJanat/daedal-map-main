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
    } else if (eventType === 'wildfire') {
      this._addWildfireLayer(options);
    } else if (eventType === 'tornado') {
      this._addTornadoLayer(options);
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
                const eventId = link.dataset.eventid;
                if (seqId || eventId) {
                  // Notify sequence change listeners (SequenceAnimator handles viewport/display)
                  // Pass both sequenceId and eventId for accurate aftershock queries
                  this._notifySequenceChange(seqId, eventId);
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

            // Setup click handler for "View fire progression" link (wildfire animation)
            const fireLinks = popupEl.querySelectorAll('.view-fire-link');
            fireLinks.forEach(link => {
              link.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const eventId = link.dataset.event;
                const duration = parseInt(link.dataset.duration) || 30;
                const timestamp = link.dataset.timestamp;
                const year = link.dataset.year;
                const latitude = link.dataset.lat ? parseFloat(link.dataset.lat) : null;
                const longitude = link.dataset.lon ? parseFloat(link.dataset.lon) : null;

                // Update link to show loading state
                link.textContent = 'Loading fire...';
                link.style.pointerEvents = 'none';

                try {
                  // First try to get daily progression data
                  const progressionUrl = year
                    ? `/api/wildfires/${eventId}/progression?year=${year}`
                    : `/api/wildfires/${eventId}/progression`;
                  const progressionResponse = await fetch(progressionUrl);
                  const progressionData = await progressionResponse.json();

                  if (progressionData.snapshots && progressionData.snapshots.length > 0) {
                    // We have daily progression data - use it
                    link.textContent = `Starting (${progressionData.total_days} days)...`;
                    link.style.color = '#ff9800';
                    this._notifyFireProgression(progressionData, eventId, timestamp, latitude, longitude);
                  } else {
                    // Fall back to single perimeter
                    const perimeterUrl = year
                      ? `/api/wildfires/${eventId}/perimeter?year=${year}`
                      : `/api/wildfires/${eventId}/perimeter`;
                    const perimeterResponse = await fetch(perimeterUrl);
                    const perimeterData = await perimeterResponse.json();

                    if (perimeterData.geometry) {
                      link.textContent = 'Starting animation...';
                      link.style.color = '#ff9800';
                      this._notifyFireAnimation(perimeterData, eventId, duration, timestamp, latitude, longitude);
                    } else {
                      link.textContent = 'No perimeter data';
                      link.style.color = '#999';
                    }
                  }
                } catch (err) {
                  console.error('Error fetching fire data:', err);
                  link.textContent = 'Error loading';
                  link.style.color = '#f44336';
                }

                // Re-enable after delay
                setTimeout(() => {
                  link.style.pointerEvents = 'auto';
                }, 2000);
              });
            });

            // Setup click handler for "View tornado track" link
            const tornadoLinks = popupEl.querySelectorAll('.view-tornado-track-link');
            tornadoLinks.forEach(link => {
              link.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const eventId = link.dataset.event;

                // Update link to show loading state
                link.textContent = 'Loading track...';
                link.style.pointerEvents = 'none';

                try {
                  // Fetch tornado detail with track data
                  const url = `/api/tornadoes/${eventId}`;
                  const response = await fetch(url);
                  const data = await response.json();

                  if (data.track && data.track.geometry) {
                    link.textContent = 'Showing track';
                    link.style.color = '#32cd32';

                    // Display the track on the map
                    this._displayTornadoTrack(data);
                  } else {
                    link.textContent = 'No track data';
                    link.style.color = '#999';
                  }
                } catch (err) {
                  console.error('Error fetching tornado track:', err);
                  link.textContent = 'Error loading';
                  link.style.color = '#f44336';
                }

                // Re-enable after delay
                setTimeout(() => {
                  link.style.pointerEvents = 'auto';
                }, 2000);
              });
            });

            // Setup click handler for "View tornado sequence" link
            const sequenceLinks = popupEl.querySelectorAll('.view-tornado-sequence-link');
            sequenceLinks.forEach(link => {
              link.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const eventId = link.dataset.event;

                // Update link to show loading state
                link.textContent = 'Finding sequence...';
                link.style.pointerEvents = 'none';

                try {
                  // Fetch tornado sequence (linked tornadoes from same storm system)
                  const url = `/api/tornadoes/${eventId}/sequence`;
                  const response = await fetch(url);
                  const data = await response.json();

                  if (data.features && data.features.length > 1) {
                    link.textContent = `Found ${data.sequence_count} linked`;
                    link.style.color = '#ffa500';

                    // Notify controller to display the sequence
                    this._notifyTornadoSequence(data, eventId);
                  } else {
                    link.textContent = 'No linked tornadoes';
                    link.style.color = '#999';
                  }
                } catch (err) {
                  console.error('Error fetching tornado sequence:', err);
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

    // Also handle clicks on polygon fill layer (for wildfires with perimeters)
    MapAdapter.map.on('click', CONFIG.layers.eventCircle + '-fill', this.clickHandler);

    // Click elsewhere to unlock popup and deselect
    this._mapClickHandler = (e) => {
      // Check if click was on an event feature (both circle and polygon fill layers)
      const layersToCheck = [CONFIG.layers.eventCircle];
      // Also check polygon fill layer if it exists (for wildfires)
      if (MapAdapter.map.getLayer(CONFIG.layers.eventCircle + '-fill')) {
        layersToCheck.push(CONFIG.layers.eventCircle + '-fill');
      }
      const features = MapAdapter.map.queryRenderedFeatures(e.point, {
        layers: layersToCheck
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
   * Add wildfire-specific layer.
   * Renders polygon perimeters when available, falls back to circles for points.
   * Size/color based on area_km2 (log scale), orange/red coloring.
   * @private
   */
  _addWildfireLayer(options = {}) {
    const map = MapAdapter.map;

    // Recency-based effects for animation
    const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];
    const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];
    const sizeBoostExpr = (baseSize) => ['*', baseSize, ['max', 1.0, recencyExpr]];

    // Color gradient: smaller fires = orange, larger = deep red
    const colorExpr = [
      'interpolate', ['linear'],
      ['log10', ['max', 10, ['coalesce', ['get', 'area_km2'], 100]]],
      2, '#ff8800',    // 100 km2 = orange
      3, '#ff4400',    // 1000 km2 = red-orange
      4, '#cc0000',    // 10000 km2 = red
      4.5, '#880000'   // 30000+ km2 = dark red
    ];

    // Filter for polygon geometries (fires with perimeters)
    const polygonFilter = ['any',
      ['==', ['geometry-type'], 'Polygon'],
      ['==', ['geometry-type'], 'MultiPolygon']
    ];

    // Filter for point geometries (fires without perimeters)
    const pointFilter = ['==', ['geometry-type'], 'Point'];

    // === POLYGON LAYERS (for fires with perimeter data) ===

    // Polygon fill layer
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-fill',
      type: 'fill',
      source: CONFIG.layers.eventSource,
      filter: polygonFilter,
      paint: {
        'fill-color': colorExpr,
        'fill-opacity': opacityExpr(0.5)
      }
    });

    // Polygon stroke layer
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-stroke',
      type: 'line',
      source: CONFIG.layers.eventSource,
      filter: polygonFilter,
      paint: {
        'line-color': '#ffcc00',
        'line-width': 1.5,
        'line-opacity': opacityExpr(0.9)
      }
    });

    // === CIRCLE LAYERS (fallback for fires without perimeter data) ===

    // Size based on area_km2 (log scale)
    const sizeExpr = [
      'interpolate', ['linear'],
      ['log10', ['max', 10, ['coalesce', ['get', 'area_km2'], 100]]],
      2, 5, 3, 10, 4, 16, 4.5, 22
    ];

    // Outer glow layer (points only)
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: pointFilter,
      paint: {
        'circle-radius': sizeBoostExpr(['*', sizeExpr, 2]),
        'circle-color': '#ff6600',
        'circle-opacity': opacityExpr(0.25),
        'circle-blur': 1
      }
    });

    // Main fire circle (points only)
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: pointFilter,
      paint: {
        'circle-radius': sizeBoostExpr(sizeExpr),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.85),
        'circle-stroke-color': '#ffcc00',
        'circle-stroke-width': 1.5
      }
    });
  },

  /**
   * Add tornado-specific layers.
   * Uses EF/F scale for color, display_radius for impact zone.
   * Supports drill-down to show track line when clicked.
   * @private
   */
  _addTornadoLayer(options = {}) {
    const map = MapAdapter.map;

    // Recency-based effects for animation
    const recencyExpr = ['coalesce', ['get', '_recency'], 1.0];
    const opacityExpr = (baseOpacity) => ['min', 1.0, ['*', baseOpacity, recencyExpr]];
    const sizeBoostExpr = (baseSize) => ['*', baseSize, ['max', 1.0, recencyExpr]];

    // Color by tornado scale (EF0-EF5 or legacy F0-F5)
    // Maps to severe weather convention: green to red
    // tornado_scale can be "EF0", "F3", etc. - extract number
    const scaleNumExpr = [
      'to-number',
      ['slice', ['coalesce', ['get', 'tornado_scale'], 'EF0'], -1],
      0
    ];

    const colorExpr = [
      'interpolate', ['linear'], scaleNumExpr,
      0, '#98fb98',  // EF0 - Pale green (weak)
      1, '#32cd32',  // EF1 - Lime green
      2, '#ffd700',  // EF2 - Gold (significant)
      3, '#ff8c00',  // EF3 - Dark orange (severe)
      4, '#ff4500',  // EF4 - Orange-red (devastating)
      5, '#8b0000'   // EF5 - Dark red (violent)
    ];

    // Size by EF scale - larger = stronger tornado
    const sizeExpr = [
      'interpolate', ['linear'], scaleNumExpr,
      0, 4,   // EF0 = 4px
      1, 6,   // EF1 = 6px
      2, 8,   // EF2 = 8px
      3, 10,  // EF3 = 10px
      4, 13,  // EF4 = 13px
      5, 16   // EF5 = 16px
    ];

    // Helper: convert km to pixels at current zoom
    const kmToPixels = (kmExpr) => [
      'interpolate', ['exponential', 2], ['zoom'],
      0, ['/', kmExpr, 156.5],
      5, ['/', kmExpr, 4.9],
      10, ['*', kmExpr, 6.54],
      15, ['*', kmExpr, 209]
    ];

    // 1. DAMAGE RADIUS - shows width-based impact zone
    // Only show if display_radius is available
    map.addLayer({
      id: CONFIG.layers.eventRadiusOuter,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['>', ['coalesce', ['get', 'display_radius'], 0], 0],
      paint: {
        'circle-radius': kmToPixels(['get', 'display_radius']),
        'circle-color': 'transparent',
        'circle-stroke-color': colorExpr,
        'circle-stroke-width': 1.5,
        'circle-stroke-opacity': opacityExpr(0.4)
      }
    });

    // 2. SELECTED EVENT LAYERS - filled circles for clicked event
    map.addLayer({
      id: CONFIG.layers.eventRadiusOuter + '-selected',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      filter: ['==', ['get', 'event_id'], ''],  // Initially matches nothing
      paint: {
        'circle-radius': kmToPixels(['coalesce', ['get', 'display_radius'], 1]),
        'circle-color': colorExpr,
        'circle-opacity': 0.2,
        'circle-stroke-color': colorExpr,
        'circle-stroke-width': 2,
        'circle-stroke-opacity': 0.7
      }
    });

    // 3. TORNADO TRACK LINE - shown during drill-down
    // Uses separate source added by drill-down handler
    // This layer is just a placeholder - actual track uses tornado-track source

    // 4. GLOW layer
    map.addLayer({
      id: CONFIG.layers.eventCircle + '-glow',
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(['+', sizeExpr, 4]),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.35),
        'circle-blur': 1
      }
    });

    // 5. MAIN TORNADO MARKER
    map.addLayer({
      id: CONFIG.layers.eventCircle,
      type: 'circle',
      source: CONFIG.layers.eventSource,
      paint: {
        'circle-radius': sizeBoostExpr(sizeExpr),
        'circle-color': colorExpr,
        'circle-opacity': opacityExpr(0.9),
        'circle-stroke-color': '#222222',
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
      map.off('click', CONFIG.layers.eventCircle + '-fill', this.clickHandler);  // Polygon fill
      this.clickHandler = null;
    }
    if (this._mapClickHandler) {
      map.off('click', this._mapClickHandler);
      this._mapClickHandler = null;
    }

    // Unlock popup
    MapAdapter.popupLocked = false;

    // Remove layers (including selection, sequence highlight, polygon, and tsunami layers)
    const layerIds = [
      CONFIG.layers.eventCircle,
      CONFIG.layers.eventCircle + '-glow',
      CONFIG.layers.eventCircle + '-fill',    // Wildfire polygon fill
      CONFIG.layers.eventCircle + '-stroke',  // Wildfire polygon stroke
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

    // Clean up track mode state (tornado drill-down)
    this._clearTornadoTrack();
    this._inTrackMode = false;
    this._hideTrackExitControl();

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
   * @param {Function} callback - Called with (sequenceId, eventId) when sequence changes
   */
  onSequenceChange(callback) {
    this.sequenceChangeCallback = callback;
  },

  /**
   * Notify sequence change listeners without highlighting.
   * Used when starting animation - SequenceAnimator handles display.
   * @param {string} sequenceId - Sequence ID
   * @param {string} eventId - Event ID (mainshock ID for accurate aftershock query)
   * @private
   */
  _notifySequenceChange(sequenceId, eventId = null) {
    if (this.sequenceChangeCallback) {
      this.sequenceChangeCallback(sequenceId, eventId);
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
   * Display a tornado track on the map.
   * Shows track line, start point, end point, and impact radius.
   * @param {Object} data - Tornado detail data with track GeoJSON
   */
  _displayTornadoTrack(data) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const trackSourceId = 'tornado-track';
    const trackLayerId = 'tornado-track-line';
    const pointsLayerId = 'tornado-track-points';
    const radiusLayerId = 'tornado-track-radius';

    // Clean up any existing track layers
    this._clearTornadoTrack();

    // Get scale color for consistent styling
    const scale = data.tornado_scale || 'EF0';
    const scaleColors = {
      'EF0': '#98fb98', 'F0': '#98fb98',
      'EF1': '#32cd32', 'F1': '#32cd32',
      'EF2': '#ffd700', 'F2': '#ffd700',
      'EF3': '#ff8c00', 'F3': '#ff8c00',
      'EF4': '#ff4500', 'F4': '#ff4500',
      'EF5': '#8b0000', 'F5': '#8b0000'
    };
    const trackColor = scaleColors[scale] || '#32cd32';

    // Build GeoJSON with track line and endpoint markers
    const features = [];

    // Add track line if available
    if (data.track && data.track.geometry) {
      features.push({
        type: 'Feature',
        geometry: data.track.geometry,
        properties: { type: 'track', tornado_scale: scale }
      });
    }

    // Add start point marker
    if (data.latitude != null && data.longitude != null) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [data.longitude, data.latitude] },
        properties: { type: 'start', tornado_scale: scale, label: 'START' }
      });
    }

    // Add end point marker
    if (data.end_latitude != null && data.end_longitude != null) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [data.end_longitude, data.end_latitude] },
        properties: { type: 'end', tornado_scale: scale, label: 'END' }
      });
    }

    const geojson = { type: 'FeatureCollection', features };

    // Add source
    map.addSource(trackSourceId, { type: 'geojson', data: geojson });

    // Helper: km to pixels
    const kmToPixels = (km) => [
      'interpolate', ['exponential', 2], ['zoom'],
      0, km / 156.5,
      5, km / 4.9,
      10, km * 6.54,
      15, km * 209
    ];

    // Add impact radius along track (using display_radius)
    if (data.display_radius > 0) {
      map.addLayer({
        id: radiusLayerId,
        type: 'line',
        source: trackSourceId,
        filter: ['==', ['get', 'type'], 'track'],
        paint: {
          'line-color': trackColor,
          'line-width': kmToPixels(data.display_radius * 2),
          'line-opacity': 0.25
        }
      });
    }

    // Add track line layer
    map.addLayer({
      id: trackLayerId,
      type: 'line',
      source: trackSourceId,
      filter: ['==', ['get', 'type'], 'track'],
      paint: {
        'line-color': trackColor,
        'line-width': 4,
        'line-opacity': 0.9
      }
    });

    // Add endpoint markers
    map.addLayer({
      id: pointsLayerId,
      type: 'circle',
      source: trackSourceId,
      filter: ['in', ['get', 'type'], ['literal', ['start', 'end']]],
      paint: {
        'circle-radius': 8,
        'circle-color': [
          'case',
          ['==', ['get', 'type'], 'start'], '#00ff00',  // Green for start
          '#ff0000'  // Red for end
        ],
        'circle-stroke-color': '#222',
        'circle-stroke-width': 2
      }
    });

    // Fit map to track bounds
    if (data.track?.geometry?.coordinates?.length > 0) {
      const coords = data.track.geometry.coordinates;
      const bounds = new maplibregl.LngLatBounds();
      coords.forEach(c => bounds.extend(c));
      map.fitBounds(bounds, { padding: 80, duration: 800, maxZoom: 12 });
    }

    // Show exit control
    this._showTrackExitControl();
    this._inTrackMode = true;

    console.log(`PointRadiusModel: Displaying tornado track for ${data.event_id}`);
  },

  /**
   * Clear tornado track display.
   * @private
   */
  _clearTornadoTrack() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const layers = ['tornado-track-line', 'tornado-track-points', 'tornado-track-radius'];

    layers.forEach(id => {
      if (map.getLayer(id)) map.removeLayer(id);
    });

    if (map.getSource('tornado-track')) {
      map.removeSource('tornado-track');
    }
  },

  /**
   * Show exit control for track/drill-down mode.
   * @private
   */
  _showTrackExitControl() {
    // Remove any existing
    this._hideTrackExitControl();

    const exitBtn = document.createElement('button');
    exitBtn.id = 'track-exit-btn';
    exitBtn.textContent = 'Exit Track View';
    exitBtn.style.cssText = `
      position: absolute;
      top: 70px;
      right: 10px;
      z-index: 100;
      padding: 8px 16px;
      background: #2e7d32;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    `;
    exitBtn.addEventListener('click', () => {
      this.exitTrackMode();
    });

    const mapContainer = MapAdapter?.map?.getContainer();
    if (mapContainer) {
      mapContainer.appendChild(exitBtn);
    }
  },

  /**
   * Hide track exit control.
   * @private
   */
  _hideTrackExitControl() {
    const existing = document.getElementById('track-exit-btn');
    if (existing) existing.remove();
  },

  /**
   * Exit track/drill-down mode.
   */
  exitTrackMode() {
    this._clearTornadoTrack();
    this._hideTrackExitControl();
    this._inTrackMode = false;
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;
    console.log('PointRadiusModel: Exited track mode');
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
   * Register callback for fire animation events.
   * @param {Function} callback - Callback function
   */
  onFireAnimation(callback) {
    this.fireAnimationCallback = callback;
  },

  /**
   * Register callback for fire progression events (daily snapshots).
   * @param {Function} callback - Callback function receiving {snapshots, eventId, totalDays, startTime}
   */
  onFireProgression(callback) {
    this.fireProgressionCallback = callback;
  },

  /**
   * Notify about fire animation request.
   * @param {Object} perimeterData - GeoJSON perimeter from API
   * @param {string} eventId - Fire event ID
   * @param {number} durationDays - Fire duration in days
   * @param {string} timestamp - Fire ignition timestamp
   * @param {number} latitude - Ignition latitude
   * @param {number} longitude - Ignition longitude
   */
  _notifyFireAnimation(perimeterData, eventId, durationDays, timestamp, latitude, longitude) {
    console.log(`PointRadiusModel: Fire animation requested for ${eventId} (${durationDays} days)`);

    if (this.fireAnimationCallback) {
      this.fireAnimationCallback({
        perimeter: perimeterData,
        eventId: eventId,
        durationDays: durationDays,
        startTime: timestamp,
        latitude: latitude,
        longitude: longitude
      });
    } else {
      console.warn('PointRadiusModel: No fire animation callback registered');
    }
  },

  /**
   * Notify listeners that fire progression animation is requested.
   * Called when daily progression data is available.
   * @param {Object} progressionData - API response with daily snapshots
   * @param {string} eventId - Fire event ID
   * @param {string} timestamp - Fire ignition timestamp
   * @param {number} latitude - Ignition latitude
   * @param {number} longitude - Ignition longitude
   */
  _notifyFireProgression(progressionData, eventId, timestamp, latitude, longitude) {
    console.log(`PointRadiusModel: Fire progression requested for ${eventId} (${progressionData.total_days} daily snapshots)`);

    if (this.fireProgressionCallback) {
      this.fireProgressionCallback({
        snapshots: progressionData.snapshots,
        eventId: eventId,
        totalDays: progressionData.total_days,
        startTime: timestamp,
        latitude: latitude,
        longitude: longitude
      });
    } else if (this.fireAnimationCallback) {
      // Fall back to single-perimeter animation using last snapshot
      console.log('PointRadiusModel: No progression callback, falling back to single perimeter');
      const lastSnapshot = progressionData.snapshots[progressionData.snapshots.length - 1];
      this.fireAnimationCallback({
        perimeter: { type: 'Feature', geometry: lastSnapshot.geometry, properties: {} },
        eventId: eventId,
        durationDays: progressionData.total_days,
        startTime: timestamp,
        latitude: latitude,
        longitude: longitude
      });
    } else {
      console.warn('PointRadiusModel: No fire animation/progression callback registered');
    }
  },

  /**
   * Register callback for tornado sequence events.
   * @param {Function} callback - Callback function receiving {geojson, seedEventId, sequenceCount}
   */
  onTornadoSequence(callback) {
    this.tornadoSequenceCallback = callback;
  },

  /**
   * Notify about tornado sequence request.
   * @param {Object} sequenceData - GeoJSON FeatureCollection with linked tornadoes
   * @param {string} seedEventId - The tornado that was clicked
   */
  _notifyTornadoSequence(sequenceData, seedEventId) {
    console.log(`PointRadiusModel: Tornado sequence found with ${sequenceData.sequence_count} linked tornadoes`);

    if (this.tornadoSequenceCallback) {
      this.tornadoSequenceCallback({
        geojson: sequenceData,
        seedEventId: seedEventId,
        sequenceCount: sequenceData.sequence_count
      });
    } else {
      console.warn('PointRadiusModel: No tornado sequence callback registered');
      // Fall back to just displaying the sequence on the map
      this._displayTornadoSequence(sequenceData);
    }
  },

  // Tornado sequence animation state
  _tornadoSeqState: null,

  /**
   * Display a tornado sequence on the map with TimeSlider animation.
   * Shows linked tornado tracks appearing one by one as time advances.
   * @param {Object} sequenceData - GeoJSON FeatureCollection with linked tornadoes
   */
  _displayTornadoSequence(sequenceData) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const sourceId = 'tornado-sequence';
    const trackLayerId = 'tornado-sequence-tracks';
    const pointsLayerId = 'tornado-sequence-points';
    const connectLayerId = 'tornado-sequence-connect';

    // Clean up existing layers and animation state
    this._clearTornadoSequence();

    // Sort features by timestamp
    const sortedFeatures = sequenceData.features.sort((a, b) => {
      return new Date(a.properties.timestamp) - new Date(b.properties.timestamp);
    });

    // Extract timestamps for TimeSlider
    const timestamps = [];
    let minTime = Infinity, maxTime = -Infinity;
    for (const f of sortedFeatures) {
      const t = new Date(f.properties.timestamp).getTime();
      if (!isNaN(t)) {
        timestamps.push(t);
        if (t < minTime) minTime = t;
        if (t > maxTime) maxTime = t;
      }
    }
    timestamps.sort((a, b) => a - b);

    // If only one tornado or no valid timestamps, just show static display
    if (timestamps.length === 0 || minTime === maxTime) {
      this._displayTornadoSequenceStatic(sequenceData, sortedFeatures, map, sourceId, trackLayerId, pointsLayerId, connectLayerId);
      return;
    }

    // Build all possible features (will be filtered by time)
    const allFeatures = this._buildTornadoSequenceFeatures(sortedFeatures);

    // Add source with empty data (will be updated by time)
    map.addSource(sourceId, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });

    // Add connecting lines (dashed) - visible when tornado reaches that point
    map.addLayer({
      id: connectLayerId,
      type: 'line',
      source: sourceId,
      filter: ['==', ['get', 'feature_type'], 'connect'],
      paint: {
        'line-color': '#ffaa00',
        'line-width': 2,
        'line-dasharray': [4, 4],
        'line-opacity': 0.8
      }
    });

    // Add track lines
    map.addLayer({
      id: trackLayerId,
      type: 'line',
      source: sourceId,
      filter: ['==', ['get', 'feature_type'], 'track'],
      paint: {
        'line-color': ['case',
          ['==', ['get', 'is_seed'], true], '#ff4500',
          '#32cd32'
        ],
        'line-width': 5,
        'line-opacity': 0.9
      }
    });

    // Add endpoint markers
    map.addLayer({
      id: pointsLayerId,
      type: 'circle',
      source: sourceId,
      filter: ['in', ['get', 'feature_type'], ['literal', ['start', 'end']]],
      paint: {
        'circle-radius': 8,
        'circle-color': ['case',
          ['==', ['get', 'feature_type'], 'start'], '#00ff00',
          '#ff0000'
        ],
        'circle-stroke-color': '#222',
        'circle-stroke-width': 2
      }
    });

    // Fit bounds to full sequence
    const bounds = new maplibregl.LngLatBounds();
    sortedFeatures.forEach(f => {
      bounds.extend([f.properties.longitude, f.properties.latitude]);
      if (f.properties.end_longitude && f.properties.end_latitude) {
        bounds.extend([f.properties.end_longitude, f.properties.end_latitude]);
      }
    });
    map.fitBounds(bounds, { padding: 80, duration: 1000, maxZoom: 10 });

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Setup TimeSlider scale
    const scaleId = `tornado-seq-${Date.now()}`;
    const firstDate = new Date(minTime).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    // Store animation state
    this._tornadoSeqState = {
      sourceId,
      trackLayerId,
      pointsLayerId,
      connectLayerId,
      scaleId,
      allFeatures,
      sortedFeatures,
      minTime,
      maxTime,
      timeChangeHandler: null
    };

    if (TimeSlider) {
      const added = TimeSlider.addScale({
        id: scaleId,
        label: `Tornado Sequence ${firstDate} (${sortedFeatures.length} paths)`,
        granularity: '1h',  // Tornado sequences typically span hours
        useTimestamps: true,
        currentTime: minTime,
        timeRange: {
          min: minTime,
          max: maxTime,
          available: timestamps
        },
        mapRenderer: 'tornado-sequence'
      });

      if (added) {
        TimeSlider.setActiveScale(scaleId);

        // Enter event animation mode with auto-calculated ~3 second playback
        if (TimeSlider.enterEventAnimation) {
          TimeSlider.enterEventAnimation(minTime, maxTime);
        }

        // Listen for time changes to filter visible features
        this._tornadoSeqState.timeChangeHandler = (time) => {
          this._updateTornadoSequenceForTime(time);
        };
        TimeSlider.addChangeListener(this._tornadoSeqState.timeChangeHandler);
      }
    }

    // Render initial state (first tornado)
    this._updateTornadoSequenceForTime(minTime);

    // Show exit button
    this._showSequenceExitControl();

    console.log(`PointRadiusModel: Displayed tornado sequence with ${sortedFeatures.length} tornadoes, TimeSlider enabled`);
  },

  /**
   * Build all features for tornado sequence (tracks, endpoints, connections).
   * @private
   */
  _buildTornadoSequenceFeatures(sortedFeatures) {
    const features = [];

    sortedFeatures.forEach((f, idx) => {
      const props = f.properties;
      const timestamp = new Date(props.timestamp).getTime();

      // Track line
      if (props.track && props.track.coordinates) {
        features.push({
          type: 'Feature',
          geometry: props.track,
          properties: { ...props, feature_type: 'track', seq_idx: idx, _timestamp: timestamp }
        });
      }

      // Start endpoint
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [props.longitude, props.latitude] },
        properties: { ...props, feature_type: 'start', seq_idx: idx, _timestamp: timestamp }
      });

      // End endpoint
      if (props.end_latitude && props.end_longitude) {
        features.push({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [props.end_longitude, props.end_latitude] },
          properties: { ...props, feature_type: 'end', seq_idx: idx, _timestamp: timestamp }
        });

        // Connection to next tornado (visible when current tornado ends)
        if (idx < sortedFeatures.length - 1) {
          const next = sortedFeatures[idx + 1].properties;
          features.push({
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: [
                [props.end_longitude, props.end_latitude],
                [next.longitude, next.latitude]
              ]
            },
            properties: { feature_type: 'connect', seq_idx: idx, _timestamp: timestamp }
          });
        }
      }
    });

    return features;
  },

  /**
   * Update tornado sequence display for current time.
   * Shows only tornadoes that have occurred by this time.
   * @private
   */
  _updateTornadoSequenceForTime(currentTime) {
    if (!this._tornadoSeqState || !MapAdapter?.map) return;

    const { sourceId, allFeatures } = this._tornadoSeqState;
    const source = MapAdapter.map.getSource(sourceId);
    if (!source) return;

    // Filter features to those at or before current time
    const visibleFeatures = allFeatures.filter(f => {
      const featureTime = f.properties._timestamp;
      return featureTime <= currentTime;
    });

    // Update source data
    source.setData({
      type: 'FeatureCollection',
      features: visibleFeatures
    });
  },

  /**
   * Display static tornado sequence (no animation, single tornado or no timestamps).
   * @private
   */
  _displayTornadoSequenceStatic(sequenceData, sortedFeatures, map, sourceId, trackLayerId, pointsLayerId, connectLayerId) {
    const features = this._buildTornadoSequenceFeatures(sortedFeatures);

    // Add source with all features
    map.addSource(sourceId, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features }
    });

    // Add layers
    map.addLayer({
      id: connectLayerId,
      type: 'line',
      source: sourceId,
      filter: ['==', ['get', 'feature_type'], 'connect'],
      paint: {
        'line-color': '#ffaa00',
        'line-width': 2,
        'line-dasharray': [4, 4],
        'line-opacity': 0.8
      }
    });

    map.addLayer({
      id: trackLayerId,
      type: 'line',
      source: sourceId,
      filter: ['==', ['get', 'feature_type'], 'track'],
      paint: {
        'line-color': ['case',
          ['==', ['get', 'is_seed'], true], '#ff4500',
          '#32cd32'
        ],
        'line-width': 5,
        'line-opacity': 0.9
      }
    });

    map.addLayer({
      id: pointsLayerId,
      type: 'circle',
      source: sourceId,
      filter: ['in', ['get', 'feature_type'], ['literal', ['start', 'end']]],
      paint: {
        'circle-radius': 8,
        'circle-color': ['case',
          ['==', ['get', 'feature_type'], 'start'], '#00ff00',
          '#ff0000'
        ],
        'circle-stroke-color': '#222',
        'circle-stroke-width': 2
      }
    });

    // Fit bounds
    const bounds = new maplibregl.LngLatBounds();
    sortedFeatures.forEach(f => {
      bounds.extend([f.properties.longitude, f.properties.latitude]);
      if (f.properties.end_longitude && f.properties.end_latitude) {
        bounds.extend([f.properties.end_longitude, f.properties.end_latitude]);
      }
    });
    map.fitBounds(bounds, { padding: 80, duration: 1000, maxZoom: 10 });

    // Hide popup
    MapAdapter?.hidePopup?.();
    MapAdapter.popupLocked = false;

    // Store minimal state for cleanup
    this._tornadoSeqState = {
      sourceId,
      trackLayerId,
      pointsLayerId,
      connectLayerId,
      scaleId: null,
      allFeatures: features,
      sortedFeatures,
      minTime: null,
      maxTime: null,
      timeChangeHandler: null
    };

    // Show exit button
    this._showSequenceExitControl();

    console.log(`PointRadiusModel: Displayed static tornado sequence with ${sortedFeatures.length} tornadoes`);
  },

  /**
   * Show exit control for tornado sequence view.
   * Positioned at top center to match other animators (EventAnimator, SequenceAnimator).
   * @private
   */
  _showSequenceExitControl() {
    this._hideSequenceExitControl();

    // Create container at top center (matching EventAnimator/SequenceAnimator style)
    const container = document.createElement('div');
    container.id = 'tornado-sequence-exit-container';
    container.style.cssText = `
      position: fixed;
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      gap: 12px;
      z-index: 1000;
    `;

    const exitBtn = document.createElement('button');
    exitBtn.id = 'sequence-exit-btn';
    exitBtn.textContent = 'Exit Sequence View';
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
    exitBtn.addEventListener('click', () => {
      this._clearTornadoSequence();
      this._hideSequenceExitControl();
    });

    container.appendChild(exitBtn);
    document.body.appendChild(container);
  },

  /**
   * Hide sequence exit control.
   * @private
   */
  _hideSequenceExitControl() {
    const container = document.getElementById('tornado-sequence-exit-container');
    if (container) container.remove();
    // Also check for old button ID for backwards compatibility
    const existingBtn = document.getElementById('sequence-exit-btn');
    if (existingBtn) existingBtn.remove();
  },

  /**
   * Clear tornado sequence display.
   * @private
   */
  _clearTornadoSequence() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const layers = ['tornado-sequence-tracks', 'tornado-sequence-points', 'tornado-sequence-connect'];

    layers.forEach(id => {
      if (map.getLayer(id)) map.removeLayer(id);
    });

    if (map.getSource('tornado-sequence')) {
      map.removeSource('tornado-sequence');
    }

    console.log('PointRadiusModel: Cleared tornado sequence');
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
        lines.push(`<a href="#" class="view-sequence-link" data-sequence="${props.sequence_id}" data-eventid="${props.event_id}" style="color:#81c784;text-decoration:underline;cursor:pointer">View sequence</a>`);
      } else if (props.mainshock_id) {
        lines.push(`<span style="color:#ffb74d">Aftershock of larger event</span>`);
        if (props.sequence_id) {
          lines.push(`<a href="#" class="view-sequence-link" data-sequence="${props.sequence_id}" data-eventid="${props.event_id}" style="color:#81c784;text-decoration:underline;cursor:pointer">View sequence</a>`);
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
    } else if (eventType === 'wildfire') {
      // Wildfire popup
      lines.push('<strong style="color:#ff6600">Wildfire</strong>');

      // Size info
      if (props.area_km2 != null) {
        const areaKm2 = props.area_km2;
        const acres = props.burned_acres || (areaKm2 * 247.105);
        lines.push(`Area: ${areaKm2.toLocaleString(undefined, {maximumFractionDigits: 0})} km2 (${Math.round(acres).toLocaleString()} acres)`);
      }

      // Duration
      if (props.duration_days != null && props.duration_days > 0) {
        lines.push(`Duration: ${props.duration_days} days`);
      }

      // Date
      if (props.timestamp) {
        const date = new Date(props.timestamp);
        lines.push(`Ignition: ${date.toLocaleDateString()}`);
      } else if (props.year) {
        lines.push(`Year: ${props.year}`);
      }

      // Land cover / vegetation type
      if (props.land_cover) {
        lines.push(`Vegetation: ${props.land_cover}`);
      }

      // Location
      if (props.latitude != null && props.longitude != null) {
        lines.push(`Location: ${props.latitude.toFixed(3)}, ${props.longitude.toFixed(3)}`);
      }

      // View fire animation link
      if (props.event_id && props.duration_days > 1) {
        lines.push(`<a href="#" class="view-fire-link" data-event="${props.event_id}" data-duration="${props.duration_days}" data-timestamp="${props.timestamp}" data-year="${props.year || ''}" data-lat="${props.latitude || ''}" data-lon="${props.longitude || ''}" style="color:#ff9800;text-decoration:underline;cursor:pointer">View fire progression</a>`);
      }
    } else if (eventType === 'tornado') {
      // Tornado popup
      const scale = props.tornado_scale || 'Unknown';
      // Color the header by scale
      const scaleColors = {
        'EF0': '#98fb98', 'F0': '#98fb98',
        'EF1': '#32cd32', 'F1': '#32cd32',
        'EF2': '#ffd700', 'F2': '#ffd700',
        'EF3': '#ff8c00', 'F3': '#ff8c00',
        'EF4': '#ff4500', 'F4': '#ff4500',
        'EF5': '#8b0000', 'F5': '#8b0000'
      };
      const scaleColor = scaleColors[scale] || '#ffffff';
      lines.push(`<strong style="color:${scaleColor}">${scale} Tornado</strong>`);

      // Scale description
      const scaleDesc = {
        'EF0': 'Light damage', 'F0': 'Light damage',
        'EF1': 'Moderate damage', 'F1': 'Moderate damage',
        'EF2': 'Significant damage', 'F2': 'Significant damage',
        'EF3': 'Severe damage', 'F3': 'Severe damage',
        'EF4': 'Devastating damage', 'F4': 'Devastating damage',
        'EF5': 'Incredible damage', 'F5': 'Incredible damage'
      };
      if (scaleDesc[scale]) {
        lines.push(`<span style="color:#aaa">${scaleDesc[scale]}</span>`);
      }

      // Track dimensions
      if (props.path_length_miles != null && props.path_length_miles > 0) {
        lines.push(`Path length: ${props.path_length_miles.toFixed(1)} miles`);
      }
      if (props.path_width_yards != null && props.path_width_yards > 0) {
        lines.push(`Path width: ${props.path_width_yards} yards`);
      }

      // Date/time
      if (props.timestamp) {
        const date = new Date(props.timestamp);
        lines.push(date.toLocaleString());
      } else if (props.year) {
        lines.push(`Year: ${props.year}`);
      }

      // Casualties
      if (props.deaths_direct != null && props.deaths_direct > 0) {
        lines.push(`<span style="color:#ef5350">Deaths: ${props.deaths_direct}</span>`);
      }
      if (props.injuries_direct != null && props.injuries_direct > 0) {
        lines.push(`Injuries: ${props.injuries_direct}`);
      }

      // Property damage
      if (props.damage_property != null && props.damage_property > 0) {
        const damage = props.damage_property >= 1e9
          ? `$${(props.damage_property / 1e9).toFixed(1)}B`
          : props.damage_property >= 1e6
          ? `$${(props.damage_property / 1e6).toFixed(1)}M`
          : `$${props.damage_property.toLocaleString()}`;
        lines.push(`Property damage: ${damage}`);
      }

      // View track link - only if end coordinates available
      if (props.event_id && (props.end_latitude != null || props.end_lat != null)) {
        lines.push(`<a href="#" class="view-tornado-track-link" data-event="${props.event_id}" style="color:#32cd32;text-decoration:underline;cursor:pointer">View tornado track</a>`);
      }

      // Animate tornado path(s) - always available
      // Shows sequence if multiple linked tornadoes, single path otherwise
      if (props.event_id && (props.end_latitude != null || props.end_lat != null)) {
        const seqCount = props.sequence_count || 1;
        const linkText = seqCount > 1
          ? `Animate tornado sequence (${seqCount} paths)`
          : 'Animate tornado path';
        lines.push(`<a href="#" class="view-tornado-sequence-link" data-event="${props.event_id}" style="color:#ffa500;text-decoration:underline;cursor:pointer">${linkText}</a>`);
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
