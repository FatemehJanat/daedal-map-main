# Time and Animation System

Current reference for the shared timeline/playback system in
`static/modules/time-slider.js` and how every display model plugs into it.

Unified 2026-07 (legacy playback paths removed). If playback behaves
differently between two overlay types, that is a bug against this contract,
not a per-overlay feature.

---

## The core model

There is ONE playback system for every overlay type:

- **The timeline is continuous timestamps** (ms since epoch), always. Yearly
  data is normalized on entry (`normalizeToTimestamp` maps 2024 to Jan 1 2024
  UTC); sub-yearly data passes real timestamps.
- **The speed slider is "how much data time passes per real second."**
  Internally `stepsPerFrame` (multiples of a 6-hour base step per rendered
  frame at 30 FPS). The label ("1mo/sec", "1yr/sec") is a direct conversion
  of `stepsPerFrame` -- there are no per-mode label formulas.
- **Playback advances continuous time**, ticking at
  `TIME_SYSTEM.FRAME_INTERVAL_MS` (~33ms / 30 FPS). Each tick advances by
  `stepsPerFrame x actual elapsed wall time`, so the displayed speed stays
  true even when a heavy frame makes a tick late (the animation skips frames
  under load rather than running slow-motion). Catch-up after a
  backgrounded/throttled tab is capped at 5 frame intervals.
- **Rendering snaps to real data frames at lookup time.** The playhead almost
  never lands exactly on a data timestamp, and no renderer should expect it
  to. Each display family owns its snap:

| Display family | Snap mechanism |
|----------------|----------------|
| Choropleths (`models/model-choropleth.js`) | calls back into `slider.getDataLookupKey`, which snaps to the most recent available time at or before the playhead (yearly mode: `timestampToYear`) |
| Rasters (`models/raster-core.js` consumers: ocean grid, Fairfax scenes; weather grid pending migration) | `frameIndexForTime` binary frame search |
| Event overlays (earthquakes, hurricanes, ...) | time-window filtering around the playhead (`filterByLifecycle`) |

Datasets of any cadence (6-hourly, weekly, monthly, yearly, mixed) therefore
play through the same loop: where frames are dense the animation is smooth,
where they are sparse the current frame holds until the next one -- no mode
switch, no dataset-specific playback code.

## What datasets must provide

Registering with the slider (`setTimeRange` / scale config):

- `min` / `max` -- range bounds (years or timestamps; normalized internally)
- `granularity` -- label/formatting hint (e.g. 'weekly', 'monthly', 'yearly')
- `available` -- the REAL timestamp array of data frames. This drives the
  indexed slider track (data-density positioning), the step buttons, and
  choropleth lookup snapping. Do not fabricate evenly-spaced timestamps.

## What was removed (do not reintroduce)

The 2026-07 unification deleted these parallel systems from time-slider.js:

- **Discrete/indexed playback** (`advanceDiscreteTime` + fractional carry):
  playback used to hop index-to-index through `sortedTimes` for indexed
  scales and yearly data. Replaced by continuous time + snap-at-lookup.
- **Legacy interval playback** (granularity-based `setInterval` table,
  `getPlaybackInterval`): dead fallback for a missing speed slider; the
  speed slider is always in the app shell.
- **Fast-forward / rewind** (`FAST_SPEED`, `playSpeed`, `playFast`,
  `rewindBtn`/`fastFwdBtn`): "fast" is just the speed slider; "rewind" is
  clicking back in the timeline. The step buttons (`stepToNext`/`stepToPrev`)
  remain and deliberately jump frame-by-frame through `available` times.
- **`stepMs` / `calculateStepMs` / per-mode speed-label math**: playback no
  longer needs a per-granularity step size; the label is one conversion.

Still present and intentional (not playback):

- `useIndexedScale` / `sortedTimes` -- slider TRACK positioning by data
  density, and the snap source for lookups.
- Trim bounds (playback range constraint), live mode, event mode (which now
  only auto-picks a speed), multi-scale tabs.
- The YEAR LANE in `overlay-controller.js` `handleTimeChange`
  (`|time| < 50000` = bare year integer): the deliberate path for
  year-granularity and very old / pre-epoch history data. Not legacy.

## Module map (after the 2026-07 unification)

- `time-slider.js` -- time source + UI only: range/available registration,
  continuous playback, trim bounds, scales/tabs, live mode. Choropleth data
  and rendering delegate to `models/model-choropleth.js`.
- `models/model-choropleth.js` -- metric timeData storage, gap filling,
  admin-level filtering, geojson build, render-on-time-change (with
  data-key dedup).
- `models/raster-core.js` -- shared raster primitives (color LUT, uint8
  dequantize, Mercator pre-warp, frame renderers, image-source placement,
  visibility caching, frame search). Consumed by
  `models/model-ocean-raster.js` (warped, NaN nodata, multi-cadence layer
  merge) and `scene-raster-model.js` (unwarped, falsy-0 nodata, loc_id
  clips). `models/model-weather-grid.js` migrates when weather gets a
  hosted data path.
- `overlay-disaster-common.js` -- shared focus-animation session lifecycle:
  `takeOverTimeSliderScale`/`releaseTimeSliderScale` and the single
  `routeTimeToFocusAnimation` gate used by `handleTimeChange`;
  `event-animator.js` and `track-animator.js` keep their render strategies.
- `overlay-cache.js` / `overlay-cache-ops.js` -- `loadedRanges` is the
  loaded-coverage source of truth (`isYearLoaded` derives year coverage;
  chat-seeded data records a `__seeded__`-signature range). `loadedYears`
  survives only for the weather grid.
- Chat order results for events/storms route through
  `OverlayController.applyEventOrderResult` into this same system -- chat,
  overlay toggles, and focus views are entry points, not parallel renderers.

## Multi-cadence datasets (ocean SST pattern)

A pack can ship the same variable at several cadences (ocean_sst: a weekly
"recent" bundle from 2025-07 plus a monthly 1982+ history bundle). The
contract, implemented in `models/model-ocean-raster.js` +
`overlay-controller.js`:

- Bundles MERGE into one model instance; the instance timeline is the sorted
  union of all bundles' timestamps (denser where finer data exists).
- The renderer shows the finest-cadence bundle covering the current playhead
  (`_activeLayersForTime`; coarser overlapping layers get `visibility: none`).
- The coarse/history bundle loads on demand when the playhead leaves the
  loaded range (see the ocean-raster branch of `onTimeChangeTimestamp`);
  in-flight fetches make repeated per-tick calls no-ops.
- Playback density then rises naturally as the playhead enters the finer
  window -- no tier switch is visible to the slider.

Use this pattern (merge + finest-cadence-wins), not a swap between bundles,
for any future multi-resolution time series.

---

*Created: 2026-07-06*
