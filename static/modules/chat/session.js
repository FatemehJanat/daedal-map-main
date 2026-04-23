/**
 * Chat Session Manager
 * Handles session ID lifecycle and chat state persistence via localStorage.
 * Reusable across map app and admin dashboard.
 */

import { getSessionMaxAgeMs, getStorageNamespace, isAuthenticated } from '../auth.js';

// Storage keys
const SESSION_ID_KEY = 'countymap_session_id';
const SESSION_TIMESTAMP_KEY = 'countymap_session_timestamp';
const CHAT_HISTORY_KEY = 'countymap_chat_history';
const CHAT_MESSAGES_KEY = 'countymap_chat_messages';

function namespacedKey(baseKey) {
  return `${baseKey}:${getStorageNamespace()}`;
}

/**
 * Get existing session ID from localStorage or create a new one.
 * Session persists across tab close/refresh for recovery.
 * @returns {string} Session ID
 */
export function getOrCreateSessionId() {
  const sessionKey = namespacedKey(SESSION_ID_KEY);
  const timestampKey = namespacedKey(SESSION_TIMESTAMP_KEY);
  let sessionId = localStorage.getItem(sessionKey);
  const timestamp = localStorage.getItem(timestampKey);

  // Check if session is expired
  const isExpired = timestamp && (Date.now() - parseInt(timestamp, 10)) > getSessionMaxAgeMs();

  if (sessionId && !isExpired) {
    // Update timestamp on reuse
    localStorage.setItem(timestampKey, Date.now().toString());
    console.log('[Session] Restored session:', sessionId);
    return sessionId;
  }

  // Create new session - also clear stale chat storage so old conversation
  // doesn't bleed into the new session on page load.
  clearChatStorage();
  const prefix = isAuthenticated() ? 'authsess_' : 'sess_';
  sessionId = prefix + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
  localStorage.setItem(sessionKey, sessionId);
  localStorage.setItem(timestampKey, Date.now().toString());
  console.log('[Session] Created new session:', sessionId);
  return sessionId;
}

/**
 * Clear the current session ID from localStorage.
 * @returns {string} New session ID (auto-created)
 */
export function resetSessionId() {
  localStorage.removeItem(namespacedKey(SESSION_ID_KEY));
  localStorage.removeItem(namespacedKey(SESSION_TIMESTAMP_KEY));
  return getOrCreateSessionId();
}

/**
 * Save chat state to localStorage for persistence across browser close.
 * Accepts either the legacy `(history, messagesHtml)` shape or a richer state object.
 */
export function saveChatState(historyOrState, messagesHtml) {
  try {
    const legacyPayload = Array.isArray(historyOrState);
    const payload = legacyPayload
      ? {
          version: 2,
          activeMode: 'explore',
          modeHistories: {
            explore: historyOrState,
            research: []
          },
          modeMessagesHtml: {
            explore: messagesHtml || '',
            research: ''
          },
          researchMemory: null,
          selectedResearchCorpusId: null
        }
      : {
          version: 2,
          activeMode: historyOrState?.activeMode || 'explore',
          modeHistories: historyOrState?.modeHistories || { explore: [], research: [] },
          modeMessagesHtml: historyOrState?.modeMessagesHtml || { explore: '', research: '' },
          researchMemory: historyOrState?.researchMemory || null,
          selectedResearchCorpusId: historyOrState?.selectedResearchCorpusId || null
        };

    localStorage.setItem(namespacedKey(CHAT_HISTORY_KEY), JSON.stringify(payload));

    const exploreHtml = payload.modeMessagesHtml?.explore || '';
    if (exploreHtml) {
      localStorage.setItem(namespacedKey(CHAT_MESSAGES_KEY), exploreHtml);
    } else {
      localStorage.removeItem(namespacedKey(CHAT_MESSAGES_KEY));
    }
  } catch (e) {
    console.warn('[Session] Could not save chat state:', e.message);
  }
}

/**
 * Restore chat state from localStorage.
 * @returns {Object|null} { history: Array, messagesHtml: string } or null if nothing saved
 */
export function restoreChatState() {
  try {
    const historyJson = localStorage.getItem(namespacedKey(CHAT_HISTORY_KEY));
    const messagesHtml = localStorage.getItem(namespacedKey(CHAT_MESSAGES_KEY));

    if (historyJson || messagesHtml) {
      const parsed = historyJson ? JSON.parse(historyJson) : [];
      if (Array.isArray(parsed)) {
        console.log('[Session] Restored chat history:', parsed.length, 'messages');
        return { history: parsed, messagesHtml: messagesHtml || '' };
      }

      const activeMode = parsed?.activeMode || 'explore';
      const modeHistories = parsed?.modeHistories || { explore: [], research: [] };
      const modeMessagesHtml = {
        explore: parsed?.modeMessagesHtml?.explore || messagesHtml || '',
        research: parsed?.modeMessagesHtml?.research || ''
      };
      const activeHistory = modeHistories[activeMode] || [];

      console.log('[Session] Restored chat history:', activeHistory.length, 'messages', `(${activeMode})`);
      return {
        activeMode,
        modeHistories,
        modeMessagesHtml,
        researchMemory: parsed?.researchMemory || null,
        selectedResearchCorpusId: parsed?.selectedResearchCorpusId || null,
        history: activeHistory,
        messagesHtml: modeMessagesHtml[activeMode] || ''
      };
    }
  } catch (e) {
    console.warn('[Session] Could not restore chat state:', e.message);
  }
  return null;
}

/**
 * Clear all chat state from localStorage.
 */
export function clearChatStorage() {
  localStorage.removeItem(namespacedKey(CHAT_HISTORY_KEY));
  localStorage.removeItem(namespacedKey(CHAT_MESSAGES_KEY));
}
