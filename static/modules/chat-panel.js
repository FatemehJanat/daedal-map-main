/**
 * Chat Panel - Sidebar chat functionality and order management.
 * Map-specific orchestrator that imports reusable chat/order modules.
 */

import { CONFIG } from './config.js';
import { postMsgpack, getApiCallsForRecovery, clearApiCalls, logExecutedOrder, getExecutedOrdersForRecovery, clearExecutedOrders } from './utils/fetch.js';

// Reusable modules
import {
  getOrCreateSessionId,
  resetSessionId,
  saveChatState,
  restoreChatState,
  clearChatStorage
} from './chat/session.js';

import {
  addMessage as renderMessage,
  formatMessage,
  showTypingIndicator as renderTypingIndicator
} from './chat/message-renderer.js';

import { sendStreamingRequest, sendChatRequest } from './chat/api.js';
import { OrderPanel } from './order/manager.js';
import { OrderTracker as OrderTrackerClass } from './order/tracker.js';
import * as SavedOrders from './order/saved.js';
import { ensureRuntimeAccessToken, getAccessToken, getCurrentUser, getSupabaseClient, isAuthBootPending, isAuthenticated, onAuthChanged, refreshRuntimeSession, waitForAuthBoot } from './auth.js';
import { TutorialMode, parseTutorialCommand } from './tutorial-mode.js';
import { ResearchModeToggle } from './research/mode.js';
import {
  getBrowserCorpusSnapshot,
  getBrowserCorpusStorageSummary,
  listBrowserCorpusSummaries,
  removeBrowserCorpusSnapshot,
  saveBrowserCorpusSnapshot
} from './research/browser-corpus-store.js';
import { getResearchPackCatalogMap } from './shared/research-pack-cache.js';

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

// Welcome message shown on first load and new chat
const WELCOME_MESSAGE =
  'Welcome! Ask me anything about global data -- earthquakes, hurricanes, ' +
  'climate indicators, and more. Enable the Demographics overlay to zoom through ' +
  'the countries, states, and territories.<br><br>' +
  'To explore datasets, type a question in natural language. ' +
  'Type "help" or "how do you work?" anytime for a full guide.<br><br>' +
  '<div class="welcome-action-row">' +
  '<button class="chat-action-btn" data-action="preload-disasters-2020">Load disasters 2020-2025</button> ' +
  '<button id="tutorialToggleBtn" class="chat-action-btn tutorial-toggle-btn" data-action="tutorial-toggle" type="button" aria-pressed="false">Tutorial Off</button>' +
  '</div>';

// Map event_type from API responses to overlay IDs
const EVENT_TYPE_TO_OVERLAY = {
  earthquake: 'earthquakes',
  volcano: 'volcanoes',
  tsunami: 'tsunamis',
  hurricane: 'hurricanes',
  wildfire: 'wildfires',
  tornado: 'tornadoes',
  flood: 'floods',
  drought: 'drought',
  landslide: 'landslides'
};

function normalizeResearchHistory(history) {
  return (history || [])
    .map(msg => ({
      role: msg?.role === 'assistant' ? 'assistant' : 'user',
      content: String(msg?.content || '').replace(/\s+/g, ' ').trim()
    }))
    .filter(msg => msg.content);
}

function clipResearchMemoryText(text, maxLen = 220) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  if (normalized.length <= maxLen) return normalized;
  return normalized.slice(0, maxLen - 3).trimEnd() + '...';
}

function uniqueResearchLines(values, maxItems) {
  const lines = [];
  for (const value of values || []) {
    const clipped = clipResearchMemoryText(value);
    if (!clipped || lines.includes(clipped)) continue;
    lines.push(clipped);
    if (lines.length >= maxItems) break;
  }
  return lines;
}

function buildResearchMemoryFromHistory(history) {
  const normalized = normalizeResearchHistory(history);
  const recentLimit = CONFIG.research?.recentHistorySendLimit || CONFIG.chatHistorySendLimit;
  const trigger = CONFIG.research?.compactionTriggerMessages || recentLimit;
  const recentHistory = normalized.slice(-recentLimit);
  const olderHistory = normalized.slice(0, Math.max(0, normalized.length - recentLimit));
  const originalGoal = normalized.find(msg => msg.role === 'user')?.content || '';

  if (olderHistory.length < trigger) {
    return {
      chatHistory: recentHistory,
      researchMemory: originalGoal
        ? {
            originalGoal,
            summary: '',
            compactedMessageCount: 0,
            totalMessageCount: normalized.length
          }
        : null
    };
  }

  const maxBullets = CONFIG.research?.maxSummaryBullets || 4;
  const olderUserTurns = olderHistory.filter(msg => msg.role === 'user').map(msg => msg.content);
  const olderAssistantTurns = olderHistory.filter(msg => msg.role === 'assistant').map(msg => msg.content);
  const recentQuestions = uniqueResearchLines(olderUserTurns.slice(-maxBullets), maxBullets);
  const recentFindings = uniqueResearchLines(olderAssistantTurns.slice(-maxBullets), maxBullets);

  const summaryParts = [];
  if (recentQuestions.length) {
    summaryParts.push(`Earlier questions:\n- ${recentQuestions.join('\n- ')}`);
  }
  if (recentFindings.length) {
    summaryParts.push(`Earlier findings and replies:\n- ${recentFindings.join('\n- ')}`);
  }

  let summary = summaryParts.join('\n\n').trim();
  const maxSummaryChars = CONFIG.research?.maxSummaryChars || 1800;
  if (summary.length > maxSummaryChars) {
    summary = summary.slice(0, maxSummaryChars - 3).trimEnd() + '...';
  }

  return {
    chatHistory: recentHistory,
    researchMemory: {
      originalGoal,
      summary,
      compactedMessageCount: olderHistory.length,
      totalMessageCount: normalized.length
    }
  };
}

function normalizeResearchColorHex(color) {
  return String(color || '').trim().toLowerCase();
}

function getResearchNamedColors() {
  return {
    red: '#ef4444',
    blue: '#3b82f6',
    green: '#10b981',
    orange: '#f59e0b',
    yellow: '#eab308',
    purple: '#8b5cf6',
    pink: '#ec4899',
    cyan: '#06b6d4',
    teal: '#14b8a6'
  };
}

// =============================================================================
// Loaded Data Tracker - tracks what data has been loaded for LLM context
// =============================================================================

/**
 * Tracks loaded data for LLM context.
 * Each entry: { source_id, source_name, region, metric, years, data_type, overlay_type }
 */
let loadedDataList = [];
let researchPackCatalogById = new Map();

/**
 * Register loaded data from an executed order.
 * Called when orders complete successfully.
 * @param {Object} order - The executed order
 * @param {Object} response - The API response
 */
function registerLoadedData(order, response) {
  if (!order?.items) return;

  const dataType = response?.data_type || 'metrics';

  for (const item of order.items) {
    // Skip removal items
    if (item.action === 'remove') continue;

    const entry = {
      source_id: item.source_id,
      region: item.region || 'global',
      metric: item.metric_label || item.metric || null,
      data_type: dataType,
      overlay_type: item.overlay_type || null
    };

    // Add year info
    if (item.year_start && item.year_end) {
      entry.years = `${item.year_start}-${item.year_end}`;
    } else if (item.year) {
      entry.years = String(item.year);
    } else {
      entry.years = 'latest';
    }

    // Dedupe: don't add if same source+region+metric already exists
    const exists = loadedDataList.some(e =>
      e.source_id === entry.source_id &&
      e.region === entry.region &&
      e.metric === entry.metric
    );

    if (!exists) {
      loadedDataList.push(entry);
      console.log('[LoadedData] Registered:', entry);
    }
  }
}

/**
 * Remove loaded data entries matching criteria.
 * Called when removal orders complete.
 * @param {Object} order - The removal order
 */
function unregisterLoadedData(order) {
  if (!order?.items) return;

  for (const item of order.items) {
    if (item.action !== 'remove') continue;

    const sourceId = item.source_id;
    const region = item.region;

    // Remove matching entries
    const before = loadedDataList.length;
    loadedDataList = loadedDataList.filter(e =>
      !(e.source_id === sourceId && (e.region === region || region === 'global'))
    );

    if (loadedDataList.length < before) {
      console.log('[LoadedData] Unregistered:', { source_id: sourceId, region });
    }
  }
}

/**
 * Get loaded data summary for LLM context.
 * @returns {Array} List of loaded data entries
 */
export function getLoadedDataList() {
  return [...loadedDataList];
}

/**
 * Clear all loaded data (on session reset).
 */
export function clearLoadedDataList() {
  loadedDataList = [];
  console.log('[LoadedData] Cleared');
}

/**
 * Route event-type order results to OverlayController for cache ingestion.
 * @param {Object} response - API response with data_type 'events'
 */
function ingestEventsToOverlay(response) {
  if (!OverlayController?.ingestOrderResult) return;
  if (!response?.geojson?.features) return;

  // Use source_id from response, fall back to event_type mapping for legacy support
  const overlayId = response.source_id || EVENT_TYPE_TO_OVERLAY[response.event_type];
  if (!overlayId) {
    console.warn('ingestEventsToOverlay: No overlayId for response', response.source_id, response.event_type);
    return;
  }

  // Build range metadata from response if available
  const rangeMeta = (response.time_range && response.time_range.min && response.time_range.max)
    ? { start: response.time_range.min, end: response.time_range.max }
    : (response.year_range && response.year_range.length === 2)
      ? { start: new Date(response.year_range[0], 0, 1).getTime(),
          end: new Date(response.year_range[1], 11, 31).getTime() }
      : null;

  OverlayController.ingestOrderResult(overlayId, response.geojson, rangeMeta);
}

/**
 * Route metrics order results to OverlayController for cache ingestion.
 * @param {Object} response - API response with data_type 'metrics'
 */
function ingestMetricsToCache(response) {
  if (!OverlayController?.ingestMetricData) return;
  if (!response?.geojson?.features) return;

  const sourceId = response.source_id;
  if (!sourceId) {
    console.warn('ingestMetricsToCache: No source_id in response');
    return;
  }

  // Build year range metadata
  const yearRange = response.year_range || null;

  OverlayController.ingestMetricData(sourceId, response.geojson, response.year_data, yearRange);
}

/**
 * Route geometry order results to OverlayController for rendering.
 * Backend SessionCache handles deduplication - this just renders.
 * @param {Object} response - API response with data_type 'geometry'
 */
function renderGeometryOrder(response) {
  if (!OverlayController?.renderGeometryData) return;
  if (!response?.geojson?.features) return;

  const sourceId = response.source_id || 'geometry_zcta';
  const geometryType = response.overlay_type || response.geographic_level || 'zcta';

  // Render geometry (backend handles dedup via SessionCache)
  OverlayController.renderGeometryData(sourceId, response.geojson, geometryType, {});
}

// Module-level instances (created during init)
let orderPanel = null;
let orderTracker = null;
let researchModeToggle = null;

// ============================================================================
// CHAT MANAGER - Sidebar chat functionality (map-specific orchestrator)
// ============================================================================

