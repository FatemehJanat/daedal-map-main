/**
 * Minimal Explore / Research mode toggle for the chat panel.
 */

import { postMsgpack } from '../utils/fetch.js';
import { getApiUrl } from '../chat/api.js';

export class ResearchModeToggle {
  constructor({ container, getSessionId, onModeChange, onLoadCorpus, onSelectCorpus, onSaveCorpus, onSyncCorpus, onRemoveBrowserCopy }) {
    this.container = container;
    this.getSessionId = getSessionId;
    this.onModeChange = onModeChange;
    this.onLoadCorpus = onLoadCorpus;
    this.onSelectCorpus = onSelectCorpus;
    this.onSaveCorpus = onSaveCorpus;
    this.onSyncCorpus = onSyncCorpus;
    this.onRemoveBrowserCopy = onRemoveBrowserCopy;
    this.mode = 'explore';
    this.buttons = {};
    this.corpusOptions = [];
    this.selectedCorpusId = '';
    this.controls = {};
    this.loadedCorpusId = '';
    this.hasActiveArtifacts = false;
    this.hasStaleArtifacts = false;
    this.optionsLoading = false;
    this.optionsLoadingLabel = 'Loading saved corpora...';
  }

  init() {
    if (!this.container) return;

    const mount = document.getElementById('sidebarModeMount');
    const corpusMount = document.getElementById('sidebarResearchMount');
    const wrap = document.createElement('div');
    wrap.className = 'chat-mode-toggle chat-mode-toggle--header';
    const corpusControls = this.createCorpusControls();

    wrap.appendChild(this.createToggleButton());
    if (mount) {
      mount.replaceChildren(wrap);
    } else {
      this.container.insertBefore(wrap, this.container.firstChild);
    }
    if (corpusMount) {
      corpusMount.replaceChildren(corpusControls);
    } else if (this.container) {
      this.container.insertBefore(corpusControls, this.container.firstChild);
    }
    this.updateActive();
  }

  createToggleButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chat-mode-toggle__btn';
    btn.dataset.mode = this.mode;
    btn.addEventListener('click', async () => {
      this.mode = this.mode === 'research' ? 'explore' : 'research';
      this.updateActive();
      await this.onModeChange?.(this.mode);
    });
    this.buttons.toggle = btn;
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
    const selectedValue = this.controls.select?.value || this.selectedCorpusId || '';
    const canLoad = Boolean(selectedValue);
    const alreadyLoaded = Boolean(
      selectedValue
      && this.loadedCorpusId
      && selectedValue === this.loadedCorpusId
      && this.hasActiveArtifacts
      && !this.hasStaleArtifacts
    );
    this.selectedCorpusId = selectedValue;
    const title = document.getElementById('sidebarModeTitle');
    if (title) {
      title.textContent = this.mode === 'research' ? 'Research Mode' : 'Explore Mode';
    }
    const toggleBtn = this.buttons.toggle;
    if (toggleBtn) {
      toggleBtn.dataset.mode = this.mode;
      toggleBtn.classList.add('active');
      toggleBtn.textContent = 'Swap Modes';
      toggleBtn.title = this.mode === 'research' ? 'Switch to Explore mode' : 'Switch to Research mode';
      toggleBtn.setAttribute('aria-pressed', 'true');
    }
    if (this.controls.wrap) {
      const hideCorpusControls = this.mode !== 'research';
      this.controls.wrap.classList.toggle('hidden', hideCorpusControls);
      this.controls.wrap.hidden = hideCorpusControls;
      this.controls.wrap.setAttribute('aria-hidden', hideCorpusControls ? 'true' : 'false');
    }
    if (this.controls.loadBtn) {
      this.controls.loadBtn.disabled = !canLoad || this.controls.loadBtn.dataset.loading === 'true' || alreadyLoaded;
      this.controls.loadBtn.textContent = this.controls.loadBtn.dataset.loading === 'true'
        ? 'Loading...'
        : (alreadyLoaded ? 'Loaded' : 'Load Data');
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
      const hasOption = Array.from(this.controls.select.options || []).some(option => option.value === this.selectedCorpusId);
      this.controls.select.value = hasOption ? this.selectedCorpusId : '';
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
    const selectedValue = this.controls.select?.value || this.selectedCorpusId || '';
    this.selectedCorpusId = selectedValue;
    this.controls.loadBtn.dataset.loading = isLoading ? 'true' : 'false';
    this.controls.loadBtn.textContent = isLoading ? 'Loading...' : 'Load Data';
    this.controls.loadBtn.disabled = isLoading || !selectedValue;
    if (this.controls.select) {
      this.controls.select.disabled = isLoading || this.corpusOptions.length === 0;
    }
    if (!isLoading) {
      this.updateActive();
    }
  }

  setActiveCorpusState({ loadedCorpusId = '', hasActiveArtifacts = false, hasStaleArtifacts = false } = {}) {
    this.loadedCorpusId = loadedCorpusId || '';
    this.hasActiveArtifacts = Boolean(hasActiveArtifacts);
    this.hasStaleArtifacts = Boolean(hasStaleArtifacts);
    this.updateActive();
  }

  renderCorpusOptions() {
    const select = this.controls.select;
    if (!select) return;

    const options = [
      {
        id: '',
        label: this.optionsLoading
          ? this.optionsLoadingLabel
          : (this.corpusOptions.length ? 'Select a saved corpus...' : 'No saved corpora found')
      },
      ...this.corpusOptions.map(option => ({
        id: option.id,
        label: option.label || option.name || option.id
      }))
    ];

    select.innerHTML = options.map(option => {
      const selected = option.id === this.selectedCorpusId ? ' selected' : '';
      return `<option value="${option.id}"${selected}>${option.label}</option>`;
    }).join('');

    select.disabled = this.optionsLoading || this.corpusOptions.length === 0 || this.controls.loadBtn?.dataset.loading === 'true';
    const validSelectedId = this.corpusOptions.some(option => option.id === this.selectedCorpusId)
      ? this.selectedCorpusId
      : (this.corpusOptions[0]?.id || '');
    this.selectedCorpusId = validSelectedId;
    select.value = validSelectedId;
  }

  setCorpusOptionsLoading(isLoading, label = 'Loading saved corpora...') {
    this.optionsLoading = Boolean(isLoading);
    this.optionsLoadingLabel = label || 'Loading saved corpora...';
    this.renderCorpusOptions();
    this.updateActive();
  }
}
