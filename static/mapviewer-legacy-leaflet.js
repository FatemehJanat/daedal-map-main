// =============================================================================
// LEGACY LEAFLET MAP VIEWER
// =============================================================================
// This file preserves the Leaflet 2D map functionality that was originally
// part of mapviewer.js. It has been archived as Cesium 3D globe is now the
// primary map display.
//
// To restore Leaflet functionality:
// 1. Include Leaflet CSS/JS in index.html
// 2. Add the leafletMap div and toggle buttons back to HTML
// 3. Merge relevant functions back into mapviewer.js
// =============================================================================

// === LEAFLET MAP INITIALIZATION ===
const defaultView = { lat: 31.5, lng: -99.3, zoom: 3, maxZoom: 20 };
let currentView = { clat: 31.5, clng: -99.3, czoom: 6, cmaxZoom: 20 };
const map = L.map('leafletMap', { maxZoom: defaultView.maxZoom }).setView([defaultView.lat, defaultView.lng], defaultView.zoom);
let geoLayer = null;
let mapType = "leaflet"; // or "cesium"

// Tile layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '(c) OpenStreetMap contributors'
}).addTo(map);

// === MAP TYPE TOGGLE ===
// Add event listeners for map type buttons (requires HTML buttons with these IDs)
document.addEventListener("DOMContentLoaded", () => {
  const leafletBtn = document.getElementById("leafletBtn");
  const cesiumBtn = document.getElementById("cesiumBtn");

  if (leafletBtn) {
    leafletBtn.addEventListener("click", () => {
      mapType = "leaflet";
      leafletBtn.classList.add("active");
      if (cesiumBtn) cesiumBtn.classList.remove("active");
      showMap();
    });
  }

  if (cesiumBtn) {
    cesiumBtn.addEventListener("click", () => {
      mapType = "cesium";
      cesiumBtn.classList.add("active");
      if (leafletBtn) leafletBtn.classList.remove("active");
      showMap();
    });
  }

  // Fix map size after load
  setTimeout(() => map.invalidateSize(), 100);
});

// === LEAFLET-SPECIFIC FUNCTIONS ===

function scaleToBoundsLeaflet() {
  const group = new L.featureGroup();
  if (geoLayer && map.hasLayer(geoLayer)) group.addLayer(geoLayer);
  const bounds = group.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: defaultView.maxZoom });
  } else {
    map.setView([defaultView.lat, defaultView.lng], defaultView.zoom);
  }
}

function clearMapLeaflet() {
  if (geoLayer) map.removeLayer(geoLayer);
}

function showMapLeaflet() {
  document.getElementById("leafletMap").classList.add("active");
  map.invalidateSize();
  if (geoLayer) map.addLayer(geoLayer);
}

function checkViewLeaflet() {
  const center = map.getCenter();
  currentView = {
    clat: center.lat,
    clng: center.lng,
    czoom: map.getZoom(),
  };
}

// === LEAFLET GEOJSON LAYER SETUP ===
function prepPolygonsLeaflet(data) {
  if (geoLayer && map.hasLayer(geoLayer)) map.removeLayer(geoLayer);

  geoLayer = L.geoJSON(data.geojson, {
    style: {
      weight: 2,
      fillColor: "#ff7800",
      color: "#ff6600",
      fillOpacity: 0.3,
      opacity: 1,
    },
    onEachFeature: (feature, layer) => {
      const popupContent = buildPopupContent(feature.properties, data);
      layer.bindPopup(popupContent);
    }
  });

  return geoLayer;
}

// === COMBINED SHOW MAP FUNCTION (handles both Leaflet and Cesium) ===
function showMapCombined() {
  document.getElementById("leafletMap").classList.remove("active");
  document.getElementById("cesiumContainer").classList.remove("active");

  if (mapType === "leaflet") {
    clearMapLeaflet();
    document.getElementById("leafletMap").classList.add("active");
    map.invalidateSize();
    if (geoLayer) map.addLayer(geoLayer);
    scaleToBoundsLeaflet();
  }
  else if (mapType === "cesium") {
    // Cesium logic would go here
    document.getElementById("cesiumContainer").classList.add("active");
    // ... Cesium-specific code
  }
}

// === COMBINED CHECK VIEW FUNCTION ===
function checkViewCombined() {
  if (mapType === "leaflet") {
    checkViewLeaflet();
  }
  else if (mapType === "cesium") {
    // Cesium view check logic would go here
  }
}

