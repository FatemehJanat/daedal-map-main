/**
 * Configuration settings for the Map Viewer application.
 * Central place for all tunable parameters.
 */

export const CONFIG = {
  // Map settings
  defaultCenter: [-78.64, 35.78],  // Centered on Raleigh, NC
  defaultZoom: 2.5,

  // Viewport area thresholds are now in ViewportLoader.areaThresholds
  // Area-based thresholds adapt better to different region sizes than fixed zoom levels

  // Viewport loading settings (tunable)
  viewport: {
    debounceMs: 300,        // Short debounce to batch rapid pan/zoom (300ms)
    cacheExpiryMs: 120000,  // Keep features cached for 2 minutes (was 60s)
    maxFeatures: 100000,    // Increased cache for smoother panning (was 50k)
    spinnerDelayMs: 500     // Show spinner after 500ms if still loading
  },

  // Colors
  colors: {
    // Focal area (center of viewport) - green tones
    focalFill: '#228855',       // Green
    focalFillOpacity: 0.45,
    focalStroke: '#116633',     // Dark green stroke
    // Surrounding areas - blue tones
    fill: '#2266aa',            // Blue
    fillOpacity: 0.35,
    stroke: '#1a5599',          // Dark blue stroke
    strokeWidth: 1,
    // Hover (applies to both)
    fillHover: '#4488cc',       // Lighter blue on hover
    fillHoverOpacity: 0.6,
    strokeHover: '#66aadd',
    strokeHoverWidth: 2
  },

  // Debug mode colors (by coverage ratio: actual_depth / expected_depth)
  // Press 'D' to toggle debug mode
  debugColors: {
    none: '#666666',   // Gray - no coverage data
    low: '#ff4444',    // Red - 0-49% coverage
    medium: '#ff9900', // Orange - 50-74% coverage
    high: '#ffcc00',   // Yellow - 75-99% coverage
    full: '#44aa44'    // Green - 100% coverage
  },

  // Layer IDs (for MapLibre)
  layers: {
    fill: 'regions-fill',
    stroke: 'regions-stroke',
    source: 'regions',
    // Parent outline layer (shows what region you're drilling into)
    parentSource: 'parent-region',
    parentStroke: 'parent-stroke',
    parentFill: 'parent-fill',
    // City overlay layer
    citySource: 'cities',
    cityCircle: 'cities-circle',
    cityLabel: 'cities-label',
    cityMinZoom: 8  // Cities appear at this zoom level
  },

  // API endpoints
  api: {
    countries: '/geometry/countries',
    children: '/geometry/{loc_id}/children',
    viewport: '/geometry/viewport',
    chat: '/chat'
  }
};
