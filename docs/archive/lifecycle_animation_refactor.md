# Universal Event Lifecycle Animation Refactor

Design document for implementing consistent three-phase animation across all disaster types.

---

## Current State (Post-Implementation)

Unified time-based animation system implemented:
- Earthquakes: Expanding circle based on timestamp (magnitude-driven speed/radius)
- Hurricanes: Progressive track drawing via coordinate trimming in filterByLifecycle
- Tsunamis: Expanding wave based on 720 km/h propagation speed
- Volcanoes: Expanding ash cloud based on VEI
- Others: Static display with opacity fade

**Solved Problems:**
1. All animations are time-based (not playback-based) - works when stepping/scrubbing
2. Hurricane tracks no longer use separate MultiTrackAnimator for rolling mode
3. Click interaction preserved (TrackModel handles all phases)
4. No flash artifacts (single rendering path via filterByLifecycle)

**Remaining Work:**
- Tornado: Could use progressive track (currently uses separate click animation)
- Wildfire: Has separate progression system (not unified)
- Flood: Static display (no expansion animation)
- "Start" phase (single dot): Not implemented - events appear with small radius

---

## Proposed Design: Three-Phase Lifecycle

Every disaster event follows the same lifecycle:

```
Timeline:
    start_ms                    end_ms                      fade_end_ms
        |                          |                             |
        v                          v                             v
--------|==========================|~~~~~~~~~~~~~~~~~~~~~~~~~~~~~|--------
        |        ACTIVE            |          FADING             |
        |  (animation plays)       |   (final state + opacity)   |

Display phases:
        |                          |                             |
   START MARKER              FULL ANIMATION              FINAL STATE
   (single point)        (progressive reveal)        (complete extent)
```

### Phase Definitions

| Phase | Trigger | Display | Interaction |
|-------|---------|---------|-------------|
| **Start** | Event enters active period | Starting position only | Clickable dot |
| **Active** | During active period | Animation progress based on elapsed time | Clickable current position |
| **Fade** | Event exits active period | Full final extent | Clickable full extent |

---

## Per-Type Implementation

### Earthquake

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | Epicenter dot only | Single point, no radius |
| Active | Expanding circle | Radius = f(elapsed_time, magnitude) |
| Fade | Full felt radius circle | Static circle at max radius |

**Animation Formula:**
```javascript
// Radius grows from 0 to max over expansion_duration
const elapsedMs = currentTime - startMs;
const progress = Math.min(1, elapsedMs / expansionDuration);
const currentRadius = maxRadius * progress;
```

### Hurricane

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | First position dot only | Single point at start_date location |
| Active | Track drawn up to current time | Line from position[0] to position[currentIndex] |
| Fade | Full track line | Complete LineString |

**Animation Formula:**
```javascript
// Find position index based on current time
const elapsedMs = currentTime - startMs;
const totalDuration = endMs - startMs;
const progress = Math.min(1, elapsedMs / totalDuration);
const currentIndex = Math.floor(progress * (positions.length - 1));
// Draw track from 0 to currentIndex
```

### Tsunami

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | Epicenter dot only | Single point |
| Active | Expanding concentric wave rings | Multiple circles at wave front |
| Fade | Full extent circle | Max radius reached |

**Animation Formula:**
```javascript
// Wave propagates at ~720 km/h
const elapsedMs = currentTime - startMs;
const waveRadiusKm = elapsedMs * WAVE_SPEED_KM_PER_MS;
const currentRadius = Math.min(waveRadiusKm, maxRadius);
```

### Volcano

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | Location dot only | Single point |
| Active | Expanding ash cloud circle | Radius grows based on VEI |
| Fade | Full ash coverage circle | Max radius based on felt_radius_km |

### Wildfire

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | Ignition point only | Single point at fire origin |
| Active | Perimeter polygon grows | Interpolate between progression polygons |
| Fade | Final burn perimeter | Complete polygon |

### Flood

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | Flood center point only | Single point |
| Active | Water spread animation | Expanding polygon/circle |
| Fade | Full flood extent | Complete affected area |

### Tornado

| Phase | Display | Technical |
|-------|---------|-----------|
| Start | Touchdown point only | Single point |
| Active | Track drawn progressively | Line grows along path |
| Fade | Full tornado path | Complete track line |

---

## Architecture Changes

### New: `_animationProgress` Property

filterByLifecycle() will calculate and attach animation progress to each feature:

```javascript
function filterByLifecycle(features, currentMs, eventType) {
  return features.map(f => {
    const startMs = config.getStartMs(f);
    const endMs = config.getEndMs(f);
    const fadeEndMs = endMs + config.fadeDuration;

    let phase, animationProgress, opacity;

    if (currentMs < startMs) {
      // Not yet started - don't include
      return null;
    } else if (currentMs <= endMs) {
      // Active phase
      phase = 'active';
      animationProgress = (currentMs - startMs) / (endMs - startMs);
      opacity = 1.0;
    } else if (currentMs <= fadeEndMs) {
      // Fade phase
      phase = 'fading';
      animationProgress = 1.0; // Animation complete
      opacity = 1.0 - (currentMs - endMs) / config.fadeDuration;
    } else {
      // Fully faded - don't include
      return null;
    }

    return {
      ...f,
      properties: {
        ...f.properties,
        _phase: phase,
        _animationProgress: animationProgress,  // 0-1
        _opacity: opacity
      }
    };
  }).filter(Boolean);
}
```