// === POPUP CONTENT BUILDER (shared between Leaflet and Cesium) ===
function buildPopupContent(props, sourceData) {
  const skipFields = ['geometry', 'country', 'country_name', 'country_code', 'name', 'Name', 'Location', 'stusab', 'state',
                      'name_long', 'Admin Country Name', 'Sov Country Name', 'postal',
                      'Admin Country Abbr', 'Sov Country Abbr', 'name_sort', 'formal_en',
                      'iso_code', 'continent', 'Admin Type', 'type', 'formal_en',
                      'population_year', 'gdp_year', 'economy type', 'income_group',
                      'UN Region', 'subregion', 'region_wb', 'Longitude', 'Latitude', 'data_year'];

  const getRelevantFields = (props) => {
    const relevant = [];
    for (const [key, value] of Object.entries(props)) {
      if (skipFields.includes(key) || value == null || value === '') continue;
      if (key.toLowerCase() === 'year') continue;
      const keyLower = key.toLowerCase();
      const isNumeric = !isNaN(parseFloat(value));
      const isRelevant = keyLower.includes('co2') || keyLower.includes('gdp') ||
                        keyLower.includes('population') || keyLower.includes('emission') ||
                        keyLower.includes('capita') || keyLower.includes('total') ||
                        keyLower.includes('methane') || keyLower.includes('temperature') ||
                        keyLower.includes('energy') || keyLower.includes('oil') ||
                        keyLower.includes('gas') || keyLower.includes('coal');
      if (isNumeric && isRelevant) {
        relevant.push(key);
      }
    }
    return relevant;
  };

  const formatValue = (key, value) => {
    const keyLower = key.toLowerCase();
    const numValue = parseFloat(value);
    if (!isNaN(numValue)) {
      if (keyLower.includes('gdp') && !keyLower.includes('per')) {
        if (numValue > 1e9) return `$${(numValue / 1e9).toFixed(2)} billion`;
        if (numValue > 1e6) return `$${(numValue / 1e6).toFixed(2)} million`;
        return `$${numValue.toLocaleString()}`;
      }
      if (keyLower.includes('co2')) {
        if (keyLower.includes('per_capita') || keyLower.includes('percapita')) {
          return `${numValue.toFixed(2)} tonnes/person`;
        }
        return `${numValue.toFixed(2)} million tonnes`;
      }
      if (keyLower.includes('population') || keyLower.includes('pop')) {
        return numValue.toLocaleString();
      }
      if (keyLower.includes('aland') || keyLower.includes('awater')) {
        return `${(numValue / 2.59e+6).toFixed(2)} sq mi`;
      }
      if (keyLower.includes('percent') || keyLower.includes('rate')) {
        return `${numValue.toFixed(1)}%`;
      }
      if (numValue > 1000) return numValue.toLocaleString();
      return numValue.toFixed(2);
    }
    return value;
  };

  let popupLines = [];
  const nameField = props.country_name || props.country || props.name || props.Name || props.Location || 'Unknown';
  const stateAbbr = props.stusab || props.state || '';
  popupLines.push(`<strong>${nameField}${stateAbbr ? ', ' + stateAbbr : ''}</strong>`);

  const relevantFields = getRelevantFields(props);
  const fieldsToShow = relevantFields.length > 0 ? relevantFields :
                      Object.keys(props).filter(k => !skipFields.includes(k) && k.toLowerCase() !== 'year' && props[k] != null && props[k] !== '');

  for (const key of fieldsToShow) {
    const value = props[key];
    if (value == null || value === '') continue;
    const fieldName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    const formattedValue = formatValue(key, value);
    const yearValue = props.year || props.data_year || '';
    const yearSuffix = yearValue ? ` (${yearValue})` : '';
    popupLines.push(`${fieldName}: ${formattedValue}${yearSuffix}`);
  }

  popupLines.push('');

  // Handle multiple sources
  if (sourceData && sourceData.sources && sourceData.sources.length > 0) {
    popupLines.push('<strong>Sources:</strong>');
    for (const source of sourceData.sources) {
      const fieldsText = source.fields && source.fields.length > 0 ? ` (${source.fields.join(', ')})` : '';
      if (source.url && source.url !== '' && source.url !== 'Unknown') {
        popupLines.push(`- <a href="${source.url}" target="_blank">${source.name}</a>${fieldsText}`);
      } else {
        popupLines.push(`- ${source.name}${fieldsText}`);
      }
    }
  } else if (sourceData && sourceData.source_url && sourceData.source_url !== '' && sourceData.source_url !== 'Unknown') {
    const sourceName = sourceData.source_name || 'Data Source';
    popupLines.push(`<strong>Source:</strong> <a href="${sourceData.source_url}" target="_blank">${sourceName}</a>`);
  } else if (sourceData) {
    const datasetName = sourceData.dataset_name || sourceData.source_name || 'Unknown Dataset';
    popupLines.push(`<strong>Source:</strong> ${datasetName}`);
  }

  return popupLines.join('<br>');
}

// =============================================================================
// HTML ELEMENTS REQUIRED FOR LEAFLET (add these back to index.html if restoring)
// =============================================================================
/*
<!-- In the map-wrapper div: -->
<div id="leafletMap" class="map-container active"></div>

<!-- CSS classes needed: -->
<style>
  #leafletMap {
    display: none;
    width: 100%;
    height: 100%;
  }
  #leafletMap.active {
    display: block;
  }
</style>

<!-- Toggle buttons in toolbar: -->
<div class="btn-group" id="mapTypeButtons">
  <button type="button" id="leafletBtn" class="btn btn-outline-secondary active">2D</button>
  <button type="button" id="cesiumBtn" class="btn btn-outline-secondary">3D</button>
</div>

<!-- Leaflet CSS/JS includes in head: -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
*/
