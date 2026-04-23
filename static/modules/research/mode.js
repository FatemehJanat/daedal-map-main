/**
 * Minimal Explore / Research mode toggle for the chat panel.
 */

import { postMsgpack } from '../utils/fetch.js';
import { getApiUrl } from '../chat/api.js';

export class ResearchModeToggle {
  constructor({ container, getSessionId, onModeChange }) {
    this.container = container;
    this.getSessionId = getSessionId;
    this.onModeChange = onModeChange;
    this.mode = 'explore';
    this.buttons = {};
  }

  init() {
    if (!this.container) return;

    const wrap = document.createElement('div');
    wrap.className = 'chat-mode-toggle';

    const exploreBtn = this.createButton('explore', 'Explore');
    const researchBtn = this.createButton('research', 'Research');

    wrap.appendChild(exploreBtn);
    wrap.appendChild(researchBtn);
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

  updateActive() {
    for (const [mode, btn] of Object.entries(this.buttons)) {
      const active = mode === this.mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
  }

  async snapshotCorpus() {
    return await postMsgpack(getApiUrl('/api/research/corpus'), {
      sessionId: this.getSessionId?.()
    });
  }
}
