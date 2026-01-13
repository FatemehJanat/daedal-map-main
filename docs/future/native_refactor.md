# Native Refactor Planning

Future architecture considerations for moving beyond browser-based webapp.

---

## Current Architecture

```
Browser (Chrome/Firefox)
    |
    v
Flask API (localhost:5000)
    |
    +---> Pandas (data processing)
    +---> Parquet files (storage)
    +---> Claude API (LLM, online)
    |
    v
JSON responses -> Browser renders with Leaflet/MapLibre
```

**Current bottlenecks:**
1. JSON serialization of geometry (biggest)
2. Browser JSON parsing
3. Pandas DataFrame operations
4. LLM round-trip latency (inherent)

---

## Why Browser Feels Slow

### Where Time Goes

| Operation | Time | Bottleneck |
|-----------|------|------------|
| Parquet load | ~50ms | Disk I/O |
| Pandas filter | ~20ms | CPU |
| JSON serialize | ~200ms | CPU (geometry is verbose) |
| HTTP transfer | ~5ms | Localhost, negligible |
| JSON.parse() | ~150ms | Browser CPU |
| Leaflet render | ~100ms | Canvas/WebGL |
| **Total** | ~500ms+ | Mostly serialization |

### Browser Sandbox Limitations

| Resource | Browser Limit | Native Potential |
|----------|---------------|------------------|
| Memory per tab | ~2-4GB | System RAM |
| CPU threads | 1 main + Web Workers | All cores |
| GPU access | WebGL/WebGPU only | Direct CUDA/Vulkan |
| File I/O | Async APIs | Direct mmap |
| LLM inference | External service only | Embed llama.cpp |

### GPU Utilization Problem

Browser restricts GPU to:
- WebGL rendering (maps, 3D)
- Video decode
- CSS transforms

Browser CANNOT use GPU for:
- General compute (CUDA/OpenCL)
- LLM inference
- Data processing
- Custom compute shaders

This is why GPU shows ~5% usage even with complex visualizations.

---

## Performance Upgrade Stack

Layered improvements, each independent:

| Layer | Change | Speedup | Effort |
|-------|--------|---------|--------|
| **Storage** | CSV -> Parquet | 5-10x | Done |
| **Serialization** | JSON -> MessagePack | 2-5x | Easy |
| **Processing** | Pandas -> Polars | 5-20x | Medium |
| **Rendering** | Leaflet -> deck.gl | 10x+ | Medium |
| **Architecture** | Browser -> Native | 2-3x | High |

### Layer 1: MessagePack (Easy)

Replace JSON with binary MessagePack:

```python
# Flask backend
import msgpack

@app.route('/api/data')
def get_data():
    data = load_and_process()
    return Response(
        msgpack.packb(data),
        mimetype='application/msgpack'
    )
```

```javascript
// Frontend
import msgpack from '@msgpack/msgpack';

const response = await fetch('/api/data');
const buffer = await response.arrayBuffer();
const data = msgpack.decode(new Uint8Array(buffer));
```

**Gains:** 2-3x faster API responses, 50% smaller payloads

### Layer 2: Polars (Medium)

Replace Pandas with Rust-based Polars:

```python
# Before (Pandas)
import pandas as pd
df = pd.read_parquet(file)
filtered = df[df['year'] == 2020]
result = filtered.groupby('loc_id').agg({'population': 'sum'})

# After (Polars)
import polars as pl
df = pl.scan_parquet(file)  # Lazy evaluation
result = (
    df.filter(pl.col('year') == 2020)
    .group_by('loc_id')
    .agg(pl.col('population').sum())
    .collect()  # Execute
)
```

**Gains:** 5-20x faster, lazy evaluation, better memory

### Layer 3: WebGL Rendering (Medium)

Replace Leaflet choropleth with GPU-accelerated deck.gl:

```javascript
import { DeckGL } from '@deck.gl/react';
import { GeoJsonLayer } from '@deck.gl/layers';

// GPU handles color interpolation and rendering
const layer = new GeoJsonLayer({
    data: geojsonFeatures,
    getFillColor: d => colorScale(d.properties.value),
    // Renders 100k+ polygons at 60fps
});
```

**Gains:** 10-100x more features at 60fps

### Layer 4: Native App (High Effort)

Full rewrite options:

| Framework | Language | Pros | Cons |
|-----------|----------|------|------|
| **Tauri** | Rust + existing JS | Keep frontend, fast backend | Learning Rust |
| **Electron** | JS | Easy migration | Still browser limits |
| **Qt/PySide** | Python | Native widgets | Rebuild UI |
| **egui** | Rust | GPU-native, fast | Full rewrite |

---

## Multi-GPU Architecture

For serious local deployment with dedicated hardware:

```
GPU 0 (Integrated/Small)
    -> OS display, desktop compositing

GPU 1 (Mid-tier, e.g., RTX 3060)
    -> App rendering (WebGL/Vulkan maps, animations)
    -> deck.gl or wgpu visualization

GPU 2 (High-end, e.g., RTX 4090)
    -> LLM inference (llama.cpp with CUDA)
    -> 24GB VRAM = ~70B parameter model at Q4
```

**Benefits:**
- No GPU context switching
- LLM doesn't stutter rendering
- Each GPU has dedicated VRAM
- Clean parallelization (no shared state)

