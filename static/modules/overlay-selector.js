/**
 * Overlay Selector - UI component for toggling data overlays.
 * Displays in top right, below zoom level and breadcrumbs.
 * Supports hierarchical categories with group toggle.
 *
 * Categories are loaded dynamically from /api/catalog/overlays.
 */

import { CONFIG } from './config.js';
import { fetchMsgpack } from './utils/fetch.js';
import { getCurrentProfile } from './auth.js';

// localStorage key prefix for persisting lane-specific overlay selections
const STORAGE_KEY_PREFIX = 'countymap_activeOverlays';

// Model mapping based on data_type
const DATA_TYPE_TO_MODEL = {
  'events': 'point-radius',
  'metrics': 'choropleth',
  'gridded': 'weather-grid',
  'geometry': 'polygon'
};

// Icon mapping for overlay types
const OVERLAY_ICONS = {
  'demographics': 'D',
  'disasters': '!',
  'climate': 'C',
  'usa': 'U',
  'earthquakes': 'E',
  'volcanoes': 'V',
  'hurricanes': 'H',
  'tornadoes': 'R',
  'tsunamis': 'T',
  'wildfires': 'W',
  'floods': 'F',
  'cyclones': 'C',
  'landslides': 'L',
  'drought': 'D',
  'risk': 'R',
  'storms': 'S',
  'fema': 'F',
  'desinventar': 'I',
  'reliefweb': 'R',
  'event_areas': 'A',
  'aurora': 'A',
  'nws_alerts': '!'
};

// Special model overrides (some overlays need specific models)
const MODEL_OVERRIDES = {
  'hurricanes': 'track',
  'drought': 'polygon'
};

const OPS_FEED_TO_OVERLAY_IDS = {
  earthquakes: ['earthquakes'],
  volcanoes: ['volcanoes'],
  hurricanes_ibtracs_nrt: ['hurricanes'],
  tsunamis: ['tsunamis'],
  wildfires_us_nifc: ['wildfires'],
  weather: [
    'temperature',
    'humidity',
    'snow-depth',
    'precipitation',
    'cloud-cover',
    'pressure',
    'solar-radiation',
    'soil-temp',
    'soil-moisture'
  ]
};

// Categories built dynamically from catalog
let ALL_CATEGORIES = [];
let CATEGORIES = [];
let OVERLAYS = [];

export function getOpsOverlayIdsForFeeds(feeds = []) {
  const overlayIds = new Set();
  for (const feed of feeds || []) {
    const ids = OPS_FEED_TO_OVERLAY_IDS[String(feed || '').trim()] || [];
    for (const overlayId of ids) {
      overlayIds.add(overlayId);
    }
  }
  return Array.from(overlayIds);
}

export function getAllOpsManagedOverlayIds() {
  const overlayIds = new Set();
  for (const ids of Object.values(OPS_FEED_TO_OVERLAY_IDS)) {
    for (const overlayId of ids || []) {
      overlayIds.add(overlayId);
    }
  }
  return Array.from(overlayIds);
}

/**
 * Build CATEGORIES from overlay_tree fetched from API.
 * @param {Object} overlayTree - The overlay_tree from catalog
 */
