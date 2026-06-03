/**
 * Ticker Controller - standalone live announcement bar.
 *
 * A self-contained, toggleable overlay (like the overlay/animation controllers)
 * that scrolls live announcements (space weather, etc.) along the bottom of the
 * map. Independent of chat mode - available in Explore, Research, and Ops.
 *
 * Data source: GET /api/ops/ticker (msgpack) -> { items: [{source, text,
 * severity, scale, issued}, ...] }. The ticker is read-only and best-effort;
 * if the endpoint is empty or fails, the bar simply shows nothing.
 */

import { fetchMsgpack } from './utils/fetch.js';

const STORAGE_KEY = 'opsTickerEnabled';
const POLL_INTERVAL_MS = 60_000;

const SEVERITY_COLORS = {
  severe: '#ff4d4d',
  warning: '#ffae42',
  watch: '#ffd166',
  alert: '#4dd2ff',
  info: '#9aa4bf'
};

export const TickerController = {
  initialized: false,
  enabled: false,
  bar: null,
  track: null,
  toggle: null,
  pollTimer: null,

  init() {
    if (this.initialized) return;
    const parent = document.getElementById('mapContainer');
    if (!parent) {
      console.warn('TickerController: #mapContainer not found, skipping');
      return;
    }
    this._injectStyles();
    this._mount(parent);
    this.initialized = true;

    // Default off; restore the user's last choice.
    let stored = false;
    try { stored = localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) {}
    this.setEnabled(stored, { persist: false });
    console.log('TickerController initialized');
  },

  _injectStyles() {
    if (document.getElementById('ops-ticker-styles')) return;
    const style = document.createElement('style');
    style.id = 'ops-ticker-styles';
    style.textContent = `
      #opsTicker {
        position: absolute; left: 0; right: 0; bottom: 0; height: 34px;
        background: rgba(13, 20, 36, 0.92); border-top: 1px solid #2a3a5e;
        overflow: hidden; white-space: nowrap; display: none; z-index: 45;
        font-family: monospace; font-size: 13px; line-height: 34px;
      }
      #opsTicker.on { display: block; }
      #opsTicker .ticker-track {
        display: inline-block; padding-left: 100%;
        animation: opsTickerScroll 80s linear infinite;
      }
      #opsTicker:hover .ticker-track { animation-play-state: paused; }
      #opsTicker .ticker-item { display: inline-block; margin: 0 26px; }
      #opsTicker .ticker-item .src {
        color: #7f8798; text-transform: uppercase; font-size: 11px; margin-right: 7px;
      }
      #opsTicker .ticker-item .scale {
        margin-left: 7px; padding: 1px 5px; border-radius: 3px;
        background: rgba(255,255,255,0.08); font-size: 11px;
      }
      #opsTicker .ticker-empty { color: #7f8798; margin-left: 16px; }
      #opsTickerToggle {
        position: absolute; right: 10px; bottom: 42px; z-index: 46;
        background: rgba(13, 20, 36, 0.92); color: #9aa4bf;
        border: 1px solid #2a3a5e; border-radius: 14px; padding: 4px 12px;
        cursor: pointer; font-family: monospace; font-size: 12px;
      }
      #opsTickerToggle:hover { color: #00d4ff; border-color: #00d4ff; }
      #opsTickerToggle.on { color: #00d4ff; border-color: #00d4ff; }
      #opsTickerToggle .dot {
        display: inline-block; width: 7px; height: 7px; border-radius: 50%;
        background: #555; margin-right: 6px; vertical-align: middle;
      }
      #opsTickerToggle.on .dot { background: #00ff88; box-shadow: 0 0 6px #00ff88; }
      @keyframes opsTickerScroll {
        from { transform: translateX(0); }
        to { transform: translateX(-50%); }
      }
    `;
    document.head.appendChild(style);
  },

  _mount(parent) {
    const toggle = document.createElement('button');
    toggle.id = 'opsTickerToggle';
    toggle.type = 'button';
    toggle.title = 'Toggle the live announcement ticker';
    toggle.innerHTML = '<span class="dot"></span>Alerts';
    toggle.addEventListener('click', () => this.setEnabled(!this.enabled));
    parent.appendChild(toggle);

    const bar = document.createElement('div');
    bar.id = 'opsTicker';
    const track = document.createElement('div');
    track.className = 'ticker-track';
    bar.appendChild(track);
    parent.appendChild(bar);

    this.toggle = toggle;
    this.bar = bar;
    this.track = track;
  },

  setEnabled(on, { persist = true } = {}) {
    this.enabled = Boolean(on);
    this.bar?.classList.toggle('on', this.enabled);
    this.toggle?.classList.toggle('on', this.enabled);
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, this.enabled ? '1' : '0'); } catch (e) {}
    }
    if (this.enabled) {
      this._refresh();
      this._startPolling();
    } else {
      this._stopPolling();
    }
  },

  _startPolling() {
    this._stopPolling();
    this.pollTimer = setInterval(() => this._refresh(), POLL_INTERVAL_MS);
  },

  _stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  },

  async _refresh() {
    if (!this.enabled) return;
    try {
      const data = await fetchMsgpack('/api/ops/ticker');
      const items = Array.isArray(data?.items) ? data.items : [];
      this._render(items);
    } catch (err) {
      console.warn('TickerController: refresh failed', err);
    }
  },

  _render(items) {
    if (!this.track) return;

    if (!items.length) {
      this.track.innerHTML = '<span class="ticker-empty">No active announcements</span>';
      return;
    }

    const html = items.map(it => this._itemHtml(it)).join('');
    // Duplicate the row so the -50% scroll loops seamlessly.
    this.track.innerHTML = html + html;
  },

  _itemHtml(it) {
    const color = SEVERITY_COLORS[it.severity] || SEVERITY_COLORS.info;
    const src = this._escape(it.source || '');
    const text = this._escape(it.text || '');
    const scale = it.scale ? `<span class="scale" style="color:${color}">${this._escape(it.scale)}</span>` : '';
    return `<span class="ticker-item" style="color:${color}"><span class="src">${src}</span>${text}${scale}</span>`;
  },

  _escape(value) {
    const div = document.createElement('div');
    div.textContent = String(value);
    return div.innerHTML;
  }
};

export default TickerController;
