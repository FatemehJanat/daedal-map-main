/**
 * Overlay Selector - UI component for toggling data overlays.
 * Displays in top right, below zoom level and breadcrumbs.
 * Supports hierarchical categories with group toggle.
 */

import { CONFIG } from './config.js';

// Category configuration with nested overlays
const CATEGORIES = [
  {
    id: 'demographics',
    label: 'Demographics',
    icon: 'D',
    isCategory: false,  // Standalone overlay, not a category
    overlay: {
      id: 'demographics',
      label: 'Demographics',
      description: 'Population, density, economic data',
      default: false,
      locked: false,
      model: 'choropleth',
      hasYearFilter: false
    }
  },
  {
    id: 'disasters',
    label: 'Disasters',
    icon: '!',
    isCategory: true,
    expanded: true,  // Default expanded
    overlays: [
      {
        id: 'earthquakes',
        label: 'Earthquakes',
        description: 'USGS seismic events',
        default: false,
        locked: false,
        model: 'point-radius',
        icon: 'E',
        hasYearFilter: true
      },
      {
        id: 'volcanoes',
        label: 'Volcanoes',
        description: 'Volcanic eruptions',
        default: false,
        locked: false,
        model: 'point-radius',
        icon: 'V',
        hasYearFilter: true
      },
      {
        id: 'hurricanes',
        label: 'Hurricanes',
        description: 'Storm tracks and positions',
        default: false,
        locked: false,
        model: 'track',
        icon: 'H',
        hasYearFilter: true
      },
      {
        id: 'tornadoes',
        label: 'Tornadoes',
        description: 'USA tornadoes 1950-present (NOAA)',
        default: false,
        locked: false,
        model: 'point-radius',
        icon: 'R',  // R for Rotation/twisteR
        hasYearFilter: true
      },
      {
        id: 'tsunamis',
        label: 'Tsunamis',
        description: 'Tsunami events and coastal runups',
        default: false,
        locked: false,
        model: 'point-radius',
        icon: 'T',
        hasYearFilter: true
      },
      {
        id: 'wildfires',
        label: 'Wildfires',
        description: 'Global fires >= 100km2 (2003-2024)',
        default: false,
        locked: false,
        model: 'point-radius',
        icon: 'W',
        hasYearFilter: true
      },
      {
        id: 'floods',
        label: 'Floods',
        description: 'Global floods (1985-2019)',
        default: false,
        locked: false,
        model: 'point-radius',
        icon: 'F',
        hasYearFilter: true
      },
      // DISABLED: Drought and Landslides - uncomment to re-enable
      // {
      //   id: 'drought',
      //   label: 'Drought',
      //   description: 'Canada drought monitoring (2019-2025)',
      //   default: false,
      //   locked: false,
      //   model: 'polygon',
      //   icon: 'D',
      //   hasYearFilter: true
      // },
      // {
      //   id: 'landslides',
      //   label: 'Landslides',
      //   description: 'Global landslides (deaths >= 1)',
      //   default: false,
      //   locked: false,
      //   model: 'point-radius',
      //   icon: 'L',
      //   hasYearFilter: true
      // }
    ]
  },
  {
    id: 'climate',
    label: 'Climate',
    icon: 'C',
    isCategory: true,
    expanded: false,
    overlays: [
      {
        id: 'wind-patterns',
        label: 'Wind Patterns',
        description: 'Global wind circulation',
        default: false,
        locked: false,
        model: 'vector',
        icon: '~',
        hasYearFilter: false,
        placeholder: true
      },
      {
        id: 'currents',
        label: 'Ocean Currents',
        description: 'Ocean circulation patterns',
        default: false,
        locked: false,
        model: 'vector',
        icon: '=',
        hasYearFilter: false,
        placeholder: true
      },
      {
        id: 'pollution',
        label: 'Pollution',
        description: 'Air and water quality data',
        default: false,
        locked: false,
        model: 'heatmap',
        icon: 'P',
        hasYearFilter: true,
        placeholder: true
      }
    ]
  }
];

// Flatten overlays for lookup
function getAllOverlays() {
  const overlays = [];
  for (const cat of CATEGORIES) {
    if (cat.isCategory) {
      overlays.push(...cat.overlays);
    } else if (cat.overlay) {
      overlays.push(cat.overlay);
    }
  }
  return overlays;
}

const OVERLAYS = getAllOverlays();

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
  expanded: true,  // Default expanded
  categoryExpanded: {},  // Track which categories are expanded

  // DOM elements
  container: null,
  header: null,
  list: null,

  // Change listeners
  listeners: [],

  /**
   * Initialize the overlay selector UI.
   * Creates DOM elements and wires up event handlers.
   */
  init() {
    // Set default overlays
    for (const overlay of OVERLAYS) {
      if (overlay.default) {
        this.activeOverlays.add(overlay.id);
      }
    }

    // Initialize category expanded state
    for (const cat of CATEGORIES) {
      if (cat.isCategory) {
        this.categoryExpanded[cat.id] = cat.expanded || false;
      }
    }

    // Find or create container
    this.container = document.getElementById('overlaySelector');
    if (!this.container) {
      console.warn('OverlaySelector: #overlaySelector not found in DOM');
      return;
    }

    // Build UI
    this._buildUI();

    // Wire up events
    this._setupEvents();

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
    this.header.innerHTML = `
      <span class="overlay-title">Overlays</span>
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

      console.log('Overlay toggled:', overlayId, checkbox.checked);
      console.log('Active overlays:', Array.from(this.activeOverlays));

      // Update parent category checkbox state
      this._updateCategoryCheckbox(overlayId);

      // Notify listeners
      this._notifyListeners(overlayId, checkbox.checked);
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

    // Update category checkbox (clear indeterminate)
    const catCheckbox = this.list.querySelector(`input[data-category-id="${categoryId}"]`);
    if (catCheckbox) {
      catCheckbox.indeterminate = false;
      catCheckbox.checked = active;
    }

    console.log('Category toggled:', categoryId, active);
    console.log('Active overlays:', Array.from(this.activeOverlays));
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

    // Update checkbox
    const checkbox = this.list.querySelector(`input[data-overlay-id="${overlayId}"]`);
    if (checkbox) {
      checkbox.checked = this.activeOverlays.has(overlayId);
    }

    // Update category checkbox
    this._updateCategoryCheckbox(overlayId);

    // Notify listeners
    this._notifyListeners(overlayId, this.activeOverlays.has(overlayId));
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
    this.list.style.display = 'block';
    this.header.querySelector('.overlay-toggle').textContent = '-';
  },

  /**
   * Collapse the overlay list.
   */
  collapse() {
    this.expanded = false;
    this.list.style.display = 'none';
    this.header.querySelector('.overlay-toggle').textContent = '+';
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

    // Update checkbox
    const checkbox = this.list.querySelector(`input[data-overlay-id="${overlayId}"]`);
    if (checkbox) {
      checkbox.checked = active;
    }

    // Update category checkbox
    this._updateCategoryCheckbox(overlayId);
  }
};

// Expose globally for ViewportLoader to check active overlays
window.OverlaySelector = OverlaySelector;
