/**
 * Chat Panel - Sidebar chat functionality and order management.
 * Combines ChatManager and OrderManager for data request handling.
 */

import { CONFIG } from './config.js';

// Dependencies set via setDependencies to avoid circular imports
let MapAdapter = null;
let App = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  App = deps.App;
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
   * Send query to API
   */
  async sendQuery(query) {
    this.history.push({ role: 'user', content: query });

    const view = MapAdapter?.getView() || { center: { lat: 0, lng: 0 }, zoom: 2 };
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat`
      : '/chat';

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        currentView: {
          clat: view.center.lat,
          clng: view.center.lng,
          czoom: view.zoom
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

    if (!this.currentOrder || !this.currentOrder.items) {
      // No existing order - use the new one
      this.currentOrder = order;
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
    }

    this.render(summary);
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