function buildCategoriesFromTree(overlayTree) {
  const categories = [];
  const metricOverlays = [];

  for (const [categoryId, categoryData] of Object.entries(overlayTree)) {
    const icon = OVERLAY_ICONS[categoryId] || categoryId[0].toUpperCase();

    // Check if this is a category with children or a standalone overlay
    if (categoryData.children) {
      // Category with sub-overlays (like disasters)
      const overlays = [];
      let allChildrenAreChoropleths = true;

      for (const [overlayId, overlayData] of Object.entries(categoryData.children)) {
        // Get data_type from first source
        const firstSource = overlayData.sources?.[0];
        const dataType = firstSource?.data_type || 'events';
        const model = MODEL_OVERRIDES[overlayId] || DATA_TYPE_TO_MODEL[dataType] || 'point-radius';
        if (model !== 'choropleth') {
          allChildrenAreChoropleths = false;
        }

        overlays.push({
          id: overlayId,
          label: overlayData.label || overlayId.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
          description: `${overlayData.sources?.length || 0} source(s)`,
          default: false,
          locked: false,
          model: model,
          icon: OVERLAY_ICONS[overlayId] || overlayId[0].toUpperCase(),
          hasYearFilter: dataType === 'events',
          sources: overlayData.sources || []
        });
      }

      if (allChildrenAreChoropleths && overlays.length) {
        metricOverlays.push(...overlays);
        continue;
      }

      categories.push({
        id: categoryId,
        label: categoryData.label || categoryId.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
        icon: icon,
        isCategory: true,
        expanded: categoryId === 'disasters',  // Disasters expanded by default
        overlays: overlays
      });
    } else if (categoryData.sources) {
      // Standalone overlay (like demographics)
      const firstSource = categoryData.sources?.[0];
      const dataType = firstSource?.data_type || 'metrics';
      const model = DATA_TYPE_TO_MODEL[dataType] || 'choropleth';

      const overlay = {
        id: categoryId,
        label: categoryData.label || categoryId.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
        description: `${categoryData.sources?.length || 0} source(s)`,
        default: false,
        locked: false,
        model: model,
        icon: OVERLAY_ICONS[categoryId] || categoryId[0].toUpperCase(),
        hasYearFilter: dataType === 'events',
        sources: categoryData.sources || []
      };

      if (model === 'choropleth') {
        metricOverlays.push(overlay);
        continue;
      }

      categories.push({
        id: categoryId,
        label: categoryData.label || categoryId.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
        icon: icon,
        isCategory: false,
        overlay
      });
    }
  }

  // Add or extend climate overlays. Some catalogs now provide a Climate
  // category, so merge instead of blindly appending a duplicate section.
  const hardcodedClimateOverlays = [
    { id: 'temperature', label: 'Temperature', description: 'Global temperature', default: false, locked: false, model: 'weather-grid', icon: '*', hasYearFilter: true, variable: 'temp_c' },
    { id: 'humidity', label: 'Humidity', description: 'Relative humidity', default: false, locked: false, model: 'weather-grid', icon: '%', hasYearFilter: true, variable: 'humidity' },
    { id: 'snow-depth', label: 'Snow Depth', description: 'Snow depth', default: false, locked: false, model: 'weather-grid', icon: '#', hasYearFilter: true, variable: 'snow_depth_m' },
    { id: 'precipitation', label: 'Precipitation', description: 'Rainfall', default: false, locked: false, model: 'weather-grid', icon: ',', hasYearFilter: true, variable: 'precipitation_mm' },
    { id: 'cloud-cover', label: 'Cloud Cover', description: 'Cloud coverage', default: false, locked: false, model: 'weather-grid', icon: 'o', hasYearFilter: true, variable: 'cloud_cover_pct' },
    { id: 'pressure', label: 'Pressure', description: 'Sea level pressure', default: false, locked: false, model: 'weather-grid', icon: 'P', hasYearFilter: true, variable: 'pressure_hpa' },
    { id: 'solar-radiation', label: 'Solar Radiation', description: 'Surface solar radiation', default: false, locked: false, model: 'weather-grid', icon: 'S', hasYearFilter: true, variable: 'solar_radiation' },
    { id: 'soil-temp', label: 'Soil Temperature', description: 'Surface soil temp', default: false, locked: false, model: 'weather-grid', icon: 'G', hasYearFilter: true, variable: 'soil_temp_c' },
    { id: 'soil-moisture', label: 'Soil Moisture', description: 'Surface soil moisture', default: false, locked: false, model: 'weather-grid', icon: 'M', hasYearFilter: true, variable: 'soil_moisture' },
    { id: 'aurora', label: 'Aurora', description: 'Live aurora forecast', default: false, locked: false, model: 'aurora', icon: 'A', hasYearFilter: false, live: true, alwaysVisible: true }
  ];
  const climateCategory = categories.find((cat) => cat.id === 'climate' && cat.isCategory);
  if (climateCategory) {
    const existingOverlayIds = new Set((climateCategory.overlays || []).map((overlay) => overlay.id));
    for (const overlay of hardcodedClimateOverlays) {
      if (!existingOverlayIds.has(overlay.id)) {
        climateCategory.overlays.push(overlay);
      }
    }
  } else {
    categories.push({
      id: 'climate',
      label: 'Climate',
      icon: 'C',
      isCategory: true,
      expanded: false,
      overlays: hardcodedClimateOverlays
    });
  }

  // Metrics overlays - the shared choropleth (global.csv country fills, etc.).
  // The toggle controls choropleth visibility, so dense global layers like the
  // currency choropleth can be hidden to see point/area feeds underneath.
  metricOverlays.push({
    id: 'currency',
    label: 'Currency',
    description: 'Global currency choropleth',
    default: true,
    locked: false,
    model: 'choropleth',
    icon: '$',
    hasYearFilter: false
  });

  if (metricOverlays.length) {
    categories.push({
      id: 'metrics',
      label: 'Metrics',
      icon: 'M',
      isCategory: true,
      expanded: false,
      alwaysVisible: true,
      overlays: metricOverlays
    });
  }

  // USA overlays - operational overlays tied to US-only alert/coverage areas.
  // NOTE: the announcement ticker is intentionally NOT here - it is a display
  // surface (chrome) that aggregates many feeds, not a single-feed overlay.
  categories.push({
    id: 'usa',
    label: 'USA',
    icon: 'U',
    isCategory: true,
    expanded: false,
    overlays: [
      { id: 'nws_alerts', label: 'US Weather Alerts', description: 'Live NWS warnings', default: false, locked: false, model: 'nws_alerts', icon: '!', hasYearFilter: false, live: true, alwaysVisible: true }
    ]
  });

  return dedupeCategories(categories);
}

