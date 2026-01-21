/**
 * Chat Panel - Sidebar chat functionality and order management.
 * Combines ChatManager and OrderManager for data request handling.
 */

import { CONFIG } from './config.js';
import { fetchMsgpack, postMsgpack, getApiCallsForRecovery, clearApiCalls } from './utils/fetch.js';

// Dependencies set via setDependencies to avoid circular imports
let MapAdapter = null;
let App = null;
let SelectionManager = null;
let OverlayController = null;
let OverlaySelector = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  App = deps.App;
  SelectionManager = deps.SelectionManager;
  OverlayController = deps.OverlayController;
  OverlaySelector = deps.OverlaySelector;
}

// ============================================================================
// CHAT MANAGER - Sidebar chat functionality
// ============================================================================

export const ChatManager = {
  history: [],
  sessionId: null,
  elements: {},
  lastDisambiguationOptions: null,  // Store options for "show them all" follow-up

  /**
   * Initialize chat manager
   */
  init() {
    // Restore or create session ID (persists across tab close/refresh)
    this.sessionId = this.getOrCreateSessionId();

    // Cache DOM elements
    this.elements = {
      sidebar: document.getElementById('sidebar'),
      toggle: document.getElementById('sidebarToggle'),
      close: document.getElementById('closeSidebar'),
      newChat: document.getElementById('newChatBtn'),
      messages: document.getElementById('chatMessages'),
      form: document.getElementById('chatForm'),
      input: document.getElementById('chatInput'),
      sendBtn: document.getElementById('sendBtn')
    };

    // Restore chat state from localStorage (survives browser close)
    this.restoreChatState();

    // Check if there are API calls to recover (map data)
    // Chat/overlays restore from localStorage, but map data needs to be re-fetched
    const apiCalls = getApiCallsForRecovery();
    if (apiCalls.length > 0) {
      this.showRecoveryPrompt(apiCalls.length);
    }

    this.setupEventListeners();
  },

  /**
   * Get existing session ID from localStorage or create a new one.
   * SessionId persists across tab close/refresh for session recovery.
   */
  getOrCreateSessionId() {
    const STORAGE_KEY = 'countymap_session_id';
    const TIMESTAMP_KEY = 'countymap_session_timestamp';

    // Check for existing session
    let sessionId = localStorage.getItem(STORAGE_KEY);
    const timestamp = localStorage.getItem(TIMESTAMP_KEY);

    // Check if session is too old (24 hours = 86400000 ms)
    const MAX_AGE_MS = 24 * 60 * 60 * 1000;
    const isExpired = timestamp && (Date.now() - parseInt(timestamp, 10)) > MAX_AGE_MS;

    if (sessionId && !isExpired) {
      // Update timestamp on reuse
      localStorage.setItem(TIMESTAMP_KEY, Date.now().toString());
      console.log('[Session] Restored session:', sessionId);
      return sessionId;
    }

    // Create new session
    sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
    localStorage.setItem(STORAGE_KEY, sessionId);
    localStorage.setItem(TIMESTAMP_KEY, Date.now().toString());
    console.log('[Session] Created new session:', sessionId);
    return sessionId;
  },

  /**
   * Clear current session and start fresh.
   * Called by "New Chat" button.
   */
  async clearSession() {
    const STORAGE_KEY = 'countymap_session_id';
    const TIMESTAMP_KEY = 'countymap_session_timestamp';

    const oldSessionId = this.sessionId;

    // Clear localStorage
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(TIMESTAMP_KEY);

    // Generate new session
    this.sessionId = this.getOrCreateSessionId();

    // Clear chat history
    this.history = [];
    this.lastDisambiguationOptions = null;

    // Clear UI
    if (this.elements.messages) {
      this.elements.messages.innerHTML = '';
    }

    // Clear order panel
    OrderManager.clearOrder();

    // Clear overlay selections (reset to defaults)
    if (window.OverlaySelector?.clearState) {
      window.OverlaySelector.clearState();
    }

    // Notify backend to clear old session cache (fire and forget)
    if (oldSessionId) {
      try {
        await postMsgpack('/api/session/clear', { sessionId: oldSessionId });
      } catch (e) {
        // Ignore errors - backend may not have the session
        console.log('[Session] Backend clear skipped:', e.message);
      }
    }

    // Clear localStorage chat state
    this.clearChatStorage();

    // Clear API call list for recovery
    clearApiCalls();

    // Clear slider settings (trim bounds, speed)
    if (window.TimeSlider?.clearSliderSettings) {
      window.TimeSlider.clearSliderSettings();
    }

    // Clear map view settings (globe, satellite)
    if (window.App?.clearMapViewSettings) {
      window.App.clearMapViewSettings();
    }

    console.log('[Session] Session cleared, new session:', this.sessionId);
    return this.sessionId;
  },

  /**
   * Save chat state to localStorage for persistence across browser close.
   * Called after each message is added.
   */
  saveChatState() {
    const CHAT_HISTORY_KEY = 'countymap_chat_history';
    const CHAT_MESSAGES_KEY = 'countymap_chat_messages';

    try {
      // Save history array (for API context)
      localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(this.history));

      // Save rendered messages HTML (for quick UI restore)
      if (this.elements.messages) {
        localStorage.setItem(CHAT_MESSAGES_KEY, this.elements.messages.innerHTML);
      }
    } catch (e) {
      // localStorage might be full or disabled
      console.warn('[Session] Could not save chat state:', e.message);
    }
  },

  /**
   * Restore chat state from localStorage.
   * Called on init to restore previous session.
   */
  restoreChatState() {
    const CHAT_HISTORY_KEY = 'countymap_chat_history';
    const CHAT_MESSAGES_KEY = 'countymap_chat_messages';

    try {
      // Restore history array
      const historyJson = localStorage.getItem(CHAT_HISTORY_KEY);
      if (historyJson) {
        this.history = JSON.parse(historyJson);
      }

      // Restore rendered messages HTML
      const messagesHtml = localStorage.getItem(CHAT_MESSAGES_KEY);
      if (messagesHtml && this.elements.messages) {
        this.elements.messages.innerHTML = messagesHtml;
        // Scroll to bottom
        this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
        console.log('[Session] Restored chat history:', this.history.length, 'messages');
        return true;
      }
    } catch (e) {
      console.warn('[Session] Could not restore chat state:', e.message);
    }
    return false;
  },

  /**
   * Clear localStorage chat state.
   */
  clearChatStorage() {
    const CHAT_HISTORY_KEY = 'countymap_chat_history';
    const CHAT_MESSAGES_KEY = 'countymap_chat_messages';

    localStorage.removeItem(CHAT_HISTORY_KEY);
    localStorage.removeItem(CHAT_MESSAGES_KEY);
  },

  /**
   * Show recovery prompt when there are API calls to replay.
   * Chat and overlays restore automatically from localStorage.
   * This prompt is for recovering map data by replaying API calls.
   * @param {number} callCount - Number of API calls to recover
   */
  showRecoveryPrompt(callCount) {
    const { messages } = this.elements;
    if (!messages) return;

    const dataSummary = `${callCount} data request${callCount === 1 ? '' : 's'}`;

    // Create recovery message with action buttons
    const div = document.createElement('div');
    div.className = 'chat-message assistant recovery-prompt';
    div.innerHTML = `
      <strong>Welcome Back</strong><br><br>
      Your previous session: <b>${dataSummary}</b><br><br>
      Type <b>"recover"</b> to reload your map data, or click <b>New Chat</b> above to start fresh.
      <div class="recovery-buttons" style="margin-top: 12px;">
        <button class="recovery-btn recover" data-action="recover">Recover Data</button>
      </div>
    `;

    messages.appendChild(div);

    // Add event listener to button
    div.querySelector('[data-action="recover"]').addEventListener('click', () => {
      this.handleRecoveryChoice('recover');
    });

    messages.scrollTop = messages.scrollHeight;
  },

  /**
   * Handle user's recovery choice.
   */
  async handleRecoveryChoice(choice) {
    const { messages } = this.elements;

    // Remove the recovery prompt
    const prompt = messages.querySelector('.recovery-prompt');
    if (prompt) {
      prompt.remove();
    }

    if (choice === 'recover') {
      // Get the list of API calls to replay
      const apiCalls = getApiCallsForRecovery();

      if (apiCalls.length === 0) {
        this.addMessage('No data to recover.', 'assistant');
        return;
      }

      // Parse URLs to extract overlay IDs and years
      // URLs look like: /api/earthquakes/geojson?min_magnitude=5.5&year=2021
      // Map API paths to overlay IDs (some differ, e.g. /api/storms/ -> hurricanes)
      const overlayYears = new Map(); // overlayId -> Set of years
      for (const url of apiCalls) {
        // Extract year parameter
        const yearMatch = url.match(/[?&]year=(\d+)/);
        if (!yearMatch) continue;
        const year = parseInt(yearMatch[1], 10);

        // Map URL path to overlay ID
        let overlayId = null;
        if (url.includes('/api/earthquakes/')) overlayId = 'earthquakes';
        else if (url.includes('/api/storms/')) overlayId = 'hurricanes';
        else if (url.includes('/api/volcanoes/')) overlayId = 'volcanoes';
        else if (url.includes('/api/wildfires/')) overlayId = 'wildfires';
        else if (url.includes('/api/tornadoes/')) overlayId = 'tornadoes';
        else if (url.includes('/api/tsunamis/')) overlayId = 'tsunamis';
        else if (url.includes('/api/floods/')) overlayId = 'floods';

        if (overlayId) {
          if (!overlayYears.has(overlayId)) {
            overlayYears.set(overlayId, new Set());
          }
          overlayYears.get(overlayId).add(year);
        }
      }

      // Count unique overlay-year combinations
      let totalLoads = 0;
      for (const years of overlayYears.values()) {
        totalLoads += years.size;
      }

      if (totalLoads === 0) {
        this.addMessage('No recoverable data found.', 'assistant');
        return;
      }

      // Show recovering message
      this.addMessage(
        `Recovering ${totalLoads} data set${totalLoads === 1 ? '' : 's'}...`,
        'assistant'
      );
      // Log overlay -> years mapping
      const logData = {};
      for (const [k, v] of overlayYears) logData[k] = Array.from(v);
      console.log('[Session] Recovering data:', logData);

      // Use OverlayController to properly load the data
      try {
        const loadPromises = [];
        for (const [overlayId, years] of overlayYears) {
          for (const year of years) {
            // Call OverlayController's load method through global reference
            if (OverlayController?.loadYearAndRender) {
              loadPromises.push(
                OverlayController.loadYearAndRender(overlayId, year).catch(e => {
                  console.warn('[Session] Failed to load:', overlayId, year, e.message);
                  return null;
                })
              );
            }
          }
        }

        const results = await Promise.all(loadPromises);
        const successCount = results.filter(r => r !== null).length;

        // Refresh time slider to show recovered data range
        if (window.OverlayController?.recalculateTimeRange) {
          window.OverlayController.recalculateTimeRange();
        }
        if (window.TimeSlider?.refreshDisplay) {
          window.TimeSlider.refreshDisplay();
        }

        this.addMessage(
          `Recovered ${successCount} of ${totalLoads} data set${totalLoads === 1 ? '' : 's'}.`,
          'assistant'
        );
        console.log('[Session] Recovery complete:', successCount, 'succeeded');
      } catch (e) {
        this.addMessage('Recovery failed: ' + e.message, 'assistant');
        console.error('[Session] Recovery failed:', e);
      }
    } else {
      // User wants fresh start - clear the session
      await this.clearSession();
      this.addMessage(
        'Welcome! I can help you explore geographic data.<br><br>' +
        'To build a map query, I need three things: <b>location</b> (where), ' +
        '<b>time period</b> (when), and <b>data</b> (what).<br><br>' +
        'Try: "What data do you have for Europe?" or "Show me CO2 emissions trends worldwide"',
        'assistant',
        { html: true }
      );
      console.log('[Session] User chose fresh start');
    }
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { sidebar, toggle, close, newChat, form, input } = this.elements;

    // Sidebar toggle
    toggle.addEventListener('click', () => {
      sidebar.classList.remove('collapsed');
      toggle.style.display = 'none';
    });

    close.addEventListener('click', () => {
      sidebar.classList.add('collapsed');
      toggle.style.display = 'flex';
    });

    // New Chat button - clear session and start fresh
    if (newChat) {
      newChat.addEventListener('click', async () => {
        if (confirm('Start a new chat? This will clear your current conversation.')) {
          await this.clearSession();
          // Show welcome message
          this.addMessage(
            'Welcome! I can help you explore geographic data.\n\n' +
            'Try: "What data do you have for Europe?" or "Show me CO2 emissions trends worldwide"',
            'assistant'
          );
        }
      });
    }

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

    // Check for "recover" command (case insensitive)
    if (query.toLowerCase() === 'recover') {
      input.value = '';
      this.handleRecoveryChoice('recover');
      return;
    }

    // Add user message
    this.addMessage(query, 'user');
    input.value = '';
    input.style.height = 'auto';

    // Disable input
    sendBtn.disabled = true;
    input.disabled = true;

    // Show staged loading indicator
    const indicator = this.showTypingIndicator(true);

    try {
      // Use streaming endpoint with progress updates
      const response = await this.sendQueryStreaming(query, (stage, message) => {
        indicator.updateStage(stage, message);
      });

      // Guard against null response
      if (!response) {
        throw new Error('No response received from server');
      }

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
          // Store options for potential "show them all" follow-up
          this.lastDisambiguationOptions = response.options || [];
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

        case 'drilldown':
          // Drill-down request - show children of a location (e.g., "texas counties")
          this.addMessage(response.message || 'Loading...', 'assistant');
          if (App && response.loc_id) {
            // Drill into the location to show its children
            App.drillDown(response.loc_id, response.name || response.loc_id);
          }
          break;

        case 'data':
          // Direct data response (from confirmed order)
          this.addMessage(response.summary || 'Here is your data.', 'assistant');
          App?.displayData(response);
          break;

        case 'events':
          // Event data response (earthquakes, volcanoes, etc.)
          this.addMessage(response.summary || `Showing ${response.count} ${response.event_type} events.`, 'assistant');
          App?.displayData(response);
          break;

        case 'cache_answer':
          // Answer from frontend cache (filter queries)
          this.addMessage(response.message || 'Here is the current state.', 'assistant');
          break;

        case 'filter_update':
          // Filter modification - apply to overlay and reload data
          this.addMessage(response.message || 'Updating filters.', 'assistant');
          this.applyFilterUpdate(response);
          break;

        case 'filter_existing':
          // Phase 7: Filter from cached data - no API call needed
          this.addMessage(response.message || 'Filtering cached data.', 'assistant');
          if (response.overlay && response.filters && OverlayController) {
            // Update display filters without clearing cache or reloading
            OverlayController.updateFilters(response.overlay, response.filters);
            // Re-render from existing cache with new filter
            OverlayController.rerenderFromCache?.();
            console.log(`ChatPanel: Applied filter to cached ${response.overlay} data (no API call)`);
          }
          break;

        case 'overlay_toggle':
          // Enable or disable an overlay from chat
          this.addMessage(response.message || (response.enabled ? 'Enabling overlay.' : 'Disabling overlay.'), 'assistant');
          if (response.overlay && OverlaySelector) {
            const isCurrentlyActive = OverlaySelector.isActive(response.overlay);
            if (response.enabled && !isCurrentlyActive) {
              // Turn it on
              OverlaySelector.toggle(response.overlay);
            } else if (!response.enabled && isCurrentlyActive) {
              // Turn it off
              OverlaySelector.toggle(response.overlay);
            }
            // Apply any filters that came with the toggle
            if (response.enabled && response.filters && OverlayController) {
              OverlayController.updateFilters(response.overlay, response.filters);
              OverlayController.reloadOverlay(response.overlay);
            }
          }
          break;

        case 'save_order':
          // User requested to save current order
          if (response.name) {
            const savedOrder = SavedOrdersManager.save(response.name);
            if (savedOrder) {
              this.addMessage(`Order saved as "${savedOrder.name}"`, 'assistant');
              OrderManager.updateSavedOrdersIndicator();
            } else {
              this.addMessage('No order to save.', 'assistant');
            }
          } else {
            // No name provided - prompt user
            OrderManager.promptSaveOrder();
          }
          break;

        case 'list_orders':
          // User requested to see saved orders
          const savedOrders = SavedOrdersManager.getAll();
          if (savedOrders.length === 0) {
            this.addMessage('No saved orders. Save an order first with "save as [name]".', 'assistant');
          } else {
            const names = savedOrders.map(o => `- ${o.name}`).join('\n');
            this.addMessage(`Saved orders:\n${names}`, 'assistant');
            OrderManager.showSavedOrdersList();
          }
          break;

        case 'load_order':
          // User requested to load a saved order
          if (response.name) {
            const order = SavedOrdersManager.load(response.name);
            if (order) {
              SavedOrdersManager.applyToOrderManager(order);
              this.addMessage(`Loaded saved order: "${order.name}"`, 'assistant');
            } else {
              this.addMessage(`No saved order found with name "${response.name}".`, 'assistant');
            }
          } else {
            // Show list for user to choose
            OrderManager.showSavedOrdersList();
          }
          break;

        case 'delete_order':
          // User requested to delete a saved order
          if (response.name) {
            if (SavedOrdersManager.delete(response.name)) {
              this.addMessage(`Deleted saved order: "${response.name}"`, 'assistant');
              OrderManager.updateSavedOrdersIndicator();
            } else {
              this.addMessage(`No saved order found with name "${response.name}".`, 'assistant');
            }
          } else {
            this.addMessage('Please specify which order to delete (e.g., "delete order California Analysis").', 'assistant');
          }
          break;

        case 'error':
          // Backend reported an error
          this.addMessage(response.message || 'An error occurred. Please try again.', 'assistant');
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

        case 'events':
          this.addMessage(response.summary || `Showing ${response.count} ${response.event_type} events.`, 'assistant');
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
      const geojson = await postMsgpack('/geometry/selection', { loc_ids: locIds });

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

    const data = await postMsgpack(apiUrl, {
      query,
      viewport: {
        center: { lat: view.center.lat, lng: view.center.lng },
        zoom: view.zoom,
        bounds: view.bounds,
        adminLevel: view.adminLevel
      },
      chatHistory: this.history.slice(-CONFIG.chatHistorySendLimit),
      sessionId: this.sessionId,
      // Disambiguation resolution - tell backend which location was selected
      resolved_location: {
        loc_id: location.loc_id,
        iso3: location.iso3,
        matched_term: location.matched_term,
        country_name: location.country_name
      },
      // Include active overlay state for context-aware responses
      activeOverlays: this.getActiveOverlays(),
      // Include cache stats so backend knows what's already loaded
      cacheStats: this.getCacheStats(),
      // Include saved order names for load/save commands
      savedOrderNames: SavedOrdersManager.getNames()
    });
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

    // Check if we have a navigation location selected (from "show me X" flow)
    const navLocations = OrderManager.currentOrder?.navigationLocations;
    let resolvedLocation = null;
    if (navLocations && navLocations.length === 1) {
      // Single location selected - use it as context for this query
      const loc = navLocations[0];
      resolvedLocation = {
        loc_id: loc.loc_id,
        iso3: loc.iso3,
        matched_term: loc.matched_term,
        country_name: loc.country_name
      };
    }

    const data = await postMsgpack(apiUrl, {
      query,
      viewport: {
        center: { lat: view.center.lat, lng: view.center.lng },
        zoom: view.zoom,
        bounds: view.bounds,  // {west, south, east, north}
        adminLevel: view.adminLevel
      },
      chatHistory: this.history.slice(-CONFIG.chatHistorySendLimit),
      sessionId: this.sessionId,
      // Include navigation location as resolved context if available
      resolved_location: resolvedLocation,
      // Include previous disambiguation options for "show them all" follow-up
      previous_disambiguation_options: this.lastDisambiguationOptions || [],
      // Include active overlay state for context-aware responses
      activeOverlays: this.getActiveOverlays(),
      // Include cache stats so backend knows what's already loaded
      cacheStats: this.getCacheStats(),
      // Include time slider state (live mode, current time)
      timeState: this.getTimeState(),
      // Include saved order names for load/save commands
      savedOrderNames: SavedOrdersManager.getNames()
    });
    this.history.push({ role: 'assistant', content: data.message || data.summary });

    return data;
  },

  /**
   * Send query to streaming API with progress updates
   * @param {string} query - The user query
   * @param {Function} onProgress - Callback for progress updates (stage, message)
   * @returns {Promise<Object>} The final result
   */
  async sendQueryStreaming(query, onProgress) {
    this.history.push({ role: 'user', content: query });

    const view = MapAdapter?.getView() || { center: { lat: 0, lng: 0 }, zoom: 2, bounds: null, adminLevel: 0 };
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat/stream`
      : '/chat/stream';

    // Check if we have a navigation location selected
    const navLocations = OrderManager.currentOrder?.navigationLocations;
    let resolvedLocation = null;
    if (navLocations && navLocations.length === 1) {
      const loc = navLocations[0];
      resolvedLocation = {
        loc_id: loc.loc_id,
        iso3: loc.iso3,
        matched_term: loc.matched_term,
        country_name: loc.country_name
      };
    }

    const requestBody = {
      query,
      viewport: {
        center: { lat: view.center.lat, lng: view.center.lng },
        zoom: view.zoom,
        bounds: view.bounds,
        adminLevel: view.adminLevel
      },
      chatHistory: this.history.slice(-CONFIG.chatHistorySendLimit),
      sessionId: this.sessionId,
      resolved_location: resolvedLocation,
      previous_disambiguation_options: this.lastDisambiguationOptions || [],
      activeOverlays: this.getActiveOverlays(),
      cacheStats: this.getCacheStats(),
      timeState: this.getTimeState(),
      savedOrderNames: SavedOrdersManager.getNames()
    };

    // Use fetch with streaming
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let result = null;
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE events
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';  // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));

            if (data.stage === 'complete') {
              result = data.result;
            } else if (onProgress) {
              onProgress(data.stage, data.message);
            }
          } catch (e) {
            console.warn('Failed to parse SSE data:', line);
          }
        }
      }
    }

    if (result) {
      this.history.push({ role: 'assistant', content: result.message || result.summary });
    }

    return result;
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

    // Save chat state to sessionStorage for page refresh restore
    this.saveChatState();

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
   * Show typing indicator with optional staged progress
   * @param {boolean} staged - If true, show staged indicator with text updates
   * @returns {Object} Indicator element with updateStage method
   */
  showTypingIndicator(staged = false) {
    const { messages } = this.elements;
    const indicator = document.createElement('div');
    indicator.className = staged ? 'loading-indicator' : 'typing-indicator';

    if (staged) {
      // Staged indicator with spinner and text
      indicator.innerHTML = `
        <div class="loading-spinner"></div>
        <span class="loading-text">Processing...</span>
      `;
      indicator.dataset.stage = 'initial';

      // Add method to update stage
      indicator.updateStage = (stage, message) => {
        indicator.dataset.stage = stage;
        const textEl = indicator.querySelector('.loading-text');
        if (textEl) textEl.textContent = message;
      };
    } else {
      // Classic bouncing dots
      indicator.innerHTML = '<span></span><span></span><span></span>';
    }

    messages.appendChild(indicator);
    messages.scrollTop = messages.scrollHeight;
    return indicator;
  },

  /**
   * Get active overlay state for chat context.
   * Returns which overlays are active and their current filter settings.
   * @returns {Object} Active overlay info {type, filters}
   */
  getActiveOverlays() {
    const activeList = OverlaySelector?.getActiveOverlays() || [];
    if (activeList.length === 0) {
      return { type: null, filters: {} };
    }

    // Primary overlay is first active one (most recently enabled)
    const primaryOverlay = activeList[0];

    // Get current filter params from OverlayController
    const filters = OverlayController?.getActiveFilters?.(primaryOverlay) || {};

    return {
      type: primaryOverlay,
      filters: filters,
      allActive: activeList  // In case multiple overlays are active
    };
  },

  /**
   * Get cache statistics for chat context.
   * Returns info about what data is currently loaded/displayed.
   * @returns {Object} Cache stats per overlay
   */
  getCacheStats() {
    if (!OverlayController) return {};

    const stats = {};
    const activeList = OverlaySelector?.getActiveOverlays() || [];

    for (const overlayId of activeList) {
      const cached = OverlayController.getCachedData(overlayId);
      if (cached && cached.features) {
        const features = cached.features;
        stats[overlayId] = {
          count: features.length,
          years: OverlayController.getLoadedYears(overlayId),
          // Phase 7: Include filter thresholds used at load time
          // This lets backend know what data is available for filtering vs what needs fetching
          loadedFilters: OverlayController.getLoadedFilters?.(overlayId) || {}
        };

        // Add overlay-specific stats from actual data (min/max in cache)
        if (overlayId === 'earthquakes') {
          const mags = features.map(f => f.properties?.magnitude).filter(m => m != null);
          if (mags.length > 0) {
            stats[overlayId].minMag = Math.min(...mags);
            stats[overlayId].maxMag = Math.max(...mags);
          }
        } else if (overlayId === 'hurricanes') {
          const cats = features.map(f => f.properties?.max_category).filter(c => c != null);
          if (cats.length > 0) {
            stats[overlayId].categories = [...new Set(cats)].sort();
          }
        } else if (overlayId === 'wildfires') {
          const areas = features.map(f => f.properties?.area_km2).filter(a => a != null);
          if (areas.length > 0) {
            stats[overlayId].minAreaKm2 = Math.min(...areas);
            stats[overlayId].maxAreaKm2 = Math.max(...areas);
          }
        } else if (overlayId === 'volcanoes') {
          const veis = features.map(f => f.properties?.vei).filter(v => v != null);
          if (veis.length > 0) {
            stats[overlayId].minVei = Math.min(...veis);
            stats[overlayId].maxVei = Math.max(...veis);
          }
        } else if (overlayId === 'tornadoes') {
          const scales = features.map(f => f.properties?.scale).filter(s => s != null);
          if (scales.length > 0) {
            stats[overlayId].scales = [...new Set(scales)].sort();
          }
        }
      }
    }

    return stats;
  },

  /**
   * Get current time slider state for chat context.
   * Returns live mode status, current time, and time range.
   * @returns {Object} Time state info
   */
  getTimeState() {
    const TimeSlider = window.TimeSlider;
    if (!TimeSlider) return { available: false };

    return {
      available: true,
      isLiveLocked: TimeSlider.isLiveLocked || false,
      isLiveMode: TimeSlider.isLiveMode || false,
      currentTime: TimeSlider.currentTime,
      currentTimeFormatted: TimeSlider.formatTimeLabel?.(TimeSlider.currentTime) || null,
      minTime: TimeSlider.minTime,
      maxTime: TimeSlider.maxTime,
      granularity: TimeSlider.granularity || 'yearly',
      timezone: TimeSlider.liveTimezone || 'local'
    };
  },

  /**
   * Apply filter update from chat response.
   * Updates overlay filters and triggers data reload.
   * @param {Object} response - Filter update response {overlay, filters}
   */
  applyFilterUpdate(response) {
    const { overlay, filters } = response;

    if (!OverlayController) {
      console.warn('OverlayController not available for filter update');
      return;
    }

    if (filters.clear) {
      // Clear filters and reload with defaults
      OverlayController.clearFilters?.(overlay);
    } else {
      // Apply new filters
      OverlayController.updateFilters?.(overlay, filters);
    }

    // Reload the overlay with new filters
    OverlayController.reloadOverlay?.(overlay);
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
      cancelBtn: document.getElementById('orderCancelBtn'),
      saveBtn: document.getElementById('orderSaveBtn'),
      savedOrdersList: document.getElementById('savedOrdersList'),
      savedOrdersItems: document.getElementById('savedOrdersItems'),
      savedOrdersClose: document.getElementById('savedOrdersClose'),
      savedOrdersIndicator: document.getElementById('savedOrdersIndicator'),
      savedOrdersCount: document.getElementById('savedOrdersCount'),
      savedOrdersToggle: document.getElementById('savedOrdersToggle'),
      cacheStatus: document.getElementById('cacheStatus'),
      cacheStatusText: document.getElementById('cacheStatusText')
    };

    this.setupEventListeners();
    this.render();
    this.updateCacheStatus();
    this.updateSaveButtonState();
    this.updateSavedOrdersIndicator();

    // Listen for cache updates from OverlayController
    window.addEventListener('overlayCacheUpdated', () => {
      this.updateCacheStatus();
    });
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { confirmBtn, cancelBtn, saveBtn, savedOrdersClose } = this.elements;

    confirmBtn.addEventListener('click', () => {
      this.confirmOrder();
    });

    cancelBtn.addEventListener('click', () => {
      this.clearOrder();
    });

    // Save button - prompts for name and saves order
    if (saveBtn) {
      saveBtn.addEventListener('click', () => {
        this.promptSaveOrder();
      });
    }

    // Close saved orders list
    if (savedOrdersClose) {
      savedOrdersClose.addEventListener('click', () => {
        this.hideSavedOrdersList();
      });
    }

    // Toggle saved orders list
    const { savedOrdersToggle } = this.elements;
    if (savedOrdersToggle) {
      savedOrdersToggle.addEventListener('click', () => {
        this.toggleSavedOrdersList();
      });
    }
  },

  /**
   * Prompt user for order name and save it.
   */
  promptSaveOrder() {
    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      ChatManager.addMessage('No order to save. Add some data first.', 'assistant');
      return;
    }

    const name = prompt('Enter a name for this saved order:');
    if (!name || !name.trim()) {
      return; // User cancelled or empty name
    }

    const savedOrder = SavedOrdersManager.save(name.trim());
    if (savedOrder) {
      ChatManager.addMessage(`Order saved as "${savedOrder.name}"`, 'assistant');
      this.updateSavedOrdersIndicator();
    }
  },

  /**
   * Show the saved orders list.
   */
  showSavedOrdersList() {
    const { savedOrdersList, savedOrdersItems } = this.elements;
    if (!savedOrdersList || !savedOrdersItems) return;

    const orders = SavedOrdersManager.getAll();

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

      // Add event listeners to the buttons
      savedOrdersItems.querySelectorAll('.saved-order-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const action = btn.dataset.action;
          const id = btn.dataset.id;
          if (action === 'load') {
            this.loadSavedOrder(id);
          } else if (action === 'delete') {
            this.deleteSavedOrder(id);
          }
        });
      });
    }

    savedOrdersList.style.display = 'block';
  },

  /**
   * Hide the saved orders list.
   */
  hideSavedOrdersList() {
    const { savedOrdersList } = this.elements;
    if (savedOrdersList) {
      savedOrdersList.style.display = 'none';
    }
  },

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
  },

  /**
   * Load a saved order by ID.
   * @param {string} orderId - ID of the order to load
   */
  loadSavedOrder(orderId) {
    const order = SavedOrdersManager.load(orderId);
    if (order) {
      SavedOrdersManager.applyToOrderManager(order);
      this.hideSavedOrdersList();
      ChatManager.addMessage(`Loaded saved order: "${order.name}"`, 'assistant');
    }
  },

  /**
   * Delete a saved order by ID.
   * @param {string} orderId - ID of the order to delete
   */
  deleteSavedOrder(orderId) {
    const orders = SavedOrdersManager.getAll();
    const order = orders.find(o => o.id === orderId);
    const name = order ? order.name : orderId;

    if (confirm(`Delete saved order "${name}"?`)) {
      if (SavedOrdersManager.delete(orderId)) {
        this.showSavedOrdersList(); // Refresh list
        this.updateSavedOrdersIndicator();
        ChatManager.addMessage(`Deleted saved order: "${name}"`, 'assistant');
      }
    }
  },

  /**
   * Update save button state based on current order.
   */
  updateSaveButtonState() {
    const { saveBtn } = this.elements;
    if (!saveBtn) return;

    const hasOrder = this.currentOrder && this.currentOrder.items && this.currentOrder.items.length > 0;
    saveBtn.disabled = !hasOrder;
  },

  /**
   * Update the saved orders indicator (shows count and toggle button).
   */
  updateSavedOrdersIndicator() {
    const { savedOrdersIndicator, savedOrdersCount } = this.elements;
    if (!savedOrdersIndicator || !savedOrdersCount) return;

    const orders = SavedOrdersManager.getAll();
    const count = orders.length;

    if (count === 0) {
      savedOrdersIndicator.style.display = 'none';
    } else {
      savedOrdersIndicator.style.display = 'flex';
      savedOrdersCount.textContent = `${count} saved order${count !== 1 ? 's' : ''}`;
    }
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

    // Clear navigation mode if active
    App?.clearNavigationMode();

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
   * Estimate order data size based on region (rough: ~1KB per location)
   * @param {Array} items - Order items
   * @returns {Object} { locations, estimatedKB }
   */
  estimateOrderSize(items) {
    // Rough location counts by region type
    const regionCounts = {
      'USA': 3200,      // ~3,200 counties
      'USA-CA': 58, 'USA-TX': 254, 'USA-FL': 67, 'USA-NY': 62, 'USA-PA': 67,
      'global': 5000,   // Rough estimate for global data
      'default': 100    // Default for unknown regions
    };

    let totalLocations = 0;
    for (const item of items) {
      const region = item.region || 'global';
      // Check for exact match, prefix match (USA-XX), or use default
      let count = regionCounts[region];
      if (!count) {
        // Check if it's a US state (USA-XX pattern)
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

    // Rough estimate: ~1KB per location
    const estimatedKB = totalLocations;
    return { locations: totalLocations, estimatedKB };
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

    // Has order - render items with size estimate
    const orderItems = this.currentOrder.items;
    const sizeEstimate = this.estimateOrderSize(orderItems);
    const sizeStr = sizeEstimate.estimatedKB >= 1024
      ? `~${(sizeEstimate.estimatedKB / 1024).toFixed(1)} MB`
      : `~${sizeEstimate.estimatedKB} KB`;
    count.textContent = `(${orderItems.length} item${orderItems.length > 1 ? 's' : ''}, ${sizeStr})`;
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

    // Update save button state after render
    this.updateSaveButtonState();
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

      const data = await postMsgpack(apiUrl, {
        confirmed_order: this.currentOrder,
        sessionId: ChatManager.sessionId
      });

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
        // Update cache status after loading data
        this.updateCacheStatus();
        // Keep order visible - only Clear button should empty it
      } else if (data.type === 'events' && data.geojson) {
        // Event data (earthquakes, volcanoes, etc.)
        const message = data.summary || `Showing ${data.count} ${data.event_type} events`;
        ChatManager.addMessage(message, 'assistant');
        App?.displayData(data);
        // Update cache status after loading events
        this.updateCacheStatus();
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
  },

  /**
   * Update the cache status display with current loaded data info.
   * Shows total features and memory usage from OverlayController.
   */
  updateCacheStatus() {
    const { cacheStatus, cacheStatusText } = this.elements;
    if (!cacheStatus || !cacheStatusText) return;

    try {
      // Get cache stats from OverlayController
      if (!OverlayController || !OverlayController.getCacheStats) {
        cacheStatusText.textContent = 'Cache: empty';
        cacheStatus.className = 'cache-status';
        return;
      }

      const stats = OverlayController.getCacheStats();
      const totalFeatures = stats.totals?.features || 0;
      const sizeMB = parseFloat(stats.totals?.sizeMB || 0);

      if (totalFeatures === 0) {
        cacheStatusText.textContent = 'Cache: empty';
        cacheStatus.className = 'cache-status';
      } else {
        // Format size nicely
        let sizeStr;
        if (sizeMB >= 1) {
          sizeStr = `${sizeMB.toFixed(1)} MB`;
        } else {
          const sizeKB = sizeMB * 1024;
          sizeStr = `${Math.round(sizeKB)} KB`;
        }

        cacheStatusText.textContent = `Cache: ${totalFeatures.toLocaleString()} features (${sizeStr})`;

        // Add warning class if cache is getting large (> 500 MB)
        if (sizeMB > 500) {
          cacheStatus.className = 'cache-status warning';
        } else {
          cacheStatus.className = 'cache-status has-data';
        }
      }
    } catch (error) {
      console.warn('Error updating cache status:', error);
      cacheStatusText.textContent = 'Cache: error';
    }
  },

  /**
   * Queue order for background processing (Phase 2 async mode)
   * Use this instead of confirmOrder() for non-blocking execution.
   */
  async queueOrder() {
    if (!this.currentOrder) return;

    const { confirmBtn } = this.elements;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Queueing...';

    try {
      const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
        ? `${API_BASE_URL}/api/orders/queue`
        : '/api/orders/queue';

      const data = await postMsgpack(apiUrl, {
        items: this.currentOrder.items,
        hints: { summary: this.currentOrder.summary },
        session_id: ChatManager.sessionId
      });

      if (data.queue_id) {
        console.log('Order queued:', data.queue_id, 'position:', data.position);
        ChatManager.addMessage(
          data.position > 1
            ? `Order queued (position ${data.position}). You can continue chatting while it loads.`
            : 'Order queued. Processing...',
          'assistant'
        );

        // Track the order for status updates
        OrderTracker.addOrder(data.queue_id, {
          items: this.currentOrder.items,
          summary: this.currentOrder.summary
        });

        confirmBtn.textContent = 'Queued';
      } else {
        throw new Error('No queue_id returned');
      }
    } catch (error) {
      console.error('Queue error:', error);
      ChatManager.addMessage('Failed to queue order. Try again.', 'assistant');
      confirmBtn.textContent = 'Display on Map';
    } finally {
      confirmBtn.disabled = false;
    }
  }
};

// Make OrderManager available globally for onclick handlers
if (typeof window !== 'undefined') {
  window.OrderManager = OrderManager;
}


// ============================================================================
// ORDER TRACKER - Background order queue polling (Phase 2)
// ============================================================================

export const OrderTracker = {
  pendingOrders: new Map(),  // queue_id -> order info
  pollInterval: null,
  pollIntervalMs: 500,  // Check every 500ms

  /**
   * Add an order to tracking and start polling
   * @param {string} queueId - Queue ID from backend
   * @param {Object} orderInfo - Order metadata for display
   */
  addOrder(queueId, orderInfo) {
    this.pendingOrders.set(queueId, {
      ...orderInfo,
      status: 'pending',
      progress: 0,
      addedAt: Date.now()
    });
    this.startPolling();
    this.renderStatus(queueId);
  },

  /**
   * Start polling for order status updates
   */
  startPolling() {
    if (this.pollInterval) return;  // Already polling

    this.pollInterval = setInterval(() => this.checkOrders(), this.pollIntervalMs);
    console.log('OrderTracker: Started polling');
  },

  /**
   * Stop polling when no orders pending
   */
  stopPolling() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
      console.log('OrderTracker: Stopped polling');
    }
  },

  /**
   * Check status of all pending orders
   */
  async checkOrders() {
    if (this.pendingOrders.size === 0) {
      this.stopPolling();
      return;
    }

    const queueIds = Array.from(this.pendingOrders.keys());

    try {
      const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
        ? `${API_BASE_URL}/api/orders/status`
        : '/api/orders/status';

      const statuses = await postMsgpack(apiUrl, { queue_ids: queueIds });

      for (const [queueId, status] of Object.entries(statuses)) {
        const order = this.pendingOrders.get(queueId);
        if (!order) continue;

        // Update local state
        order.status = status.status;
        order.progress = status.progress || 0;
        order.message = status.message;

        // Update UI
        this.renderStatus(queueId);

        // Handle completion
        if (status.status === 'complete') {
          this.onOrderReady(queueId, status.result);
          this.pendingOrders.delete(queueId);
        } else if (status.status === 'failed') {
          this.onOrderFailed(queueId, status.error);
          this.pendingOrders.delete(queueId);
        } else if (status.status === 'cancelled') {
          this.pendingOrders.delete(queueId);
        }
      }
    } catch (error) {
      console.error('OrderTracker: Poll error', error);
    }
  },

  /**
   * Render status in the order panel
   * @param {string} queueId - Queue ID to render
   */
  renderStatus(queueId) {
    const order = this.pendingOrders.get(queueId);
    if (!order) return;

    // Find or create status element
    let statusEl = document.getElementById(`queue-status-${queueId}`);
    if (!statusEl) {
      statusEl = document.createElement('div');
      statusEl.id = `queue-status-${queueId}`;
      statusEl.className = 'order-queue-status';

      // Insert at top of order items
      const orderItems = document.getElementById('orderItems');
      if (orderItems) {
        orderItems.insertBefore(statusEl, orderItems.firstChild);
      }
    }

    const progressPercent = Math.round(order.progress * 100);
    const statusMessages = {
      'pending': 'Queued',
      'executing': 'Processing...',
      'complete': 'Ready!',
      'failed': 'Failed'
    };

    statusEl.innerHTML = `
      <div class="queue-status-header">
        <span class="queue-status-label">${statusMessages[order.status] || order.status}</span>
        <span class="queue-status-progress">${progressPercent}%</span>
      </div>
      <div class="queue-progress-bar">
        <div class="queue-progress-fill" style="width: ${progressPercent}%"></div>
      </div>
      ${order.message ? `<div class="queue-status-message">${order.message}</div>` : ''}
    `;

    // Update styling based on status
    statusEl.className = `order-queue-status status-${order.status}`;
  },

  /**
   * Handle completed order - display data
   * @param {string} queueId - Queue ID
   * @param {Object} result - Result data from backend
   */
  onOrderReady(queueId, result) {
    console.log(`OrderTracker: Order ${queueId} ready`, result);

    // Remove status element
    const statusEl = document.getElementById(`queue-status-${queueId}`);
    if (statusEl) statusEl.remove();

    // Display the data
    if (result && (result.type === 'data' || result.type === 'events')) {
      const count = result.count || result.geojson?.features?.length || 0;
      ChatManager.addMessage(`Loaded ${count} locations.`, 'assistant');
      App?.displayData(result);
    }
  },

  /**
   * Handle failed order
   * @param {string} queueId - Queue ID
   * @param {string} error - Error message
   */
  onOrderFailed(queueId, error) {
    console.error(`OrderTracker: Order ${queueId} failed:`, error);

    // Remove status element after brief display
    setTimeout(() => {
      const statusEl = document.getElementById(`queue-status-${queueId}`);
      if (statusEl) statusEl.remove();
    }, 3000);

    ChatManager.addMessage(`Order failed: ${error || 'Unknown error'}`, 'assistant');
  },

  /**
   * Cancel a pending order
   * @param {string} queueId - Queue ID to cancel
   */
  async cancel(queueId) {
    try {
      const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
        ? `${API_BASE_URL}/api/orders/cancel`
        : '/api/orders/cancel';

      await postMsgpack(apiUrl, { queue_id: queueId });
      this.pendingOrders.delete(queueId);

      const statusEl = document.getElementById(`queue-status-${queueId}`);
      if (statusEl) statusEl.remove();

    } catch (error) {
      console.error('OrderTracker: Cancel error', error);
    }
  },

  /**
   * Get queue statistics
   */
  getStats() {
    return {
      pending: this.pendingOrders.size,
      isPolling: this.pollInterval !== null
    };
  }
};

// Make OrderTracker available globally
if (typeof window !== 'undefined') {
  window.OrderTracker = OrderTracker;
}


// ============================================================================
// SAVED ORDERS MANAGER - Persist order recipes for recall (Phase 7)
// ============================================================================

export const SavedOrdersManager = {
  STORAGE_KEY: 'countymap_saved_orders',

  /**
   * Get all saved orders from localStorage.
   * @returns {Array} Array of saved order objects
   */
  getAll() {
    try {
      const data = localStorage.getItem(this.STORAGE_KEY);
      return data ? JSON.parse(data) : [];
    } catch (error) {
      console.error('[SavedOrders] Failed to load:', error);
      return [];
    }
  },

  /**
   * Save current order with a name.
   * @param {string} name - Name for the saved order
   * @param {Object} options - Optional additional data (hints, map_state)
   * @returns {Object} The saved order object
   */
  save(name, options = {}) {
    if (!OrderManager.currentOrder) {
      console.warn('[SavedOrders] No current order to save');
      return null;
    }

    const orders = this.getAll();

    // Check for duplicate name
    const existingIndex = orders.findIndex(o => o.name === name);

    const savedOrder = {
      id: 'order_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
      name: name,
      items: JSON.parse(JSON.stringify(OrderManager.currentOrder.items)),
      summary: OrderManager.currentOrder.summary,
      hints: options.hints || {},
      map_state: options.map_state || null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };

    if (existingIndex >= 0) {
      // Update existing
      savedOrder.id = orders[existingIndex].id;
      savedOrder.created_at = orders[existingIndex].created_at;
      orders[existingIndex] = savedOrder;
      console.log('[SavedOrders] Updated:', name);
    } else {
      // Add new
      orders.push(savedOrder);
      console.log('[SavedOrders] Created:', name);
    }

    this._persist(orders);
    return savedOrder;
  },

  /**
   * Load a saved order by name or id.
   * @param {string} nameOrId - Name or ID of the order to load
   * @returns {Object|null} The saved order or null if not found
   */
  load(nameOrId) {
    const orders = this.getAll();
    const order = orders.find(o => o.name === nameOrId || o.id === nameOrId);

    if (!order) {
      console.warn('[SavedOrders] Not found:', nameOrId);
      return null;
    }

    console.log('[SavedOrders] Loaded:', order.name);
    return order;
  },

  /**
   * Delete a saved order by name or id.
   * @param {string} nameOrId - Name or ID of the order to delete
   * @returns {boolean} True if deleted, false if not found
   */
  delete(nameOrId) {
    const orders = this.getAll();
    const index = orders.findIndex(o => o.name === nameOrId || o.id === nameOrId);

    if (index < 0) {
      console.warn('[SavedOrders] Not found for deletion:', nameOrId);
      return false;
    }

    const deleted = orders.splice(index, 1)[0];
    this._persist(orders);
    console.log('[SavedOrders] Deleted:', deleted.name);
    return true;
  },

  /**
   * Get names of all saved orders (for LLM context).
   * @returns {Array<string>} Array of saved order names
   */
  getNames() {
    return this.getAll().map(o => o.name);
  },

  /**
   * Apply a saved order to the current OrderManager state.
   * @param {Object} savedOrder - The saved order object
   */
  applyToOrderManager(savedOrder) {
    if (!savedOrder || !savedOrder.items) {
      console.warn('[SavedOrders] Invalid order to apply');
      return false;
    }

    // Set as current order
    OrderManager.currentOrder = {
      items: JSON.parse(JSON.stringify(savedOrder.items)),
      summary: savedOrder.summary || 'Loaded saved order: ' + savedOrder.name
    };

    // Render the order panel
    OrderManager.showOrder({
      type: 'order',
      items: OrderManager.currentOrder.items,
      summary: OrderManager.currentOrder.summary
    });

    console.log('[SavedOrders] Applied to OrderManager:', savedOrder.name);
    return true;
  },

  /**
   * Persist orders to localStorage.
   * @private
   */
  _persist(orders) {
    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(orders));
    } catch (error) {
      console.error('[SavedOrders] Failed to persist:', error);
    }
  },

  /**
   * Clear all saved orders.
   */
  clearAll() {
    localStorage.removeItem(this.STORAGE_KEY);
    console.log('[SavedOrders] Cleared all');
  },

  /**
   * Get statistics about saved orders.
   * @returns {Object} Stats object
   */
  getStats() {
    const orders = this.getAll();
    return {
      count: orders.length,
      names: orders.map(o => o.name),
      totalItems: orders.reduce((sum, o) => sum + (o.items?.length || 0), 0)
    };
  }
};

// Make SavedOrdersManager available globally
if (typeof window !== 'undefined') {
  window.SavedOrdersManager = SavedOrdersManager;
}