### Model Changes

Each model reads `_animationProgress` to determine display:

**PointRadiusModel:**
```javascript
// Circle radius based on progress
'circle-radius': [
  '*',
  ['get', 'maxRadius'],
  ['coalesce', ['get', '_animationProgress'], 1.0]
]
```

**TrackModel (new rolling mode built-in):**
```javascript
// Line-trim based on progress (MapLibre feature)
'line-trim-offset': [
  'literal',
  [0, ['coalesce', ['get', '_animationProgress'], 1.0]]
]
```

**PolygonModel:**
```javascript
// Opacity based on progress (start invisible, end full)
// Or scale transform if geometry supports it
```

### Remove TrackAnimator for Rolling Mode

Instead of separate TrackAnimator, TrackModel handles progressive track display via `_animationProgress`. Benefits:
- Consistent click handling (TrackModel already has it)
- No flash between overview and animator
- Works while paused (progress based on timestamp, not playback)

---

## Key Insight: Time-Based, Not Playback-Based

**Current Problem:** Animation tied to playback state (isPlaying)

**Solution:** Animation tied to timestamp comparison

```javascript
// DON'T do this (tied to playback):
if (isPlaying) {
  advanceAnimation();
}

// DO this (tied to time):
const progress = (currentTimestamp - startTimestamp) / duration;
renderAtProgress(progress);
```

This means:
- Stepping through time shows correct animation frame
- Pausing shows frozen animation state (not overview)
- Scrubbing shows smooth animation interpolation
- No flash when crossing phase boundaries

---

## Implementation Order

### Phase 1: Core Infrastructure - COMPLETE
- [x] Update filterByLifecycle to calculate _animationProgress
- [x] Add _phase property ('active', 'fading')
- [x] Pass progress to model render calls

### Phase 2: Hurricane Track Progressive Display - COMPLETE
- [x] Trim LineString coordinates in filterByLifecycle based on _animationProgress
- [x] Remove MultiTrackAnimator rolling mode dependency
- [x] Test: track draws progressively based on timestamp
- Note: line-trim not used (MapLibre doesn't support it); coordinates trimmed instead

### Phase 3: Earthquake/Tsunami Expanding Radius - COMPLETE
- [x] PointRadiusModel uses _waveRadiusKm for expanding circles
- [x] Earthquakes, tsunamis, volcanoes expand based on timestamp

### Phase 4: Other Types - PARTIAL
- [x] Volcano: Expanding circle (same as earthquake)
- [ ] Tornado: Progressive track (uses separate click-based animation)
- [ ] Wildfire: Polygon interpolation (uses separate progression system)
- [ ] Flood: Circle/polygon expansion (static display currently)

### Phase 5: Cleanup - COMPLETE
- [x] MultiTrackAnimator rolling mode disabled (checkHurricaneRollingAnimation returns early)
- [x] Documentation updated
- [x] Animation is time-based (timestamp comparison), not playback-based

---

## Files Modified

| File | Changes | Status |
|------|---------|--------|
| overlay-controller.js | filterByLifecycle calculates _animationProgress, trims hurricane LineStrings, disabled MultiTrackAnimator rolling mode | DONE |
| model-point-radius.js | Uses _waveRadiusKm for expanding circles (earthquakes, tsunamis, volcanoes) | DONE |
| model-track.js | Uses _opacity for lifecycle fade; progressive track via trimmed coordinates | DONE |
| track-animator.js | Rolling mode disabled; focused drill-down mode preserved for individual storm animation | DONE |
| model-polygon.js | Uses _opacity for lifecycle fade | DONE |

---

## Benefits

1. **Consistent behavior** - All types follow same lifecycle
2. **Time-based display** - Works stepping, paused, or playing
3. **No flash artifacts** - Single rendering path, no overlay switching
4. **Click always works** - Same model handles all phases
5. **Simpler code** - Remove separate TrackAnimator rolling logic

---

## Answers to Open Questions

1. **Wildfire/Flood progression:** Three display options based on data availability:
   - **Option A:** Time-series polygons - animate through sequence
   - **Option B:** Final polygon only - fade in during active phase
   - **Option C:** Point with expanding circle - fallback when no polygon data

2. **Performance:** TBD - will monitor during implementation

3. **Line-trim support:** MapLibre does NOT support `line-trim-offset` (Mapbox-only feature, [open issue #1360](https://github.com/maplibre/maplibre-style-spec/issues/1360)).
   **Alternative:** Update GeoJSON LineString coordinates to include only points up to current progress (same as current TrackAnimator approach, just calculated from timestamp instead of playback state).

---

*Created: 2026-01-12*
*Updated: 2026-01-14*
*Status: IMPLEMENTED (Phases 1-3, 5 complete; Phase 4 partial)*
