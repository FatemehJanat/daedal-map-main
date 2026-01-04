/**
 * Chat Panel - Sidebar chat functionality and order management.
 * Combines ChatManager and OrderManager for data request handling.
 */

import { CONFIG } from './config.js';

// Dependencies set via setDependencies to avoid circular imports
let MapAdapter = null;
let App = null;
let SelectionManager = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  App = deps.App;
  SelectionManager = deps.SelectionManager;
}

// ============================================================================
// CHAT MANAGER - Sidebar chat functionality
// ============================================================================

export const ChatManager = {
  history: [],
  sessionId: null,
  elements: {},

  /**
   * Initialize chat manager
   */
  init() {
    this.sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);

    // Cache DOM elements
    this.elements = {
      sidebar: document.getElementById('sidebar'),
      toggle: document.getElementById('sidebarToggle'),
      close: document.getElementById('closeSidebar'),
      messages: document.getElementById('chatMessages'),
      form: document.getElementById('chatForm'),
      input: document.getElementById('chatInput'),
      sendBtn: document.getElementById('sendBtn')
    };

    this.setupEventListeners();
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { sidebar, toggle, close, form, input } = this.elements;

    // Sidebar toggle
    toggle.addEventListener('click', () => {
      sidebar.classList.remove('collapsed');
      toggle.style.display = 'none';
    });

    close.addEventListener('click', () => {
      sidebar.classList.add('collapsed');
      toggle.style.display = 'flex';
    });

    // Auto-resize textarea
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Enter to send
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        form.dispatchEvent(new Event('submit'));
      }
    });

    // Form submission
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handleSubmit();
    });
  },

  /**
   * Handle form submission
   */
  async handleSubmit() {
    const { input, sendBtn } = this.elements;
    const query = input.value.trim();
    if (!query) return;

    // Add user message
    this.addMessage(query, 'user');
    input.value = '';
    input.style.height = 'auto';

    // Disable input
    sendBtn.disabled = true;
    input.disabled = true;

    // Show typing indicator
    const indicator = this.showTypingIndicator();

    try {
      const response = await this.sendQuery(query);

      // Handle response based on type (Order Taker model)
      switch (response.type) {
        case 'order':
          // LLM created an order - show in order panel for confirmation
          this.addMessage('Added to your order. Click "Display on Map" when ready.', 'assistant');
          OrderManager.setOrder(response.order, response.summary);
          break;

        case 'clarify':
          // LLM needs more information
          this.addMessage(response.message || 'Could you be more specific?', 'assistant');
          break;

        case 'disambiguate':
          // Multiple locations match - enter selection mode
          this.addMessage(response.message || 'Please select a location:', 'assistant');
          if (SelectionManager) {
            SelectionManager.enter(response, (selected, originalQuery) => {
              // User selected a location - retry the query with specific loc_id
              this.handleDisambiguationSelection(selected, originalQuery);
            });
          }
          break;

        case 'navigate':
          // Navigation request - zoom to locations and prepare for data
          this.addMessage(response.message || 'Showing locations.', 'assistant');
          this.handleNavigation(response);
          break;

        case 'data':
          // Direct data response (from confirmed order)
          this.addMessage(response.summary || 'Here is your data.', 'assistant');
          App?.displayData(response);
          break;

        case 'chat':
        default:
          // General chat response or legacy format
          if (response.geojson && response.geojson.features && response.geojson.features.length > 0) {
            const message = response.summary || response.message || 'Found data for you.';
            this.addMessage(message, 'assistant');
            App?.displayData(response);
          } else {
            const message = response.summary || response.message || 'Could you be more specific?';
            this.addMessage(message, 'assistant');
          }
          break;
      }
    } catch (error) {
      console.error('Chat error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant');
    } finally {
      indicator.remove();
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  },

  /**
   * Handle user selection from disambiguation mode
   * @param {Object} selected - The selected location option
   * @param {string} originalQuery - The original query to retry
   */
  async handleDisambiguationSelection(selected, originalQuery) {
    const locationName = selected.matched_term || selected.loc_id;
    const countryName = selected.country_name || selected.iso3;

    // Show what was selected
    this.addMessage(`Selected: ${locationName} in ${countryName}`, 'user');

    // Retry the query with the selected location's loc_id
    // The backend should use this to scope the data request
    const { sendBtn, input } = this.elements;
    sendBtn.disabled = true;
    input.disabled = true;

    const indicator = this.showTypingIndicator();

    try {
      // Send query with disambiguation resolution
      const response = await this.sendQueryWithLocation(originalQuery, selected);

      // Handle response (same as normal response handling)
      switch (response.type) {
        case 'order':
          this.addMessage('Added to your order. Click "Display on Map" when ready.', 'assistant');
          OrderManager.setOrder(response.order, response.summary);
          break;

        case 'clarify':
          this.addMessage(response.message || 'Could you be more specific?', 'assistant');
          break;

        case 'data':
          this.addMessage(response.summary || 'Here is your data.', 'assistant');
          App?.displayData(response);
          break;

        case 'chat':
        default:
          if (response.geojson && response.geojson.features && response.geojson.features.length > 0) {
            this.addMessage(response.summary || response.message || 'Found data for you.', 'assistant');
            App?.displayData(response);
          } else {
            this.addMessage(response.summary || response.message || 'Could you be more specific?', 'assistant');
          }
          break;
      }
    } catch (error) {
      console.error('Disambiguation retry error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant');
    } finally {
      indicator.remove();
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  },

  /**
   * Handle navigation request - zoom to locations and highlight them
   * @param {Object} response - Navigate response with locations and loc_ids
   */
  async handleNavigation(response) {
    const locIds = response.loc_ids || [];
    const locations = response.locations || [];

    if (locIds.length === 0) {
      console.warn('Navigation: no loc_ids to show');
      return;
    }

    try {
      // Fetch geometries for the locations
      const geomResponse = await fetch('/geometry/selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ loc_ids: locIds })
      });

      if (!geomResponse.ok) {
        throw new Error('Failed to fetch location geometries');
      }

      const geojson = await geomResponse.json();

      if (geojson.features && geojson.features.length > 0) {
        // Calculate bounding box for all features
        let minLng = 180, maxLng = -180, minLat = 90, maxLat = -90;

        for (const feature of geojson.features) {
          const props = feature.properties || {};
          // Use bbox if available
          if (props.bbox_min_lon !== undefined) {
            minLng = Math.min(minLng, props.bbox_min_lon);
            maxLng = Math.max(maxLng, props.bbox_max_lon);
            minLat = Math.min(minLat, props.bbox_min_lat);
            maxLat = Math.max(maxLat, props.bbox_max_lat);
          } else if (props.centroid_lon !== undefined) {
            // Fallback to centroid with buffer
            minLng = Math.min(minLng, props.centroid_lon - 1);
            maxLng = Math.max(maxLng, props.centroid_lon + 1);
            minLat = Math.min(minLat, props.centroid_lat - 1);
            maxLat = Math.max(maxLat, props.centroid_lat + 1);
          }
        }

        // Fit map to bounds with padding
        if (MapAdapter?.map && minLng < maxLng && minLat < maxLat) {
          MapAdapter.map.fitBounds(
            [[minLng, minLat], [maxLng, maxLat]],
            { padding: 50, duration: 1000 }
          );
        }

        // Display the locations as a highlight layer
        App?.displayNavigationLocations(geojson, locations);

        // Set up empty order with these locations
        OrderManager.setNavigationLocations(locations);
      }
    } catch (error) {
      console.error('Navigation error:', error);
      this.addMessage('Sorry, could not display those locations.', 'assistant');
    }
  },

  /**
   * Send query with resolved location (after disambiguation)
   * @param {string} query - Original query
   * @param {Object} location - Resolved location with loc_id, iso3, etc.
   */
  async sendQueryWithLocation(query, location) {
    this.history.push({ role: 'user', content: query });

    const view = MapAdapter?.getView() || { center: { lat: 0, lng: 0 }, zoom: 2, bounds: null, adminLevel: 0 };
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat`
      : '/chat';

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        viewport: {
          center: { lat: view.center.lat, lng: view.center.lng },
          zoom: view.zoom,
          bounds: view.bounds,
          adminLevel: view.adminLevel
        },
        chatHistory: this.history.slice(-10),
        sessionId: this.sessionId,
        // Disambiguation resolution - tell backend which location was selected
        resolved_location: {
          loc_id: location.loc_id,
          iso3: location.iso3,
          matched_term: location.matched_term,
          country_name: location.country_name
        }
      })
    });

    if (!response.ok) {
      throw new Error('Failed to get response: ' + response.statusText);
    }

    const data = await response.json();
    this.history.push({ role: 'assistant', content: data.message || data.summary });

    return data;
  },

  /**
   * Send query to API
   */
  async sendQuery(query) {
    this.history.push({ role: 'user', content: query });

    const view = MapAdapter?.getView() || { center: { lat: 0, lng: 0 }, zoom: 2, bounds: null, adminLevel: 0 };
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat`
      : '/chat';

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        viewport: {
          center: { lat: view.center.lat, lng: view.center.lng },
          zoom: view.zoom,
          bounds: view.bounds,  // {west, south, east, north}
          adminLevel: view.adminLevel
        },
        chatHistory: this.history.slice(-10),
        sessionId: this.sessionId
      })
    });

    if (!response.ok) {
      throw new Error('Failed to get response: ' + response.statusText);
    }

    const data = await response.json();
    this.history.push({ role: 'assistant', content: data.message || data.summary });

    return data;
  },

  /**
   * Add message to chat
   */
  addMessage(text, type, options = {}) {
    const { messages } = this.elements;
    const div = document.createElement('div');
    div.className = `chat-message ${type}`;

    if (options.html) {
      div.innerHTML = text;
    } else if (type === 'assistant') {
      // For assistant messages, render basic formatting:
      // - Convert newlines to <br>
      // - Bold text with **text** or __text__
      // - Numbered lists (1. item)
      // - Bullet lists (- item)
      let formatted = this.escapeHtml(text);

      // Bold: **text** or __text__
      formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      formatted = formatted.replace(/__(.+?)__/g, '<strong>$1</strong>');

      // Newlines to <br>
      formatted = formatted.replace(/\n/g, '<br>');

      div.innerHTML = formatted;
    } else {
      div.textContent = text;
    }

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  },

  /**
   * Escape HTML for safe rendering
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * Show typing indicator
   */
  showTypingIndicator() {
    const { messages } = this.elements;
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(indicator);
    messages.scrollTop = messages.scrollHeight;
    return indicator;
  }
};

