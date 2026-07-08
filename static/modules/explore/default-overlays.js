export function getExploreDefaultOverlayIds() {
  // Buoys are deliberately NOT here: the NDBC feed is a live snapshot
  // (Ops keeps it, with its retained ~72h window). Explore is history-first,
  // and buoys have no historical lane to participate in the time slider.
  // Revisit if a canonical buoy history source is ever built.
  return [
    'earthquakes',
    'tsunamis',
    'volcanoes',
    'hurricanes',
    'wildfires',
    'floods',
    'tornadoes',
    'fema_declarations',
    'risk',
    'ocean-sst-grid',
    'demographics',
    'world_bank_wdi',
    'distributed_manufacturing'
  ];
}
