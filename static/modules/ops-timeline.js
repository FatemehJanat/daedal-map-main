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
// The shared Ops cursor is an operational replay, not each source's complete
// archive. Long retained histories remain available for event drill-down, but
// the normal cross-overlay scrubber always means "the last three days".
const SHARED_OPS_HISTORY_MS = 72 * 60 * 60 * 1000;
const NWS_BACKGROUND_BATCH_SIZE = 24;
// Hurricane replay frames are presently cumulative display payloads.  The
// bounded 72-hour window is still only about 22 MB, which is small enough to
// hydrate once per Ops session and avoids a request on every scrub position.
const HURRICANE_BACKGROUND_BATCH_SIZE = 24;
const INTERACTIVE_GRACE_MS = 250;
const HISTORY_PRELOAD_METHODS = {
  nws_alerts: '_preloadNwsFrames',
  hurricane_history: '_preloadHurricaneFrames',
  live_point: '_preloadPointFrames',
};

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
  nwsInteractiveRequestedAt: 0,
  pointFrameCache: new Map(),
  // Point feeds are independent overlays. A single global request token would
  // let an AirNow request cancel an in-flight buoy frame (or the reverse),
  // leaving one station layer visually stuck on an older cursor value.
  pointRequestTokens: new Map(),
  pointInteractiveRequestedAt: 0,
  hurricaneFrameCache: new Map(),
  hurricaneFrameInFlight: new Map(),
  hurricaneRequestToken: 0,
  hurricaneInteractiveRequestedAt: 0,
  hurricaneDebounceTimer: null,
  backgroundPrefetchTimers: [],
  backgroundPrefetchRun: 0,
  selectedDisplayPayloads: new Map(),

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
    this.pointRequestTokens.clear();
    this.hurricaneFrameCache.clear();
    this.hurricaneFrameInFlight.clear();
    this.selectedDisplayPayloads.clear();
    if (this.hurricaneDebounceTimer) clearTimeout(this.hurricaneDebounceTimer);
    this.hurricaneDebounceTimer = null;
    for (const timer of this.backgroundPrefetchTimers) clearTimeout(timer);
    this.backgroundPrefetchTimers = [];
    this.backgroundPrefetchRun += 1;
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
    const providerRangeEnd = Math.max(
      this.timeline.currentMs,
      ...Object.values(feeds).flatMap((frames) => (Array.isArray(frames) ? frames : []))
        .map((frame) => toMs(frame?.start_at)).filter(Number.isFinite)
    );
    this.timeline = { ...this.timeline, feeds, rangeEnd: providerRangeEnd };
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
    const suppliedRangeStart = toMs(timeline.range_start);
    const currentMs = toMs(timeline.range_end);
    if (!Number.isFinite(suppliedRangeStart) || !Number.isFinite(currentMs)) {
      this.clear();
      return;
    }
    const rangeStart = Math.max(suppliedRangeStart, currentMs - SHARED_OPS_HISTORY_MS);
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
    const rangeEnd = Math.max(
      currentMs,
      ...Object.values(mergedFeeds).flatMap((frames) => (Array.isArray(frames) ? frames : []))
        .map((frame) => toMs(frame?.start_at)).filter(Number.isFinite)
    );
    this.timeline = {
      ...timeline,
      feeds: mergedFeeds,
      rangeStart,
      currentMs,
      rangeEnd,
      historyHours: Math.max(1, Math.round((currentMs - rangeStart) / 3_600_000)),
    };
    this._render();
    this.selectAt(currentMs, { preserveCurrent: true });
    this._scheduleBackgroundPrefetch();
  },

  _render() {
    const { rangeStart, rangeEnd, currentMs } = this.timeline;
    this.element.hidden = false;
    this.element.innerHTML = `
      <div class="ops-timeline-header"><strong>Ops snapshots</strong><span data-ops-time></span></div>
      <div class="ops-timeline-track">
        <span class="ops-timeline-past" aria-hidden="true"></span>
        <span class="ops-timeline-forecast" aria-hidden="true"></span>
        <button type="button" class="ops-timeline-now" data-ops-now title="Jump to live now" aria-label="Jump to live now"></button>
        <input data-ops-timeline-input type="range" step="${CURSOR_STEP_MS}" aria-label="Ops snapshot time">
      </div>
      <div class="ops-timeline-labels"><span>${this.timeline.historyHours >= 48 && this.timeline.historyHours % 24 === 0 ? `${this.timeline.historyHours / 24}d` : `${this.timeline.historyHours}h`} history</span><button type="button" class="ops-timeline-now-label" data-ops-now>Now</button><span>${this.timeline.rangeEnd > currentMs ? `${Math.max(1, Math.round((this.timeline.rangeEnd - currentMs) / 60_000))}m forecast` : 'No forecast'}</span></div>
    `;
    this.input = this.element.querySelector('[data-ops-timeline-input]');
    this.timeLabel = this.element.querySelector('[data-ops-time]');
    this.input.min = String(floorToCursor(rangeStart));
    this.input.max = String(floorToCursor(rangeEnd));
    this.input.value = String(floorToCursor(currentMs));
    const nowPercent = ((currentMs - rangeStart) / (rangeEnd - rangeStart)) * 100;
    this.element.style.setProperty('--ops-now-position', `${Math.max(0, Math.min(100, nowPercent))}%`);
    this.input.addEventListener('input', () => this.selectAt(Number(this.input.value)));
    this.element.querySelectorAll('[data-ops-now]').forEach((control) => {
      control.addEventListener('click', () => this.selectAt(this.timeline.currentMs));
    });
  },

  selectAt(ms, { preserveCurrent = false } = {}) {
    if (!this.timeline || !Number.isFinite(ms)) return;
    this.selectedMs = ms;
    if (this.input && Number(this.input.value) !== ms) this.input.value = String(ms);
    if (this.timeLabel) this.timeLabel.textContent = formatCursor(ms);
    const displayPayloads = [];
    const specialFrames = [];
    let hasDeferredPayload = false;
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
      } else if (selected?.timeline_provider === 'hurricane_history') {
        // The live snapshot is already on-map. Historical additive tracks are
        // intentionally materialized only after a user moves the cursor so
        // timeline hydration stays fast even with many retained collector polls.
        if (ms < this.timeline.currentMs) {
          hasDeferredPayload = true;
          this._scheduleHurricaneFrame(feedId, selected, ms);
        }
      } else if (selected?.display_payload?.ops_timeline_provider) {
        specialFrames.push(selected.display_payload);
      } else if (selected?.display_payload) {
        displayPayloads.push(selected.display_payload);
        this.selectedDisplayPayloads.set(feedId, selected.display_payload);
      } else if (!feedId.startsWith('external:')) {
        this.selectedDisplayPayloads.delete(feedId);
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
      this.onFrame?.(Array.from(this.selectedDisplayPayloads.values()), {
        at: new Date(ms).toISOString(),
        // Initial hydration can legitimately have retained frames for only a
        // subset of active feeds. Keep their normal current snapshots until
        // the user deliberately scrubs to a time where a feed is absent.
        // A deferred additive hurricane frame must not clear the last
        // coherent track while its compact frame is materialized.
        preserveMissing: preserveCurrent || hasDeferredPayload,
      });
    }
    for (const frame of specialFrames) {
      if (frame.ops_timeline_provider === 'nws_alerts') {
        void NwsAlertsOverlay.setOpsTimelineFrame?.(frame.geojson);
      }
    }
  },

  async _loadNwsFrame(frame, selectedMs) {
    // A retained-frame timestamp is the cursor identity. Some collectors
    // legitimately reuse a payload hash for a compact/no-op envelope; using
    // only that hash would make a second active provider appear to freeze NWS
    // on the first cached alert frame.
    const key = `${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
    if (!key) return;
    const token = ++this.nwsRequestToken;
    this.nwsInteractiveRequestedAt = Date.now();
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
    const key = `${overlayId}:${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
    if (!overlayId || !key) return;
    const token = (this.pointRequestTokens.get(overlayId) || 0) + 1;
    this.pointRequestTokens.set(overlayId, token);
    this.pointInteractiveRequestedAt = Date.now();
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
    if (token !== this.pointRequestTokens.get(overlayId) || this.selectedMs !== selectedMs || !loaded?.geojson) return;
    void getLivePointOverlay(overlayId)?.setOpsTimelineFrame?.(loaded.geojson);
  },

  async _loadHurricaneFrame(feedId, frame, selectedMs) {
    const key = `${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
    if (!key) return;
    const token = ++this.hurricaneRequestToken;
    this.hurricaneInteractiveRequestedAt = Date.now();
    const loaded = await this._getHurricaneFrame(key, frame, selectedMs);
    if (!loaded) return;
    if (token !== this.hurricaneRequestToken || this.selectedMs !== selectedMs || !loaded?.display_payload) return;
    this.selectedDisplayPayloads.set(feedId, loaded.display_payload);
    this.onFrame?.(Array.from(this.selectedDisplayPayloads.values()), {
      at: new Date(selectedMs).toISOString(),
      preserveMissing: true,
    });
  },

  _scheduleHurricaneFrame(feedId, frame, selectedMs) {
    if (this.hurricaneDebounceTimer) clearTimeout(this.hurricaneDebounceTimer);
    // Slider input can emit dozens of intermediate cursor positions. Keep the
    // last coherent track visible and only materialize the settled position.
    this.hurricaneDebounceTimer = setTimeout(() => {
      this.hurricaneDebounceTimer = null;
      void this._loadHurricaneFrame(feedId, frame, selectedMs);
    }, 90);
  },

  async _getHurricaneFrame(key, frame, selectedMs) {
    const cached = this.hurricaneFrameCache.get(key);
    if (cached) return cached;
    const inFlight = this.hurricaneFrameInFlight.get(key);
    if (inFlight) return inFlight;
    const request = postMsgpack('/api/local/ops/timeline/hurricane-frame', {
      at: frame.start_at || new Date(selectedMs).toISOString(),
    }).then((response) => {
      const loaded = response?.frame || null;
      if (loaded) this.hurricaneFrameCache.set(key, loaded);
      return loaded;
    }).catch((error) => {
      console.warn('OpsTimeline: retained hurricane frame failed', error);
      return null;
    }).finally(() => {
      this.hurricaneFrameInFlight.delete(key);
    });
    this.hurricaneFrameInFlight.set(key, request);
    return request;
  },

  _scheduleBackgroundPrefetch() {
    for (const timer of this.backgroundPrefetchTimers) clearTimeout(timer);
    this.backgroundPrefetchTimers = [];
    const run = ++this.backgroundPrefetchRun;
    const timeline = this.timeline;
    const contracts = timeline?.preload_history || {};
    for (const [feedId, contract] of Object.entries(contracts)) {
      if (!contract?.preload_history) continue;
      const provider = String(contract.provider || '');
      const methodName = HISTORY_PRELOAD_METHODS[provider];
      const preload = methodName && this[methodName];
      const frames = Array.isArray(timeline?.feeds?.[feedId])
        ? timeline.feeds[feedId].filter((frame) => frame?.timeline_provider === provider).reverse()
        : [];
      if (!frames.length || typeof preload !== 'function') continue;
      // Current data has already rendered.  Each declared provider warms its
      // own fixed retained window silently, in its measured batch size.
      void preload.call(this, frames, timeline, run, contract.batch_size, contract);
    }
  },

  async _preloadNwsFrames(frames, timeline, run, declaredBatchSize = NWS_BACKGROUND_BATCH_SIZE) {
    const batchSize = Math.max(1, Math.min(24, Number(declaredBatchSize) || NWS_BACKGROUND_BATCH_SIZE));
    for (let index = 0; index < frames.length; index += batchSize) {
      if (run !== this.backgroundPrefetchRun || timeline !== this.timeline) return;
      // Never let a background batch compete with an immediately preceding
      // slider action. The visible selected frame always wins.
      while (Date.now() - this.nwsInteractiveRequestedAt < INTERACTIVE_GRACE_MS) {
        await new Promise((resolve) => setTimeout(resolve, 50));
        if (run !== this.backgroundPrefetchRun || timeline !== this.timeline) return;
      }
      const batch = frames.slice(index, index + batchSize);
      const missing = batch.filter((frame) => {
        const key = `${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
        return key && !this.nwsFrameCache.has(key);
      });
      if (!missing.length) continue;
      try {
        const response = await postMsgpack('/api/local/ops/timeline/nws-frames', {
          at: missing.map((frame) => frame.start_at),
        }, { silent: true });
        for (const loaded of response?.frames || []) {
          const key = `${String(loaded?.start_at || '')}:${String(loaded?.payload_hash || '')}`;
          if (key) this.nwsFrameCache.set(key, loaded);
        }
      } catch (error) {
        console.warn('OpsTimeline: background NWS frame batch failed', error);
        return;
      }
      // Preserve interactive requests and map rendering between batches.
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  },

  async _preloadHurricaneFrames(frames, timeline, run, declaredBatchSize = HURRICANE_BACKGROUND_BATCH_SIZE) {
    const batchSize = Math.max(1, Math.min(24, Number(declaredBatchSize) || HURRICANE_BACKGROUND_BATCH_SIZE));
    for (let index = 0; index < frames.length; index += batchSize) {
      if (run !== this.backgroundPrefetchRun || timeline !== this.timeline) return;
      while (Date.now() - this.hurricaneInteractiveRequestedAt < INTERACTIVE_GRACE_MS) {
        await new Promise((resolve) => setTimeout(resolve, 50));
        if (run !== this.backgroundPrefetchRun || timeline !== this.timeline) return;
      }
      const batch = frames.slice(index, index + batchSize);
      const missing = batch.filter((frame) => {
        const key = `${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
        return key && !this.hurricaneFrameCache.has(key);
      });
      if (!missing.length) continue;
      try {
        const response = await postMsgpack('/api/local/ops/timeline/hurricane-frames', {
          at: missing.map((frame) => frame.start_at),
        }, { silent: true });
        for (const loaded of response?.frames || []) {
          const key = `${String(loaded?.start_at || '')}:${String(loaded?.payload_hash || '')}`;
          if (key) this.hurricaneFrameCache.set(key, loaded);
        }
      } catch (error) {
        console.warn('OpsTimeline: background hurricane frame batch failed', error);
        return;
      }
      // Give paint and interactive scrub work a turn before the next bundle.
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  },

  async _preloadPointFrames(frames, timeline, run, declaredBatchSize, contract = {}) {
    const overlayId = String(contract.overlay_id || '');
    if (!overlayId) return;
    const batchSize = Math.max(1, Math.min(24, Number(declaredBatchSize) || 24));
    for (let index = 0; index < frames.length; index += batchSize) {
      if (run !== this.backgroundPrefetchRun || timeline !== this.timeline) return;
      while (Date.now() - this.pointInteractiveRequestedAt < INTERACTIVE_GRACE_MS) {
        await new Promise((resolve) => setTimeout(resolve, 50));
        if (run !== this.backgroundPrefetchRun || timeline !== this.timeline) return;
      }
      const batch = frames.slice(index, index + batchSize);
      const missing = batch.filter((frame) => {
        const key = `${overlayId}:${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
        return key && !this.pointFrameCache.has(key);
      });
      if (!missing.length) continue;
      try {
        const response = await postMsgpack('/api/local/ops/timeline/point-frames', {
          overlay_id: overlayId,
          at: missing.map((frame) => frame.start_at),
        }, { silent: true });
        for (const loaded of response?.frames || []) {
          const key = `${overlayId}:${String(loaded?.start_at || '')}:${String(loaded?.payload_hash || '')}`;
          if (key) this.pointFrameCache.set(key, loaded);
        }
      } catch (error) {
        console.warn(`OpsTimeline: background ${overlayId} point frame batch failed`, error);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  },
};
