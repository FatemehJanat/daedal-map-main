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
import { formatOpsTime } from './ops-time-display.js';

const CURSOR_STEP_MS = 5 * 60 * 1000;
const NWS_BACKGROUND_BATCH_SIZE = 24;
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
  return formatOpsTime(ms);
}

function frameCacheKey(frame, overlayId = '') {
  const prefix = overlayId ? `${String(overlayId)}:` : '';
  return `${prefix}${String(frame?.start_at || '')}:${String(frame?.payload_hash || '')}`;
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
  hurricaneReplayData: new Map(),
  hurricaneWarmupPromise: null,
  hurricaneWarmupRun: 0,
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
    this.hurricaneReplayData.clear();
    this.selectedDisplayPayloads.clear();
    this.hurricaneWarmupRun += 1;
    this.hurricaneWarmupPromise = null;
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
    const forecastEnd = toMs(this.timeline.forecast_end);
    const providerRangeEnd = Math.max(
      this.timeline.currentMs,
      Number.isFinite(forecastEnd) ? forecastEnd : 0,
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
    await this.setTimeline(response?.timeline);
    return response;
  },

  async setTimeline(timeline) {
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
    const rangeStart = suppliedRangeStart;
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
    const forecastEnd = toMs(timeline.forecast_end);
    const rangeEnd = Math.max(
      currentMs,
      Number.isFinite(forecastEnd) ? forecastEnd : 0,
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
    this.hurricaneReplayData.clear();
    for (const [feedId, replay] of Object.entries(timeline?.hurricane_replay || {})) {
      if (replay?.type === 'hurricane_replay') {
        this.hurricaneReplayData.set(feedId, replay);
      }
    }
    this._render();
    this.selectAt(currentMs, { preserveCurrent: true });
    await this._warmRequiredHistory();
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
    this.input.disabled = this._hasPendingRequiredHistoryWarmup();
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
    const updatedFeedIds = new Set();
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
        // Hurricane replay is hydrated as browser-held display frames before
        // the cursor is enabled. A scrub is therefore a synchronous render
        // change, not a data request.
        if (ms < this.timeline.currentMs) {
          const replayPayload = this._buildHurricaneReplayDisplayPayload(feedId, ms, selected);
          const loaded = replayPayload ? { display_payload: replayPayload } : this.hurricaneFrameCache.get(frameCacheKey(selected));
          if (loaded?.display_payload) {
            displayPayloads.push(loaded.display_payload);
            this.selectedDisplayPayloads.set(feedId, loaded.display_payload);
            updatedFeedIds.add(feedId);
          } else {
            hasDeferredPayload = true;
          }
        }
      } else if (selected?.display_payload?.ops_timeline_provider) {
        specialFrames.push(selected.display_payload);
      } else if (selected?.display_payload) {
        const displayPayload = feedId === 'hurricanes_live'
          ? this._hurricanePayloadAt(selected.display_payload, ms)
          : selected.display_payload;
        displayPayloads.push(displayPayload);
        this.selectedDisplayPayloads.set(feedId, displayPayload);
        updatedFeedIds.add(feedId);
      } else if (!feedId.startsWith('external:')) {
        this.selectedDisplayPayloads.delete(feedId);
        updatedFeedIds.add(feedId);
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
        opsTimelineUpdate: true,
        opsTimelineFeedIds: Array.from(updatedFeedIds),
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

  _hasPendingRequiredHistoryWarmup() {
    const contracts = this.timeline?.preload_history || {};
    for (const [feedId, contract] of Object.entries(contracts)) {
      if (contract?.preload_history && String(contract.provider || '') === 'hurricane_history') {
        if (this.hurricaneReplayData.has(feedId)) continue;
        const frames = Array.isArray(this.timeline?.feeds?.[feedId])
          ? this.timeline.feeds[feedId].filter((frame) => frame?.timeline_provider === 'hurricane_history')
          : [];
        if (frames.some((frame) => !this.hurricaneFrameCache.has(frameCacheKey(frame)))) {
          return true;
        }
      }
    }
    return false;
  },

  async _warmRequiredHistory() {
    const timeline = this.timeline;
    const contracts = timeline?.preload_history || {};
    const batches = [];
    const run = ++this.hurricaneWarmupRun;
    for (const [feedId, contract] of Object.entries(contracts)) {
      if (!contract?.preload_history || String(contract.provider || '') !== 'hurricane_history') continue;
      const frames = Array.isArray(timeline?.feeds?.[feedId])
        ? timeline.feeds[feedId].filter((frame) => frame?.timeline_provider === 'hurricane_history').reverse()
        : [];
      if (frames.length && !this.hurricaneReplayData.has(feedId)) {
        batches.push(this._preloadHurricaneFrames(frames, timeline, this.backgroundPrefetchRun, contract.batch_size));
      }
    }
    if (!batches.length) return;
    this.hurricaneWarmupPromise = Promise.allSettled(batches).finally(() => {
      if (run === this.hurricaneWarmupRun) {
        this.hurricaneWarmupPromise = null;
        if (this.input) this.input.disabled = false;
        if (this.selectedMs != null) this.selectAt(this.selectedMs, { preserveCurrent: true });
      }
    });
    await this.hurricaneWarmupPromise;
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
        const key = frameCacheKey(frame);
        return key && !this.nwsFrameCache.has(key);
      });
      if (!missing.length) continue;
      try {
        const response = await postMsgpack('/api/local/ops/timeline/nws-frames', {
          at: missing.map((frame) => frame.start_at),
        }, { silent: true });
        for (const loaded of response?.frames || []) {
          const key = frameCacheKey(loaded);
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
      const batch = frames.slice(index, index + batchSize);
      const missing = batch.filter((frame) => {
        const key = frameCacheKey(frame);
        return key && !this.hurricaneFrameCache.has(key);
      });
      if (!missing.length) continue;
      try {
        const response = await postMsgpack('/api/local/ops/timeline/hurricane-frames', {
          at: missing.map((frame) => frame.start_at),
        }, { silent: true });
        for (const loaded of response?.frames || []) {
          const key = frameCacheKey(loaded);
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

  _normalizeHurricaneCoord(storm, point) {
    const lat = Number(point?.latitude);
    let lon = Number(point?.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    if (String(storm?.source || '').trim().toUpperCase() === 'NHC' && lon > 0 && lon <= 180) {
      lon = -lon;
    }
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return null;
    return [lon, lat];
  },

  _buildHurricaneReplayDisplayPayload(feedId, selectedMs, selectedFrame = null) {
    const replay = this.hurricaneReplayData.get(feedId);
    if (!replay || !Array.isArray(replay.storms)) return null;
    const historyHours = Math.max(1, Number(replay.history_hours) || 72);
    const cutoffMs = selectedMs - (historyHours * 60 * 60 * 1000);
    const features = [];
    let stormCount = 0;
    for (const storm of replay.storms) {
      const points = Array.isArray(storm?.observed_track) ? storm.observed_track : [];
      const usable = points
        .map((point) => ({ point, timeMs: toMs(point?.timestamp), coord: this._normalizeHurricaneCoord(storm, point) }))
        .filter((item) => Number.isFinite(item.timeMs) && item.coord && item.timeMs >= cutoffMs && item.timeMs <= selectedMs)
        .sort((a, b) => a.timeMs - b.timeMs);
      if (!usable.length) continue;
      const latest = usable[usable.length - 1];
      const baseProps = {
        storm_id: storm.storm_id,
        name: storm.name,
        basin: storm.basin,
        source: storm.source,
        selected_observed_source: storm.selected_observed_source,
        selected_forecast_source: storm.selected_forecast_source,
        source_name: storm.source_name || storm.source || 'Tropical cyclone advisory source',
        source_url: storm.source_page_url || storm.source_url || storm.source_product_url,
        source_page_url: storm.source_page_url,
        source_product_url: storm.source_product_url,
        advisory_number: storm.advisory_number,
        issued_at: storm.issued_at,
        wind_kt: latest.point.wind_kt,
        max_wind_kt: Math.max(...usable.map((item) => Number(item.point.wind_kt)).filter(Number.isFinite), 0),
        category: latest.point.category,
        max_category: latest.point.category,
        event_type: 'hurricane',
        track_state: 'replay',
        track_opacity: 0.95,
        last_observed_at: latest.point.timestamp,
        track_kind: 'observed',
      };
      stormCount += 1;
      if (usable.length >= 2) {
        features.push({
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: usable.map((item) => item.coord) },
          properties: { ...baseProps, line_style: 'solid' },
        });
      }
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: latest.coord },
        properties: {
          ...baseProps,
          ...latest.point,
          longitude: latest.coord[0],
          latitude: latest.coord[1],
          track_kind: 'current',
        },
      });
    }
    if (!features.length) return null;
    return {
      type: 'data',
      data_type: 'events',
      event_type: 'hurricane',
      source_id: 'hurricanes_live_ops',
      snapshot_hash: selectedFrame?.payload_hash || null,
      dataset_name: 'Hurricanes',
      source_name: 'Tropical cyclone advisory sources',
      summary: `Showing ${stormCount} recent storm tracks from advisory sources.`,
      count: stormCount,
      fit: false,
      ops_default_view: 'history',
      geojson: { type: 'FeatureCollection', features },
    };
  },

  _hurricanePayloadAt(payload, selectedMs) {
    if (!payload?.geojson?.features?.length || !Number.isFinite(selectedMs)) return payload;
    const features = payload.geojson.features.map((feature) => {
      if (feature?.properties?.track_kind !== 'forecast' || feature?.geometry?.type !== 'LineString') return feature;
      const coordinates = Array.isArray(feature.geometry.coordinates) ? feature.geometry.coordinates : [];
      const times = Array.isArray(feature.properties?.forecast_timestamps) ? feature.properties.forecast_timestamps : [];
      if (coordinates.length < 2 || times.length !== coordinates.length) return feature;
      const revealed = coordinates.filter((coordinate, index) => {
        const at = toMs(times[index]);
        // The first coordinate is the current observed fix: keep it as the
        // anchor, but do not draw a dotted segment until a later source-valid
        // forecast point has entered the future cursor.
        return index === 0 || (Number.isFinite(at) && at <= selectedMs);
      });
      if (revealed.length < 2) return null;
      return { ...feature, geometry: { ...feature.geometry, coordinates: revealed } };
    }).filter(Boolean);
    return { ...payload, geojson: { ...payload.geojson, features } };
  },
};
