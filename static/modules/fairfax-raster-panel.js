/**
 * Fairfax Raster Panel - UI controls for the LST raster layer.
 *
 * Shows scene selector buttons (by date) and color range sliders.
 * Communicates with LstRasterModel to load scenes and update colormap.
 */

import { LstRasterModel } from './model-lst-raster.js';
import { fetchMsgpack } from './utils/fetch.js';

const PANEL_ID = 'fairfax-raster-panel';

let _scenes    = [];
let _activePeriod = null;

// -------------------------------------------------------------------------
// Public API
// -------------------------------------------------------------------------

export const FairfaxRasterPanel = {

  async init() {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;

    let manifest;
    try {
      manifest = await fetchMsgpack('/api/fairfax/raster/manifest');
    } catch (err) {
      console.error('FairfaxRasterPanel: failed to load manifest', err);
      return;
    }

    _scenes = manifest?.scenes || [];
    if (_scenes.length === 0) return;

    _buildPanel(panel);
    panel.style.display = 'block';

    // Auto-load the first scene
    await _loadScene(_scenes[0].period);
  },

  hide() {
    const panel = document.getElementById(PANEL_ID);
    if (panel) panel.style.display = 'none';
    LstRasterModel.hide();
  },

  show() {
    const panel = document.getElementById(PANEL_ID);
    if (panel) panel.style.display = 'block';
    LstRasterModel.show();
  },

  cleanup() {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      panel.style.display = 'none';
      panel.innerHTML = '';
    }
    LstRasterModel.cleanup();
    _scenes = [];
    _activePeriod = null;
  },
};

// -------------------------------------------------------------------------
// Build panel DOM
// -------------------------------------------------------------------------

function _buildPanel(panel) {
  panel.innerHTML = '';

  // Header
  const header = document.createElement('div');
  header.className = 'lst-panel-header';
  header.innerHTML = '<span>Heat Layer</span>';

  const btnGroup = document.createElement('div');
  btnGroup.className = 'lst-panel-btn-group';

  // Toggle raster layer visibility (does not close the panel)
  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'lst-panel-toggle active';
  toggleBtn.textContent = 'On';
  toggleBtn.title = 'Toggle heat map layer';
  toggleBtn.addEventListener('click', () => {
    if (LstRasterModel.isVisible) {
      LstRasterModel.hide();
      toggleBtn.textContent = 'Off';
      toggleBtn.classList.remove('active');
    } else {
      LstRasterModel.show();
      toggleBtn.textContent = 'On';
      toggleBtn.classList.add('active');
    }
  });

  const closeBtn = document.createElement('button');
  closeBtn.className = 'lst-panel-close';
  closeBtn.textContent = 'x';
  closeBtn.title = 'Close heat layer panel';
  closeBtn.addEventListener('click', () => FairfaxRasterPanel.hide());

  btnGroup.appendChild(toggleBtn);
  btnGroup.appendChild(closeBtn);
  header.appendChild(btnGroup);
  panel.appendChild(header);

  // Scene buttons
  const sceneRow = document.createElement('div');
  sceneRow.className = 'lst-scene-row';

  // Group scenes by year
  const byYear = {};
  for (const scene of _scenes) {
    if (!byYear[scene.year]) byYear[scene.year] = [];
    byYear[scene.year].push(scene);
  }

  for (const [year, scenes] of Object.entries(byYear)) {
    const yearLabel = document.createElement('span');
    yearLabel.className = 'lst-year-label';
    yearLabel.textContent = year;
    sceneRow.appendChild(yearLabel);

    for (const scene of scenes) {
      const btn = document.createElement('button');
      btn.className = 'lst-scene-btn';
      btn.dataset.period = scene.period;
      btn.textContent = _formatPeriod(scene.period);
      btn.title = `Load scene: ${scene.period}`;
      btn.addEventListener('click', () => _loadScene(scene.period));
      sceneRow.appendChild(btn);
    }
  }
  panel.appendChild(sceneRow);

  // Color range controls
  const rangeSection = document.createElement('div');
  rangeSection.className = 'lst-range-section';

  rangeSection.appendChild(_makeSliderRow(
    'Min temp (F)',
    'lst-min-slider',
    55, 130, LstRasterModel.minF,
    (val, setValue) => {
      const clamped = Math.min(val, LstRasterModel.maxF - 5);
      setValue(clamped);
      LstRasterModel.setColorRange(clamped, LstRasterModel.maxF);
    }
  ));

  rangeSection.appendChild(_makeSliderRow(
    'Max temp (F)',
    'lst-max-slider',
    90, 155, LstRasterModel.maxF,
    (val, setValue) => {
      const clamped = Math.max(val, LstRasterModel.minF + 5);
      setValue(clamped);
      LstRasterModel.setColorRange(LstRasterModel.minF, clamped);
    }
  ));

  rangeSection.appendChild(_makeSliderRow(
    'Opacity',
    'lst-opacity-slider',
    0, 100, Math.round(LstRasterModel.opacity * 100),
    (val) => LstRasterModel.setOpacity(val / 100)
  ));

  panel.appendChild(rangeSection);

  // Color legend
  const legend = document.createElement('div');
  legend.className = 'lst-legend';
  legend.id = 'lst-legend';
  panel.appendChild(legend);
  _updateLegend();
}

