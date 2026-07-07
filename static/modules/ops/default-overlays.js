const OPS_PUBLIC_DEFAULT_OVERLAY_IDS = [
  'earthquakes',
  'wildfires',
  'hurricanes',
  'tsunamis',
  'volcanoes',
  'ocean-sst-grid',
  'buoys',
  'aurora',
  'nws_alerts'
];

export function getOpsPublicDefaultOverlayIds() {
  return [...OPS_PUBLIC_DEFAULT_OVERLAY_IDS];
}

export function getOpsDefaultOverlayIds() {
  return getOpsPublicDefaultOverlayIds();
}