export const ChatManager = {
  history: [],
  mode: 'explore',
  modeHistories: { explore: [], research: [] },
  modeMessagesHtml: { explore: '', research: '' },
  modeRequestInFlight: { explore: false, research: false },
  pendingResearchRasterMode: null,
  researchMemory: null,
  selectedResearchCorpusId: '',
  researchCorpusOptions: [],
  latestResearchManifest: null,
  lastResearchDisplay: null,
  browserCorpusSummaries: new Map(),
  pendingMetricOrder: null,
  pendingResearchDisplayWarning: null,
  sessionId: null,
  researchCorpusOptionsLoading: false,
  messagePanes: {},
  elements: {},
  lastDisambiguationOptions: null,
  addressContext: null,
  addressMarker: null,
  googleMapsLoader: null,

  /**
   * Initialize chat manager
   */
  init() {
    this.sessionId = getOrCreateSessionId();

    // Cache DOM elements
    this.elements = {
      sidebar: document.getElementById('sidebar'),
      toggle: document.getElementById('sidebarToggle'),
      close: document.getElementById('closeSidebar'),
      messagesHost: document.getElementById('chatMessages'),
      messages: null,
      form: document.getElementById('chatForm'),
      input: document.getElementById('chatInput'),
      sendBtn: document.getElementById('sendBtn'),
      resizeOrder: document.getElementById('resizeOrder'),
      orderPanel: document.getElementById('orderPanel')
    };
    this.initMessagePanes();

    // Restore minimal chat UI state from localStorage
    this.restoreState();
    this.syncAllMessagePanes();
    this.setActiveMessagePane(this.mode);

    this.initModeToggle();
    if (this.mode === 'research') {
      App?.enterResearchCanvasMode?.();
    } else {
      App?.leaveResearchCanvasMode?.();
    }
    Promise.resolve(this.seedEmptyConversation(this.mode)).catch((error) => {
      console.warn('Could not seed initial conversation:', error);
    });
    this.syncSidebarToggleVisibility();
    this.updateSidebarModeLayout();
    this.updateComposerState();

    // Setup UI event listeners
    this.setupEventListeners();

    // Initialize order panel and tracker
    this.initOrderPanel();

    onAuthChanged((event) => {
      Promise.resolve().then(async () => {
        const authState = Boolean(event?.detail?.isAuthenticated);
        try {
          await this.refreshResearchCorpusOptions();
          if (this.mode === 'research') {
            await this.refreshResearchManifest();
          }
          this.updateComposerState();
        } catch (error) {
          console.warn('Could not refresh chat state after auth change:', error);
        }

        if (!authState && this.mode === 'research') {
          this.updateResearchCorpusStatus();
        }
      });
    });
  },

  /**
   * Initialize Explore/Research chat mode toggle.
   */
  initModeToggle() {
    researchModeToggle = new ResearchModeToggle({
      container: document.getElementById('chatContainer'),
      getSessionId: () => this.getSessionIdForMode('research'),
      onModeChange: async (mode) => {
        await this.switchChatMode(mode);
      },
      onLoadCorpus: async (corpusId) => {
        await this.loadSelectedResearchCorpus(corpusId);
      },
      onSelectCorpus: async (corpusId) => {
        this.selectedResearchCorpusId = corpusId || '';
        this.updateResearchCorpusStatus();
        this.saveState();
      },
      onSaveCorpus: async (corpusId) => {
        await this.saveResearchCorpusToBrowser(corpusId);
      },
      onSyncCorpus: async (corpusId) => {
        await this.syncResearchCorpusBrowserCopy(corpusId);
      },
      onRemoveBrowserCopy: async (corpusId) => {
        await this.removeResearchCorpusBrowserCopy(corpusId);
      }
    });
    researchModeToggle.mode = this.mode;
    researchModeToggle.init();
    researchModeToggle.setSelectedCorpusId(this.selectedResearchCorpusId);
    researchModeToggle.setCorpusOptions(this.researchCorpusOptions, this.selectedResearchCorpusId);
    this.updateResearchCorpusStatus();
  },

  async switchChatMode(mode) {
    if (mode !== 'explore' && mode !== 'research') return;
    if (mode === this.mode) return;

    this.syncModeMessagesHtml(this.mode);
    this.modeHistories[this.mode] = this.history;

    this.mode = mode;
    this.history = this.modeHistories[mode] || [];
    this.setActiveMessagePane(mode);
    if (mode !== 'research') {
      this.researchMemory = this.researchMemory || null;
    }

    if (mode === 'research') {
      App?.enterResearchCanvasMode?.();
      await this.refreshResearchCorpusOptions();
    } else {
      App?.leaveResearchCanvasMode?.();
    }

    if (this.history.length === 0 && !this.modeMessagesHtml[mode]) {
      await this.seedEmptyConversation(mode);
    }

    this.updateResearchCorpusStatus();
    this.updateSidebarModeLayout();
    this.updateComposerState();
    this.saveState();
  },

  async seedEmptyConversation(mode = this.mode) {
    const pane = this.messagePanes?.[mode];
    if (pane && pane.childElementCount > 0) return;

    if (mode === 'research') {
      try {
        await this.refreshResearchCorpusOptions();
        const manifest = await this.refreshResearchManifest();
        if ((manifest?.artifact_count || 0) > 0 && !manifest?.stale_artifacts) {
          this.addMessage(`Research mode ready. Active corpus: ${manifest.artifact_count} loaded artifact${manifest.artifact_count === 1 ? '' : 's'}.`, 'assistant', { mode: 'research' });
          return;
        }
        if (manifest?.saved_corpus) {
          const saved = manifest.saved_corpus;
          const message = manifest?.stale_artifacts
            ? `Research workspace found an out-of-date local session for "${saved.name}". Click Load Data to refresh it.`
            : `Research workspace ready. "${saved.name}" is selected. Click Load Data to activate it for this session.`;
          this.addMessage(message, 'assistant', { mode: 'research' });
          return;
        }
        this.addMessage(this.getResearchEmptyStateMessage(), 'assistant', { mode: 'research' });
      } catch (error) {
        console.warn('Research corpus snapshot failed:', error);
        this.addMessage('Research mode is available, but I could not read the active corpus yet.', 'assistant', { mode: 'research' });
      }
      return;
    }

    this.addMessage(WELCOME_MESSAGE, 'assistant', { html: true, mode: 'explore' });
  },

  initMessagePanes() {
    const host = this.elements.messagesHost;
    if (!host) return;
    host.innerHTML = '';
    this.messagePanes = {};
    for (const mode of ['explore', 'research']) {
      const pane = document.createElement('div');
      pane.className = 'chat-messages-pane';
      pane.dataset.chatMode = mode;
      pane.hidden = mode !== this.mode;
      host.appendChild(pane);
      this.messagePanes[mode] = pane;
    }
    this.elements.messages = this.messagePanes[this.mode] || null;
  },

  setActiveMessagePane(mode) {
    for (const [paneMode, pane] of Object.entries(this.messagePanes || {})) {
      pane.hidden = paneMode !== mode;
    }
    this.elements.messages = this.messagePanes?.[mode] || null;
    if (this.elements.messagesHost) {
      this.elements.messagesHost.scrollTop = this.elements.messagesHost.scrollHeight;
    }
  },

  syncModeMessagesHtml(mode) {
    const pane = this.messagePanes?.[mode];
    if (!pane) return;
    this.modeMessagesHtml[mode] = pane.innerHTML;
  },

  syncAllMessagePanes() {
    for (const mode of ['explore', 'research']) {
      const pane = this.messagePanes?.[mode];
      if (!pane) continue;
      pane.innerHTML = this.modeMessagesHtml[mode] || '';
      pane.querySelectorAll('.loading-indicator, .typing-indicator').forEach(el => el.remove());
      this.modeMessagesHtml[mode] = pane.innerHTML;
    }
  },

  getSessionIdForMode(mode = this.mode) {
    const base = String(this.sessionId || '').trim();
    if (!base) return getOrCreateSessionId();
    return `${base}:${mode}`;
  },

  updateComposerState() {
    const { input, sendBtn } = this.elements;
    const disabled = !!this.modeRequestInFlight?.[this.mode];
    if (sendBtn) sendBtn.disabled = disabled;
    if (input) input.disabled = disabled;
  },

  syncSidebarToggleVisibility() {
    const { sidebar, toggle } = this.elements;
    if (!sidebar || !toggle) return;
    toggle.style.display = sidebar.classList.contains('collapsed') ? 'flex' : 'none';
  },

  updateSidebarModeLayout() {
    const { orderPanel, resizeOrder, form } = this.elements;
    const hideOrderTaker = this.mode === 'research';
    const container = document.getElementById('chatContainer');
    if (container) {
      container.classList.toggle('chat-container--research', hideOrderTaker);
      container.classList.toggle('chat-container--explore', !hideOrderTaker);
    }
    if (orderPanel) {
      orderPanel.hidden = hideOrderTaker;
      orderPanel.setAttribute('aria-hidden', hideOrderTaker ? 'true' : 'false');
      orderPanel.style.display = hideOrderTaker ? 'none' : '';
    }
    if (resizeOrder) {
      resizeOrder.hidden = hideOrderTaker;
      resizeOrder.setAttribute('aria-hidden', hideOrderTaker ? 'true' : 'false');
      resizeOrder.style.display = hideOrderTaker ? 'none' : '';
    }
    if (form) {
      form.setAttribute('data-chat-mode', this.mode);
    }
    this.enforceResearchUiBoundaries();
  },

  enforceResearchUiBoundaries() {
    const hideOrderTaker = this.mode === 'research';
    const { orderPanel, resizeOrder } = this.elements;
    const container = document.getElementById('chatContainer');
    if (container) {
      container.classList.toggle('chat-container--research', hideOrderTaker);
      container.classList.toggle('chat-container--explore', !hideOrderTaker);
    }
    for (const element of [orderPanel, resizeOrder]) {
      if (!element) continue;
      element.hidden = hideOrderTaker;
      element.setAttribute('aria-hidden', hideOrderTaker ? 'true' : 'false');
      element.style.display = hideOrderTaker ? 'none' : '';
      element.style.visibility = hideOrderTaker ? 'hidden' : '';
      element.style.pointerEvents = hideOrderTaker ? 'none' : '';
    }
  },

  async refreshResearchCorpusOptions() {
    if (!researchModeToggle) return [];

    this.researchCorpusOptionsLoading = true;
    if (isAuthBootPending()) {
      researchModeToggle.setCorpusOptionsLoading(true, 'Checking account...');
      researchModeToggle.setCorpusStatus('Checking account session...');
      await waitForAuthBoot(3000);
    }

    if (!isAuthenticated()) {
      this.researchCorpusOptions = [];
      this.researchCorpusOptionsLoading = false;
      researchModeToggle.setCorpusOptionsLoading(false);
      researchModeToggle.setCorpusOptions([], '');
      researchModeToggle.setCorpusStatus('Sign in to use saved corpora in Research.');
      return [];
    }

    const sb = getSupabaseClient();
    const user = getCurrentUser();
    if (!sb || !user?.id) {
      this.researchCorpusOptions = [];
      this.researchCorpusOptionsLoading = false;
      researchModeToggle.setCorpusOptionsLoading(false);
      researchModeToggle.setCorpusOptions([], '');
      researchModeToggle.setCorpusStatus('Saved corpora are not available right now.');
      return [];
    }

    try {
      const email = String(user?.email || '').trim();
      const loadingLabel = email ? `Loading saved corpora for ${email}...` : 'Loading saved corpora...';
      researchModeToggle.setCorpusOptionsLoading(true, loadingLabel);
      researchModeToggle.setCorpusStatus(email ? `${email}: authenticated runtime access enabled. Loading saved corpora...` : 'Authenticated runtime access enabled. Loading saved corpora...');
      await this.refreshBrowserCorpusSummaries();
      try {
        researchPackCatalogById = await getResearchPackCatalogMap();
      } catch (metadataError) {
        console.warn('Could not load shared research pack catalog metadata:', metadataError);
        researchPackCatalogById = new Map();
      }
      const { data, error } = await sb
        .from('research_corpora')
        .select('id, name, updated_at, research_corpus_items(item_type, item_id)')
        .eq('user_id', user.id)
        .order('updated_at', { ascending: false });

      if (error) throw error;

      this.researchCorpusOptions = (data || []).map(corpus => {
        const items = Array.isArray(corpus.research_corpus_items) ? corpus.research_corpus_items : [];
        const packIds = items
          .filter(item => item.item_type === 'pack')
          .map(item => String(item.item_id || '').trim())
          .filter(Boolean);
        const packCount = packIds.length;
        const sourceCount = items.filter(item => item.item_type === 'source').length;
        const browserSummary = this.getBrowserCorpusSummary(corpus.id);
        const isStale = Boolean(browserSummary?.corpusUpdatedAt && corpus.updated_at && browserSummary.corpusUpdatedAt !== corpus.updated_at);
        const packMetadata = packIds
          .map((packId) => researchPackCatalogById.get(packId))
          .filter(Boolean);
        const estimatedBrowserStorageMb = packMetadata.reduce((sum, pack) => {
          return sum + Number(pack?.browser_storage_estimate_mb || 0);
        }, 0);
        const estimatedSourceRows = packMetadata.reduce((sum, pack) => {
          return sum + Number(pack?.row_count || 0);
        }, 0);
        return {
          id: corpus.id,
          name: corpus.name || 'Untitled corpus',
          label: `${corpus.name || 'Untitled corpus'}${packCount ? ` (${packCount} pack${packCount === 1 ? '' : 's'})` : ''}${sourceCount ? ` + ${sourceCount} source${sourceCount === 1 ? '' : 's'}` : ''}`,
          packCount,
          packIds,
          sourceCount,
          updatedAt: corpus.updated_at || null,
          browserSummary,
          browserStatus: browserSummary ? (isStale ? 'stale' : (browserSummary.status || 'complete')) : 'missing',
          estimatedBrowserStorageMb: estimatedBrowserStorageMb > 0 ? estimatedBrowserStorageMb : 0,
          estimatedSourceRows: estimatedSourceRows > 0 ? estimatedSourceRows : 0
        };
      });

      if (!this.researchCorpusOptions.some(option => option.id === this.selectedResearchCorpusId)) {
        this.selectedResearchCorpusId = '';
      }

      this.researchCorpusOptionsLoading = false;
      researchModeToggle.setCorpusOptionsLoading(false);
      researchModeToggle.setCorpusOptions(this.researchCorpusOptions, this.selectedResearchCorpusId);
      this.updateResearchCorpusStatus();
      this.saveState();
      return this.researchCorpusOptions;
    } catch (error) {
      console.warn('Could not load saved corpora for Research:', error);
      this.researchCorpusOptions = [];
      this.researchCorpusOptionsLoading = false;
      researchModeToggle.setCorpusOptionsLoading(false);
      researchModeToggle.setCorpusOptions([], '');
      researchModeToggle.setCorpusStatus('Could not load saved corpora right now.');
      return [];
    }
  },

  async refreshResearchManifest() {
    if (!researchModeToggle) return null;
    if (isAuthBootPending()) {
      researchModeToggle.setCorpusStatus('Checking account session...');
      await waitForAuthBoot(3000);
    }
    const manifest = await researchModeToggle.snapshotCorpus();
    this.latestResearchManifest = manifest || null;
    this.updateResearchCorpusStatus();
    return manifest;
  },

  async refreshBrowserCorpusSummaries() {
    try {
      const summaries = await listBrowserCorpusSummaries();
      this.browserCorpusSummaries = new Map((summaries || []).map(item => [item.corpusId, item]));
    } catch (error) {
      console.warn('Could not read browser corpus summaries:', error);
      this.browserCorpusSummaries = new Map();
    }
    return this.browserCorpusSummaries;
  },

  getBrowserCorpusSummary(corpusId) {
    return this.browserCorpusSummaries.get(corpusId) || null;
  },

  canUseBrowserSnapshotRecord(record, selectedOption = null) {
    if (!record?.snapshot) return false;
    const selectedUpdatedAt = String(selectedOption?.updatedAt || '').trim();
    const snapshotUpdatedAt = String(record?.corpusUpdatedAt || '').trim();
    if (!selectedUpdatedAt || !snapshotUpdatedAt) return true;
    if (selectedUpdatedAt === snapshotUpdatedAt) return true;
    const selectedMs = Date.parse(selectedUpdatedAt);
    const snapshotMs = Date.parse(snapshotUpdatedAt);
    if (Number.isFinite(selectedMs) && Number.isFinite(snapshotMs)) {
      return Math.abs(selectedMs - snapshotMs) <= 1500;
    }
    return false;
  },

  async buildResearchBrowserSnapshot(corpusId, { sessionId } = {}) {
    const token = getAccessToken();
    return await postMsgpack('/api/research/browser-save/build', {
      sessionId: sessionId || this.getSessionIdForMode('research'),
      corpusId
    }, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
  },

  async restoreResearchBrowserSnapshot(snapshot, { sessionId } = {}) {
    const token = getAccessToken();
    return await postMsgpack('/api/research/browser-save/load', {
      sessionId: sessionId || this.getSessionIdForMode('research'),
      snapshot
    }, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
  },

  getSelectedResearchCorpusOption() {
    return this.researchCorpusOptions.find(option => option.id === this.selectedResearchCorpusId) || null;
  },

  isResearchCorpusAlreadyLoaded(corpusId) {
    const selectedId = corpusId || this.selectedResearchCorpusId;
    const manifest = this.latestResearchManifest;
    const saved = manifest?.saved_corpus || null;
    const artifactCount = Number(manifest?.artifact_count || 0);
    return Boolean(selectedId && saved?.id && saved.id === selectedId && artifactCount > 0 && !manifest?.stale_artifacts);
  },

  getResearchEmptyStateMessage() {
    if (isAuthBootPending()) {
      return 'Checking account session...';
    }
    if (this.researchCorpusOptionsLoading && isAuthenticated()) {
      const email = String(getCurrentUser()?.email || '').trim();
      return email
        ? `${email}: authenticated runtime access enabled. Loading saved corpora...`
        : 'Authenticated runtime access enabled. Loading saved corpora...';
    }
    if (isAuthenticated()) {
      if (this.researchCorpusOptions.length > 0) {
        return 'No Research corpus is loaded yet. Select a saved corpus above and click Load Data.';
      }
      return 'No Research corpus is loaded yet. Create a saved corpus from your account page, then return here and click Load Data.';
    }
    return 'No Research corpus is loaded yet. Sign in to use saved corpora in Research.';
  },

  updateResearchCorpusStatus() {
    if (!researchModeToggle) return;
    if (isAuthBootPending()) {
      researchModeToggle.setActiveCorpusState({
        loadedCorpusId: '',
        hasActiveArtifacts: false,
        hasStaleArtifacts: false
      });
      researchModeToggle.setCorpusStatus('Checking account session...');
      return;
    }
    if (this.researchCorpusOptionsLoading && isAuthenticated()) {
      const email = String(getCurrentUser()?.email || '').trim();
      researchModeToggle.setActiveCorpusState({
        loadedCorpusId: '',
        hasActiveArtifacts: false,
        hasStaleArtifacts: false
      });
      researchModeToggle.setCorpusStatus(email
        ? `${email}: authenticated runtime access enabled. Loading saved corpora...`
        : 'Authenticated runtime access enabled. Loading saved corpora...');
      return;
    }
    const selected = this.getSelectedResearchCorpusOption();
    const manifest = this.latestResearchManifest;
    const saved = manifest?.saved_corpus || null;
    const artifactCount = Number(manifest?.artifact_count || 0);
    researchModeToggle.setActiveCorpusState({
      loadedCorpusId: saved?.id || '',
      hasActiveArtifacts: artifactCount > 0,
      hasStaleArtifacts: Boolean(manifest?.stale_artifacts)
    });
    const browserStatus = selected?.browserStatus || 'missing';
    const browserSummary = selected?.browserSummary || null;
    const selectedEstimateText = selected?.estimatedBrowserStorageMb
      ? ` Estimated browser save ${selected.estimatedBrowserStorageMb.toFixed(1)} MB.`
      : '';
    const browserSizeText = browserSummary?.sizeBytes
      ? (browserSummary?.sizeKind === 'measured'
        ? ` Browser copy ${this.formatBytes(browserSummary.sizeBytes)} on this device.`
        : ` Browser copy ${this.formatBytes(browserSummary.sizeBytes)} as a compressed local snapshot.`)
      : '';

    if (!isAuthenticated()) {
      if (artifactCount > 0) {
        researchModeToggle.setCorpusStatus(`Research has ${artifactCount} loaded artifact${artifactCount === 1 ? '' : 's'} in this workspace. Sign in to use saved corpora.`);
        return;
      }
      researchModeToggle.setCorpusStatus('Sign in to select saved corpora.');
      return;
    }
    if (saved && selected && saved.id === selected.id) {
      const sizeText = saved.estimated_file_size_mb_total
        ? ` Estimated size ${saved.estimated_file_size_mb_total.toFixed(1)} MB.`
        : selectedEstimateText;
      if (manifest?.stale_artifacts) {
        researchModeToggle.setCorpusStatus(`"${saved.name}" is selected, but the current Research session is out of date. Click Load Data to refresh it.${sizeText}`);
        return;
      }
      const browserText = browserStatus === 'stale'
        ? ' Browser copy on this device is out of date. Refresh it from the account page if needed.'
        : (browserStatus === 'complete' ? browserSizeText : '');
      researchModeToggle.setCorpusStatus(`Loaded "${saved.name}" into this Research workspace.${sizeText}${browserText}`);
      return;
    }
    if (selected) {
      const browserText = browserStatus === 'complete'
        ? ` Browser-saved on this device.${browserSizeText}`
        : (browserStatus === 'stale'
          ? ' Browser copy on this device is out of date. Refresh it from the account page if needed.'
          : ' No browser copy on this device yet.');
      researchModeToggle.setCorpusStatus(`Selected "${selected.name}". Click Load Data to attach it to this Research workspace.${selectedEstimateText}${browserText}`);
      return;
    }
    if (this.researchCorpusOptions.length > 0) {
      researchModeToggle.setCorpusStatus('Select a saved corpus, then click Load Data.');
      return;
    }
    if (artifactCount > 0) {
      researchModeToggle.setCorpusStatus(`Research has ${artifactCount} loaded artifact${artifactCount === 1 ? '' : 's'} in this workspace.`);
      return;
    }
    researchModeToggle.setCorpusStatus('No saved corpora found yet.');
  },

  formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let unitIndex = 0;
    let current = value;
    while (current >= 1024 && unitIndex < units.length - 1) {
      current /= 1024;
      unitIndex += 1;
    }
    return `${current.toFixed(current >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  },

  async loadSelectedResearchCorpus(corpusId) {
    const selectedId = corpusId || this.selectedResearchCorpusId;
    if (!selectedId) return;

    this.selectedResearchCorpusId = selectedId;
    this.updateResearchCorpusStatus();
    this.saveState();

    try {
      const manifest = this.latestResearchManifest || await this.refreshResearchManifest();
      const saved = manifest?.saved_corpus || null;
      const artifactCount = Number(manifest?.artifact_count || 0);
      if (saved?.id === selectedId && artifactCount > 0 && !manifest?.stale_artifacts) {
        const selected = this.getSelectedResearchCorpusOption();
        this.addMessage(
          `Research already has "${selected?.name || saved?.name || 'this corpus'}" loaded with ${artifactCount} artifact${artifactCount === 1 ? '' : 's'}.`,
          'assistant',
          { mode: 'research' }
        );
        this.updateResearchCorpusStatus();
        return;
      }
    } catch (manifestError) {
      console.warn('Could not verify active Research corpus before loading:', manifestError);
    }

    const indicator = this.showTypingIndicator(true);
    indicator.updateStage?.('thinking', 'Loading saved corpus into Research...');
    researchModeToggle?.setCorpusLoading(true);

    try {
      await ensureRuntimeAccessToken();
      await this.refreshBrowserCorpusSummaries();
      const selected = this.getSelectedResearchCorpusOption();
      let browserSnapshotRecord = null;
      try {
        browserSnapshotRecord = await getBrowserCorpusSnapshot(selectedId);
      } catch (browserLookupError) {
        console.warn('Could not look up browser snapshot before loading corpus:', browserLookupError);
      }
      if (!browserSnapshotRecord && selected?.browserStatus !== 'complete') {
        try {
          await this.refreshResearchCorpusOptions();
        } catch (refreshError) {
          console.warn('Could not refresh corpus options before browser restore attempt:', refreshError);
        }
      }
      const refreshedSelected = this.getSelectedResearchCorpusOption() || selected;
      const hasUsableBrowserSnapshot = this.canUseBrowserSnapshotRecord(browserSnapshotRecord, refreshedSelected);
      if (browserSnapshotRecord && !hasUsableBrowserSnapshot) {
        console.info('Browser snapshot exists but is stale for selected corpus; falling back to cloud load.', {
          corpusId: selectedId,
          selectedUpdatedAt: refreshedSelected?.updatedAt || selected?.updatedAt || null,
          snapshotUpdatedAt: browserSnapshotRecord?.corpusUpdatedAt || null
        });
      }
      let response = null;
      if (hasUsableBrowserSnapshot) {
        try {
          indicator.updateStage?.('thinking', 'Restoring browser-saved corpus into Research...');
          response = await this.restoreResearchBrowserSnapshot(browserSnapshotRecord.snapshot);
        } catch (browserError) {
          console.warn('Browser snapshot restore failed, falling back to cloud load:', browserError);
        }
      }
      if (!response) {
        try {
          indicator.updateStage?.('thinking', 'Loading saved corpus from cloud into Research...');
          response = await postMsgpack('/api/research/load-saved-corpus', {
            sessionId: this.getSessionIdForMode('research'),
            corpusId: selectedId
          });
        } catch (loadError) {
          if (Number(loadError?.status || 0) === 401) {
            await refreshRuntimeSession();
            indicator.updateStage?.('thinking', 'Rechecking account session, then loading corpus...');
            response = await postMsgpack('/api/research/load-saved-corpus', {
              sessionId: this.getSessionIdForMode('research'),
              corpusId: selectedId
            });
          } else {
            throw loadError;
          }
        }
      }
      this.lastResearchDisplay = null;
      if (response?.focus_geojson?.features?.length) {
        App?.focusResearchGeojson?.(response.focus_geojson);
      }
      this.latestResearchManifest = response?.corpus || null;
      const saved = response?.corpus?.saved_corpus || null;
      const packCount = Number(saved?.pack_count || 0);
      const sourceCount = Number(saved?.source_count || 0);
      const artifactCount = Number(response?.corpus?.artifact_count || 0);
      const extraSourcesText = sourceCount ? ` and ${sourceCount} direct source${sourceCount === 1 ? '' : 's'}` : '';
        const baseLoadMessage = saved
          ? `Loaded "${saved.name}" into Research. This workspace includes ${packCount} pack${packCount === 1 ? '' : 's'}${extraSourcesText} and ${artifactCount} hydrated artifact${artifactCount === 1 ? '' : 's'}.`
          : (response?.message || 'Loaded the saved corpus into Research.');
        const loadWarning = String(response?.warning || '').trim();
        this.addMessage(
          loadWarning ? `${baseLoadMessage}\n\nNote: ${loadWarning}` : baseLoadMessage,
          'assistant',
          { mode: 'research' }
        );
      this.updateResearchCorpusStatus();
    } catch (error) {
      console.error('Saved corpus load error:', error);
      const message = Number(error?.status || 0) === 401
        ? 'Research could not verify your runtime session. Reload the app or sign in again, then retry Load Data.'
        : (error.message || 'Could not load that saved corpus into Research.');
      this.addMessage(message, 'assistant', { mode: 'research' });
    } finally {
      indicator.remove();
      researchModeToggle?.setCorpusLoading(false);
      this.updateResearchCorpusStatus();
      this.saveState();
    }
  },

  async saveResearchCorpusToBrowser(corpusId) {
    const selectedId = corpusId || this.selectedResearchCorpusId;
    if (!selectedId) return;
    const selected = this.researchCorpusOptions.find(option => option.id === selectedId) || null;
    const indicator = this.showTypingIndicator(true);
    indicator.updateStage?.('thinking', 'Saving this corpus into browser storage...');
    researchModeToggle?.setCorpusLoading(true);
    try {
      const payload = await this.buildResearchBrowserSnapshot(selectedId);
      this.latestResearchManifest = payload?.corpus || this.latestResearchManifest;
      await saveBrowserCorpusSnapshot({
        corpusId: selectedId,
        corpusName: selected?.name || payload?.corpus?.saved_corpus?.name || 'Saved corpus',
        corpusUpdatedAt: selected?.updatedAt || payload?.corpus?.saved_corpus?.updated_at || null,
        snapshot: payload.snapshot
      });
      await this.refreshBrowserCorpusSummaries();
      await this.refreshResearchCorpusOptions();
      this.addMessage(`Saved "${selected?.name || 'Saved corpus'}" in browser on this device.`, 'assistant', { mode: 'research' });
    } catch (error) {
      console.error('Browser save error:', error);
      this.addMessage(error.message || 'Could not save this corpus in browser storage.', 'assistant', { mode: 'research' });
    } finally {
      indicator.remove();
      researchModeToggle?.setCorpusLoading(false);
      this.updateResearchCorpusStatus();
    }
  },

  async syncResearchCorpusBrowserCopy(corpusId) {
    await this.saveResearchCorpusToBrowser(corpusId);
  },

  async removeResearchCorpusBrowserCopy(corpusId) {
    const selectedId = corpusId || this.selectedResearchCorpusId;
    if (!selectedId) return;
    const selected = this.researchCorpusOptions.find(option => option.id === selectedId) || null;
    await removeBrowserCorpusSnapshot(selectedId);
    await this.refreshBrowserCorpusSummaries();
    await this.refreshResearchCorpusOptions();
    this.addMessage(`Removed the browser copy for "${selected?.name || 'Saved corpus'}" on this device.`, 'assistant', { mode: 'research' });
  },

  /**
   * Initialize OrderPanel and OrderTracker with map-specific callbacks.
   */
  initOrderPanel() {
    orderPanel = new OrderPanel({
      elements: {
        panel: document.getElementById('orderPanel'),
        count: document.getElementById('orderCount'),
        summary: document.getElementById('orderSummary'),
        items: document.getElementById('orderItems'),
        confirmBtn: document.getElementById('orderConfirmBtn'),
        cancelBtn: document.getElementById('orderCancelBtn'),
        orderTabBtn: document.getElementById('orderTabBtn'),
        loadedTabBtn: document.getElementById('loadedTabBtn'),
        orderTabContent: document.getElementById('orderTabContent'),
        loadedTabContent: document.getElementById('loadedTabContent'),
        loadedItems: document.getElementById('loadedItems'),
        loadedActions: document.getElementById('loadedActions'),
        loadedClearAllBtn: document.getElementById('loadedClearAllBtn')
      },
      onConfirm: async (order) => {
        await this.executeOrder(order);
      },
      onQueue: async (order) => {
        await this.queueOrder(order);
      },
      onClear: () => {
        App?.clearNavigationMode();
        // Turn off demographics overlay - user can re-enable to see countries
        if (OverlaySelector?.isActive('demographics')) {
          OverlaySelector.toggle('demographics');
        }
      },
      onClearSource: (overlayId) => {
        if (!OverlayController) return;
        OverlayController.clearOverlay(overlayId);
        // Uncheck the overlay if it's active
        if (OverlaySelector?.isActive(overlayId)) {
          OverlaySelector.toggle(overlayId);
        }
        // Clear backend session cache for this source (keeps caches in sync)
        const sessionId = this.getSessionIdForMode('explore');
        postMsgpack('/api/session/clear-source', {
          sessionId,
          sourceId: overlayId
        }).catch(err => console.warn('Failed to clear backend source cache:', err.message));
      },
      getCacheStats: () => {
        if (!OverlayController || !OverlayController.getCacheStats) return null;
        return OverlayController.getCacheStats();
      },
      addMessage: (text, type) => this.addMessage(text, type)
    });
    orderPanel.init();
    this.updateSidebarModeLayout();
    this.enforceResearchUiBoundaries();

    orderTracker = new OrderTrackerClass({
      container: document.getElementById('orderItems'),
      getSessionId: () => this.getSessionIdForMode('explore'),
      onReady: (queueId, result) => {
        if (result && (result.type === 'data' || result.type === 'events')) {
          const count = result.count || result.geojson?.features?.length || 0;
          this.addMessage(`Loaded ${count} locations.`, 'assistant');
          if (result.type === 'events') {
            ingestEventsToOverlay(result);
          }
          App?.displayData(result);
        }
      },
      onFailed: (queueId, error) => {
        this.addMessage(`Order failed: ${error || 'Unknown error'}`, 'assistant');
      }
    });

    // Make globally available for any legacy onclick handlers
    if (typeof window !== 'undefined') {
      window.OrderManager = orderPanel;
      window.OrderTracker = orderTracker;
    }
  },

  /**
   * Execute a confirmed order - send to backend and display results.
   * @param {Object} order - The order to execute
   * @param {Object} options - Options {skipLog: boolean, force: boolean} - skip logging, force re-fetch (bypass dedup)
   */
  async executeOrder(order, options = {}) {
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat`
      : '/chat';

    // Check for mixed geometry orders (different source_ids with overlay_type)
    // Split them into separate calls so backend processes each geometry type correctly
    const geometryItems = (order.items || []).filter(item => item.overlay_type);
    if (geometryItems.length > 0) {
      const sourceIds = new Set(geometryItems.map(item => item.source_id));
      if (sourceIds.size > 1) {
        console.log('Mixed geometry order detected, splitting by source_id:', [...sourceIds]);
        // Group items by source_id
        const itemsBySource = {};
        for (const item of order.items) {
          const key = item.source_id || 'default';
          if (!itemsBySource[key]) itemsBySource[key] = [];
          itemsBySource[key].push(item);
        }
        // Execute each group separately (recursive call, but each group has only 1 source_id so won't split again)
        for (const [sourceId, items] of Object.entries(itemsBySource)) {
          const subOrder = { ...order, items, summary: order.summary };
          await this.executeOrder(subOrder, options);
        }
        return;
      }
    }

    console.log('Sending order:', JSON.stringify(order, null, 2));

    const data = await postMsgpack(apiUrl, {
      confirmed_order: order,
      sessionId: this.getSessionIdForMode('explore'),
      force: options.force || false  // Bypass dedup for recovery
    });

    console.log('Received response:', {
      type: data.type,
      multi_year: data.multi_year,
      has_year_data: !!data.year_data,
      year_range: data.year_range,
      feature_count: data.geojson?.features?.length
    });

    if (data.type === 'already_loaded') {
      this.addMessage(data.message || 'This data is already loaded on your map.', 'assistant');
      if (orderPanel.switchTab) orderPanel.switchTab('loaded');
    } else if (data.type === 'error') {
      this.addMessage(data.message || 'Failed to load data.', 'assistant');
      throw new Error(data.message || 'Order execution failed');
    } else if (data.action === 'remove') {
      // Handle removal orders (no geojson, just identifiers)
      const message = data.summary || `Removed ${data.count || 0} ${data.data_type || 'items'}`;
      this.addMessage(message, 'assistant');
      App?.displayData(data, { order });
      unregisterLoadedData(order);  // Track removal for LLM context
      if (orderPanel.switchTab) orderPanel.switchTab('loaded');
    } else if (data.type === 'mixed_order' && data.results) {
      // Handle mixed add/remove orders - process each result
      for (const result of data.results) {
        App?.displayData(result, { order });
      }
      // Track both adds and removes for LLM context
      registerLoadedData(order, data);
      unregisterLoadedData(order);
      const message = data.summary || `Updated map: added ${data.add_count || 0}, removed ${data.remove_count || 0}`;
      this.addMessage(message, 'assistant');
      if (orderPanel.switchTab) orderPanel.switchTab('loaded');
    } else if (data.geojson) {
      // Route by data_type for cache ingestion
      const dataType = data.data_type || (data.type === 'events' ? 'events' : 'metrics');

      if (dataType === 'events') {
        const message = data.summary || `Showing ${data.count} ${data.event_type || 'event'} events`;
        this.addMessage(message, 'assistant');
        ingestEventsToOverlay(data);
      } else if (dataType === 'metrics') {
        const message = data.data_note || `Loaded ${data.count || data.geojson.features?.length || 0} locations`;
        this.addMessage(message, 'assistant');
        ingestMetricsToCache(data);
      } else if (dataType === 'geometry') {
        const message = data.summary || `Showing ${data.count || data.geojson.features?.length || 0} ${data.geographic_level || data.overlay_type || 'geometry'} areas`;
        this.addMessage(message, 'assistant');
        renderGeometryOrder(data);
      } else {
        // Fallback for unknown data_type
        const message = data.summary || data.data_note || `Loaded ${data.count || 0} items`;
        this.addMessage(message, 'assistant');
      }

      // Log order for session recovery (skip during recovery to avoid duplicates)
      if (!options.skipLog) {
        logExecutedOrder(order);
      }

      // Track loaded data for LLM context
      registerLoadedData(order, data);

      App?.displayData(data, { order });
    }
  },

  /**
   * Queue an order for background processing.
   * @param {Object} order - The order to queue
   */
  async queueOrder(order) {
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/api/orders/queue`
      : '/api/orders/queue';

    const data = await postMsgpack(apiUrl, {
      items: order.items,
      hints: { summary: order.summary },
      session_id: this.getSessionIdForMode('explore')
    });

    if (data.queue_id) {
      console.log('Order queued:', data.queue_id, 'position:', data.position);
      this.addMessage(
        data.position > 1
          ? `Order queued (position ${data.position}). You can continue chatting while it loads.`
          : 'Order queued. Processing...',
        'assistant'
      );
      orderTracker.addOrder(data.queue_id, {
        items: order.items,
        summary: order.summary
      });
    } else {
      throw new Error('No queue_id returned');
    }
  },

  /**
   * Restore chat state from localStorage.
   */
  restoreState() {
    const state = restoreChatState();
    if (state) {
      this.mode = state.activeMode === 'research' ? 'research' : 'explore';
      this.modeHistories = { explore: [], research: [] };
      this.modeMessagesHtml = { explore: '', research: '' };
      this.researchMemory = null;
      this.selectedResearchCorpusId = state.selectedResearchCorpusId || '';
      this.history = [];
      return;
    }

    this.mode = 'explore';
    this.modeHistories = { explore: [], research: [] };
    this.modeMessagesHtml = { explore: '', research: '' };
    this.researchMemory = null;
    this.selectedResearchCorpusId = '';
    this.history = [];
  },

  /**
   * Save current chat state to localStorage.
   */
  saveState() {
    saveChatState({
      activeMode: this.mode,
      selectedResearchCorpusId: this.selectedResearchCorpusId
    });
  },

  /**
   * Clear current session and start fresh.
   */
  async clearSession() {
    const oldSessionIds = ['explore', 'research'].map(mode => this.getSessionIdForMode(mode));
    const preservedMode = this.mode === 'research' ? 'research' : 'explore';
    const preservedResearchCorpusId = preservedMode === 'research' ? this.selectedResearchCorpusId : '';

    // Clear state
    this.history = [];
    this.mode = preservedMode;
    this.modeHistories = { explore: [], research: [] };
    this.modeMessagesHtml = { explore: '', research: '' };
    this.modeRequestInFlight = { explore: false, research: false };
    this.researchMemory = null;
    this.selectedResearchCorpusId = preservedResearchCorpusId;
    this.researchCorpusOptions = [];
    this.latestResearchManifest = null;
    if (researchModeToggle) {
      researchModeToggle.mode = preservedMode;
      researchModeToggle.setCorpusOptions([], preservedResearchCorpusId);
      researchModeToggle.setCorpusStatus(preservedMode === 'research' ? 'Select a saved corpus to begin.' : '');
      researchModeToggle.updateActive();
    }
    this.lastDisambiguationOptions = null;
    if (this.elements.messages) {
      this.syncAllMessagePanes();
      this.setActiveMessagePane(preservedMode);
    }

    // Clear order panel
    if (orderPanel) orderPanel.clearOrder();

    // Clear map-specific state
    if (window.OverlaySelector?.clearState) window.OverlaySelector.clearState();
    if (window.TimeSlider?.clearSliderSettings) window.TimeSlider.clearSliderSettings();
    if (window.App?.clearMapViewSettings) window.App.clearMapViewSettings();
    clearApiCalls();
    clearExecutedOrders();
    clearLoadedDataList();  // Clear loaded data tracker

    // Reset session
    this.sessionId = resetSessionId();
    clearChatStorage();

    // Notify backend (fire and forget)
    for (const oldSessionId of oldSessionIds) {
      if (!oldSessionId) continue;
      try {
        await postMsgpack('/api/session/clear', { sessionId: oldSessionId });
      } catch (e) {
        console.log('[Session] Backend clear skipped:', e.message);
      }
    }

    console.log('[Session] Session cleared, new session:', this.sessionId);
    await this.seedEmptyConversation(this.mode);
    return this.sessionId;
  },

  /**
   * Show recovery prompt for map data.
   * @param {number} overlayCount - Number of overlay API calls to recover
   * @param {number} orderCount - Number of executed orders to recover
   */
  showRecoveryPrompt(overlayCount, orderCount = 0) {
    const { messages } = this.elements;
    if (!messages) return;

    // Build summary of what can be recovered
    const parts = [];
    if (orderCount > 0) {
      parts.push(`${orderCount} data order${orderCount === 1 ? '' : 's'}`);
    }
    if (overlayCount > 0) {
      parts.push(`${overlayCount} overlay request${overlayCount === 1 ? '' : 's'}`);
    }
    const dataSummary = parts.join(' and ');

    const div = document.createElement('div');
    div.className = 'chat-message assistant recovery-prompt';
    div.innerHTML = `
      <strong>Welcome Back</strong><br><br>
      Your previous session: <b>${dataSummary}</b><br><br>
      Click <b>Recover Data</b> to reload your map data, or refresh the page to start fresh.
      <div class="recovery-buttons" style="margin-top: 12px;">
        <button class="recovery-btn recover" data-action="recover">Recover Data</button>
      </div>
    `;

    messages.appendChild(div);
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
    if (prompt) prompt.remove();

    if (choice === 'recover') {
      const apiCalls = getApiCallsForRecovery();
      const executedOrders = getExecutedOrdersForRecovery();

      if (apiCalls.length === 0 && executedOrders.length === 0) {
        this.addMessage('No data to recover.', 'assistant');
        return;
      }

      let totalRecovered = 0;
      let totalFailed = 0;

      // 1. Recover executed orders (metrics data)
      if (executedOrders.length > 0) {
        this.addMessage(`Recovering ${executedOrders.length} data order${executedOrders.length === 1 ? '' : 's'}...`, 'assistant');

        for (const record of executedOrders) {
          try {
            // Re-execute the order with skipLog and force to bypass dedup
            await this.executeOrder(record.order, { skipLog: true, force: true });
            totalRecovered++;
          } catch (e) {
            console.warn('[Session] Failed to recover order:', record.summary, e.message);
            totalFailed++;
          }
        }
      }

      // 2. Recover overlay API calls (disaster data)
      if (apiCalls.length > 0) {
        // Parse URLs to extract overlay IDs and years
        const overlayYears = new Map();
        for (const url of apiCalls) {
          const yearMatch = url.match(/[?&]year=(\d+)/);
          if (!yearMatch) continue;
          const year = parseInt(yearMatch[1], 10);

          let overlayId = null;
          if (url.includes('/api/earthquakes/')) overlayId = 'earthquakes';
          else if (url.includes('/api/storms/')) overlayId = 'hurricanes';
          else if (url.includes('/api/volcanoes/')) overlayId = 'volcanoes';
          else if (url.includes('/api/wildfires/')) overlayId = 'wildfires';
          else if (url.includes('/api/tornadoes/')) overlayId = 'tornadoes';
          else if (url.includes('/api/tsunamis/')) overlayId = 'tsunamis';
          else if (url.includes('/api/floods/')) overlayId = 'floods';

          if (overlayId) {
            if (!overlayYears.has(overlayId)) overlayYears.set(overlayId, new Set());
            overlayYears.get(overlayId).add(year);
          }
        }

        let overlayLoads = 0;
        for (const years of overlayYears.values()) overlayLoads += years.size;

        if (overlayLoads > 0) {
          this.addMessage(`Recovering ${overlayLoads} overlay data set${overlayLoads === 1 ? '' : 's'}...`, 'assistant');

          try {
            const loadPromises = [];
            for (const [overlayId, years] of overlayYears) {
              for (const year of years) {
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
            totalRecovered += results.filter(r => r !== null).length;
            totalFailed += results.filter(r => r === null).length;

            if (window.OverlayController?.recalculateTimeRange) {
              window.OverlayController.recalculateTimeRange();
            }
            if (window.TimeSlider?.refreshDisplay) {
              window.TimeSlider.refreshDisplay();
            }
          } catch (e) {
            console.error('[Session] Overlay recovery failed:', e);
            totalFailed++;
          }
        }
      }

      // Final summary
      if (totalFailed === 0) {
        this.addMessage(`Recovery complete. Restored ${totalRecovered} data set${totalRecovered === 1 ? '' : 's'}.`, 'assistant');
      } else {
        this.addMessage(`Recovery complete. Restored ${totalRecovered}, failed ${totalFailed}.`, 'assistant');
      }
    } else {
      await this.clearSession();
      this.addMessage(WELCOME_MESSAGE, 'assistant', { html: true, mode: 'explore' });
    }
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { sidebar, toggle, close, form, input } = this.elements;

    // Sidebar toggle
    toggle.addEventListener('click', () => {
      sidebar.classList.remove('collapsed');
      this.syncSidebarToggleVisibility();
    });

    close.addEventListener('click', () => {
      sidebar.classList.add('collapsed');
      this.syncSidebarToggleVisibility();
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

    // Delegated handler for chat action buttons (e.g. preload buttons in welcome message)
    this.elements.sidebar.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === 'preload-disasters-2020') {
        await this.handlePreloadDisasters2020(btn);
      } else if (action === 'tutorial-toggle') {
        e.preventDefault();
        TutorialMode.applyCommand('toggle');
      }
    });
  },

  /**
   * Handle the "Load disasters 2020-2025" preload button.
   * Makes one ranged API call per disaster type and caches the results in the browser.
   */
  async handlePreloadDisasters2020(btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spinner"></span> Loading...';
    try {
      const disasterIds = ['earthquakes', 'hurricanes', 'volcanoes', 'wildfires', 'tsunamis', 'tornadoes'];

      // Move trim handles to 2020-2025 (overall range stays at default 2000-present)
      window.TimeSlider?.setTrimBounds(2020, 2025);

      // Preload first so enabling overlays reuses the warmed browser cache
      // instead of triggering an extra "past 30 days" fetch per overlay.
      const summary = await window.OverlayController?.preloadDisasters2020to2025((done, total, id) => {
        btn.innerHTML = `<span class="btn-spinner"></span> Loading ${id}... (${done}/${total})`;
      });

      // Enable overlays after preload so they render from cache.
      for (const id of disasterIds) {
        if (!window.OverlaySelector?.isActive(id)) {
          window.OverlaySelector?.toggle(id);
        }
      }

      const loaded = summary ? Object.values(summary).filter(r => r.loaded).length : 0;
      btn.textContent = `Loaded (${loaded}/6 datasets)`;
    } catch (e) {
      console.error('Preload failed:', e);
      btn.textContent = 'Load disasters 2020-2025';
      btn.disabled = false;
    }
  },

  /**
   * Handle form submission - send query, handle response types.
   */
  async handleSubmit() {
    const { input, sendBtn } = this.elements;
    const requestMode = this.mode;
    const query = input.value.trim();
    if (!query) return;
    if (this.modeRequestInFlight[requestMode]) return;

    if (requestMode === 'research') {
      try {
        const manifest = await this.refreshResearchManifest();
        if ((manifest?.artifact_count || 0) === 0 && !manifest?.saved_corpus) {
          this.addMessage(this.getResearchEmptyStateMessage(), 'assistant', { mode: requestMode });
          return;
        }
      } catch (error) {
        console.warn('Research manifest refresh failed before submit:', error);
      }
    }

    // Check for "recover" command
    if (query.toLowerCase() === 'recover') {
      input.value = '';
      this.handleRecoveryChoice('recover');
      return;
    }

    if (requestMode === 'explore' && this.isAllMetricsConfirmation(query) && this.pendingMetricOrder) {
      this.addMessage(query, 'user');
      input.value = '';
      input.style.height = 'auto';
      this.history.push({ role: 'user', content: query });
      this.addMessage('Added all available metrics to your order. Click "Display on Map" when ready.', 'assistant');
      this.history.push({ role: 'assistant', content: 'Added all available metrics to your order.' });
      orderPanel.setOrder(
        this.pendingMetricOrder.order,
        this.pendingMetricOrder.summary,
        this.pendingMetricOrder.full_order
      );
      this.pendingMetricOrder = null;
      this.saveState();
      return;
    }

    if (requestMode === 'research' && this.isResearchDisplayConfirmation(query) && this.pendingResearchDisplayWarning) {
      this.addMessage(query, 'user');
      input.value = '';
      input.style.height = 'auto';
      await this.resendWithResearchDisplayForce();
      return;
    }

    // Add user message
    this.addMessage(query, 'user', { mode: requestMode });
    input.value = '';
    input.style.height = 'auto';

    const tutorialCommand = parseTutorialCommand(query);
    if (tutorialCommand) {
      this.history.push({ role: 'user', content: query });
      const result = TutorialMode.applyCommand(tutorialCommand.action);
      this.history.push({ role: 'assistant', content: result.message });
      this.addMessage(result.message, 'assistant', { mode: requestMode });
      return;
    }

    if (requestMode === 'research') {
      const styleCommand = this.parseResearchStyleCommand(query);
      if (styleCommand) {
        this.history.push({ role: 'user', content: query });
        this.modeHistories[requestMode] = this.history;
        if (styleCommand.styleUpdates) {
          App?.updateResearchDisplayStyle?.(styleCommand.styleUpdates);
        }
        this.history.push({ role: 'assistant', content: styleCommand.reply });
        this.modeHistories[requestMode] = this.history;
        this.addMessage(styleCommand.reply, 'assistant', { mode: requestMode });
        this.saveState();
        return;
      }

      const legendCommand = this.parseResearchLegendCommand(query);
      if (legendCommand) {
        this.history.push({ role: 'user', content: query });
        this.modeHistories[requestMode] = this.history;
        this.history.push({ role: 'assistant', content: legendCommand.reply });
        this.modeHistories[requestMode] = this.history;
        this.addMessage(legendCommand.reply, 'assistant', { mode: requestMode });
        this.saveState();
        return;
      }

      const rasterCommand = this.parseResearchRasterCommand(query);
      if (rasterCommand) {
        this.history.push({ role: 'user', content: query });
        this.modeHistories[requestMode] = this.history;
        if (rasterCommand.raster) {
          App?.applyResearchDisplay?.({ action: 'raster_visibility', raster: rasterCommand.raster });
        }
        this.history.push({ role: 'assistant', content: rasterCommand.reply });
        this.modeHistories[requestMode] = this.history;
        this.addMessage(rasterCommand.reply, 'assistant', { mode: requestMode });
        this.saveState();
        return;
      }
    }

    // Track last query for potential re-send (metric warning)
    this.lastQuery = query;

    this.modeRequestInFlight[requestMode] = true;
    this.updateComposerState();

    // Show staged loading indicator
    const requestMessages = this.messagePanes?.[requestMode] || this.elements.messages;
    const indicator = this.showTypingIndicator(true, requestMode);
    let streamedAssistantEl = null;
    let removedIndicatorForStream = false;

    try {
      // Build payload with map-specific context
      this.history.push({ role: 'user', content: query });
      this.modeHistories[requestMode] = this.history;
      const payload = this.buildPayload(query, null, {}, requestMode);

      // Send via streaming API
      const endpoint = requestMode === 'research' ? '/chat/research/stream' : '/chat/stream';
      this.pendingResearchRasterMode = requestMode === 'research' && this.shouldAutoShowResearchRaster(query)
        ? 'selection'
        : null;
      const response = await sendStreamingRequest(payload, (stage, message, deltaText, rawEvent) => {
        if (stage === 'display' && rawEvent?.display) {
          const displayPayload = this.decorateResearchDisplay(rawEvent.display, {
            rasterMode: this.pendingResearchRasterMode
          });
          this.applySupplementalChatActions({ display: displayPayload });
          return;
        }
        if (stage === 'answer_start') {
          if (!removedIndicatorForStream) {
            indicator.remove();
            removedIndicatorForStream = true;
          }
          return;
        }
        if (stage === 'delta') {
          if (!removedIndicatorForStream) {
            indicator.remove();
            removedIndicatorForStream = true;
          }
          const accumulatedText = deltaText || '';
          if (!accumulatedText) return;
          if (!streamedAssistantEl) {
            streamedAssistantEl = this.addMessage('', 'assistant', { mode: requestMode });
          }
          if (streamedAssistantEl) {
            streamedAssistantEl.innerHTML = formatMessage(accumulatedText);
          }
          if (requestMessages && this.mode === requestMode && this.elements.messagesHost) {
            this.elements.messagesHost.scrollTop = this.elements.messagesHost.scrollHeight;
          }
          this.syncModeMessagesHtml(requestMode);
          return;
        }
        indicator.updateStage(stage, message);
      }, endpoint);

      if (!response) {
        throw new Error('No response received from server');
      }

      const fallbackText = this.getResearchDisplayFallbackMessage(response);
      if (response.type === 'chat' && !(response.message || response.summary) && fallbackText) {
        response.message = fallbackText;
      }

      // Track in history
      const responseHistory = this.modeHistories[requestMode] || [];
      responseHistory.push({ role: 'assistant', content: response.message || response.summary });
      this.modeHistories[requestMode] = responseHistory;
      if (this.mode === requestMode) {
        this.history = responseHistory;
      }

      // Handle response based on type
      if (response._streamed && response.type === 'chat') {
        const finalText = response.message || response.summary || '';
        if (!streamedAssistantEl && finalText) {
          this.addMessage(finalText, 'assistant', { mode: requestMode });
        } else if (streamedAssistantEl && finalText) {
          streamedAssistantEl.innerHTML = formatMessage(finalText);
          this.syncModeMessagesHtml(requestMode);
        } else if (streamedAssistantEl && !finalText) {
          streamedAssistantEl.remove();
          this.syncModeMessagesHtml(requestMode);
        }
        const decoratedResponse = this.decorateResearchResponse(response, {
          rasterMode: this.pendingResearchRasterMode
        });
        this.applySupplementalChatActions(decoratedResponse);
        this.saveState();
      } else {
        if (streamedAssistantEl) {
          streamedAssistantEl.remove();
          this.syncModeMessagesHtml(requestMode);
        }
        this.handleResponse({ ...this.decorateResearchResponse(response, {
          rasterMode: this.pendingResearchRasterMode
        }), _requestMode: requestMode });
      }

    } catch (error) {
      console.error('Chat error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant', { mode: requestMode });
    } finally {
      this.pendingResearchRasterMode = null;
      if (!removedIndicatorForStream) {
        indicator.remove();
      }
      this.modeRequestInFlight[requestMode] = false;
      this.updateComposerState();
      input.focus();
    }
  },

  /**
   * Handle API response based on type (map-specific routing).
   * @param {Object} response - The API response
   */
  handleResponse(response) {
    const targetMode = response?._requestMode || this.mode;
    if (targetMode === 'research' || this.mode === 'research') {
      this.enforceResearchUiBoundaries();
    }
    const add = (text, type = 'assistant', options = {}) => this.addMessage(text, type, { ...options, mode: targetMode });
    switch (response.type) {
      case 'order':
        this.pendingMetricOrder = null;
        add('Added to your order. Click "Display on Map" when ready.', 'assistant');
        orderPanel.setOrder(response.order, response.summary, response.full_order || response.order);
        break;

      case 'already_loaded':
        add(response.message || 'This data is already loaded on your map.', 'assistant');
        // Switch to Loaded tab so user can see their data
        if (orderPanel.switchTab) orderPanel.switchTab('loaded');
        break;

      case 'metric_warning': {
        this.pendingResearchDisplayWarning = null;
        this.pendingMetricOrder = {
          order: response.pending_order,
          full_order: response.full_order,
          summary: response.summary
        };
        const msgEl = add(response.message, 'assistant');
        const btnContainer = document.createElement('div');
        btnContainer.className = 'metric-warning-buttons';

        const yesBtn = document.createElement('button');
        yesBtn.textContent = 'Yes, show all';
        yesBtn.className = 'chat-action-btn confirm';
        yesBtn.addEventListener('click', () => {
          btnContainer.remove();
          this.resendWithForce();
        });

        const noBtn = document.createElement('button');
        noBtn.textContent = 'No, let me narrow it';
        noBtn.className = 'chat-action-btn cancel';
        noBtn.addEventListener('click', () => {
          btnContainer.remove();
          add('Sure - what specific metrics would you like?', 'assistant');
        });

        btnContainer.appendChild(yesBtn);
        btnContainer.appendChild(noBtn);
        msgEl.appendChild(btnContainer);
        break;
      }

      case 'display_warning': {
        this.pendingMetricOrder = null;
        this.pendingResearchDisplayWarning = {
          level: response.warning_level,
          rowCount: response.row_count,
          softCap: response.soft_cap,
          hardCap: response.hard_cap,
          overrideAllowed: Boolean(response.override_allowed)
        };
        const msgEl = add(response.message, 'assistant');
        const btnContainer = document.createElement('div');
        btnContainer.className = 'metric-warning-buttons';

        if (response.override_allowed) {
          const yesBtn = document.createElement('button');
          yesBtn.textContent = 'Yes, load it anyway';
          yesBtn.className = 'chat-action-btn confirm';
          yesBtn.addEventListener('click', () => {
            btnContainer.remove();
            this.resendWithResearchDisplayForce();
          });
          btnContainer.appendChild(yesBtn);
        }
        if (btnContainer.childNodes.length) {
          msgEl.appendChild(btnContainer);
        }
        break;
      }

      case 'clarify':
        this.pendingMetricOrder = null;
        this.pendingResearchDisplayWarning = null;
        add(response.message || 'Could you be more specific?', 'assistant');
        break;

      case 'disambiguate':
        add(response.message || 'Please select a location:', 'assistant');
        this.lastDisambiguationOptions = response.options || [];
        if (SelectionManager) {
          SelectionManager.enter(response, (selected, originalQuery) => {
            this.handleDisambiguationSelection(selected, originalQuery);
          });
        }
        break;

      case 'navigate':
        add(response.message || 'Showing locations.', 'assistant');
        this.handleNavigation(response);
        break;

      case 'drilldown':
        add(response.message || 'Loading...', 'assistant');
        if (App && response.loc_id) {
          App.drillDown(response.loc_id, response.name || response.loc_id);
        }
        break;

      case 'data':
        add(response.summary || 'Here is your data.', 'assistant');
        App?.displayData(response);
        break;

      case 'events':
        add(response.summary || `Showing ${response.count} ${response.event_type} events.`, 'assistant');
        ingestEventsToOverlay(response);
        App?.displayData(response);
        break;

      case 'cache_answer':
        add(response.message || 'Here is the current state.', 'assistant');
        break;

      case 'order_response':
        // Handle order execution responses (including removals)
        if (response.action === 'remove') {
          add(response.summary || `Removed ${response.count || 0} ${response.data_type || 'items'}.`, 'assistant');
        } else {
          add(response.summary || 'Order complete.', 'assistant');
        }
        App?.displayData(response);
        break;

      case 'mixed_order':
        // Handle mixed add/remove orders
        if (response.results) {
          for (const result of response.results) {
            App?.displayData(result);
          }
        }
        add(response.summary || `Updated: added ${response.add_count || 0}, removed ${response.remove_count || 0}`, 'assistant');
        break;

      case 'geometry_remove':
        // Legacy: Remove geometry regions from display (now handled by order_response)
        add(response.message || 'Removing geometry.', 'assistant');
        App?.displayData({ ...response, action: 'remove', data_type: 'geometry' });
        break;

      case 'filter_update':
        add(response.message || 'Updating filters.', 'assistant');
        this.applyFilterUpdate(response);
        break;

      case 'filter_existing':
        add(response.message || 'Filtering cached data.', 'assistant');
        if (response.overlay && response.filters && OverlayController) {
          OverlayController.updateFilters(response.overlay, response.filters);
          OverlayController.rerenderFromCache?.();
        }
        break;

      case 'overlay_toggle':
        add(response.message || (response.enabled ? 'Enabling overlay.' : 'Disabling overlay.'), 'assistant');
        if (response.overlay && OverlaySelector) {
          const isCurrentlyActive = OverlaySelector.isActive(response.overlay);
          if (response.enabled && !isCurrentlyActive) {
            OverlaySelector.toggle(response.overlay);
          } else if (!response.enabled && isCurrentlyActive) {
            OverlaySelector.toggle(response.overlay);
          }
          if (response.enabled && response.filters && OverlayController) {
            OverlayController.updateFilters(response.overlay, response.filters);
            OverlayController.reloadOverlay(response.overlay);
          }
        }
        break;

      case 'tutorial_mode': {
        const result = TutorialMode.applyCommand(response.action || (response.enabled ? 'on' : 'off'));
        add(response.message || result.message, 'assistant');
        break;
      }

      case 'address_prompt':
        this.showAddressPrompt(response);
        break;

      case 'save_order':
        if (response.name) {
          const saved = SavedOrders.save(
            response.name,
            orderPanel?.currentOrder?.items || [],
            orderPanel?.currentOrder?.summary || ''
          );
          if (saved) {
            add(`Order saved as "${saved.name}"`, 'assistant');
          } else {
            add('No order to save.', 'assistant');
          }
        } else {
          add('Please specify a name to save the order (e.g., "save as California Data").', 'assistant');
        }
        break;

      case 'list_orders': {
        const savedOrders = SavedOrders.getAll();
        if (savedOrders.length === 0) {
          add('No saved orders. Save an order first with "save as [name]".', 'assistant');
        } else {
          const names = savedOrders.map(o => `- ${o.name}`).join('\n');
          add(`Saved orders:\n${names}`, 'assistant');
        }
        break;
      }

      case 'load_order':
        if (response.name) {
          const order = SavedOrders.load(response.name);
          if (order && orderPanel) {
            orderPanel.currentOrder = {
              items: JSON.parse(JSON.stringify(order.items)),
              summary: order.summary || 'Loaded saved order: ' + order.name
            };
            orderPanel.render(orderPanel.currentOrder.summary);
            orderPanel.switchTab('order');
            add(`Loaded saved order: "${order.name}"`, 'assistant');
          } else if (!order) {
            add(`No saved order found with name "${response.name}".`, 'assistant');
          }
        } else {
          const allOrders = SavedOrders.getAll();
          if (allOrders.length > 0) {
            const names = allOrders.map(o => `- ${o.name}`).join('\n');
            add(`Which order? Available:\n${names}`, 'assistant');
          } else {
            add('No saved orders available.', 'assistant');
          }
        }
        break;

      case 'delete_order':
        if (response.name) {
          if (SavedOrders.deleteOrder(response.name)) {
            add(`Deleted saved order: "${response.name}"`, 'assistant');
          } else {
            add(`No saved order found with name "${response.name}".`, 'assistant');
          }
        } else {
          add('Please specify which order to delete (e.g., "delete order California Analysis").', 'assistant');
        }
        break;

      case 'error':
        add(response.message || 'An error occurred. Please try again.', 'assistant');
        break;

      case 'chat':
      default:
        this.pendingMetricOrder = null;
        this.pendingResearchDisplayWarning = null;
        this.applySupplementalChatActions(response);
        if (response.geojson && response.geojson.features && response.geojson.features.length > 0) {
          add(response.summary || response.message || 'Found data for you.', 'assistant');
          if (response.event_type) {
            ingestEventsToOverlay(response);
          }
          App?.displayData(response);
        } else {
          add(response.summary || response.message || 'Could you be more specific?', 'assistant');
        }
        break;
    }
  },

  applySupplementalChatActions(response) {
    const display = response?.display;
    this.enforceResearchUiBoundaries();
    if (!display || !App) return;

    if (display.action === 'highlight_features' && display.geojson?.features?.length) {
      this.lastResearchDisplay = display;
      App.applyResearchDisplay?.(display);
      return;
    }

    if (display.raster?.provider) {
      App.applyResearchDisplay?.(display);
    }
  },

  shouldAutoShowResearchRaster(query) {
    const normalized = String(query || '').trim().toLowerCase();
    if (!normalized) return false;
    if (!/\b(raster|rasters|heat layer|heat map|heatmap)\b/.test(normalized)) return false;
    if (/\b(turn on|turn off|hide|disable|enable|open|close|raster mode|normal mode|vector mode|map mode|go back|undo)\b/.test(normalized)) {
      return false;
    }
    return /\b(hottest|coolest|top|rank|ranking|compare|find|identify|which|what|where|show me|list)\b/.test(normalized);
  },

  decorateResearchResponse(response, options = {}) {
    if (!response || typeof response !== 'object') return response;
    if (!response.display) return response;
    return {
      ...response,
      display: this.decorateResearchDisplay(response.display, options)
    };
  },

  decorateResearchDisplay(display, options = {}) {
    if (!display || typeof display !== 'object') return display;
    const rasterMode = options.rasterMode;
    let decorated = display;
    if (String(display.source_id || '').trim() === 'fairfax_buildings') {
      decorated = {
        ...decorated,
        context_visibility: decorated.context_visibility || 'keep',
        style: {
          ...(decorated.style || {}),
          building_fill_mode: 'type'
        }
      };
    }
    if (rasterMode !== 'selection') return decorated;
    const locIds = Array.isArray(decorated.loc_ids) ? decorated.loc_ids.filter(Boolean) : [];
    if (!locIds.length) return decorated;
    return {
      ...decorated,
      raster: {
        provider: 'fairfax_lst',
        visibility: 'show',
        clip_mode: 'selection',
        loc_ids: locIds
      }
    };
  },

  parseResearchLegendCommand(query) {
    const normalized = String(query || '').trim().toLowerCase();
    if (!normalized) return null;
    if (String(this.lastResearchDisplay?.source_id || '').trim() !== 'fairfax_buildings') return null;
    if (/\b(make|color|turn|change|set)\b/.test(normalized) && /\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/.test(normalized)) {
      return null;
    }

    const colorMatch = normalized.match(/\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (!colorMatch) return null;
    if (!/\b(building|buildings|color|colors)\b/.test(normalized)) return null;

    const legend = App?.getCurrentResearchBuildingLegend?.();
    if (!legend) return null;

    const namedColors = getResearchNamedColors();
    const requestedColorName = colorMatch[1];
    const requestedColor = normalizeResearchColorHex(namedColors[requestedColorName]);
    const entries = Object.entries(legend.typeColors || {});
    const typeLabels = legend.typeLabels || {};
    const matchedLabels = entries
      .filter(([, color]) => normalizeResearchColorHex(color) === requestedColor)
      .map(([typeCode]) => typeLabels[typeCode] || typeCode);
    const fallbackMatches = normalizeResearchColorHex(legend.defaultColor) === requestedColor;

    if (!matchedLabels.length && !fallbackMatches) {
      return {
        reply: `No buildings in the current Research display are specifically assigned ${requestedColorName} right now.`
      };
    }

    const uniqueLabels = [...new Set(matchedLabels)];
    const parts = [];
    if (uniqueLabels.length) {
      parts.push(
        `${requestedColorName[0].toUpperCase()}${requestedColorName.slice(1)} currently marks ${uniqueLabels.join(', ')} buildings.`
      );
    }
    if (fallbackMatches) {
      parts.push(
        `${requestedColorName[0].toUpperCase()}${requestedColorName.slice(1)} is also the fallback color for any buildings whose TYPE is not currently mapped, including unclassified or less-common codes.`
      );
    }
    return {
      reply: parts.join(' ')
    };
  },

  parseResearchStyleCommand(query) {
    const normalized = String(query || '').trim().toLowerCase();
    if (!normalized) return null;
    if (String(this.lastResearchDisplay?.source_id || '').trim() !== 'fairfax_buildings') return null;
    if (!/\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/.test(normalized)) return null;

    const namedColors = getResearchNamedColors();
    const colorUpdates = {};
    const residentialMatch = normalized.match(/\bresidential(?:\s+buildings?)?.{0,24}?\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (residentialMatch) {
      colorUpdates.SFR = namedColors[residentialMatch[1]];
    }
    const commercialMatch = normalized.match(/\bcommercial(?:\s+buildings?)?.{0,24}?\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (commercialMatch) {
      colorUpdates.C = namedColors[commercialMatch[1]];
      colorUpdates.MU = namedColors[commercialMatch[1]];
    }
    const parkingMatch = normalized.match(/\b(parking|transportation)(?:\s+buildings?)?.{0,24}?\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (parkingMatch) {
      colorUpdates.MG = namedColors[parkingMatch[2]];
    }
    const industrialMatch = normalized.match(/\bindustrial(?:\s+buildings?)?.{0,24}?\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (industrialMatch) {
      colorUpdates.I = namedColors[industrialMatch[1]];
    }
    const mixedUseMatch = normalized.match(/\b(mixed(?:-|\s)?use|mixed)(?:\s+buildings?)?.{0,24}?\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (mixedUseMatch) {
      colorUpdates.MU = namedColors[mixedUseMatch[2]];
    }
    const publicMatch = normalized.match(/\b(public|civic|government)(?:\s+buildings?)?.{0,24}?\b(red|blue|green|orange|yellow|purple|pink|cyan|teal)\b/);
    if (publicMatch) {
      colorUpdates.P = namedColors[publicMatch[2]];
    }

    if (!Object.keys(colorUpdates).length) return null;
    const labelParts = [];
    if (colorUpdates.SFR) labelParts.push('residential');
    if (colorUpdates.C || colorUpdates.MU) labelParts.push('commercial/mixed-use');
    if (colorUpdates.I) labelParts.push('industrial');
    if (colorUpdates.MG) labelParts.push('parking/transportation');
    if (colorUpdates.P) labelParts.push('public');
    return {
      styleUpdates: {
        buildingTypeColors: colorUpdates
      },
      reply: labelParts.length
        ? `Updated the ${labelParts.join(', ')} building colors for the current Research display.`
        : 'Updated the building colors for the current Research display.'
    };
  },

  parseResearchRasterCommand(query) {
    const normalized = String(query || '').trim().toLowerCase();
    if (!normalized) return null;
    if (
      /\b(raster|rasters|heat layer|heat map|heatmap)\b/.test(normalized) &&
      /\b(hottest|coolest|top|rank|ranking|compare|find|identify|which|what|where|show me|list)\b/.test(normalized)
    ) {
      return null;
    }

    const referencesSelection = /\b(those|these|selected|selection|them)\b/.test(normalized);
    if (referencesSelection && /\b(raster|rasters|heat layer|heat map|heatmap)\b/.test(normalized)) {
      const locIds = Array.isArray(this.lastResearchDisplay?.loc_ids) ? this.lastResearchDisplay.loc_ids.filter(Boolean) : [];
      if (!locIds.length) {
        return {
          reply: 'I do not have a recent highlighted selection to turn into raster clips yet. Highlight specific locations first, then ask for only those rasters.'
        };
      }
      return {
        raster: {
          provider: 'fairfax_lst',
          visibility: 'show',
          clip_mode: 'selection',
          loc_ids: locIds
        },
        reply: `Showing raster clips for the current ${locIds.length}-location Research selection.`
      };
    }

    if (/\b(go back|undo)\b/.test(normalized) || /\bback to (the )?(first|previous|vector|normal) view\b/.test(normalized)) {
      return {
        raster: { provider: 'fairfax_lst', visibility: 'hide' },
        reply: 'Went back to the vector-only view and hid the Fairfax heat raster layer.'
      };
    }

    if (/\b(normal mode|vector mode|map mode)\b/.test(normalized)) {
      return {
        raster: { provider: 'fairfax_lst', visibility: 'hide' },
        reply: 'Switched back to normal map mode and hid the Fairfax heat raster layer.'
      };
    }

    if (/\b(raster mode|heat mode)\b/.test(normalized)) {
      return {
        raster: { provider: 'fairfax_lst', visibility: 'show' },
        reply: 'Switched into raster mode and opened the Fairfax heat layer controls.'
      };
    }

    const referencesRaster = /\b(raster|rasters|heat layer|heat map|heatmap)\b/.test(normalized);
    if (!referencesRaster) return null;

    if (/\b(turn off|hide|disable|remove|close)\b/.test(normalized)) {
      return {
        raster: { provider: 'fairfax_lst', visibility: 'hide' },
        reply: 'Turned off the Fairfax heat raster layer.'
      };
    }

    if (/\b(turn on|show|enable|open)\b/.test(normalized)) {
      return {
        raster: { provider: 'fairfax_lst', visibility: 'show' },
        reply: 'Turned on the Fairfax heat raster layer.'
      };
    }

    return null;
  },

  getResearchDisplayFallbackMessage(response) {
    const display = response?.display;
    if (!display || display.action !== 'highlight_features') return '';
    const featureCount = display?.geojson?.features?.length || 0;
    if (!featureCount) return '';
    const sourceId = String(display?.source_id || '').trim();
    if (sourceId === 'fairfax_buildings') {
      return `Highlighted ${featureCount} building footprint${featureCount === 1 ? '' : 's'} on the map.`;
    }
    if (sourceId === 'fairfax_lst') {
      return `Highlighted ${featureCount} hot area${featureCount === 1 ? '' : 's'} on the map.`;
    }
    return `Highlighted ${featureCount} matching feature${featureCount === 1 ? '' : 's'} on the map.`;
  },

  isAllMetricsConfirmation(query) {
    const normalized = String(query || '').trim().toLowerCase();
    return [
      'all',
      'all of them',
      'all metrics',
      'show all',
      'yes',
      'y',
      'yeah',
      'yep',
      'sure'
    ].includes(normalized);
  },

  async showAddressPrompt(response) {
    const message = response.message || 'Start typing an address and choose a suggestion.';
    const msgEl = this.addMessage(message, 'assistant');
    const card = document.createElement('div');
    card.className = 'address-prompt-card';

    const label = document.createElement('label');
    label.className = 'address-prompt-label';
    label.textContent = 'Address search';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'address-prompt-input';
    input.placeholder = response.placeholder || 'Search for an address...';
    input.autocomplete = 'street-address';

    const status = document.createElement('div');
    status.className = 'address-prompt-status';
    status.textContent = 'Loading address search...';

    const details = document.createElement('div');
    details.className = 'address-prompt-details';
    details.hidden = true;

    card.appendChild(label);
    card.appendChild(input);
    card.appendChild(status);
    card.appendChild(details);
    msgEl.appendChild(card);

    try {
      await this.ensureGoogleMapsPlaces();
      this.attachAddressAutocomplete(input, status, details);
      status.textContent = 'Start typing and choose a suggested address.';
      input.focus();
    } catch (error) {
      console.warn('Address autocomplete unavailable:', error);
      status.textContent = 'Address autocomplete is not configured yet. Add a Google Maps API key to enable it.';
    }
  },

  async ensureGoogleMapsPlaces() {
    if (window.google?.maps?.places?.Autocomplete) {
      return window.google;
    }
    if (this.googleMapsLoader) {
      return this.googleMapsLoader;
    }

    this.googleMapsLoader = (async () => {
      const response = await fetch('/api/config/maps-key', {
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) {
        throw new Error(`maps_key_request_failed_${response.status}`);
      }
      const { key } = await response.json();
      const trimmedKey = (key || '').trim();
      if (!trimmedKey || trimmedKey.includes('your_google_maps_api_key_here')) {
        throw new Error('maps_key_missing');
      }

      await new Promise((resolve, reject) => {
        const existing = document.querySelector('script[data-google-maps-places="true"]');
        if (existing) {
          existing.addEventListener('load', () => resolve(), { once: true });
          existing.addEventListener('error', () => reject(new Error('maps_script_failed')), { once: true });
          return;
        }

        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(trimmedKey)}&libraries=places`;
        script.async = true;
        script.defer = true;
        script.dataset.googleMapsPlaces = 'true';
        script.onload = () => resolve();
        script.onerror = () => reject(new Error('maps_script_failed'));
        document.head.appendChild(script);
      });

      if (!window.google?.maps?.places?.Autocomplete) {
        throw new Error('maps_places_unavailable');
      }

      return window.google;
    })();

    try {
      return await this.googleMapsLoader;
    } catch (error) {
      this.googleMapsLoader = null;
      throw error;
    }
  },

  attachAddressAutocomplete(input, status, details) {
    const autocomplete = new window.google.maps.places.Autocomplete(input, {
      types: ['address'],
      fields: ['address_components', 'formatted_address', 'geometry', 'place_id']
    });

    autocomplete.addListener('place_changed', async () => {
      const place = autocomplete.getPlace();
      const geometry = place?.geometry?.location;
      if (!geometry) {
        status.textContent = 'That suggestion did not include coordinates. Please choose another result.';
        details.hidden = true;
        return;
      }

      const parsed = this.parseGoogleAddress(place);
      this.addressContext = parsed;
      status.textContent = 'Address captured. Resolving the containing map region...';
      details.hidden = false;
      details.innerHTML = '';

      const lines = [
        parsed.formatted_address,
        `Lat/Lng: ${parsed.lat.toFixed(6)}, ${parsed.lng.toFixed(6)}`,
        parsed.county ? `County: ${parsed.county}` : null,
        parsed.locality ? `City: ${parsed.locality}` : null,
        parsed.admin_area_1 ? `State/Province: ${parsed.admin_area_1}` : null,
        parsed.postal_code ? `Postal code: ${parsed.postal_code}` : null,
        parsed.country ? `Country: ${parsed.country}` : null,
      ].filter(Boolean);

      for (const line of lines) {
        const row = document.createElement('div');
        row.className = 'address-prompt-detail-row';
        row.textContent = line;
        details.appendChild(row);
      }

      await this.resolveAddressSelection(parsed, status, details);
    });
  },

  async resolveAddressSelection(parsed, status, details) {
    try {
      const resolution = await postMsgpack('/geometry/resolve-point', {
        lon: parsed.lng,
        lat: parsed.lat
      });
      this.addressContext = {
        ...parsed,
        resolved_loc_id: resolution?.matched?.loc_id || null,
        resolved_name: resolution?.matched?.name || null,
        resolved_admin_level: resolution?.matched?.admin_level ?? null,
        resolution_stack: resolution?.stack || []
      };

      if (!resolution?.matched?.loc_id || !resolution?.geojson?.features?.length) {
        status.textContent = 'Address captured, but I could not match a containing loc_id shape yet.';
        return;
      }

      this.showResolvedAddressOnMap(parsed, resolution);
      status.textContent = `Address matched to ${resolution.matched.name} (${resolution.matched.loc_id}).`;

      const matchLines = [
        `Matched loc_id: ${resolution.matched.loc_id}`,
        `Matched level: admin_${resolution.matched.admin_level}`,
      ];
      for (const line of matchLines) {
        const row = document.createElement('div');
        row.className = 'address-prompt-detail-row address-prompt-detail-row--match';
        row.textContent = line;
        details.appendChild(row);
      }
    } catch (error) {
      console.error('Address resolution failed:', error);
      status.textContent = 'Address captured, but the loc_id highlight lookup failed.';
    }
  },

  showResolvedAddressOnMap(parsed, resolution) {
    if (!MapAdapter?.map) return;

    const matched = resolution.matched || {};
    const location = {
      loc_id: matched.loc_id,
      matched_term: matched.name || matched.loc_id,
      country_name: matched.country_name || matched.iso3 || '',
      iso3: matched.iso3 || '',
      admin_level: matched.admin_level
    };

    App?.displayNavigationLocations(resolution.geojson, [location]);
    this.placeAddressMarker(parsed.lng, parsed.lat);

    const feature = resolution.geojson?.features?.[0];
    const props = feature?.properties || {};
    if (
      props.bbox_min_lon !== undefined &&
      props.bbox_max_lon !== undefined &&
      props.bbox_min_lat !== undefined &&
      props.bbox_max_lat !== undefined
    ) {
      MapAdapter.map.fitBounds(
        [
          [props.bbox_min_lon, props.bbox_min_lat],
          [props.bbox_max_lon, props.bbox_max_lat]
        ],
        { padding: 60, duration: 1200, maxZoom: 16 }
      );
    } else {
      MapAdapter.map.flyTo({
        center: [parsed.lng, parsed.lat],
        zoom: Math.max(MapAdapter.map.getZoom(), 15),
        duration: 1200
      });
    }
  },

  placeAddressMarker(lng, lat) {
    if (!MapAdapter?.map || typeof maplibregl === 'undefined') return;
    if (this.addressMarker) {
      this.addressMarker.remove();
      this.addressMarker = null;
    }

    const el = document.createElement('div');
    el.className = 'address-map-marker';
    el.innerHTML = '<span class="address-map-marker__dot"></span>';

    this.addressMarker = new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lng, lat])
      .addTo(MapAdapter.map);
  },

  parseGoogleAddress(place) {
    const components = place.address_components || [];
    const byType = (type) => {
      const component = components.find(entry => entry.types?.includes(type));
      return component?.long_name || '';
    };
    const byTypeShort = (type) => {
      const component = components.find(entry => entry.types?.includes(type));
      return component?.short_name || '';
    };

    return {
      formatted_address: place.formatted_address || '',
      place_id: place.place_id || '',
      lat: place.geometry.location.lat(),
      lng: place.geometry.location.lng(),
      street_number: byType('street_number'),
      route: byType('route'),
      locality: byType('locality') || byType('postal_town') || byType('sublocality'),
      county: byType('administrative_area_level_2'),
      admin_area_1: byType('administrative_area_level_1'),
      admin_area_1_code: byTypeShort('administrative_area_level_1'),
      postal_code: byType('postal_code'),
      country: byType('country'),
      country_code: byTypeShort('country')
    };
  },

  /**
   * Re-send the last query with force_metrics flag to bypass metric count warning.
   */
  async resendWithForce() {
    if (!this.lastQuery) return;

    const requestMode = this.mode;
    if (this.modeRequestInFlight[requestMode]) return;
    this.modeRequestInFlight[requestMode] = true;
    this.updateComposerState();

    const indicator = this.showTypingIndicator(true);

    try {
      const payload = this.buildPayload(this.lastQuery, null, { force_metrics: true });
      const response = await sendStreamingRequest(payload, (stage, message) => {
        indicator.updateStage(stage, message);
      });

      if (response) {
        this.history.push({ role: 'assistant', content: response.message || response.summary });
        this.handleResponse(response);
      }
    } catch (error) {
      console.error('Force metrics re-send error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant');
    } finally {
      indicator.remove();
      this.modeRequestInFlight[requestMode] = false;
      this.updateComposerState();
      this.elements.input?.focus();
    }
  },

  isResearchDisplayConfirmation(query) {
    const normalized = String(query || '').trim().toLowerCase();
    if (!normalized) return false;
    return [
      'yes',
      'yes, show all',
      'yes, load it anyway',
      'load it anyway',
      'show it anyway',
      'do it anyway',
      'go ahead',
      'proceed',
      'continue'
    ].includes(normalized);
  },

  async resendWithResearchDisplayForce() {
    if (!this.lastQuery || !this.pendingResearchDisplayWarning?.overrideAllowed) return;

    const requestMode = this.mode;
    if (this.modeRequestInFlight[requestMode]) return;
    this.modeRequestInFlight[requestMode] = true;
    this.updateComposerState();

    const indicator = this.showTypingIndicator(true, requestMode);

    try {
      const payload = this.buildPayload(
        this.lastQuery,
        null,
        { force_research_display: true },
        requestMode
      );
      const endpoint = requestMode === 'research' ? '/chat/research/stream' : '/chat/stream';
      const response = await sendStreamingRequest(payload, (stage, message, deltaText, rawEvent) => {
        if (stage === 'display' && rawEvent?.display) {
          const displayPayload = this.decorateResearchDisplay(rawEvent.display, {
            rasterMode: this.pendingResearchRasterMode
          });
          this.applySupplementalChatActions({ display: displayPayload });
          return;
        }
        indicator.updateStage(stage, message);
      }, endpoint);

      if (response) {
        this.pendingResearchDisplayWarning = null;
        this.history.push({ role: 'assistant', content: response.message || response.summary });
        this.handleResponse({ ...this.decorateResearchResponse(response, {
          rasterMode: this.pendingResearchRasterMode
        }), _requestMode: requestMode });
      }
    } catch (error) {
      console.error('Force research display re-send error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant', { mode: requestMode });
    } finally {
      this.pendingResearchRasterMode = null;
      indicator.remove();
      this.modeRequestInFlight[requestMode] = false;
      this.updateComposerState();
      this.elements.input?.focus();
    }
  },

  /**
   * Handle user selection from disambiguation mode.
   * @param {Object} selected - The selected location
   * @param {string} originalQuery - The original query to retry
   */
  async handleDisambiguationSelection(selected, originalQuery) {
    const requestMode = this.mode;
    const locationName = selected.matched_term || selected.loc_id;
    const countryName = selected.country_name || selected.iso3;

    this.addMessage(`Selected: ${locationName} in ${countryName}`, 'user');

    if (this.modeRequestInFlight[requestMode]) return;
    this.modeRequestInFlight[requestMode] = true;
    this.updateComposerState();

    const indicator = this.showTypingIndicator();

    try {
      this.history.push({ role: 'user', content: originalQuery });
      const resolvedLocation = {
        loc_id: selected.loc_id,
        iso3: selected.iso3,
        matched_term: selected.matched_term,
        country_name: selected.country_name
      };
      const payload = this.buildPayload(originalQuery, resolvedLocation);
      const response = await sendChatRequest(payload);

      if (response) {
        this.history.push({ role: 'assistant', content: response.message || response.summary });
        this.handleResponse(response);
      }
    } catch (error) {
      console.error('Disambiguation retry error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant');
    } finally {
      indicator.remove();
      this.modeRequestInFlight[requestMode] = false;
      this.updateComposerState();
      this.elements.input?.focus();
    }
  },

  /**
   * Handle navigation request - zoom to locations and highlight them.
   * Optionally displays geometry overlay data (ZCTAs, tribal areas, etc.)
   * @param {Object} response - Navigate response with locations, loc_ids, and optional geojson
   */
  async handleNavigation(response) {
    const locIds = response.loc_ids || [];
    const locations = response.locations || [];
    const geometryOverlay = response.geometry_overlay || null;
    const overlayGeojson = response.geojson || null;

    if (locIds.length === 0) {
      console.warn('Navigation: no loc_ids to show');
      return;
    }

    try {
      // If geometry overlay data was returned, display it directly
      // Geometry overlays (ZCTA, tribal, etc.) are complete data - no metrics needed
      if (geometryOverlay && overlayGeojson && overlayGeojson.features && overlayGeojson.features.length > 0) {
        console.log(`Navigation with geometry overlay: ${overlayGeojson.features.length} features`);

        // Display the geometry overlay via the geometry pipeline
        // displayData will handle fitToBounds internally
        App?.displayData({
          data_type: 'geometry',
          geojson: overlayGeojson,
          source_id: geometryOverlay.source_id,
          summary: response.message || `Showing ${overlayGeojson.features.length} areas`
        });

        // Note: Don't call clearOrder() here - it triggers onClear() which calls loadCountries()
        // and would overwrite the geometry we just displayed. Just render the panel to update UI.
        if (orderPanel) {
          orderPanel.currentOrder = null;
          orderPanel.render();
        }
        return;
      }

      // Standard navigation (no geometry overlay) - fetch and highlight location boundaries
      const geojson = await postMsgpack('/geometry/selection', { loc_ids: locIds });

      if (geojson.features && geojson.features.length > 0) {
        // Calculate bounding box
        let minLng = 180, maxLng = -180, minLat = 90, maxLat = -90;

        for (const feature of geojson.features) {
          const props = feature.properties || {};
          if (props.bbox_min_lon !== undefined) {
            minLng = Math.min(minLng, props.bbox_min_lon);
            maxLng = Math.max(maxLng, props.bbox_max_lon);
            minLat = Math.min(minLat, props.bbox_min_lat);
            maxLat = Math.max(maxLat, props.bbox_max_lat);
          } else if (props.centroid_lon !== undefined) {
            minLng = Math.min(minLng, props.centroid_lon - 1);
            maxLng = Math.max(maxLng, props.centroid_lon + 1);
            minLat = Math.min(minLat, props.centroid_lat - 1);
            maxLat = Math.max(maxLat, props.centroid_lat + 1);
          }
        }

        // Fit map to bounds
        if (MapAdapter?.map && minLng < maxLng && minLat < maxLat) {
          MapAdapter.map.fitBounds(
            [[minLng, minLat], [maxLng, maxLat]],
            { padding: 50, duration: 1000 }
          );
        }

        // Display locations as highlight layer
        App?.displayNavigationLocations(geojson, locations);

        // Set up order with these locations
        orderPanel?.setNavigationLocations(locations);
      }
    } catch (error) {
      console.error('Navigation error:', error);
      this.addMessage('Sorry, could not display those locations.', 'assistant');
    }
  },

  /**
   * Build API payload with map-specific context.
   * @param {string} query - User query
   * @param {Object} [resolvedLocation] - Resolved location from disambiguation
   * @returns {Object} Full request payload
   */
  buildPayload(query, resolvedLocation = null, extraOptions = {}, modeOverride = this.mode) {
    const view = MapAdapter?.getView() || { center: { lat: 0, lng: 0 }, zoom: 2, bounds: null, adminLevel: 0 };

    // Check for navigation location if no explicit resolution
    if (!resolvedLocation) {
      const navLocations = orderPanel?.currentOrder?.navigationLocations;
      if (navLocations && navLocations.length === 1) {
        const loc = navLocations[0];
        resolvedLocation = {
          loc_id: loc.loc_id,
          iso3: loc.iso3,
          matched_term: loc.matched_term,
          country_name: loc.country_name
        };
      }
    }

    const normalizedQuery = String(query || '').trim();
    const sourceHistory = Array.isArray(this.modeHistories?.[modeOverride])
      ? this.modeHistories[modeOverride]
      : (modeOverride === this.mode ? this.history : []);
    const historyForPayload = Array.isArray(sourceHistory) ? [...sourceHistory] : [];
    const lastHistoryMessage = historyForPayload[historyForPayload.length - 1];
    if (
      normalizedQuery &&
      lastHistoryMessage?.role === 'user' &&
      String(lastHistoryMessage.content || '').trim() === normalizedQuery
    ) {
      historyForPayload.pop();
    }

    const researchHistoryState = modeOverride === 'research'
      ? buildResearchMemoryFromHistory(historyForPayload)
      : null;
    if (modeOverride === 'research') {
      const activeDisplayState = App?.getCurrentResearchDisplayMemory?.() || null;
      const nextResearchMemory = researchHistoryState?.researchMemory
        ? {
            ...researchHistoryState.researchMemory,
            activeDisplayState
          }
        : (activeDisplayState ? { activeDisplayState } : null);
      this.researchMemory = nextResearchMemory || this.researchMemory;
    }

    return {
      query,
      viewport: {
        center: { lat: view.center.lat, lng: view.center.lng },
        zoom: view.zoom,
        bounds: view.bounds,
        adminLevel: view.adminLevel
      },
      chatHistory: modeOverride === 'research'
        ? (researchHistoryState?.chatHistory || [])
        : historyForPayload.slice(-CONFIG.chatHistorySendLimit),
      researchMemory: modeOverride === 'research'
        ? (this.researchMemory || null)
        : null,
      sessionId: this.getSessionIdForMode(modeOverride),
      resolved_location: resolvedLocation,
      previous_disambiguation_options: this.lastDisambiguationOptions || [],
      activeOverlays: this.getActiveOverlays(),
      cacheStats: this.getCacheStats(),
      timeState: this.getTimeState(),
      savedOrderNames: SavedOrders.getNames(),
      loadedData: getLoadedDataList(),  // Track what data is loaded for LLM context
      selectedAddress: this.addressContext,
      tutorialMode: { enabled: TutorialMode.enabled },
      ...extraOptions
    };
  },

  /**
   * Add a message to the chat UI (delegates to message-renderer).
   * @param {string} text - Message text
   * @param {string} type - 'user' or 'assistant'
   * @param {Object} [options] - { html: boolean }
   * @returns {HTMLElement} The message element
   */
  addMessage(text, type, options = {}) {
    const targetMode = options.mode || this.mode;
    const renderOptions = { ...options };
    delete renderOptions.mode;
    const targetMessages = this.messagePanes?.[targetMode] || this.elements.messages;
    const div = renderMessage(targetMessages, text, type, renderOptions);
    if (this.elements.messagesHost && targetMode === this.mode) {
      this.elements.messagesHost.scrollTop = this.elements.messagesHost.scrollHeight;
    }
    this.syncModeMessagesHtml(targetMode);
    this.saveState();
    return div;
  },

  /**
   * Show typing/loading indicator (delegates to message-renderer).
   * @param {boolean} [staged=false] - Show staged indicator
   * @returns {HTMLElement} Indicator with updateStage method
   */
  showTypingIndicator(staged = false, mode = this.mode) {
    const targetMessages = this.messagePanes?.[mode] || this.elements.messages;
    const indicator = renderTypingIndicator(targetMessages, staged);
    if (this.elements.messagesHost && mode === this.mode) {
      this.elements.messagesHost.scrollTop = this.elements.messagesHost.scrollHeight;
    }
    const originalRemove = indicator.remove.bind(indicator);
    indicator.remove = () => {
      originalRemove();
      this.syncModeMessagesHtml(mode);
      if (this.elements.messagesHost && mode === this.mode) {
        this.elements.messagesHost.scrollTop = this.elements.messagesHost.scrollHeight;
      }
    };
    return indicator;
  },

  /**
   * Get active overlay state for chat context.
   * @returns {Object} Active overlay info
   */
  getActiveOverlays() {
    const activeList = OverlaySelector?.getActiveOverlays() || [];
    if (activeList.length === 0) {
      return { type: null, filters: {} };
    }

    const primaryOverlay = activeList[0];
    const filters = OverlayController?.getActiveFilters?.(primaryOverlay) || {};

    return {
      type: primaryOverlay,
      filters: filters,
      allActive: activeList
    };
  },

  /**
   * Get cache statistics for chat context.
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
          loadedFilters: OverlayController.getLoadedFilters?.(overlayId) || {}
        };

        // Overlay-specific stats
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
   * @param {Object} response - { overlay, filters }
   */
  applyFilterUpdate(response) {
    const { overlay, filters } = response;

    if (!OverlayController) {
      console.warn('OverlayController not available for filter update');
      return;
    }

    if (filters.clear) {
      OverlayController.clearFilters?.(overlay);
    } else {
      OverlayController.updateFilters?.(overlay, filters);
    }

    OverlayController.reloadOverlay?.(overlay);
  }
};

