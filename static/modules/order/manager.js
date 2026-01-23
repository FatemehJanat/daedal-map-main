/**
 * Order Panel Manager
 * Handles order panel rendering, item management, and saved orders UI.
 * Uses callbacks for app-specific actions (confirm, clear, display).
 *
 * Usage:
 *   const panel = new OrderPanel({
 *     elements: { panel, count, summary, items, confirmBtn, cancelBtn, ... },
 *     onConfirm: async (order) => { ... },  // app handles API + display
 *     onClear: () => { ... },               // app handles map reset
 *     getCacheStats: () => ({ features, sizeMB }),
 *     addMessage: (text, type) => { ... }
 *   });
 */

import * as SavedOrders from './saved.js';

export class OrderPanel {
  /**
   * @param {Object} config
   * @param {Object} config.elements - DOM element references
   * @param {Function} config.onConfirm - async (order) => void - Handle order confirmation
   * @param {Function} config.onQueue - async (order) => void - Handle order queueing
   * @param {Function} [config.onClear] - () => void - Handle order clear/reset
   * @param {Function} [config.getCacheStats] - () => { features, sizeMB }
   * @param {Function} [config.addMessage] - (text, type) => void - Display chat message
   */
  constructor(config) {
    this.elements = config.elements || {};
    this.onConfirm = config.onConfirm || (() => {});
    this.onQueue = config.onQueue || (() => {});
    this.onClear = config.onClear || (() => {});
    this.getCacheStats = config.getCacheStats || (() => null);
    this.addMessage = config.addMessage || (() => {});

    this.currentOrder = null;
  }

  /**
   * Initialize the order panel - setup listeners and initial render.
   */
  init() {
    this.setupEventListeners();
    this.render();
    this.updateCacheStatus();
    this.updateSaveButtonState();
    this.updateSavedOrdersIndicator();

    // Listen for cache updates
    window.addEventListener('overlayCacheUpdated', () => {
      this.updateCacheStatus();
    });
  }

