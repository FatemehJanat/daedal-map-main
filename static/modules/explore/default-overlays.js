export function getExploreDefaultOverlayIds() {
  // Buoys are deliberately NOT here: the NDBC feed is a live snapshot
  // (Ops keeps it, with its retained ~72h window). Explore is history-first,
  // and buoys have no historical lane to participate in the time slider.
  // Revisit if a canonical buoy history source is ever built.
  return [
    // Published historical event families.
    'earthquakes',
    'tsunamis',
    'volcanoes',
    'hurricanes',
    'wildfires',
    'floods',
    'tornadoes',
    'risk',

    // Published country/region indicator families.  These IDs are overlay
    // paths from the catalog, rather than individual source or pack IDs.
    'economy',
    'demographics',
    'distributed_manufacturing',
    'cejst',
    'usa_industrial_activity',

    // Runtime-owned historical raster layers.  They remain distinct from the
    // catalog tree because their frame services are shared with Ops.
    'ocean-sst-grid',
    'land-temperature-grid',

    // WIP-only choices such as FEMA declarations, Fairfax Climate, ZIP codes,
    // and historical NWS are injected only when the local WIP catalog is on.
  ];
}