function dedupeCategories(categories) {
  const merged = new Map();

  for (const category of categories || []) {
    if (!category || !category.id) continue;

    if (!merged.has(category.id)) {
      if (category.isCategory) {
        merged.set(category.id, {
          ...category,
          overlays: [...(category.overlays || [])]
        });
      } else if (category.overlay) {
        merged.set(category.id, {
          ...category,
          overlay: { ...category.overlay }
        });
      } else {
        merged.set(category.id, { ...category });
      }
      continue;
    }

    const existing = merged.get(category.id);
    if (existing.isCategory && category.isCategory) {
      const seenOverlayIds = new Set((existing.overlays || []).map((overlay) => overlay.id));
      for (const overlay of category.overlays || []) {
        if (!seenOverlayIds.has(overlay.id)) {
          existing.overlays.push(overlay);
          seenOverlayIds.add(overlay.id);
        }
      }
      existing.label = existing.label || category.label;
      existing.icon = existing.icon || category.icon;
      existing.expanded = existing.expanded || category.expanded;
      continue;
    }

    if (!existing.isCategory && !category.isCategory && category.overlay && !existing.overlay) {
      existing.overlay = { ...category.overlay };
    }
  }

  return Array.from(merged.values());
}

/**
 * Flatten overlays for lookup.
 */
function getAllOverlaysFromCategories(categories) {
  const overlays = [];
  for (const cat of categories) {
    if (cat.isCategory) {
      overlays.push(...cat.overlays);
    } else if (cat.overlay) {
      overlays.push(cat.overlay);
    }
  }
  return overlays;
}

function getCurrentOverlayLaneMode() {
  if (document.body.classList.contains('chat-mode-ops')) return 'ops';
  if (document.body.classList.contains('chat-mode-research')) return 'research';
  return 'explore';
}

function getAllowedOpsOverlayIds() {
  const profile = getCurrentProfile();
  const opsFeeds = Array.isArray(profile?.ops_feeds) ? profile.ops_feeds : [];
  const allowed = new Set();
  for (const feed of opsFeeds) {
    const overlayIds = OPS_FEED_TO_OVERLAY_IDS[feed] || [];
    for (const overlayId of overlayIds) {
      allowed.add(overlayId);
    }
  }
  return allowed;
}

function cloneVisibleCategories(categories) {
  return categories.map((cat) => {
    if (cat.isCategory) {
      return {
        ...cat,
        overlays: [...cat.overlays]
      };
    }
    if (cat.overlay) {
      return {
        ...cat,
        overlay: { ...cat.overlay }
      };
    }
    return { ...cat };
  });
}

function filterCategoriesForCurrentMode(categories) {
  const cloned = cloneVisibleCategories(categories);
  if (getCurrentOverlayLaneMode() !== 'ops') {
    return cloned;
  }

  const allowedOverlayIds = getAllowedOpsOverlayIds();

  const visibleCategories = [];
  for (const category of cloned) {
    // alwaysVisible categories show in every mode, independent of the Ops
    // watch's allowed feeds.
    if (category.alwaysVisible) {
      visibleCategories.push(category);
      continue;
    }

    if (category.isCategory) {
      const overlays = category.overlays.filter((overlay) => overlay.alwaysVisible || allowedOverlayIds.has(overlay.id));
      if (overlays.length) {
        visibleCategories.push({
          ...category,
          overlays
        });
      }
      continue;
    }

    if (category.overlay && allowedOverlayIds.has(category.overlay.id)) {
      visibleCategories.push(category);
    }
  }

  return visibleCategories;
}