// ============================================================================
// ORDER MANAGER - Order panel for confirming data requests
// ============================================================================

export const OrderManager = {
  currentOrder: null,
  elements: {},

  /**
   * Initialize order manager
   */
  init() {
    this.elements = {
      panel: document.getElementById('orderPanel'),
      count: document.getElementById('orderCount'),
      summary: document.getElementById('orderSummary'),
      items: document.getElementById('orderItems'),
      confirmBtn: document.getElementById('orderConfirmBtn'),
      cancelBtn: document.getElementById('orderCancelBtn')
    };

    this.setupEventListeners();
    this.render();
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { confirmBtn, cancelBtn } = this.elements;

    confirmBtn.addEventListener('click', () => {
      this.confirmOrder();
    });

    cancelBtn.addEventListener('click', () => {
      this.clearOrder();
    });
  },

  /**
   * Add items from LLM response to the current order (accumulates until Clear)
   * @param {Object} order - The order object from backend
   * @param {string} summary - Summary text from LLM
   */
  setOrder(order, summary) {
    if (!order || !order.items || order.items.length === 0) {
      // Nothing to add
      return;
    }

    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      // No existing order (or only navigation locations) - use the new one
      // Clear navigationLocations to exit navigation mode
      this.currentOrder = order;
      delete this.currentOrder.navigationLocations;
    } else {
      // Append new items, but deduplicate by source_id + metric + region
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
      // Clear navigationLocations when adding data
      delete this.currentOrder.navigationLocations;
    }

    // Reset confirm button text (may have been in navigation mode)
    this.elements.confirmBtn.textContent = 'Display on Map';

    this.render(summary);
  },

  /**
   * Set navigation locations - locations are selected, ready for data request
   * @param {Array} locations - List of location objects from navigation
   */
  setNavigationLocations(locations) {
    if (!locations || locations.length === 0) return;

    // Store locations as pending selection (no data yet)
    this.currentOrder = {
      items: [],  // No data items yet
      navigationLocations: locations,  // Store the locations for reference
      summary: `${locations.length} location${locations.length > 1 ? 's' : ''} selected`
    };

    this.renderNavigationMode();
  },

  /**
   * Render order panel in navigation mode (locations selected, awaiting data request)
   */
  renderNavigationMode() {
    const { count, items, confirmBtn, summary: summaryEl } = this.elements;

    if (!this.currentOrder || !this.currentOrder.navigationLocations) {
      return this.render();
    }

    const locations = this.currentOrder.navigationLocations;
    count.textContent = `(${locations.length} location${locations.length > 1 ? 's' : ''})`;
    summaryEl.textContent = 'Locations ready - ask for data';
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Add Data First';

    // Render location list
    items.innerHTML = locations.map((loc, index) => {
      const name = loc.matched_term || loc.loc_id || 'Unknown';
      const country = loc.country_name || loc.iso3 || '';
      return `
        <div class="order-item order-item-location">
          <div class="order-item-info">
            <div class="order-item-name">${this.escapeHtml(name)}</div>
            <div class="order-item-details">${this.escapeHtml(country)}</div>
          </div>
        </div>
      `;
    }).join('');
  },

  /**
   * Clear the current order and reset map to exploration mode
   */
  clearOrder() {
    this.currentOrder = null;
    this.render();

    // Reset map to exploration mode (reload default countries)
    App?.loadCountries();
  },

  /**
   * Remove a specific item from the order
   * @param {number} index - Index of item to remove
   */
  removeItem(index) {
    if (!this.currentOrder || !this.currentOrder.items) return;

    this.currentOrder.items.splice(index, 1);

    if (this.currentOrder.items.length === 0) {
      this.currentOrder = null;
    }

    this.render();
  },

  /**
   * Render the order panel
   * @param {string} summary - Optional summary text
   */
  render(summary = '') {
    const { count, items, confirmBtn, summary: summaryEl } = this.elements;

    // Update summary
    summaryEl.textContent = summary || '';

    // No order - show empty state
    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      count.textContent = '(empty)';
      items.innerHTML = '<div style="color: #999; font-size: 12px; text-align: center; padding: 10px;">Ask for data to add items here</div>';
      confirmBtn.disabled = true;
      return;
    }

    // Has order - render items
    const orderItems = this.currentOrder.items;
    count.textContent = `(${orderItems.length} item${orderItems.length > 1 ? 's' : ''})`;
    confirmBtn.disabled = false;

    // Check if any items are invalid
    const hasInvalid = orderItems.some(item => item._valid === false);
    confirmBtn.disabled = hasInvalid;
    if (hasInvalid) {
      confirmBtn.title = 'Fix invalid items before displaying';
    } else {
      confirmBtn.title = '';
    }

    items.innerHTML = orderItems.map((item, index) => {
      // Show human-readable label only (column name hidden from user)
      const label = item.metric_label || item.metric || 'unknown';
      const region = item.region || 'global';
      // Handle year range (year_start/year_end) vs single year
      let year;
      if (item.year_start && item.year_end) {
        year = `${item.year_start}-${item.year_end}`;
      } else {
        year = item.year || 'latest';
      }
      const isValid = item._valid !== false;
      const error = item._error || '';

      // Format: Label | region | year (source shown in popup, not here)
      const name = label;
      const details = [region, year].filter(Boolean).join(' | ');

      const itemClass = isValid ? 'order-item' : 'order-item order-item-invalid';
      const errorHtml = error ? `<div class="order-item-error">${this.escapeHtml(error)}</div>` : '';

      return `
        <div class="${itemClass}">
          <div class="order-item-info">
            <div class="order-item-name">${this.escapeHtml(name)}</div>
            <div class="order-item-details">${this.escapeHtml(details)}</div>
            ${errorHtml}
          </div>
          <button class="order-item-remove" onclick="OrderManager.removeItem(${index})" title="Remove">x</button>
        </div>
      `;
    }).join('');
  },

  /**
   * Confirm and execute the order
   */
  async confirmOrder() {
    if (!this.currentOrder) return;

    const { confirmBtn } = this.elements;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Loading...';

    try {
      const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
        ? `${API_BASE_URL}/chat`
        : '/chat';

      console.log('Sending order:', JSON.stringify(this.currentOrder, null, 2));

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed_order: this.currentOrder
        })
      });

      const data = await response.json();

      console.log('Received response:', {
        type: data.type,
        multi_year: data.multi_year,
        has_year_data: !!data.year_data,
        year_range: data.year_range,
        feature_count: data.geojson?.features?.length
      });

      if (data.type === 'data' && data.geojson) {
        // Success - display data on map
        // Show data note if available (year range warnings, etc), otherwise just confirm load
        const message = data.data_note || `Loaded ${data.count || data.geojson.features?.length || 0} locations`;
        ChatManager.addMessage(message, 'assistant');
        App?.displayData(data);
        // Keep order visible - only Clear button should empty it
      } else if (data.type === 'error') {
        ChatManager.addMessage(data.message || 'Failed to load data.', 'assistant');
      }
    } catch (error) {
      console.error('Order execution error:', error);
      ChatManager.addMessage('Sorry, something went wrong executing the order.', 'assistant');
    } finally {
      confirmBtn.disabled = false;
      confirmBtn.textContent = 'Display on Map';
    }
  },

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
};

// Make OrderManager available globally for onclick handlers
if (typeof window !== 'undefined') {
  window.OrderManager = OrderManager;
}
