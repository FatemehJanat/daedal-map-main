/**
 * Chat Session Manager
 * Handles session ID lifecycle and chat state persistence via localStorage.
 * Reusable across map app and admin dashboard.
 */

// Storage keys
const SESSION_ID_KEY = 'countymap_session_id';
const SESSION_TIMESTAMP_KEY = 'countymap_session_timestamp';
const CHAT_HISTORY_KEY = 'countymap_chat_history';
const CHAT_MESSAGES_KEY = 'countymap_chat_messages';

// Session expires after 24 hours of inactivity
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * Get existing session ID from localStorage or create a new one.
 * Session persists across tab close/refresh for recovery.
 * @returns {string} Session ID
 */
export function getOrCreateSessionId() {
  let sessionId = localStorage.getItem(SESSION_ID_KEY);
  const timestamp = localStorage.getItem(SESSION_TIMESTAMP_KEY);

  // Check if session is expired
  const isExpired = timestamp && (Date.now() - parseInt(timestamp, 10)) > MAX_AGE_MS;

  if (sessionId && !isExpired) {
    // Update timestamp on reuse
    localStorage.setItem(SESSION_TIMESTAMP_KEY, Date.now().toString());
    console.log('[Session] Restored session:', sessionId);
    return sessionId;
  }

  // Create new session
  sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
  localStorage.setItem(SESSION_ID_KEY, sessionId);
  localStorage.setItem(SESSION_TIMESTAMP_KEY, Date.now().toString());
  console.log('[Session] Created new session:', sessionId);
  return sessionId;
}

/**
 * Clear the current session ID from localStorage.
 * @returns {string} New session ID (auto-created)
 */
export function resetSessionId() {
  localStorage.removeItem(SESSION_ID_KEY);
  localStorage.removeItem(SESSION_TIMESTAMP_KEY);
  return getOrCreateSessionId();
}

/**
 * Save chat state to localStorage for persistence across browser close.
 * @param {Array} history - Chat history array (role/content pairs)
 * @param {string} messagesHtml - Rendered messages HTML string
 */
export function saveChatState(history, messagesHtml) {
  try {
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(history));
    if (messagesHtml) {
      localStorage.setItem(CHAT_MESSAGES_KEY, messagesHtml);
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
    const historyJson = localStorage.getItem(CHAT_HISTORY_KEY);
    const messagesHtml = localStorage.getItem(CHAT_MESSAGES_KEY);

    if (historyJson || messagesHtml) {
      const history = historyJson ? JSON.parse(historyJson) : [];
      console.log('[Session] Restored chat history:', history.length, 'messages');
      return { history, messagesHtml: messagesHtml || '' };
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
  localStorage.removeItem(CHAT_HISTORY_KEY);
  localStorage.removeItem(CHAT_MESSAGES_KEY);
}