// Dependencies (set via setDependencies)
let MapAdapter = null;
let ModelRegistry = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  ModelRegistry = deps.ModelRegistry;
}

export const OverlaySelector = {
  // State
  activeOverlays: new Set(),
  laneOverlayStates: new Map(),
  currentLaneMode: 'explore',
  expanded: true,  // Default expanded
  categoryExpanded: {},  // Track which categories are expanded
  initialized: false,

  // DOM elements
  container: null,
  header: null,
  list: null,

  // Change listeners
  listeners: [],

  /**
   * Initialize the overlay selector UI.
   * Fetches categories from API and builds UI.
   */
  async init(options = {}) {
    const restoreState = options.restoreState !== false;
    this.currentLaneMode = getCurrentOverlayLaneMode();
    // Find container first
    this.container = document.getElementById('overlaySelector');
    if (!this.container) {
      console.warn('OverlaySelector: #overlaySelector not found in DOM');
      return;
    }

    // Show loading state
    this.container.innerHTML = '<div class="overlay-header"><span class="overlay-title">Loading overlays...</span></div>';

    try {
      // Fetch overlay tree from API
      const response = await fetchMsgpack('/api/catalog/overlays');
      const overlayTree = response.overlay_tree || {};

      // Build categories from tree
      ALL_CATEGORIES = buildCategoriesFromTree(overlayTree);
      CATEGORIES = filterCategoriesForCurrentMode(ALL_CATEGORIES);
      OVERLAYS = getAllOverlaysFromCategories(CATEGORIES);

      console.log('OverlaySelector: Loaded', CATEGORIES.length, 'categories,', OVERLAYS.length, 'overlays from catalog');
    } catch (err) {
      console.error('OverlaySelector: Failed to load from API, using fallback', err);
      // Fallback to minimal hardcoded categories
      ALL_CATEGORIES = [
        {
          id: 'metrics',
          label: 'Metrics',
          icon: 'M',
          isCategory: true,
          expanded: false,
          alwaysVisible: true,
          overlays: [
            { id: 'demographics', label: 'Demographics', description: 'Choropleth data', default: false, locked: false, model: 'choropleth', icon: 'D', hasYearFilter: false },
            { id: 'currency', label: 'Currency', description: 'Global currency choropleth', default: true, locked: false, model: 'choropleth', icon: '$', hasYearFilter: false }
          ]
        },
        {
          id: 'disasters',
          label: 'Disasters',
          icon: '!',
          isCategory: true,
          expanded: true,
          overlays: [
            { id: 'earthquakes', label: 'Earthquakes', description: 'Seismic events', default: false, locked: false, model: 'point-radius', icon: 'E', hasYearFilter: true },
            { id: 'hurricanes', label: 'Hurricanes', description: 'Storm tracks', default: false, locked: false, model: 'track', icon: 'H', hasYearFilter: true },
            { id: 'wildfires', label: 'Wildfires', description: 'Fire events', default: false, locked: false, model: 'point-radius', icon: 'W', hasYearFilter: true }
          ]
        }
      ];
      CATEGORIES = filterCategoriesForCurrentMode(ALL_CATEGORIES);
      OVERLAYS = getAllOverlaysFromCategories(CATEGORIES);
    }

    // Try to restore from localStorage, fall back to defaults
    if (restoreState && !this._restoreState(this.currentLaneMode)) {
      // Set default overlays if no saved state
      for (const overlay of OVERLAYS) {
        if (overlay.default) {
          this.activeOverlays.add(overlay.id);
        }
      }
    } else if (!restoreState) {
      this.activeOverlays.clear();
    }
    this._rememberCurrentLaneState();

    // Initialize category expanded state
    for (const cat of CATEGORIES) {
      if (cat.isCategory) {
        this.categoryExpanded[cat.id] = cat.expanded || false;
      }
    }

    // Build UI
    this._buildUI();

    // Wire up events
    this._setupEvents();

    this.initialized = true;
    console.log('OverlaySelector initialized with:', Array.from(this.activeOverlays));
  },

  /**
   * Build the overlay selector UI elements.
   * @private
   */
  _buildUI() {
    this.container.innerHTML = '';

    // Header (clickable to expand/collapse)
    this.header = document.createElement('div');
    this.header.className = 'overlay-header';
    const modeLabel = this.currentLaneMode === 'ops'
      ? 'Ops Overlays'
      : this.currentLaneMode === 'research'
        ? 'Research Overlays'
        : 'Explore Overlays';
    this.header.innerHTML = `
      <span class="overlay-title">${modeLabel}</span>
      <span class="overlay-toggle">${this.expanded ? '-' : '+'}</span>
    `;
    this.container.appendChild(this.header);

    // List container
    this.list = document.createElement('div');
    this.list.className = 'overlay-list';
    this.list.style.display = this.expanded ? 'block' : 'none';

    // Build categories and overlays
    for (const cat of CATEGORIES) {
      if (cat.isCategory) {
        // Category with sub-items
        const categoryEl = this._createCategory(cat);
        this.list.appendChild(categoryEl);
      } else if (cat.overlay) {
        // Standalone overlay (like Demographics)
        const item = this._createOverlayItem(cat.overlay, false);
        this.list.appendChild(item);
      }
    }

    this.container.appendChild(this.list);
  },

  /**
   * Create a category element with sub-overlays.
   * @private
   */
  _createCategory(category) {
    const wrapper = document.createElement('div');
    wrapper.className = 'overlay-category';
    wrapper.dataset.categoryId = category.id;

    // Check if any overlays in this category are active
    const activeCount = category.overlays.filter(o => this.activeOverlays.has(o.id)).length;
    const allActive = activeCount === category.overlays.length;
    const someActive = activeCount > 0 && !allActive;

    // Category header
    const header = document.createElement('div');
    header.className = 'overlay-category-header';
    header.innerHTML = `
      <input type="checkbox"
             class="category-checkbox"
             data-category-id="${category.id}"
             ${allActive ? 'checked' : ''}
             ${someActive ? 'data-indeterminate="true"' : ''}>
      <span class="overlay-icon">${category.icon}</span>
      <span class="overlay-label">${category.label}</span>
      <span class="category-toggle">${this.categoryExpanded[category.id] ? '-' : '+'}</span>
    `;
    wrapper.appendChild(header);

    // Set indeterminate state after adding to DOM
    setTimeout(() => {
      const checkbox = header.querySelector('.category-checkbox');
      if (checkbox && someActive) {
        checkbox.indeterminate = true;
      }
    }, 0);

    // Sub-overlay list
    const subList = document.createElement('div');
    subList.className = 'overlay-sub-list';
    subList.style.display = this.categoryExpanded[category.id] ? 'block' : 'none';

    for (const overlay of category.overlays) {
      const item = this._createOverlayItem(overlay, true);
      subList.appendChild(item);
    }

    wrapper.appendChild(subList);
    return wrapper;
  },

  /**
   * Create a single overlay item element.
   * @private
   */
  _createOverlayItem(overlay, isSubItem = false) {
    const item = document.createElement('label');
    item.className = 'overlay-item' + (isSubItem ? ' overlay-sub-item' : '');
    item.dataset.overlayId = overlay.id;

    const isChecked = this.activeOverlays.has(overlay.id);
    const isLocked = overlay.locked;
    const isPlaceholder = overlay.placeholder;

    item.innerHTML = `
      <input type="checkbox"
             ${isChecked ? 'checked' : ''}
             ${isLocked ? 'disabled' : ''}
             ${isPlaceholder ? 'disabled' : ''}
             data-overlay-id="${overlay.id}">
      <span class="overlay-icon">${overlay.icon || overlay.id[0].toUpperCase()}</span>
      <span class="overlay-label ${isPlaceholder ? 'placeholder' : ''}">${overlay.label}${isPlaceholder ? ' (soon)' : ''}</span>
    `;

    return item;
  },

  /**
   * Set up event handlers.
   * @private
   */
  _setupEvents() {
    // Header click - expand/collapse main list
    this.header.addEventListener('click', () => {
      this.expanded = !this.expanded;
      this.list.style.display = this.expanded ? 'block' : 'none';
      this.header.querySelector('.overlay-toggle').textContent = this.expanded ? '-' : '+';
    });

    // Category header clicks - expand/collapse sub-list and toggle all
    this.list.addEventListener('click', (e) => {
      const categoryHeader = e.target.closest('.overlay-category-header');
      if (!categoryHeader) return;

      const wrapper = categoryHeader.closest('.overlay-category');
      const categoryId = wrapper.dataset.categoryId;
      const checkbox = categoryHeader.querySelector('.category-checkbox');

      // If clicked on checkbox, toggle all overlays in category
      if (e.target === checkbox || e.target.closest('.category-checkbox')) {
        e.stopPropagation();
        this._toggleCategory(categoryId, checkbox.checked);
        return;
      }

      // Otherwise expand/collapse the category
      this.categoryExpanded[categoryId] = !this.categoryExpanded[categoryId];
      const subList = wrapper.querySelector('.overlay-sub-list');
      const toggle = categoryHeader.querySelector('.category-toggle');

      subList.style.display = this.categoryExpanded[categoryId] ? 'block' : 'none';
      toggle.textContent = this.categoryExpanded[categoryId] ? '-' : '+';
    });

    // Individual overlay checkbox changes
    this.list.addEventListener('change', (e) => {
      const checkbox = e.target;
      if (checkbox.type !== 'checkbox') return;

      // Handle category checkbox
      if (checkbox.classList.contains('category-checkbox')) {
        const categoryId = checkbox.dataset.categoryId;
        this._toggleCategory(categoryId, checkbox.checked);
        return;
      }

      // Handle individual overlay checkbox
      const overlayId = checkbox.dataset.overlayId;
      if (!overlayId) return;

      // Check if placeholder
      const overlay = OVERLAYS.find(o => o.id === overlayId);
      if (overlay?.placeholder) {
        checkbox.checked = false;
        return;
      }

      if (checkbox.checked) {
        this.activeOverlays.add(overlayId);
      } else {
        this.activeOverlays.delete(overlayId);
      }
      this._rememberCurrentLaneState();

      console.log('Overlay toggled:', overlayId, checkbox.checked);
      console.log('Active overlays:', Array.from(this.activeOverlays));

      // Update parent category checkbox state
      this._updateCategoryCheckbox(overlayId);

      // Notify listeners
      this._notifyListeners(overlayId, checkbox.checked);

      // Persist to localStorage
      this._saveState();
    });
  },

  /**
   * Toggle all overlays in a category.
   * @private
   */
  _toggleCategory(categoryId, active) {
    const category = CATEGORIES.find(c => c.id === categoryId);
    if (!category || !category.isCategory) return;

    for (const overlay of category.overlays) {
      if (overlay.locked || overlay.placeholder) continue;

      const wasActive = this.activeOverlays.has(overlay.id);

      if (active) {
        this.activeOverlays.add(overlay.id);
      } else {
        this.activeOverlays.delete(overlay.id);
      }

      // Update individual checkbox
      const checkbox = this.list.querySelector(`input[data-overlay-id="${overlay.id}"]`);
      if (checkbox) {
        checkbox.checked = active;
      }

      // Notify if state changed
      if (wasActive !== active) {
        this._notifyListeners(overlay.id, active);
      }
    }
    this._rememberCurrentLaneState();

    // Update category checkbox (clear indeterminate)
    const catCheckbox = this.list.querySelector(`input[data-category-id="${categoryId}"]`);
    if (catCheckbox) {
      catCheckbox.indeterminate = false;
      catCheckbox.checked = active;
    }

    console.log('Category toggled:', categoryId, active);
    console.log('Active overlays:', Array.from(this.activeOverlays));

    // Persist to localStorage
    this._saveState();
  },

  /**
   * Update category checkbox based on child states.
   * @private
   */
  _updateCategoryCheckbox(overlayId) {
    // Find which category this overlay belongs to
    for (const cat of CATEGORIES) {
      if (!cat.isCategory) continue;

      const overlay = cat.overlays.find(o => o.id === overlayId);
      if (!overlay) continue;

      // Count active non-placeholder overlays
      const nonPlaceholders = cat.overlays.filter(o => !o.placeholder);
      const activeCount = nonPlaceholders.filter(o => this.activeOverlays.has(o.id)).length;
      const allActive = activeCount === nonPlaceholders.length;
      const someActive = activeCount > 0 && !allActive;

      const checkbox = this.list.querySelector(`input[data-category-id="${cat.id}"]`);
      if (checkbox) {
        checkbox.checked = allActive;
        checkbox.indeterminate = someActive;
      }
      break;
    }
  },

  /**
   * Toggle an overlay on/off.
   * @param {string} overlayId - Overlay ID
   */
  toggle(overlayId) {
    const overlay = OVERLAYS.find(o => o.id === overlayId);
    if (!overlay || overlay.locked || overlay.placeholder) return;

    if (this.activeOverlays.has(overlayId)) {
      this.activeOverlays.delete(overlayId);
    } else {
      this.activeOverlays.add(overlayId);
    }
    this._rememberCurrentLaneState();

    // Update checkbox
    const checkbox = this.list?.querySelector(`input[data-overlay-id="${overlayId}"]`);
    if (checkbox) {
      checkbox.checked = this.activeOverlays.has(overlayId);
    }

    // Update category checkbox
    this._updateCategoryCheckbox(overlayId);

    // Notify listeners
    this._notifyListeners(overlayId, this.activeOverlays.has(overlayId));

    // Persist to localStorage
    this._saveState();
  },

  /**
   * Check if an overlay is active.
   * @param {string} overlayId - Overlay ID
   * @returns {boolean}
   */
  isActive(overlayId) {
    return this.activeOverlays.has(overlayId);
  },

  /**
   * Get list of active overlay IDs.
   * Used by preprocessor for chat context.
   * @returns {string[]}
   */
  getActiveOverlays() {
    return Array.from(this.activeOverlays);
  },

  /**
   * Get overlay configuration by ID.
   * @param {string} overlayId - Overlay ID
   * @returns {Object|null}
   */
  getOverlayConfig(overlayId) {
    return OVERLAYS.find(o => o.id === overlayId) || null;
  },

  refreshVisibility() {
    if (!ALL_CATEGORIES.length) return;

    this.currentLaneMode = getCurrentOverlayLaneMode();
    CATEGORIES = filterCategoriesForCurrentMode(ALL_CATEGORIES);
    OVERLAYS = getAllOverlaysFromCategories(CATEGORIES);

    const visibleOverlayIds = new Set(OVERLAYS.map((overlay) => overlay.id));
    const removed = [];
    for (const overlayId of Array.from(this.activeOverlays)) {
      if (!visibleOverlayIds.has(overlayId)) {
        this.activeOverlays.delete(overlayId);
        removed.push(overlayId);
      }
    }

    const nextCategoryExpanded = {};
    for (const category of CATEGORIES) {
      if (category.isCategory) {
        nextCategoryExpanded[category.id] = this.categoryExpanded[category.id] ?? category.expanded ?? false;
      }
    }
    this.categoryExpanded = nextCategoryExpanded;
    this._rememberCurrentLaneState();

    if (this.initialized) {
      this._buildUI();
      this._setupEvents();
      for (const overlayId of removed) {
        this._notifyListeners(overlayId, false);
      }
      this._saveState();
    }
  },

  syncToCurrentMode() {
    const nextMode = getCurrentOverlayLaneMode();
    const previousOverlays = new Set(this.activeOverlays);
    this._rememberCurrentLaneState();
    this.currentLaneMode = nextMode;
    if (!this._restoreState(nextMode)) {
      for (const overlay of OVERLAYS) {
        if (overlay.default) {
          this.activeOverlays.add(overlay.id);
        }
      }
      this._rememberCurrentLaneState();
    }
    this.refreshVisibility();

    const nextOverlays = new Set(this.activeOverlays);
    for (const overlayId of previousOverlays) {
      if (!nextOverlays.has(overlayId)) {
        this._notifyListeners(overlayId, false);
      }
    }
    for (const overlayId of nextOverlays) {
      if (!previousOverlays.has(overlayId)) {
        this._notifyListeners(overlayId, true);
      }
    }
  },

  /**
   * Add a listener for overlay changes.
   * @param {Function} callback - Called with (overlayId, isActive)
   */
  addListener(callback) {
    this.listeners.push(callback);
  },

  /**
   * Remove a listener.
   * @param {Function} callback
   */
  removeListener(callback) {
    const index = this.listeners.indexOf(callback);
    if (index >= 0) {
      this.listeners.splice(index, 1);
    }
  },

  /**
   * Notify all listeners of an overlay change.
   * @private
   */
  _notifyListeners(overlayId, isActive) {
    for (const listener of this.listeners) {
      try {
        listener(overlayId, isActive);
      } catch (err) {
        console.error('OverlaySelector listener error:', err);
      }
    }
  },

  /**
   * Expand the overlay list.
   */
  expand() {
    this.expanded = true;
    if (this.list) {
      this.list.style.display = 'block';
    }
    if (this.header) {
      this.header.querySelector('.overlay-toggle').textContent = '-';
    }
  },

  /**
   * Collapse the overlay list.
   */
  collapse() {
    this.expanded = false;
    if (this.list) {
      this.list.style.display = 'none';
    }
    if (this.header) {
      this.header.querySelector('.overlay-toggle').textContent = '+';
    }
  },

  /**
   * Set overlay state programmatically.
   * @param {string} overlayId - Overlay ID
   * @param {boolean} active - Active state
   */
  setActive(overlayId, active) {
    const overlay = OVERLAYS.find(o => o.id === overlayId);
    if (!overlay || overlay.locked || overlay.placeholder) return;

    if (active) {
      this.activeOverlays.add(overlayId);
    } else {
      this.activeOverlays.delete(overlayId);
    }
    this._rememberCurrentLaneState();

    // Update checkbox
    const checkbox = this.list?.querySelector(`input[data-overlay-id="${overlayId}"]`);
    if (checkbox) {
      checkbox.checked = active;
    }

    // Update category checkbox
    this._updateCategoryCheckbox(overlayId);

    // Persist to localStorage
    this._saveState();
  },

  _storageKey(mode = this.currentLaneMode) {
    return `${STORAGE_KEY_PREFIX}_${mode}`;
  },

  _rememberCurrentLaneState() {
    this.laneOverlayStates.set(this.currentLaneMode, Array.from(this.activeOverlays));
  },

  /**
   * Save active overlays to localStorage.
   * @private
   */
  _saveState() {
    try {
      const data = Array.from(this.activeOverlays);
      this.laneOverlayStates.set(this.currentLaneMode, data);
      localStorage.setItem(this._storageKey(), JSON.stringify(data));
    } catch (e) {
      // localStorage not available or full
      console.warn('OverlaySelector: Could not save state to localStorage', e);
    }
  },

  /**
   * Restore active overlays from localStorage.
   * @private
   * @returns {boolean} True if state was restored, false otherwise
   */
  _restoreState(mode = this.currentLaneMode) {
    try {
      this.activeOverlays.clear();
      const cached = this.laneOverlayStates.get(mode);
      const raw = cached || JSON.parse(localStorage.getItem(this._storageKey(mode)) || 'null');
      if (Array.isArray(raw)) {
        for (const id of raw) {
          if (OVERLAYS.find(o => o.id === id)) {
            this.activeOverlays.add(id);
          }
        }
        this.laneOverlayStates.set(mode, Array.from(this.activeOverlays));
        console.log('OverlaySelector: Restored state for lane', mode, Array.from(this.activeOverlays));
        return true;
      }
    } catch (e) {
      console.warn('OverlaySelector: Could not restore state from localStorage', e);
    }
    return false;
  },

  /**
   * Clear saved state and reset to defaults.
   * Called by New Chat button.
   */
  clearState() {
    try {
      for (const mode of ['explore', 'research', 'ops']) {
        localStorage.removeItem(this._storageKey(mode));
      }
    } catch (e) {
      // Ignore
    }
    this.laneOverlayStates.clear();

    // Clear current state
    const previousOverlays = Array.from(this.activeOverlays);
    this.activeOverlays.clear();

    // Reset to defaults
    for (const overlay of OVERLAYS) {
      if (overlay.default) {
        this.activeOverlays.add(overlay.id);
      }
    }
    this._rememberCurrentLaneState();

    // Rebuild UI to reflect reset state
    if (this.list) {
      this._buildUI();
      this._setupEvents();
    }

    // Notify listeners of changes
    for (const id of previousOverlays) {
      if (!this.activeOverlays.has(id)) {
        this._notifyListeners(id, false);
      }
    }
    for (const id of this.activeOverlays) {
      if (!previousOverlays.includes(id)) {
        this._notifyListeners(id, true);
      }
    }

    console.log('OverlaySelector: State cleared, reset to defaults');
  }
};

// Expose globally for ViewportLoader to check active overlays
window.OverlaySelector = OverlaySelector;