  /**
   * Setup event listeners for panel buttons.
   */
  setupEventListeners() {
    const { confirmBtn, cancelBtn, saveBtn, savedOrdersClose, savedOrdersToggle } = this.elements;

    if (confirmBtn) {
      confirmBtn.addEventListener('click', () => this.confirmOrder());
    }

    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => this.clearOrder());
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', () => this.promptSaveOrder());
    }

    if (savedOrdersClose) {
      savedOrdersClose.addEventListener('click', () => this.hideSavedOrdersList());
    }

    if (savedOrdersToggle) {
      savedOrdersToggle.addEventListener('click', () => this.toggleSavedOrdersList());
    }
  }

  /**
   * Add items from a response to the current order (accumulates until Clear).
   * @param {Object} order - The order object { items, summary, ... }
   * @param {string} summary - Summary text
   */
  setOrder(order, summary) {
    if (!order || !order.items || order.items.length === 0) {
      return;
    }

    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      // No existing order - use the new one
      this.currentOrder = order;
      delete this.currentOrder.navigationLocations;
    } else {
      // Append new items, deduplicate by source_id + metric + region
      const existingKeys = new Set(
        this.currentOrder.items.map(item =>
          `${item.source_id || item.source}|${item.metric}|${item.region}`
        )
      );

      const newItems = order.items.filter(item => {
        const key = `${item.source_id || item.source}|${item.metric}|${item.region}`;
        return !existingKeys.has(key);
      });

      if (newItems.length > 0) {
        this.currentOrder.items = this.currentOrder.items.concat(newItems);
        this.currentOrder.summary = summary || this.currentOrder.summary;
      }
      delete this.currentOrder.navigationLocations;
    }

    // Reset confirm button text
    if (this.elements.confirmBtn) {
      this.elements.confirmBtn.textContent = 'Display on Map';
    }

    this.render(summary);
  }

  /**
   * Set navigation locations - locations selected, ready for data request.
   * @param {Array} locations - Location objects from navigation
   */
  setNavigationLocations(locations) {
    if (!locations || locations.length === 0) return;

    this.currentOrder = {
      items: [],
      navigationLocations: locations,
      summary: `${locations.length} location${locations.length > 1 ? 's' : ''} selected`
    };

    this.renderNavigationMode();
  }

  /**
   * Render order panel in navigation mode (locations selected, awaiting data).
   */
  renderNavigationMode() {
    const { count, items, confirmBtn, summary: summaryEl } = this.elements;

    if (!this.currentOrder || !this.currentOrder.navigationLocations) {
      return this.render();
    }

    const locations = this.currentOrder.navigationLocations;
    if (count) count.textContent = `(${locations.length} location${locations.length > 1 ? 's' : ''})`;
    if (summaryEl) summaryEl.textContent = 'Locations ready - ask for data';
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Add Data First';
    }

    if (items) {
      items.innerHTML = locations.map(loc => {
        const name = loc.matched_term || loc.loc_id || 'Unknown';
        const country = loc.country_name || loc.iso3 || '';
        return `
          <div class="order-item order-item-location">
            <div class="order-item-info">
              <div class="order-item-name">${escapeHtml(name)}</div>
              <div class="order-item-details">${escapeHtml(country)}</div>
            </div>
          </div>
        `;
      }).join('');
    }
  }

  /**
   * Clear the current order and notify consumer.
   */
  clearOrder() {
    this.currentOrder = null;
    this.render();
    this.onClear();
  }

  /**
   * Remove a specific item from the order.
   * @param {number} index - Index of item to remove
   */
  removeItem(index) {
    if (!this.currentOrder || !this.currentOrder.items) return;

    this.currentOrder.items.splice(index, 1);

    if (this.currentOrder.items.length === 0) {
      this.currentOrder = null;
    }

    this.render();
  }

  /**
   * Estimate order data size based on region.
   * @param {Array} items - Order items
   * @returns {Object} { locations, estimatedKB }
   */
  estimateOrderSize(items) {
    const regionCounts = {
      'USA': 3200,
      'USA-CA': 58, 'USA-TX': 254, 'USA-FL': 67, 'USA-NY': 62, 'USA-PA': 67,
      'global': 5000,
      'default': 100
    };

    let totalLocations = 0;
    for (const item of items) {
      const region = item.region || 'global';
      let count = regionCounts[region];
      if (!count) {
        if (region.match(/^USA-[A-Z]{2}$/)) {
          count = regionCounts['default'];
        } else if (region.startsWith('USA')) {
          count = regionCounts['USA'];
        } else {
          count = regionCounts['default'];
        }
      }
      totalLocations += count;
    }

    return { locations: totalLocations, estimatedKB: totalLocations };
  }

  /**
   * Render the order panel.
   * @param {string} [summary] - Optional summary text
   */
  render(summary = '') {
    const { count, items, confirmBtn, summary: summaryEl } = this.elements;

    if (summaryEl) summaryEl.textContent = summary || '';

    // Empty state
    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      if (count) count.textContent = '(empty)';
      if (items) items.innerHTML = '<div style="color: #999; font-size: 12px; text-align: center; padding: 10px;">Ask for data to add items here</div>';
      if (confirmBtn) confirmBtn.disabled = true;
      return;
    }

    // Render items with size estimate
    const orderItems = this.currentOrder.items;
    const sizeEstimate = this.estimateOrderSize(orderItems);
    const sizeStr = sizeEstimate.estimatedKB >= 1024
      ? `~${(sizeEstimate.estimatedKB / 1024).toFixed(1)} MB`
      : `~${sizeEstimate.estimatedKB} KB`;

    if (count) count.textContent = `(${orderItems.length} item${orderItems.length > 1 ? 's' : ''}, ${sizeStr})`;
    if (confirmBtn) confirmBtn.disabled = false;

    // Check for invalid items
    const hasInvalid = orderItems.some(item => item._valid === false);
    if (confirmBtn) {
      confirmBtn.disabled = hasInvalid;
      confirmBtn.title = hasInvalid ? 'Fix invalid items before displaying' : '';
    }

    if (items) {
      items.innerHTML = orderItems.map((item, index) => {
        const label = item.metric_label || item.metric || 'unknown';
        const region = item.region || 'global';
        let year;
        if (item.year_start && item.year_end) {
          year = `${item.year_start}-${item.year_end}`;
        } else {
          year = item.year || 'latest';
        }
        const isValid = item._valid !== false;
        const error = item._error || '';
        const details = [region, year].filter(Boolean).join(' | ');
        const itemClass = isValid ? 'order-item' : 'order-item order-item-invalid';
        const errorHtml = error ? `<div class="order-item-error">${escapeHtml(error)}</div>` : '';

        return `
          <div class="${itemClass}">
            <div class="order-item-info">
              <div class="order-item-name">${escapeHtml(label)}</div>
              <div class="order-item-details">${escapeHtml(details)}</div>
              ${errorHtml}
            </div>
            <button class="order-item-remove" data-remove-index="${index}" title="Remove">x</button>
          </div>
        `;
      }).join('');

      // Bind remove buttons
      items.querySelectorAll('.order-item-remove').forEach(btn => {
        btn.addEventListener('click', () => {
          this.removeItem(parseInt(btn.dataset.removeIndex, 10));
        });
      });
    }

    this.updateSaveButtonState();
  }

  /**
   * Confirm the current order via callback.
   */
  async confirmOrder() {
    if (!this.currentOrder) return;

    const { confirmBtn } = this.elements;
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Loading...';
    }

    try {
      await this.onConfirm(this.currentOrder);
      this.updateCacheStatus();
    } catch (error) {
      console.error('[OrderPanel] Confirm error:', error);
      this.addMessage('Sorry, something went wrong executing the order.', 'assistant');
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Display on Map';
      }
    }
  }

  /**
   * Queue order for background processing via callback.
   */
  async queueOrder() {
    if (!this.currentOrder) return;

    const { confirmBtn } = this.elements;
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Queueing...';
    }

    try {
      await this.onQueue(this.currentOrder);
      if (confirmBtn) confirmBtn.textContent = 'Queued';
    } catch (error) {
      console.error('[OrderPanel] Queue error:', error);
      this.addMessage('Failed to queue order. Try again.', 'assistant');
      if (confirmBtn) confirmBtn.textContent = 'Display on Map';
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
    }
  }

  /**
   * Prompt user for name and save current order.
   */
  promptSaveOrder() {
    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      this.addMessage('No order to save. Add some data first.', 'assistant');
      return;
    }

    const name = prompt('Enter a name for this saved order:');
    if (!name || !name.trim()) return;

    const savedOrder = SavedOrders.save(
      name.trim(),
      this.currentOrder.items,
      this.currentOrder.summary
    );

    if (savedOrder) {
      this.addMessage(`Order saved as "${savedOrder.name}"`, 'assistant');
      this.updateSavedOrdersIndicator();
    }
  }

  /**
   * Show the saved orders list.
   */
  showSavedOrdersList() {
    const { savedOrdersList, savedOrdersItems } = this.elements;
    if (!savedOrdersList || !savedOrdersItems) return;

    const orders = SavedOrders.getAll();

    if (orders.length === 0) {
      savedOrdersItems.innerHTML = '<div class="saved-orders-empty">No saved orders</div>';
    } else {
      savedOrdersItems.innerHTML = orders.map(order => `
        <div class="saved-order-item" data-order-id="${order.id}">
          <span class="saved-order-name">${order.name}</span>
          <div class="saved-order-actions">
            <button class="saved-order-btn load" data-action="load" data-id="${order.id}" title="Load this order">Load</button>
            <button class="saved-order-btn delete" data-action="delete" data-id="${order.id}" title="Delete this order">Del</button>
          </div>
        </div>
      `).join('');

      // Bind action buttons
      savedOrdersItems.querySelectorAll('.saved-order-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const action = btn.dataset.action;
          const id = btn.dataset.id;
          if (action === 'load') this.loadSavedOrder(id);
          else if (action === 'delete') this.deleteSavedOrder(id);
        });
      });
    }

    savedOrdersList.style.display = 'block';
  }

  /**
   * Hide the saved orders list.
   */
  hideSavedOrdersList() {
    const { savedOrdersList } = this.elements;
    if (savedOrdersList) savedOrdersList.style.display = 'none';
  }

  /**
   * Toggle saved orders list visibility.
   */
  toggleSavedOrdersList() {
    const { savedOrdersList } = this.elements;
    if (savedOrdersList && savedOrdersList.style.display === 'block') {
      this.hideSavedOrdersList();
    } else {
      this.showSavedOrdersList();
    }
  }

  /**
   * Load a saved order by ID.
   * @param {string} orderId - ID of the order to load
   */
  loadSavedOrder(orderId) {
    const order = SavedOrders.load(orderId);
    if (order) {
      this.currentOrder = {
        items: JSON.parse(JSON.stringify(order.items)),
        summary: order.summary || 'Loaded saved order: ' + order.name
      };
      this.render(this.currentOrder.summary);
      this.hideSavedOrdersList();
      this.addMessage(`Loaded saved order: "${order.name}"`, 'assistant');
    }
  }

  /**
   * Delete a saved order by ID.
   * @param {string} orderId - ID of the order to delete
   */
  deleteSavedOrder(orderId) {
    const orders = SavedOrders.getAll();
    const order = orders.find(o => o.id === orderId);
    const name = order ? order.name : orderId;

    if (confirm(`Delete saved order "${name}"?`)) {
      if (SavedOrders.deleteOrder(orderId)) {
        this.showSavedOrdersList();  // Refresh list
        this.updateSavedOrdersIndicator();
        this.addMessage(`Deleted saved order: "${name}"`, 'assistant');
      }
    }
  }

  /**
   * Update save button enabled state.
   */
  updateSaveButtonState() {
    const { saveBtn } = this.elements;
    if (!saveBtn) return;
    const hasOrder = this.currentOrder && this.currentOrder.items && this.currentOrder.items.length > 0;
    saveBtn.disabled = !hasOrder;
  }

  /**
   * Update saved orders indicator (count badge).
   */
  updateSavedOrdersIndicator() {
    const { savedOrdersIndicator, savedOrdersCount } = this.elements;
    if (!savedOrdersIndicator || !savedOrdersCount) return;

    const orders = SavedOrders.getAll();
    const count = orders.length;

    if (count === 0) {
      savedOrdersIndicator.style.display = 'none';
    } else {
      savedOrdersIndicator.style.display = 'flex';
      savedOrdersCount.textContent = `${count} saved order${count !== 1 ? 's' : ''}`;
    }
  }

  /**
   * Update cache status display using getCacheStats callback.
   */
  updateCacheStatus() {
    const { cacheStatus, cacheStatusText } = this.elements;
    if (!cacheStatus || !cacheStatusText) return;

    try {
      const stats = this.getCacheStats();
      if (!stats) {
        cacheStatusText.textContent = 'Cache: empty';
        cacheStatus.className = 'cache-status';
        return;
      }

      const totalFeatures = stats.totals?.features || 0;
      const sizeMB = parseFloat(stats.totals?.sizeMB || 0);

      if (totalFeatures === 0) {
        cacheStatusText.textContent = 'Cache: empty';
        cacheStatus.className = 'cache-status';
      } else {
        let sizeStr;
        if (sizeMB >= 1) {
          sizeStr = `${sizeMB.toFixed(1)} MB`;
        } else {
          const sizeKB = sizeMB * 1024;
          sizeStr = `${Math.round(sizeKB)} KB`;
        }

        cacheStatusText.textContent = `Cache: ${totalFeatures.toLocaleString()} features (${sizeStr})`;
        cacheStatus.className = sizeMB > 500 ? 'cache-status warning' : 'cache-status has-data';
      }
    } catch (error) {
      console.warn('[OrderPanel] Error updating cache status:', error);
      cacheStatusText.textContent = 'Cache: error';
    }
  }
}

/**
 * Escape HTML to prevent XSS.
 * @param {string} text - Raw text
 * @returns {string} Escaped HTML
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
