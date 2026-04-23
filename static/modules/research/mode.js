/**
 * Minimal Explore / Research mode toggle for the chat panel.
 */

import { postMsgpack } from '../utils/fetch.js';
import { getApiUrl } from '../chat/api.js';

export class ResearchModeToggle {
  constructor({ container, getSessionId, onModeChange, onLoadCorpus, onSelectCorpus }) {
    this.container = container;
    this.getSessionId = getSessionId;
    this.onModeChange = onModeChange;
    this.onLoadCorpus = onLoadCorpus;
    this.onSelectCorpus = onSelectCorpus;
    this.mode = 'explore';
    this.buttons = {};
    this.corpusOptions = [];
    this.selectedCorpusId = '';
    this.controls = {};
  }

  init() {
    if (!this.container) return;

    const wrap = document.createElement('div');
    wrap.className = 'chat-mode-toggle';

    const exploreBtn = this.createButton('explore', 'Explore');
    const researchBtn = this.createButton('research', 'Research');

    wrap.appendChild(exploreBtn);
    wrap.appendChild(researchBtn);
    wrap.appendChild(this.createCorpusControls());
    this.container.insertBefore(wrap, this.container.firstChild);
    this.updateActive();
  }

  createButton(mode, label) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chat-mode-toggle__btn';
    btn.textContent = label;
    btn.addEventListener('click', async () => {
      if (this.mode === mode) return;
      this.mode = mode;
      this.updateActive();
      await this.onModeChange?.(mode);
    });
    this.buttons[mode] = btn;
    return btn;
  }

  createCorpusControls() {
    const controls = document.createElement('div');
    controls.className = 'chat-mode-toggle__corpus hidden';

    const select = document.createElement('select');
    select.className = 'chat-mode-toggle__select';
    select.disabled = true;
    select.addEventListener('change', async () => {
      this.selectedCorpusId = select.value || '';
      await this.onSelectCorpus?.(this.selectedCorpusId);
    });

    const loadBtn = document.createElement('button');
    loadBtn.type = 'button';
    loadBtn.className = 'chat-mode-toggle__load';
    loadBtn.textContent = 'Load Data';
    loadBtn.disabled = true;
    loadBtn.addEventListener('click', async () => {
      if (!this.selectedCorpusId) return;
      await this.onLoadCorpus?.(this.selectedCorpusId);
    });

    const status = document.createElement('div');
    status.className = 'chat-mode-toggle__status';
    status.textContent = 'Select a saved corpus to begin.';

    controls.appendChild(select);
    controls.appendChild(loadBtn);
    controls.appendChild(status);

    this.controls.wrap = controls;
    this.controls.select = select;
    this.controls.loadBtn = loadBtn;
    this.controls.status = status;
    this.renderCorpusOptions();
    return controls;
  }

  updateActive() {
    for (const [mode, btn] of Object.entries(this.buttons)) {
      const active = mode === this.mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
    if (this.controls.wrap) {
      this.controls.wrap.classList.toggle('hidden', this.mode !== 'research');
    }
    if (this.controls.loadBtn) {
      this.controls.loadBtn.disabled = !this.selectedCorpusId || this.controls.loadBtn.dataset.loading === 'true';
    }
  }

  async snapshotCorpus() {
    return await postMsgpack(getApiUrl('/api/research/corpus'), {
      sessionId: this.getSessionId?.()
    });
  }

  setCorpusOptions(options = [], selectedId = '') {
    this.corpusOptions = Array.isArray(options) ? options : [];
    this.selectedCorpusId = selectedId || '';
    this.renderCorpusOptions();
    this.updateActive();
  }

  setSelectedCorpusId(selectedId = '') {
    this.selectedCorpusId = selectedId || '';
    if (this.controls.select) {
      this.controls.select.value = this.selectedCorpusId;
    }
    this.updateActive();
  }

  setCorpusStatus(message = '') {
    if (this.controls.status) {
      this.controls.status.textContent = message || '';
    }
  }

  setCorpusLoading(isLoading) {
    if (!this.controls.loadBtn) return;
    this.controls.loadBtn.dataset.loading = isLoading ? 'true' : 'false';
    this.controls.loadBtn.textContent = isLoading ? 'Loading...' : 'Load Data';
    this.controls.loadBtn.disabled = isLoading || !this.selectedCorpusId;
    if (this.controls.select) {
      this.controls.select.disabled = isLoading || this.corpusOptions.length === 0;
    }
  }

  renderCorpusOptions() {
    const select = this.controls.select;
    if (!select) return;

    const options = [
      { id: '', label: this.corpusOptions.length ? 'Select a saved corpus...' : 'No saved corpora found' },
      ...this.corpusOptions.map(option => ({
        id: option.id,
        label: option.label || option.name || option.id
      }))
    ];

    select.innerHTML = options.map(option => {
      const selected = option.id === this.selectedCorpusId ? ' selected' : '';
      return `<option value="${option.id}"${selected}>${option.label}</option>`;
    }).join('');

    select.disabled = this.corpusOptions.length === 0 || this.controls.loadBtn?.dataset.loading === 'true';
    if (!this.corpusOptions.some(option => option.id === this.selectedCorpusId)) {
      this.selectedCorpusId = '';
      select.value = '';
    } else {
      select.value = this.selectedCorpusId;
    }
  }
}
