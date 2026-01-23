/**
 * Chat Message Renderer
 * Handles rendering messages, typing indicators, and text formatting.
 * Reusable across map app and admin dashboard.
 */

/**
 * Escape HTML to prevent XSS.
 * @param {string} text - Raw text to escape
 * @returns {string} HTML-safe string
 */
export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Format assistant message text with basic markdown.
 * Supports bold (**text**), newlines, and inline formatting.
 * @param {string} text - Raw message text
 * @returns {string} Formatted HTML string
 */
export function formatMessage(text) {
  let formatted = escapeHtml(text);

  // Bold: **text** or __text__
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/__(.+?)__/g, '<strong>$1</strong>');

  // Newlines to <br>
  formatted = formatted.replace(/\n/g, '<br>');

  return formatted;
}

/**
 * Add a message to the chat container.
 * @param {HTMLElement} container - The messages container element
 * @param {string} text - Message text
 * @param {string} type - 'user' or 'assistant'
 * @param {Object} options - { html: boolean } - if html=true, text is inserted as raw HTML
 * @returns {HTMLElement} The created message div
 */
export function addMessage(container, text, type, options = {}) {
  const div = document.createElement('div');
  div.className = `chat-message ${type}`;

  if (options.html) {
    div.innerHTML = text;
  } else if (type === 'assistant') {
    div.innerHTML = formatMessage(text);
  } else {
    div.textContent = text;
  }

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;

  return div;
}

/**
 * Show a typing/loading indicator in the chat.
 * @param {HTMLElement} container - The messages container element
 * @param {boolean} staged - If true, show staged indicator with text updates
 * @returns {HTMLElement} Indicator element with updateStage(stage, message) method
 */
export function showTypingIndicator(container, staged = false) {
  const indicator = document.createElement('div');
  indicator.className = staged ? 'loading-indicator' : 'typing-indicator';

  if (staged) {
    indicator.innerHTML = `
      <div class="loading-spinner"></div>
      <span class="loading-text">Processing...</span>
    `;
    indicator.dataset.stage = 'initial';

    indicator.updateStage = (stage, message) => {
      indicator.dataset.stage = stage;
      const textEl = indicator.querySelector('.loading-text');
      if (textEl) textEl.textContent = message;
    };
  } else {
    indicator.innerHTML = '<span></span><span></span><span></span>';
    indicator.updateStage = () => {};  // no-op for non-staged
  }

  container.appendChild(indicator);
  container.scrollTop = container.scrollHeight;
  return indicator;
}