**Requirements:**
- Native app (browser can't orchestrate multi-GPU)
- Explicit GPU selection in code
- Separate CUDA contexts

---

## Nullschool-Style Visualization

Reference: https://earth.nullschool.net/

To achieve fluid particle animations like nullschool:

### Current Approach (Slow)
```
1. Load all data points (JSON)
2. CPU calculates positions (JavaScript)
3. Canvas draws particles
Result: 1000s of particles, ~30fps
```

### GPU Approach (Fast)
```
1. Load data as GPU texture
2. Shader interpolates field (GPU)
3. Shader renders particles (GPU)
Result: 100,000+ particles at 60fps
```

### Implementation Path

1. **Encode data as textures** - Wind/current vectors as RGB values
2. **Write GLSL shaders** - Particle advection, interpolation
3. **Use WebGL2 or wgpu** - Transform feedback for particle state
4. **Stream updates** - WebSocket for live data

**Libraries:**
- regl (WebGL wrapper)
- deck.gl (high-level)
- wgpu (native, Rust)

---

## Local LLM Integration

### Phase 1: Ollama Backend (Keep Browser)

```
Browser <--HTTP--> Flask <--HTTP--> Ollama (localhost:11434)
```

- Install Ollama, run model
- Flask proxies to Ollama instead of Claude API
- No browser changes needed

### Phase 2: Embedded LLM (Native App)

```
Native App
    |
    +---> llama.cpp (embedded, same process)
    +---> GPU inference (CUDA/Metal)
```

- Tauri + llama-cpp-rs
- Or Python + llama-cpp-python
- Direct memory sharing, no HTTP

### Model Size vs VRAM

| VRAM | Max Model (Q4) | Examples |
|------|----------------|----------|
| 8GB | ~13B params | Llama 3 8B, Mistral 7B |
| 12GB | ~20B params | Llama 3 13B |
| 24GB | ~70B params | Llama 3 70B, Mixtral |
| 48GB | ~120B params | Larger models |

---

## Recommended Evolution Path

### Now (Browser + Flask)
- Fine for: Data viz, online LLM, URL sharing
- Limits: Memory cap, no GPU compute, JSON overhead

### Phase 1: Optimize Within Browser
- MessagePack for serialization
- Polars for data processing
- deck.gl for rendering
- Client-side caching (IndexedDB)
- **Result:** 3-5x faster, still browser-based

### Phase 2: Add Local LLM
- Ollama running as service
- Flask routes to localhost:11434
- Offline-capable for LLM
- **Result:** No Claude API dependency

### Phase 3: Tauri Shell (If Needed)
- Keep existing HTML/JS/CSS frontend
- Rust backend for file I/O, IPC
- No JSON serialization (direct memory)
- Native file dialogs, system tray
- **Result:** Native feel, keep web skills

### Phase 4: Full Native (If Scale Demands)
- egui or Qt for UI
- wgpu for GPU rendering
- Embedded llama.cpp
- Multi-GPU orchestration
- **Result:** Maximum performance, full hardware access

---

## Decision Matrix

| Need | Browser OK? | Recommendation |
|------|-------------|----------------|
| Data viz < 10k features | Yes | deck.gl |
| Data viz > 100k features | Marginal | Native + wgpu |
| Online LLM | Yes | Current setup |
| Local LLM (small) | Yes | Ollama service |
| Local LLM (large, GPU) | No | Native + llama.cpp |
| Multi-GPU | No | Native required |
| Offline-first | Partial | Tauri or native |
| URL sharing | Yes | Keep web version |

---

## Hardware Upgrades: What Helps Where

### Helps NOW (Browser)
- **SSD**: Faster parquet loads
- **RAM (8-16GB)**: More Flask headroom
- **CPU**: Faster pandas/JSON

### Only Helps with Native
- **GPU (beyond rendering)**: Compute, LLM
- **RAM > 16GB**: Large in-memory datasets
- **Multi-core CPU**: True parallelism
- **Multiple GPUs**: Dedicated workloads

---

## Links and References

- **deck.gl**: https://deck.gl/
- **Polars**: https://pola.rs/
- **Tauri**: https://tauri.app/
- **Ollama**: https://ollama.ai/
- **llama.cpp**: https://github.com/ggerganov/llama.cpp
- **wgpu**: https://wgpu.rs/
- **earth.nullschool.net**: https://earth.nullschool.net/ (inspiration)

---

## The Real Data Journey

### Current (Web App)

```
1. Disk (SSD)
   | ~50ms - read parquet bytes
   v
2. Python RAM (DataFrame)
   | ~200ms - json.dumps() converts to STRING
   v
3. JSON String in Python RAM
   | ~5ms - HTTP socket (localhost = memory copy)
   v
4. JSON String in Browser RAM
   | ~150ms - JSON.parse() converts to OBJECTS
   v
5. JavaScript Objects in Browser RAM
   | ~50ms - MapLibre converts to GPU format
   v
6. GPU VRAM (vertices, textures)
   | ~16ms - render
   v
7. Screen

Total transforms: 5
Serialization steps: 2 (json.dumps + JSON.parse)
```

### Native App

```
1. Disk (SSD)
   | ~50ms - read parquet bytes
   v
2. App RAM (DataFrame or direct buffer)
   | ~10ms - convert to GPU format (no JSON!)
   v
3. GPU VRAM (vertices, textures)
   | ~16ms - render
   v
4. Screen

Total transforms: 2
Serialization steps: 0
```

### Why "Local" HTTP Isn't Really Local

```
Python process                    Browser process
[DataFrame]                       [JS Objects]
     |                                 |
     v                                 v
[json.dumps]  ----socket---->    [JSON.parse]
     ^                                 ^
     |                                 |
  ~200ms                            ~150ms
```

Even though the socket is localhost, you're still:
1. **Serializing** - turning structured data into text
2. **Copying** - Python RAM -> kernel buffer -> browser RAM
3. **Deserializing** - parsing text back into structures

The "localhost" part is fast (~5ms). The format conversion is slow (~350ms).

### Native: Same Process, Shared Memory

```
Native App (single process)
[DataFrame in RAM]
     |
     | direct pointer, no copy
     v
[GPU upload buffer]
     |
     | DMA transfer
     v
[GPU VRAM]
```

No serialization. No parsing. Just memory addresses.

### The Geometry Problem Specifically

Your 16MB GeoJSON looks like:
```json
{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[151.2,-33.8],[151.3,-33.9]...
```

Every coordinate is a text string that has to be:
- **Python**: float -> "151.2" (number to string)
- **Browser**: "151.2" -> float (string to number)

In a native app with binary format:
```
[4 bytes: 151.2 as IEEE 754 float]
```
No conversion. Just copy the bytes.

### Transfer Summary

| "Transfer" Type | Web App | Native App |
|-----------------|---------|------------|
| Disk -> RAM | Same | Same |
| RAM -> RAM (serialize) | Slow (JSON) | N/A |
| Process -> Process | Slow (HTTP+parse) | N/A (same process) |
| RAM -> GPU | Same | Same |

Native removes the middle layers entirely. The speed gain isn't from "faster network" - it's from eliminating format conversions.

---

## GPU Compute Beyond LLM

GPU acceleration applies to more than just LLM inference:

### Geospatial Operations (cuSpatial)

| Operation | CPU Time | GPU Time | Use Case |
|-----------|----------|----------|----------|
| Point-in-polygon (1M points) | ~5 sec | ~50ms | "Which county contains each earthquake?" |
| Spatial join (100k x 100k) | ~30 sec | ~200ms | Joining datasets by location |
| Distance matrix | O(n^2) slow | O(n^2) fast | Proximity analysis |
| Polygon simplification | seconds | milliseconds | Level-of-detail rendering |

### Data Processing (RAPIDS cuDF)

| Operation | Pandas | cuDF (GPU) |
|-----------|--------|------------|
| GroupBy + Sum (10M rows) | ~2 sec | ~50ms |
| Filter + Sort | ~1 sec | ~20ms |
| Merge/Join large tables | ~5 sec | ~100ms |

```python
# cuDF - GPU DataFrames (same API as Pandas)
import cudf

df = cudf.read_parquet("huge_dataset.parquet")  # Loads to GPU
result = df.groupby('loc_id').agg({'population': 'sum'})  # GPU compute
```

### When GPU Compute Matters

GPU becomes essential when:
- **100k+ features** - Individual earthquake points, weather stations
- **Real-time updates** - Live data streaming, continuous recalculation
- **Complex spatial queries** - "All counties within 100km of coastline"
- **Large aggregations** - "Sum GDP across all NUTS-3 regions for 20 years"
- **Particle animations** - Nullschool-style wind/current visualization (100k particles at 60fps)

### What GPU is BAD At

- Small datasets (<10k rows) - transfer overhead exceeds benefit
- Sequential logic with dependencies
- Heavy branching (if/else per item)
- Random memory access patterns

---

## Live World View vs Historical Exploration

Two major operational modes with different technical requirements:

### Mode Comparison

| Aspect | Historical Exploration | Live World View |
|--------|------------------------|-----------------|
| Data flow | Pull on demand | Push/stream continuously |
| Update frequency | Query-triggered | Seconds to minutes |
| Rendering | Static choropleth | Animated particles, moving icons |
| Storage | Parquet files | Time-series DB + archive |
| GPU usage | Occasional | Continuous |
| Network | Burst (query) | Sustained (WebSocket) |

### Live Data Source Examples

| Source | Data Type | Update Rate | Format |
|--------|-----------|-------------|--------|
| NOAA GFS | Weather grids | 6 hours | GRIB2 |
| NASA FIRMS | Active fires | 3 hours | CSV/GeoJSON |
| USGS Earthquake | Seismic events | Real-time | GeoJSON feed |
| GDACS | Disaster alerts | Minutes | RSS/XML |
| Lightning networks | Strikes | Seconds | WebSocket |
| AIS | Ship positions | Seconds | WebSocket |
| River gauges | Water levels | 15 min | API |

### Dual Mode Architecture

```
                    +------------------+
                    |   Data Ingestors |
                    +------------------+
                           |
          +----------------+----------------+
          |                                 |
          v                                 v
   +-------------+                  +---------------+
   | Live Buffer |                  | Archive Write |
   | (in-memory) |                  | (time-series) |
   +-------------+                  +---------------+
          |                                 |
          v                                 v
   +-------------+                  +---------------+
   | Live Render |                  | Historical    |
   | (GPU stream)|                  | Query Engine  |
   +-------------+                  +---------------+
          |                                 |
          +----------------+----------------+
                           |
                           v
                    +-------------+
                    |   Map View  |
                    |  (overlay)  |
                    +-------------+
```

### Time-Series Database Options

| DB | Best For | Notes |
|----|----------|-------|
| TimescaleDB | SQL familiarity | PostgreSQL extension |
| InfluxDB | High ingest rate | Purpose-built for metrics |
| QuestDB | Fast queries | Good for real-time dashboards |
| DuckDB | Analytics | Could append parquet files |

### Mode Transition: Live to Historical

The key challenge is seamless transition between modes while preserving context:

```
LIVE MODE                          HISTORICAL MODE
    |                                    |
    v                                    v
[Real-time WebSocket]            [Time-range Query]
    |                                    |
    v                                    v
[Event Buffer: last 24h]  <---->  [Archive: all time]
    |                                    |
    v                                    v
[Animate as received]            [Playback at speed]
    |                                    |
    +------------+  +--------------------+
                 |  |
                 v  v
           [Unified Renderer]
                 |
                 v
           [Map Display]
```

**Transition triggers:**
- User clicks timeline scrubber -> switch to historical
- User clicks "Live" button -> switch to real-time
- User pauses playback -> freeze at current time
- User resumes -> continue from paused position OR jump to live

**Data continuity:**
- Live buffer always writes to archive in background
- Historical queries can include "up to now" for seamless handoff
- Playback speed: 1x, 10x, 100x, 1000x (watch a week in minutes)

---

## Animated Event Visualization

Beyond static dots - making events feel alive:

### Earthquake Ripple Effects

Goal: See seismic waves propagate like ripples in a pond.

**Animation approaches by complexity:**

| Approach | Max Events | FPS | Effort |
|----------|------------|-----|--------|
| CSS animations | ~20 | 30 | Low |
| Canvas 2D | ~100 | 45 | Medium |
| WebGL shaders | 1000+ | 60 | High |

**WebGL Ripple Shader (Best Performance):**

```glsl
// Fragment shader - renders expanding rings for each earthquake
uniform float u_time;
uniform sampler2D u_earthquakeData;  // Texture with [lon, lat, mag, time]
uniform int u_count;

void main() {
  vec2 pos = v_position;
  float intensity = 0.0;

  for (int i = 0; i < u_count; i++) {
    vec4 quake = texelFetch(u_earthquakeData, ivec2(i, 0), 0);
    vec2 center = quake.xy;
    float magnitude = quake.z;
    float startTime = quake.w;

    float elapsed = u_time - startTime;
    float waveSpeed = 200.0;  // pixels per second
    float waveRadius = elapsed * waveSpeed;
    float maxRadius = magnitude * 100.0;

    if (waveRadius < maxRadius) {
      float dist = distance(pos, center);
      // Concentric rings with falloff
      float ring = sin((dist - waveRadius) * 0.3);
      float falloff = exp(-abs(dist - waveRadius) * 0.02);
      float fade = 1.0 - (waveRadius / maxRadius);
      intensity += ring * falloff * fade * magnitude * 0.1;
    }
  }

  // Red glow for positive intensity, subtle blue for negative
  vec3 color = intensity > 0.0
    ? vec3(1.0, 0.3, 0.2) * intensity
    : vec3(0.2, 0.3, 0.5) * abs(intensity) * 0.3;

  gl_FragColor = vec4(color, abs(intensity));
}
```

**Realistic Seismic Wave Propagation:**

| Wave Type | Speed | Appearance | Delay After Event |
|-----------|-------|------------|-------------------|
| P-wave (primary) | ~6 km/s | Fast subtle pulse | Immediate |
| S-wave (secondary) | ~3.5 km/s | Stronger shaking | P + distance/3.5 |
| Surface waves | ~2-4 km/s | Rolling motion | P + distance/2 |

```javascript
// Calculate when each wave type arrives at a point
function waveArrivalTimes(epicenter, point, eventTime) {
  const distanceKm = haversineDistance(epicenter, point);
  return {
    pWave: eventTime + (distanceKm / 6.0) * 1000,      // ms
    sWave: eventTime + (distanceKm / 3.5) * 1000,
    surface: eventTime + (distanceKm / 2.5) * 1000
  };
}
```

### Fire Spread Animation

For NASA FIRMS data - show fires as glowing, pulsing points:

```javascript
// Pulsing glow effect based on fire confidence/intensity
const fireLayer = new ScatterplotLayer({
  id: 'active-fires',
  data: fires,
  getPosition: d => [d.longitude, d.latitude],
  getRadius: d => {
    const pulse = Math.sin(Date.now() * 0.003 + d.id) * 0.3 + 1;
    return d.bright_ti4 * 0.1 * pulse;  // Brightness affects size
  },
  getFillColor: d => {
    // Orange to red based on temperature
    const temp = Math.min(d.bright_ti4, 400);
    const r = 255;
    const g = Math.max(0, 200 - (temp - 300) * 2);
    return [r, g, 50, 200];
  },
  updateTriggers: { getRadius: [Date.now()] }
});
```

### Storm Track Animation

For hurricane/cyclone paths - animated dashed lines showing projected path:

```javascript
// Animated dashed line for storm track
const stormTrackLayer = new PathLayer({
  id: 'storm-tracks',
  data: storms,
  getPath: d => d.forecastPath,
  getColor: d => categoryColor(d.category),
  getWidth: d => 3 + d.category,
  getDashArray: [8, 4],
  dashJustified: true,
  // Animate dash offset for "marching ants" effect
  extensions: [new PathStyleExtension({ dash: true })],
  dashGapPickable: true
});
```

### Historical Playback UI

```
+------------------------------------------------------------------+
|  [<<] [<] [>] [>>]  |  1x  10x  100x  |  2024-01-15 14:32:00    |
+------------------------------------------------------------------+
|  |----o--------------------------------------------|  [LIVE]    |
|  Jan 1                                        Jan 31             |
+------------------------------------------------------------------+
```

**Playback controls:**
- Play/Pause
- Step forward/backward (1 event at a time)
- Speed multiplier (1x = real-time, 1000x = 1 day per minute)
- Scrubber for time navigation
- "Jump to Live" button

**Event buffering for smooth playback:**

```javascript
class EventPlayback {
  constructor(events) {
    // Sort by timestamp
    this.events = events.sort((a, b) => a.timestamp - b.timestamp);
    this.currentIndex = 0;
    this.playbackTime = this.events[0]?.timestamp || Date.now();
    this.speed = 1;
    this.playing = false;
  }

  tick(deltaMs) {
    if (!this.playing) return [];

    const newEvents = [];
    this.playbackTime += deltaMs * this.speed;

    // Collect all events up to current playback time
    while (this.currentIndex < this.events.length &&
           this.events[this.currentIndex].timestamp <= this.playbackTime) {
      newEvents.push(this.events[this.currentIndex]);
      this.currentIndex++;
    }

    return newEvents;
  }

  seek(timestamp) {
    this.playbackTime = timestamp;
    // Binary search for new index
    this.currentIndex = this.events.findIndex(e => e.timestamp > timestamp);
    if (this.currentIndex === -1) this.currentIndex = this.events.length;
  }

  goLive() {
    this.playbackTime = Date.now();
    this.currentIndex = this.events.length;
    // Switch to real-time feed
  }
}
```

### Animation Performance Budget

At 60fps, you have ~16ms per frame:

| Task | Budget | Notes |
|------|--------|-------|
| Event queries | 2ms | Pre-filter by visible bounds |
| Position updates | 1ms | Only for moving events |
| GPU upload | 2ms | Batch updates |
| Shader execution | 8ms | Main rendering |
| Compositing | 2ms | Layer blending |
| Buffer | 1ms | Safety margin |

**Optimization strategies:**
- Spatial indexing (R-tree) for visible event queries
- GPU instancing for repeated shapes
- Level-of-detail: fewer ripple rings when zoomed out
- Event culling: skip animations for off-screen events
- Time-based culling: fade out events older than N seconds

---

## deck.gl Animation Integration Architecture

The current animation system is designed for clean deck.gl integration when advanced effects are needed.

### Current Architecture (Ready for Extension)

```
                    +------------------+
                    |    TimeSlider    |  (Playback control, speed, scrubbing)
                    +------------------+
                            |
                            v
                    +------------------+
                    |  EventAnimator   |  (Timing, state machine, frame coordination)
                    +------------------+
                            |
                            v
                    +------------------+
                    |  ModelRegistry   |  (Routes to appropriate display model)
                    +------------------+
                            |
            +---------------+---------------+
            |               |               |
            v               v               v
     +-----------+   +-----------+   +-----------+
     |PointRadius|   |   Track   |   |  Polygon  |  (MapLibre layers)
     |   Model   |   |   Model   |   |   Model   |
     +-----------+   +-----------+   +-----------+
                            |
                            v (future)
                    +------------------+
                    |   Effects Layer  |  (deck.gl overlays)
                    +------------------+
```

### Extension Point Pattern

The key insight: **deck.gl adds as a layer ON TOP of MapLibre**, not replacing it.

```javascript
// Current: MapLibre handles base map + feature layers
const map = new maplibregl.Map({ container: 'map' });

// Future: deck.gl overlay for effects only
const deckOverlay = new MapboxOverlay({
  layers: [
    new ParticleLayer({ ... }),  // Volcano ash particles
    new RippleLayer({ ... }),    // Earthquake wave effects
    new AnimatedPathLayer({ ... }) // Storm track animations
  ]
});
map.addControl(deckOverlay);
```

**No changes needed to:**
- EventAnimator (timing/state stays the same)
- TimeSlider (playback control unchanged)
- Model render() methods (they continue to work)
- DisasterPopup (interaction still works)

### Components and Their Roles

| Component | Current Role | deck.gl Upgrade Role |
|-----------|-------------|---------------------|
| **EventAnimator** | Timing, frame dispatch | Same - dispatch to effects too |
| **TimeSlider** | User playback control | Same - no changes |
| **PointRadiusModel** | MapLibre circles/labels | Keep for base markers |
| **TrackModel** | MapLibre lines/cones | Keep for base paths |
| **PolygonModel** | MapLibre fills/strokes | Keep for base areas |
| **EffectsLayer** (new) | N/A | deck.gl particles/ripples |

### Effect Types Per Disaster

| Disaster Type | Base Layer (MapLibre) | Effect Layer (deck.gl) |
|--------------|----------------------|----------------------|
| **Earthquake** | Epicenter marker + radius | Seismic wave ripples, ground shake lines |
| **Tsunami** | Warning zone circle | Expanding wave rings, ocean texture distortion |
| **Volcano** | Location marker | Ash particle flow, plume animation |
| **Hurricane** | Track line + cone | Spiral wind particles, rain bands |
| **Wildfire** | Perimeter polygon | Ember particles, heat shimmer |
| **Flood** | Affected area polygon | Water flow particles, wave patterns |

### Implementation Approach

**Phase 1 (Current):** CSS + MapLibre animations
- Pulsing markers, expanding circles
- Works for ~20 concurrent events at 30fps
- Simple, no additional dependencies

**Phase 2:** Canvas 2D overlay
- Custom canvas element over map
- Draw particles/ripples in 2D context
- Works for ~100 events at 45fps
- Medium complexity

**Phase 3:** deck.gl WebGL integration
- GPU-accelerated particle systems
- 1000+ particles at 60fps
- Advanced effects (flow fields, instancing)
- Requires deck.gl dependency

### Integration Code Pattern

When ready to add deck.gl:

```javascript
// In EventAnimator.playSequence() or similar
if (effectsEnabled && EffectsLayer) {
  EffectsLayer.addEffect({
    type: 'ripple',
    center: [lon, lat],
    magnitude: event.magnitude,
    startTime: Date.now(),
    duration: 3000
  });
}
```

The effects layer maintains its own render loop synced to requestAnimationFrame, reading from an effects queue that the animator populates.

### Why This Architecture Works

1. **Separation of concerns:** Base rendering (MapLibre) vs effects (deck.gl)
2. **Graceful degradation:** Effects optional, base map always works
3. **No code rewrites:** Existing models continue unchanged
4. **Additive complexity:** Only add deck.gl when needed for specific effects
5. **Performance scaling:** CSS (20 events) -> Canvas (100) -> WebGL (1000+)

---

## Infrastructure Split

Separating data collection (lightweight, always-on) from data processing (GPU-heavy, on-demand):

### Architecture Overview

```
+------------------------------------------+
|  INGESTION SERVER (Always On)            |
|  - Raspberry Pi / Small VPS / Home NAS   |
|  - Low power, no GPU needed              |
+------------------------------------------+
          |
          | Scheduled jobs (cron/systemd)
          v
+------------------------------------------+
|  Data Collectors                         |
|  - USGS earthquakes (every 5 min)        |
|  - NASA FIRMS fires (every hour)         |
|  - Weather models (every 6 hours)        |
|  - Economic feeds (daily)                |
+------------------------------------------+
          |
          v
+------------------------------------------+
|  Storage Layer                           |
|  - Append-only parquet files             |
|  - Or TimescaleDB/InfluxDB               |
|  - Serves sync API                       |
+------------------------------------------+
          |
          | Sync (rsync / API / S3)
          v
+------------------------------------------+
|  GPU WORKSTATION (On Demand)             |
|  - Native app with visualization         |
|  - Local LLM inference                   |
|  - Syncs from ingestion server           |
|  - Can also run collectors when online   |
+------------------------------------------+
```

### Why This Split Works

| Concern | Ingestion Server | GPU Workstation |
|---------|-----------------|-----------------|
| Uptime | 24/7/365 | When you're using it |
| Power | 5-15W | 300-500W |
| Cost | $5/mo VPS or Pi | Your existing rig |
| GPU | Not needed | Required |
| Network | Stable connection | Can be offline |
| Storage | Growing archive | Local cache + sync |

### Ingestion Server Options

| Option | Cost | Pros | Cons |
|--------|------|------|------|
| **Raspberry Pi 5** | $80 one-time | Home network, no monthly | Home internet dependency |
| **Small VPS** | $5-10/mo | Reliable, offsite | Storage limits |
| **Home NAS** | $200+ | Lots of storage | Power, home network |
| **Cloud storage + Lambda** | Variable | Scales, no server | Complexity |

### Sync Strategies

**Option 1: File-based (Simple)**
```bash
# On GPU workstation, pull new data
rsync -avz ingestion-server:/data/events/ ~/county-map-data/events/

# Or use rclone for cloud storage
rclone sync s3:my-bucket/events ~/county-map-data/events/
```

**Option 2: API-based (More Control)**
```python
# Ingestion server exposes sync API
GET /api/sync?since=2026-01-07T00:00:00
# Returns all new events since timestamp

# GPU workstation pulls incrementally
last_sync = load_last_sync_timestamp()
new_data = fetch(f"/api/sync?since={last_sync}")
append_to_local(new_data)
```

**Option 3: Append-only Parquet (Hybrid)**
```
Ingestion server writes:
  events/2026/01/07/earthquakes_00.parquet
  events/2026/01/07/earthquakes_01.parquet
  events/2026/01/07/fires_00.parquet

GPU workstation syncs folder, reads all parquet files
DuckDB/Polars can query across partitioned files efficiently
```

### Data Flow Example

```
1. USGS publishes earthquake (magnitude 4.2, California)
         |
         v
2. Ingestion server polls USGS API (every 5 min)
         |
         v
3. New event appended to events/earthquakes/2026-01-08.parquet
         |
         v (next time you open the app)
4. GPU workstation syncs: "47 new events since last sync"
         |
         v
5. Native app shows earthquake on map with animation
         |
         v
6. You can scrub timeline back to see historical earthquakes
```

Never miss an earthquake at 3am - when you open the app next morning, it's all there waiting.

---

## Cloud Sync Architecture

Separating data collection from display enables offline-capable clients with live data freshness.

### The Key Insight

**Display code doesn't care about freshness.** Whether the timestamp is 5 seconds ago or 50 years ago, it's the same render path. The only differences are:

| Aspect | Historical | Live |
|--------|-----------|------|
| Data source | Static files | Polling/streaming |
| Refresh | Manual/none | Auto (30s, 5min, etc.) |
| UI indicator | "Data from 2020" | "Updated 30s ago" |
| Timeline | User scrubs | Auto-advances |

### Architecture

```
[Ingestion Server]  -->  [Cloud Storage]  -->  [Local Instance]
  (always-on)            (S3/R2/Supabase)       (offline-capable)

  Scrapers run           Data folders           Sync on startup
  Convert to schema      Versioned/CDN          Display from local
  Push updates           Public read            Works offline
```

### Cloud Storage Options

| Provider | Free Tier | Pros | Best For |
|----------|-----------|------|----------|
| **Cloudflare R2** | 10 GB | No egress fees, fast CDN | Public data distribution |
| **Supabase Storage** | 1 GB | Already using for DB | Small datasets |
| **AWS S3** | 5 GB | Industry standard | Enterprise |
| **GitHub Releases** | 2 GB/file | Version control, free | Infrequent updates |

### Sync Protocol

**Option 1: Manifest-based (Simple)**

```json
// manifest.json at storage root
{
  "version": "2026-01-08",
  "files": {
    "countries/USA/usgs_earthquakes/events.parquet": {
      "size": 7340032,
      "hash": "sha256:abc123...",
      "updated": "2026-01-08T06:00:00Z"
    }
  }
}
```

Client compares local manifest to remote, downloads only changed files.

**Option 2: Append-only Partitions**

```
events/earthquakes/
  2026-01-07.parquet  (yesterday's events)
  2026-01-08.parquet  (today's events)
```

Client syncs folder, reads all parquets. DuckDB/Polars handles partitioned files efficiently.

### Local Instance Behavior

```
On startup:
  1. Check network connectivity
  2. If online: fetch manifest, compare hashes, download changed files
  3. If offline: use cached data, show "Last synced: X hours ago"
  4. Load data from local files
  5. Display works identically either way
```

**User never waits for sync** - app opens immediately with cached data, sync happens in background.

---

## Business Model: Open Core

The architecture enables monetization while keeping the project open source.

### What's Free (Always)

- All source code (GitHub, MIT/Apache license)
- Schema documentation
- Example converters
- Self-hosting instructions

### What Can Be Monetized

| Offering | Description | Pricing Model |
|----------|-------------|---------------|
| **Pre-built Data Packs** | Ready-to-use parquet files | One-time purchase |
| **Update Subscriptions** | Fresh data delivered to your storage | Monthly/annual |
| **Converter Library** | Production converters for live sources | Per-converter purchase |
| **Priority Support** | Help with deployment/customization | Hourly/retainer |

### Data Pack Examples

| Pack | Contents | Size | Use Case |
|------|----------|------|----------|
| "USA Complete" | All USA sub-national data (census, disasters, risk) | ~500 MB | US-focused apps |
| "Global Disasters" | Earthquakes, hurricanes, volcanoes, tsunamis | ~200 MB | Disaster monitoring |
| "World Demographics" | Population, GDP, health for all countries | ~100 MB | Global visualizations |

### Converter Subscriptions

For live data sources that require ongoing maintenance:

| Source | Update Frequency | Effort | Subscription Value |
|--------|------------------|--------|-------------------|
| USGS Earthquakes | 5 minutes | Low | API is stable |
| NASA FIRMS Fires | Hourly | Low | Simple CSV |
| NOAA Weather | 6 hours | Medium | GRIB parsing |
| Census Updates | Annual | High | Format changes |

Users CAN run these themselves (code is open), but subscription saves the effort.

### Why This Works

1. **Can't sell open data** - USGS, NASA, Census data is public domain
2. **CAN sell labor** - Converting, cleaning, maintaining takes work
3. **CAN sell convenience** - Download ready-to-use vs build from scratch
4. **CAN sell freshness** - Guaranteed updates vs DIY scraping

This is the same model as: Mapbox (OSM data), Observable (open source tools), PostGIS (open source DB).

---

## Optimization Targets (REVISIT)

Items flagged for future optimization when performance becomes an issue:

### Viewport Feature Truncation (geometry_handlers.py)

**Location:** `get_viewport_geometry()` around line 1206

**Current implementation:** When more than 10k features are loaded, we sort by distance from viewport center so edges get trimmed naturally. This uses:
1. O(n) loop to pre-compute distances
2. O(n log n) sort of indices
3. O(n) list comprehension to select first N

**Concern:** For 200k+ features (blocks at deep zoom), this could add noticeable latency.

**Potential optimizations:**
- Use numpy for vectorized distance calculation (if numpy already imported)
- Use heapq.nsmallest() instead of full sort - O(n log k) vs O(n log n)
- Move truncation earlier in pipeline (filter during parquet read)
- Use spatial index (R-tree) to load features from center outward
- Skip sorting entirely if feature count is close to limit (e.g., 10k-12k)

**When to revisit:** If block-level loading takes >500ms and profiling shows sorting as culprit.

---

## Links and References

- **deck.gl**: https://deck.gl/
- **Polars**: https://pola.rs/
- **Tauri**: https://tauri.app/
- **Ollama**: https://ollama.ai/
- **llama.cpp**: https://github.com/ggerganov/llama.cpp
- **wgpu**: https://wgpu.rs/
- **cuDF (RAPIDS)**: https://docs.rapids.ai/api/cudf/stable/
- **cuSpatial**: https://docs.rapids.ai/api/cuspatial/stable/
- **TimescaleDB**: https://www.timescale.com/
- **earth.nullschool.net**: https://earth.nullschool.net/ (inspiration)

---

## Implementation Priority (2026-01-09)

### Phase 1: Complete Disaster Views [CURRENT]
Finish earthquake, volcano, hurricane, wildfire display system before live pipeline.

### Phase 2: Live Data Pipeline [NEXT]

Implementation order:
1. **Find live data sources** - USGS earthquake feed already has real-time API, NASA FIRMS for fires
2. **Create scraper/monitor** - Python daemon that polls APIs, detects new events
3. **Modify converters** - Add incremental append mode (not just full dumps)
4. **Cloud storage** - Move parquet files to R2/S3 for scraper write access
5. **Sync system** - Manifest-based comparison, incremental download on startup

Key insight: **Frontend stays unchanged** - "Read databases, filter by user request, display" is the same whether data is 5 seconds old or 50 years old.

### Phase 3: Dual-Mode UI

After live pipeline works:
- `/live` route - Globe projection, current year only
- `/historical` route - 2D mercator, full timeline
- Globe projection already implemented in map-adapter.js (just disabled)
- Year filtering already works in overlay-controller.js

---

## Code Research: Dual-Mode Implementation (2026-01-09)

Detailed findings from codebase exploration - reference when implementing.

### 1. Route Structure (app.py)

**Framework:** FastAPI (async), NOT Flask
**Main route:** Lines 121-125
```python
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    template_path = BASE_DIR / "templates" / "index.html"
    return template_path.read_text(encoding='utf-8')
```

**To add `/live` route:**
```python
@app.get("/live", response_class=HTMLResponse)
async def serve_live():
    template_path = BASE_DIR / "templates" / "live.html"
    return template_path.read_text(encoding='utf-8')
```

**Key:** No Jinja2 templating used - raw HTML served directly. All dynamic content via JavaScript.

### 2. Globe Projection (map-adapter.js)

**Location:** `static/modules/map-adapter.js`

**Current status:** Globe DISABLED for performance (lines 70-74)
```javascript
// Globe projection disabled - using flat mercator for smoother panning
// To re-enable globe: uncomment the enableGlobe() call below
// this.map.on('style.load', () => {
//   this.enableGlobe();
// });
```

**enableGlobe() method:** Lines 181-207 - FULLY IMPLEMENTED
```javascript
enableGlobe() {
  this.map.setProjection({ type: 'globe' });
  this.map.setSky({
    'sky-color': '#0a0a1a',
    'sky-horizon-blend': 0.5,
    'horizon-color': '#1a1a3e',
    'horizon-fog-blend': 0.8,
    'fog-color': '#0f0f2a',
    'fog-ground-blend': 0.9
  });
  // + setFog() for atmosphere effect
}
```

**To make configurable:** Add to config.js:
```javascript
map: {
  projection: 'mercator',  // or 'globe'
}
```
Then in MapAdapter.init(), check CONFIG.map.projection.

### 3. Year Filtering (overlay-controller.js)

**Location:** `static/modules/overlay-controller.js`

**Pattern:** Cache-first, filter-second
- `loadOverlay()` fetches ALL data (no year filter in API call)
- `dataCache[overlayId]` stores full dataset
- `renderFilteredData()` filters by current year from TimeSlider

**Key code (lines 533-580):**
```javascript
if (endpoint.yearField && year) {
  const yearNum = parseInt(year);
  const filtered = cachedData.features.filter(f => {
    const propYear = f.properties[endpoint.yearField];
    return parseInt(propYear) === yearNum;
  });
  filteredGeojson = { type: 'FeatureCollection', features: filtered };
}
```

**To add live mode:** Add property and method:
```javascript
displayMode: 'historical', // 'historical' | 'live'

setDisplayMode(mode) {
  this.displayMode = mode;
  if (mode === 'live') {
    // Lock to current year
    const currentYear = new Date().getFullYear();
    TimeSlider.setTime(currentYear);
  }
  this.refreshActive();
},

getFilterYear() {
  if (this.displayMode === 'live') {
    return new Date().getFullYear();
  }
  return this.getCurrentYear(); // From TimeSlider
}
```

### 4. TimeSlider Integration

**Location:** `static/modules/time-slider.js`

**For live mode:**
- Hide slider entirely, OR
- Show locked "Live 2026" label
- Disable step buttons and scrubbing

**Key methods to modify:**
- `setTimeRange()` - already has `replace: true` mode
- `show()` / `hide()` - for visibility control
- Add `setLocked(boolean)` to prevent user interaction

### 5. Files to Create/Modify

| File | Action | Notes |
|------|--------|-------|
| `templates/live.html` | CREATE | Copy index.html, add `window.APP_MODE = 'live'` |
| `app.py` | MODIFY | Add `/live` route (2 lines) |
| `config.js` | MODIFY | Add `mode` and `projection` settings |
| `map-adapter.js` | MODIFY | Check config for projection on init |
| `overlay-controller.js` | MODIFY | Add `displayMode` property |
| `time-slider.js` | MODIFY | Add lock/hide for live mode |
| `app.js` | MODIFY | Read `window.APP_MODE`, configure components |

### 6. Minimal Implementation Path

1. **live.html** - Copy index.html, add before app.js import:
   ```html
   <script>window.APP_MODE = 'live';</script>
   ```

2. **app.js init()** - Read mode and configure:
   ```javascript
   const appMode = window.APP_MODE || 'historical';
   if (appMode === 'live') {
     MapAdapter.enableGlobe();
     OverlayController.setDisplayMode('live');
     TimeSlider.hide(); // or lock
   }
   ```

3. **app.py** - Add route (copy existing pattern)

This keeps changes minimal while enabling mode switching.

---

*Last Updated: 2026-01-09*