function _makeSliderRow(label, id, min, max, value, onChange) {
  const row = document.createElement('div');
  row.className = 'lst-slider-row';

  const lbl = document.createElement('label');
  lbl.htmlFor = id;
  lbl.textContent = label;

  const valDisplay = document.createElement('span');
  valDisplay.className = 'lst-slider-val';
  valDisplay.textContent = value;

  const slider = document.createElement('input');
  slider.type  = 'range';
  slider.id    = id;
  slider.min   = min;
  slider.max   = max;
  slider.value = value;
  slider.addEventListener('input', () => {
    const setValue = (v) => {
      slider.value = String(v);
      valDisplay.textContent = String(v);
    };
    setValue(parseInt(slider.value));
    onChange(parseInt(slider.value), setValue);
    _updateLegend();
  });

  row.appendChild(lbl);
  row.appendChild(slider);
  row.appendChild(valDisplay);
  return row;
}

function _updateLegend() {
  const legend = document.getElementById('lst-legend');
  if (!legend) return;

  const minF = LstRasterModel.minF;
  const maxF = LstRasterModel.maxF;

  // Build gradient from color stops
  const stops = LstRasterModel.colorStops;
  const gradientStops = stops
    .filter(([v]) => v >= minF - 5 && v <= maxF + 5)
    .map(([v, color]) => {
      const pct = Math.round(((v - minF) / (maxF - minF)) * 100);
      return `${color} ${pct}%`;
    })
    .join(', ');

  legend.innerHTML = `
    <div class="lst-legend-bar" style="background: linear-gradient(to right, ${gradientStops || '#313695, #67001f'})"></div>
    <div class="lst-legend-labels">
      <span>${minF}F</span>
      <span>${Math.round((minF + maxF) / 2)}F</span>
      <span>${maxF}F</span>
    </div>
  `;
}

// -------------------------------------------------------------------------
// Scene loading
// -------------------------------------------------------------------------

async function _loadScene(period) {
  _activePeriod = period;
  _updateActiveButton(period);

  const ok = await LstRasterModel.load(period);
  if (!ok) {
    console.error(`FairfaxRasterPanel: failed to load scene ${period}`);
  }
}

function _updateActiveButton(period) {
  const panel = document.getElementById(PANEL_ID);
  if (!panel) return;

  panel.querySelectorAll('.lst-scene-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.period === period);
  });
}

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

function _formatPeriod(period) {
  // "2024-06-14_06-18" -> "Jun 14-18"
  const parts = period.split('_');
  if (parts.length !== 2) return period;
  const [startPart] = parts;
  const segments = startPart.split('-');
  if (segments.length < 3) return period;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const month = months[parseInt(segments[1]) - 1] || segments[1];
  const startDay = parseInt(segments[2]);
  const endDay = parseInt(parts[1].split('-')[1]);
  return `${month} ${startDay}-${endDay}`;
}
