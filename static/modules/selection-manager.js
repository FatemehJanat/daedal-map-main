/**
 * Selection Manager - Handles disambiguation selection mode.
 * Similar to Windows Snipping Tool: freezes map, highlights candidates,
 * click to select or click elsewhere to exit.
 */

import { CONFIG } from './config.js';

// Dependencies set via setDependencies to avoid circular imports
let MapAdapter = null;
let ChatManager = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  ChatManager = deps.ChatManager;
}

// ============================================================================
// SELECTION MANAGER - Disambiguation selection mode
// ============================================================================

export const SelectionManager = {
  active: false,
  options: [],           // List of disambiguation options
  originalQuery: '',     // Original query to retry with selected location
  queryTerm: '',         // The ambiguous term
  onSelect: null,        // Callback when selection is made
  hoveredOptionIndex: null,

  /**
   * Enter selection mode - freeze map and show candidate highlights
   * @param {Object} response - The disambiguate response from backend
   * @param {Function} onSelectCallback - Called with selected option
   */
  async enter(response, onSelectCallback) {
    if (this.active) {
      this.exit(false);
    }

    this.active = true;
    this.options = response.options || [];
    this.originalQuery = response.original_query || '';
    this.queryTerm = response.query_term || '';
    this.onSelect = onSelectCallback;
    this.hoveredOptionIndex = null;

    console.log('SelectionManager: Entering selection mode with', this.options.length, 'options');

    // Freeze the map (disable all interactions)
    this.freezeMap();

    // Dim the existing map layers
    this.dimMapLayers();

    // Fetch and display candidate geometries
    await this.loadCandidateGeometries();

    // Setup click handlers for selection
    this.setupClickHandlers();

    // Show instruction overlay
    this.showOverlay();
  },

  /**
   * Exit selection mode - restore map and clean up
   * @param {boolean} cancelled - True if user clicked away (not selected)
   */
  exit(cancelled = false) {
    if (!this.active) return;

    console.log('SelectionManager: Exiting selection mode, cancelled:', cancelled);

    this.active = false;

    // Unfreeze the map
    this.unfreezeMap();

    // Restore map layer opacity
    this.restoreMapLayers();

    // Remove selection layers
    this.removeSelectionLayers();

    // Remove click handlers
    this.removeClickHandlers();

    // Hide overlay
    this.hideOverlay();

    // If cancelled, show retry message in chat
    if (cancelled && ChatManager) {
      ChatManager.addMessage(
        'Selection cancelled. Would you like to try again with a more specific location?',
        'assistant'
      );
    }

    // Clear state
    this.options = [];
    this.originalQuery = '';
    this.queryTerm = '';
    this.onSelect = null;
  },

  /**
   * Freeze map - disable all pan/zoom interactions
   */
  freezeMap() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    map.scrollZoom.disable();
    map.boxZoom.disable();
    map.dragRotate.disable();
    map.dragPan.disable();
    map.keyboard.disable();
    map.doubleClickZoom.disable();
    map.touchZoomRotate.disable();

    // Add visual indicator class
    map.getContainer().classList.add('selection-mode');
  },

  /**
   * Unfreeze map - restore all interactions
   */
  unfreezeMap() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    map.scrollZoom.enable();
    map.boxZoom.enable();
    map.dragRotate.enable();
    map.dragPan.enable();
    map.keyboard.enable();
    // Note: doubleClickZoom is intentionally left disabled (per map-adapter init)
    map.touchZoomRotate.enable();

    // Remove visual indicator class
    map.getContainer().classList.remove('selection-mode');
  },

  /**
   * Dim existing map layers to make selection stand out
   */
  dimMapLayers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const fillLayer = CONFIG.layers.fill;

    if (map.getLayer(fillLayer)) {
      // Store original opacity and reduce it
      map.setPaintProperty(fillLayer, 'fill-opacity', 0.15);
    }
  },

  /**
   * Restore map layer opacity
   */
  restoreMapLayers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const fillLayer = CONFIG.layers.fill;

    if (map.getLayer(fillLayer)) {
      // Restore to original opacity expression
      map.setPaintProperty(fillLayer, 'fill-opacity', [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        CONFIG.colors.fillHoverOpacity,
        CONFIG.colors.fillOpacity
      ]);
    }
  },

  /**
   * Fetch geometry for candidate locations and add to map
   */
  async loadCandidateGeometries() {
    if (!MapAdapter?.map || this.options.length === 0) return;

    const map = MapAdapter.map;
    const locIds = this.options.map(opt => opt.loc_id).filter(Boolean);

    if (locIds.length === 0) {
      console.warn('SelectionManager: No loc_ids to load');
      return;
    }

    try {
      // Fetch geometries for the candidate loc_ids
      const response = await fetch('/geometry/selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ loc_ids: locIds })
      });

      if (!response.ok) {
        throw new Error('Failed to fetch selection geometries');
      }

      const geojson = await response.json();

      if (!geojson.features || geojson.features.length === 0) {
        console.warn('SelectionManager: No geometries returned');
        return;
      }

      // Add feature IDs for hover state
      geojson.features.forEach((feature, index) => {
        feature.id = index;
        // Add option index for click identification
        const locId = feature.properties?.loc_id;
        const optIndex = this.options.findIndex(o => o.loc_id === locId);
        feature.properties._optionIndex = optIndex;
      });

      // Add source for selection layer
      if (map.getSource(CONFIG.layers.selectionSource)) {
        map.getSource(CONFIG.layers.selectionSource).setData(geojson);
      } else {
        map.addSource(CONFIG.layers.selectionSource, {
          type: 'geojson',
          data: geojson,
          generateId: true
        });
      }

      // Add fill layer
      if (!map.getLayer(CONFIG.layers.selectionFill)) {
        map.addLayer({
          id: CONFIG.layers.selectionFill,
          type: 'fill',
          source: CONFIG.layers.selectionSource,
          paint: {
            'fill-color': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              CONFIG.selectionColors.hoverFill,
              CONFIG.selectionColors.fill
            ],
            'fill-opacity': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              CONFIG.selectionColors.hoverOpacity,
              CONFIG.selectionColors.fillOpacity
            ]
          }
        });
      }

      // Add stroke layer
      if (!map.getLayer(CONFIG.layers.selectionStroke)) {
        map.addLayer({
          id: CONFIG.layers.selectionStroke,
          type: 'line',
          source: CONFIG.layers.selectionSource,
          paint: {
            'line-color': CONFIG.selectionColors.stroke,
            'line-width': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              CONFIG.selectionColors.hoverStrokeWidth,
              CONFIG.selectionColors.strokeWidth
            ]
          }
        });
      }

      console.log('SelectionManager: Loaded', geojson.features.length, 'candidate geometries');

    } catch (error) {
      console.error('SelectionManager: Error loading geometries:', error);
    }
  },

  /**
   * Remove selection layers from map
   */
  removeSelectionLayers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;

    if (map.getLayer(CONFIG.layers.selectionFill)) {
      map.removeLayer(CONFIG.layers.selectionFill);
    }
    if (map.getLayer(CONFIG.layers.selectionStroke)) {
      map.removeLayer(CONFIG.layers.selectionStroke);
    }
    if (map.getSource(CONFIG.layers.selectionSource)) {
      map.removeSource(CONFIG.layers.selectionSource);
    }
  },

  /**
   * Setup click and hover handlers for selection
   */
  setupClickHandlers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const selectionFill = CONFIG.layers.selectionFill;

    // Bind handlers so we can remove them later
    this._handleSelectionClick = this.handleSelectionClick.bind(this);
    this._handleMapClick = this.handleMapClick.bind(this);
    this._handleSelectionHover = this.handleSelectionHover.bind(this);
    this._handleSelectionLeave = this.handleSelectionLeave.bind(this);

    // Click on selection feature - select it
    map.on('click', selectionFill, this._handleSelectionClick);

    // Click anywhere else - cancel selection
    map.on('click', this._handleMapClick);

    // Hover handlers for visual feedback
    map.on('mousemove', selectionFill, this._handleSelectionHover);
    map.on('mouseleave', selectionFill, this._handleSelectionLeave);
  },

  /**
   * Remove click handlers
   */
  removeClickHandlers() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    const selectionFill = CONFIG.layers.selectionFill;

    if (this._handleSelectionClick) {
      map.off('click', selectionFill, this._handleSelectionClick);
    }
    if (this._handleMapClick) {
      map.off('click', this._handleMapClick);
    }
    if (this._handleSelectionHover) {
      map.off('mousemove', selectionFill, this._handleSelectionHover);
    }
    if (this._handleSelectionLeave) {
      map.off('mouseleave', selectionFill, this._handleSelectionLeave);
    }

    this._handleSelectionClick = null;
    this._handleMapClick = null;
    this._handleSelectionHover = null;
    this._handleSelectionLeave = null;
  },

  /**
   * Handle click on a selection candidate
   */
  handleSelectionClick(e) {
    e.preventDefault?.();

    if (e.features && e.features.length > 0) {
      const feature = e.features[0];
      const optionIndex = feature.properties._optionIndex;

      if (optionIndex >= 0 && optionIndex < this.options.length) {
        const selectedOption = this.options[optionIndex];
        console.log('SelectionManager: Selected option', selectedOption);

        // Call the callback with selected option
        if (this.onSelect) {
          this.onSelect(selectedOption, this.originalQuery);
        }

        // Exit selection mode (not cancelled)
        this.exit(false);
      }
    }
  },

  /**
   * Handle click on map (not on selection feature) - cancel
   */
  handleMapClick(e) {
    // Check if click was on a selection feature (that handler fires first)
    const features = MapAdapter.map.queryRenderedFeatures(e.point, {
      layers: [CONFIG.layers.selectionFill]
    });

    if (features.length === 0) {
      // Clicked outside selection features - cancel
      this.exit(true);
    }
  },

  /**
   * Handle hover on selection feature
   */
  handleSelectionHover(e) {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    map.getCanvas().style.cursor = 'pointer';

    if (e.features && e.features.length > 0) {
      const feature = e.features[0];

      // Clear previous hover state
      if (this.hoveredOptionIndex !== null) {
        map.setFeatureState(
          { source: CONFIG.layers.selectionSource, id: this.hoveredOptionIndex },
          { hover: false }
        );
      }

      // Set new hover state
      this.hoveredOptionIndex = feature.id;
      map.setFeatureState(
        { source: CONFIG.layers.selectionSource, id: this.hoveredOptionIndex },
        { hover: true }
      );
    }
  },

  /**
   * Handle mouse leave from selection features
   */
  handleSelectionLeave() {
    if (!MapAdapter?.map) return;

    const map = MapAdapter.map;
    map.getCanvas().style.cursor = '';

    if (this.hoveredOptionIndex !== null) {
      map.setFeatureState(
        { source: CONFIG.layers.selectionSource, id: this.hoveredOptionIndex },
        { hover: false }
      );
      this.hoveredOptionIndex = null;
    }
  },

  /**
   * Show instruction overlay
   */
  showOverlay() {
    let overlay = document.getElementById('selectionOverlay');

    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'selectionOverlay';
      overlay.className = 'selection-overlay';
      document.body.appendChild(overlay);
    }

    const optionsList = this.options.map((opt, i) => {
      const name = opt.matched_term || 'Unknown';
      const country = opt.country_name || opt.iso3 || '';
      return `<div class="selection-option-label">${i + 1}. ${name} (${country})</div>`;
    }).join('');

    overlay.innerHTML = `
      <div class="selection-overlay-content">
        <div class="selection-overlay-title">Select a location</div>
        <div class="selection-overlay-subtitle">Multiple matches for "${this.queryTerm}"</div>
        <div class="selection-options-list">${optionsList}</div>
        <div class="selection-overlay-hint">Click a highlighted area to select, or click elsewhere to cancel</div>
      </div>
    `;

    overlay.classList.add('visible');
  },

  /**
   * Hide instruction overlay
   */
  hideOverlay() {
    const overlay = document.getElementById('selectionOverlay');
    if (overlay) {
      overlay.classList.remove('visible');
    }
  }
};

// Make SelectionManager available globally for debugging
if (typeof window !== 'undefined') {
  window.SelectionManager = SelectionManager;
}