// Backward-compatible exports
export const OrderManager = {
  init() { /* handled by ChatManager.initOrderPanel() */ },
  get currentOrder() { return orderPanel?.currentOrder; },
  set currentOrder(val) { if (orderPanel) orderPanel.currentOrder = val; },
  setOrder(order, summary) { orderPanel?.setOrder(order, summary); },
  setNavigationLocations(locs) { orderPanel?.setNavigationLocations(locs); },
  clearOrder() { orderPanel?.clearOrder(); },
  removeItem(idx) { orderPanel?.removeItem(idx); },
  render(summary) { orderPanel?.render(summary); },
  switchTab(tab) { orderPanel?.switchTab(tab); },
  renderLoadedTab() { orderPanel?.renderLoadedTab(); }
};

export const OrderTracker = {
  addOrder(queueId, info) { orderTracker?.addOrder(queueId, info); },
  cancel(queueId) { orderTracker?.cancel(queueId); },
  getStats() { return orderTracker?.getStats() || { pending: 0, isPolling: false }; }
};

export const SavedOrdersManager = {
  getAll() { return SavedOrders.getAll(); },
  save(name) {
    const items = orderPanel?.currentOrder?.items;
    const summary = orderPanel?.currentOrder?.summary;
    return SavedOrders.save(name, items || [], summary || '');
  },
  load(nameOrId) { return SavedOrders.load(nameOrId); },
  delete(nameOrId) { return SavedOrders.deleteOrder(nameOrId); },
  getNames() { return SavedOrders.getNames(); },
  getStats() { return SavedOrders.getStats(); },
  clearAll() { return SavedOrders.clearAll(); },
  applyToOrderManager(savedOrder) {
    if (!savedOrder || !savedOrder.items || !orderPanel) return false;
    orderPanel.currentOrder = {
      items: JSON.parse(JSON.stringify(savedOrder.items)),
      summary: savedOrder.summary || 'Loaded saved order: ' + savedOrder.name
    };
    orderPanel.render(orderPanel.currentOrder.summary);
    return true;
  }
};
