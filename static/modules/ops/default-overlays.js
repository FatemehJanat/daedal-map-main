const OPS_PUBLIC_DEFAULT_OVERLAY_IDS = [
  'earthquakes',
  'wildfires',
  'hurricanes',
  'tsunamis',
  'volcanoes',
  'ocean_sst',
  'aurora',
  'currency'
];

export function getOpsPublicDefaultOverlayIds() {
  return [...OPS_PUBLIC_DEFAULT_OVERLAY_IDS];
}

export function getOpsDefaultOverlayIds() {
  return getOpsPublicDefaultOverlayIds();
}
