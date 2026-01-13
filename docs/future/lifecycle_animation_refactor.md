# Universal Event Lifecycle Animation Refactor

Design document for implementing consistent three-phase animation across all disaster types.

---

## Current State

Each disaster type has ad-hoc animation behavior:
- Earthquakes: Show expanding circle immediately (no "start" phase)
- Hurricanes: TrackAnimator draws progressive track, but flash issues at start/end
- Tsunamis: Expanding wave circle (similar to earthquake)
- Others: Static display with opacity fade

**Problems:**
1. No consistent "start" phase - full display appears instantly
2. Animation only works during playback (stepping shows inconsistent state)
3. Click interaction lost during some animations (TrackAnimator)
4. Flash artifacts at phase transitions

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

### Phase 1: Core Infrastructure
- [ ] Update filterByLifecycle to calculate _animationProgress
- [ ] Add _phase property ('start', 'active', 'fading')
- [ ] Pass progress to model render calls

### Phase 2: Hurricane Track Progressive Display
- [ ] Add line-trim support to TrackModel
- [ ] Build LineString from track positions in filterByLifecycle
- [ ] Remove TrackAnimator rolling mode dependency
- [ ] Test: track draws progressively based on timestamp

### Phase 3: Earthquake/Tsunami Expanding Radius
- [ ] Modify PointRadiusModel to use _animationProgress for radius
- [ ] Test: circles expand from 0 to max based on timestamp

### Phase 4: Other Types
- [ ] Volcano: Same as earthquake (expanding circle)
- [ ] Tornado: Same as hurricane (progressive track)
- [ ] Wildfire: Polygon interpolation (if progression data available)
- [ ] Flood: Circle/polygon expansion

### Phase 5: Cleanup
- [ ] Remove TrackAnimator rolling mode
- [ ] Update documentation
- [ ] Remove isPlaying checks from animation code

---

## Files to Modify

| File | Changes |
|------|---------|
| overlay-controller.js | Update filterByLifecycle, remove rolling animation calls |
| model-point-radius.js | Use _animationProgress for circle-radius |
| model-track.js | Add line-trim for progressive track, built-in progress |
| model-polygon.js | Add _animationProgress support |
| track-animator.js | Remove rolling mode (keep focused drill-down mode) |

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
*Status: Planning*
