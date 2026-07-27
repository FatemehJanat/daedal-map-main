/**
 * Shared retained-snapshot scrubber for Ops.
 *
 * The server sends the retained frame index once. This module chooses compact
 * per-feed payloads locally and lazily fetches only a selected large
 * alert/point geometry frame. It intentionally does not reuse the Explore
 * animator.
 */

import { postMsgpack } from './utils/fetch.js';
import { NwsAlertsOverlay } from './overlay-nws-alerts.js';
import { getLivePointOverlay } from './live-point-overlay.js';

const CURSOR_STEP_MS = 5 * 60 * 1000;
const FORECAST_HORIZON_MS = 5 * 24 * 60 * 60 * 1000;

function toMs(value) {
  const result = Date.parse(String(value || ''));
  return Number.isFinite(result) ? result : null;
}

function floorToCursor(ms) {
  return Math.floor(ms / CURSOR_STEP_MS) * CURSOR_STEP_MS;
}

function formatCursor(ms) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(new Date(ms));
}

export const OpsTimeline = {
  enabled: false,
  element: null,
  input: null,
  timeLabel: null,
  onFrame: null,
  timeline: null,
  selectedMs: null,
  externalProviders: new Map(),
  nwsFrameCache: new Map(),
  nwsRequestToken: 0,
  pointFrameCache: new Map(),
  pointRequestToken: 0,

  init({ onFrame } = {}) {
    this.element = document.getElementById('opsTimelineContainer');
    this.enabled = Boolean(this.element);
    this.onFrame = typeof onFrame === 'function' ? onFrame : null;
    if (!this.enabled && this.element) this.element.hidden = true;
  },

  clear() {
    this.timeline = null;
    this.selectedMs = null;
    this.nwsFrameCache.clear();
    this.pointFrameCache.clear();
    if (this.element) {
      this.element.hidden = true;
      this.element.replaceChildren();
    }
  },

  setExternalProvider(id, frames, renderAt) {
    const normalized = String(id || '').trim();
    if (!normalized) return;
    const usable = Array.isArray(frames) ? frames.filter((frame) => toMs(frame?.start_at) !== null) : [];
    // A raster may currently hold only one authoritative Ops frame.  Keep it
    // registered so it still receives the shared cursor while another feed
    // supplies the timeline's multiple selectable snapshots.
    if (!usable.length || typeof renderAt !== 'function') {
      this.externalProviders.delete(normalized);
      this._mergeExternalProviders();
      return;
    }
    this.externalProviders.set(normalized, { frames: usable, renderAt });
    this._mergeExternalProviders();
  },

  _mergeExternalProviders() {
    if (!this.timeline || !this.externalProviders.size) return;
    // Rebuild external entries from the provider registry.  Keeping an old
    // external:* entry here would make a disabled raster keep responding to
    // the cursor after its overlay was turned off.
    const feeds = Object.fromEntries(
      Object.entries(this.timeline.feeds || {}).filter(([id]) => !id.startsWith('external:'))
    );
    for (const [id, provider] of this.externalProviders) feeds[`external:${id}`] = provider.frames;
    this.timeline = { ...this.timeline, feeds };
    this._render();
    this.selectAt(this.selectedMs || this.timeline.currentMs, { preserveCurrent: true });
  },

  async load({ sessionId, watchId, watchContext, timelineFeeds = [] } = {}) {
    if (!this.enabled) return null;
    const response = await postMsgpack('/api/local/ops/timeline', {
      sessionId,
      watch_id: watchId,
      watch_context: watchContext,
      timeline_feeds: timelineFeeds,
    });
    this.setTimeline(response?.timeline);
    return response;
  },

  setTimeline(timeline) {
    const feedFrames = timeline?.feeds;
    if (!this.enabled || !feedFrames || typeof feedFrames !== 'object') {
      this.clear();
      return;
    }
    const rangeStart = toMs(timeline.range_start);
    const currentMs = toMs(timeline.range_end);
    if (!Number.isFinite(rangeStart) || !Number.isFinite(currentMs)) {
      this.clear();
      return;
    }
    const frameCount = Object.values(feedFrames).reduce(
      (total, frames) => total + (Array.isArray(frames) ? frames.length : 0),
      0
    ) + Array.from(this.externalProviders.values()).reduce(
      (total, provider) => total + provider.frames.length,
      0
    );
    // A single current snapshot is timestamped, but has no changing state to
    // inspect.  Keep the control invisible until an active provider offers a
    // real choice of frames.
    if (frameCount < 2) {
      this.clear();
      return;
    }
    const mergedFeeds = { ...feedFrames };
    for (const [id, provider] of this.externalProviders) mergedFeeds[`external:${id}`] = provider.frames;
    this.timeline = {
      ...timeline,
      feeds: mergedFeeds,
      rangeStart,
      currentMs,
      rangeEnd: currentMs + FORECAST_HORIZON_MS,
      historyHours: Number(timeline.history_hours) || Math.max(1, Math.round((currentMs - rangeStart) / 3_600_000)),
    };
    this._render();
    this.selectAt(currentMs, { preserveCurrent: true });
  },

  _render() {
    const { rangeStart, rangeEnd, currentMs } = this.timeline;
    this.element.hidden = false;
    this.element.innerHTML = `
      <div class="ops-timeline-header"><strong>Ops snapshots</strong><span data-ops-time></span></div>
      <div class="ops-timeline-track">
        <span class="ops-timeline-past" aria-hidden="true"></span>
        <span class="ops-timeline-forecast" aria-hidden="true"></span>
        <span class="ops-timeline-now" title="Now" aria-hidden="true"></span>
        <input data-ops-timeline-input type="range" step="${CURSOR_STEP_MS}" aria-label="Ops snapshot time">
      </div>
      <div class="ops-timeline-labels"><span>${this.timeline.historyHours >= 48 && this.timeline.historyHours % 24 === 0 ? `${this.timeline.historyHours / 24}d` : `${this.timeline.historyHours}h`} history</span><span class="ops-timeline-now-label">Now</span><span>5d forecast</span></div>
    `;
    this.input = this.element.querySelector('[data-ops-timeline-input]');
    this.timeLabel = this.element.querySelector('[data-ops-time]');
    this.input.min = String(floorToCursor(rangeStart));
    this.input.max = String(floorToCursor(rangeEnd));
    this.input.value = String(floorToCursor(currentMs));
    const nowPercent = ((currentMs - rangeStart) / (rangeEnd - rangeStart)) * 100;
    this.element.style.setProperty('--ops-now-position', `${Math.max(0, Math.min(100, nowPercent))}%`);
    this.input.addEventListener('input', () => this.selectAt(Number(this.input.value)));
  },

  selectAt(ms, { preserveCurrent = false } = {}) {
    if (!this.timeline || !Number.isFinite(ms)) return;
    this.selectedMs = ms;
    if (this.input && Number(this.input.value) !== ms) this.input.value = String(ms);
    if (this.timeLabel) this.timeLabel.textContent = formatCursor(ms);
    const displayPayloads = [];
    const specialFrames = [];
    for (const [feedId, frames] of Object.entries(this.timeline.feeds || {})) {
      if (!Array.isArray(frames)) continue;
      let selected = null;
      for (const frame of frames) {
        const start = toMs(frame?.start_at);
        const end = toMs(frame?.end_at);
        if (start === null || start > ms) break;
        selected = (end === null || ms < end) ? frame : null;
      }
      if (selected?.timeline_provider === 'nws_alerts') {
        if (ms >= this.timeline.currentMs) NwsAlertsOverlay.clearOpsTimelineFrame?.();
        else void this._loadNwsFrame(selected, ms);
      } else if (selected?.timeline_provider === 'live_point') {
        const pointOverlay = getLivePointOverlay(selected.overlay_id);
        if (ms >= this.timeline.currentMs) pointOverlay?.clearOpsTimelineFrame?.();
        else void this._loadPointFrame(selected, ms);
      } else if (frames[0]?.timeline_provider === 'live_point') {
        const pointOverlay = getLivePointOverlay(frames[0].overlay_id);
        if (ms >= this.timeline.currentMs) pointOverlay?.clearOpsTimelineFrame?.();
        else pointOverlay?.setOpsTimelineFrame?.({ type: 'FeatureCollection', features: [] });
      } else if (selected?.display_payload?.ops_timeline_provider) {
        specialFrames.push(selected.display_payload);
      } else if (selected?.display_payload) {
        displayPayloads.push(selected.display_payload);
      }
      if (feedId.startsWith('external:')) {
        const provider = this.externalProviders.get(feedId.slice('external:'.length));
        provider?.renderAt?.(ms);
      }
    }
    // A collector can be temporarily stale beyond its declared cadence.  On
    // first hydrate retain the normal Ops snapshot rather than blanking the
    // map; later deliberate scrubs can still show an honestly empty moment.
    if (displayPayloads.length || !preserveCurrent) {
      this.onFrame?.(displayPayloads, { at: new Date(ms).toISOString() });
    }
    for (const frame of specialFrames) {
      if (frame.ops_timeline_provider === 'nws_alerts') {
        void NwsAlertsOverlay.setOpsTimelineFrame?.(frame.geojson);
      }
    }
  },

  async _loadNwsFrame(frame, selectedMs) {
    const key = String(frame?.payload_hash || frame?.start_at || '');
    if (!key) return;
    const token = ++this.nwsRequestToken;
    let loaded = this.nwsFrameCache.get(key);
    if (!loaded) {
      try {
        const response = await postMsgpack('/api/local/ops/timeline/nws-frame', {
          at: frame.start_at || new Date(selectedMs).toISOString(),
        });
        loaded = response?.frame;
        if (loaded) this.nwsFrameCache.set(key, loaded);
      } catch (error) {
        console.warn('OpsTimeline: retained NWS frame failed', error);
        return;
      }
    }
    // Do not paint a late response after the cursor moved to a newer frame.
    if (token !== this.nwsRequestToken || this.selectedMs !== selectedMs || !loaded?.geojson) return;
    void NwsAlertsOverlay.setOpsTimelineFrame?.(loaded.geojson);
  },

  async _loadPointFrame(frame, selectedMs) {
    const overlayId = String(frame?.overlay_id || '');
    const key = `${overlayId}:${String(frame?.payload_hash || frame?.start_at || '')}`;
    if (!overlayId || !key) return;
    const token = ++this.pointRequestToken;
    let loaded = this.pointFrameCache.get(key);
    if (!loaded) {
      try {
        const response = await postMsgpack('/api/local/ops/timeline/point-frame', {
          overlay_id: overlayId,
          at: frame.start_at || new Date(selectedMs).toISOString(),
        });
        loaded = response?.frame;
        if (loaded) this.pointFrameCache.set(key, loaded);
      } catch (error) {
        console.warn('OpsTimeline: retained point frame failed', error);
        return;
      }
    }
    if (token !== this.pointRequestToken || this.selectedMs !== selectedMs || !loaded?.geojson) return;
    void getLivePointOverlay(overlayId)?.setOpsTimelineFrame?.(loaded.geojson);
  },
};
