/**
 * Lane switching and chat-mode UI helpers.
 */

function normalizeChatMode(mode, chatModes = ['explore', 'research', 'ops']) {
  return chatModes.includes(mode) ? mode : 'explore';
}

function paneHasMessages(pane) {
  if (!pane) return false;
  if (pane.querySelector('.chat-message')) return true;
  return String(pane.textContent || '').trim().length > 0;
}

export async function switchChatMode(ctx, mode, deps = {}) {
  const App = deps.App || null;
  const OverlaySelector = deps.OverlaySelector || null;
  const chatModes = deps.CHAT_MODES || ['explore', 'research', 'ops'];
  mode = normalizeChatMode(mode, chatModes);
  if (mode === ctx.mode) return;

  ctx.syncModeMessagesHtml(ctx.mode);
  ctx.modeHistories[ctx.mode] = ctx.history;

  ctx.mode = mode;
  ctx.history = ctx.modeHistories[mode] || [];
  applyModeUiState(ctx, deps);
  App?.activateLaneMapView?.(mode);

  if (mode === 'research') {
    await ctx.refreshResearchCorpusOptions();
  } else if (mode === 'ops') {
    try {
      await ctx.refreshOpsReport({ loadWatch: true });
      OverlaySelector?.refreshVisibility?.();
    } catch (error) {
      console.warn('Ops report refresh failed:', error);
    }
  }

  const pane = ctx.messagePanes?.[mode] || null;
  const hasStoredHtml = String(ctx.modeMessagesHtml?.[mode] || '').trim().length > 0;
  if (ctx.history.length === 0 && !hasStoredHtml && !paneHasMessages(pane)) {
    await seedEmptyConversation(ctx, mode, deps);
  }

  applyModeUiState(ctx, deps);
  ctx.saveState();
}

export async function seedEmptyConversation(ctx, mode = ctx.mode, deps = {}) {
  const welcomeMessage = deps.WELCOME_MESSAGE || '';
  const pane = ctx.messagePanes?.[mode];
  if (paneHasMessages(pane)) return;

  if (mode === 'research') {
    try {
      await ctx.refreshResearchCorpusOptions();
      const manifest = await ctx.refreshResearchManifest();
      if ((manifest?.artifact_count || 0) > 0 && !manifest?.stale_artifacts) {
        ctx.addMessage(`Research mode ready. Active corpus: ${manifest.artifact_count} loaded artifact${manifest.artifact_count === 1 ? '' : 's'}.`, 'assistant', { mode: 'research' });
        return;
      }
      if (manifest?.saved_corpus) {
        const saved = manifest.saved_corpus;
        const message = manifest?.stale_artifacts
          ? `Research workspace found an out-of-date local session for "${saved.name}". Click Load Data to refresh it.`
          : `Research workspace ready. "${saved.name}" is selected. Click Load Data to activate it for this session.`;
        ctx.addMessage(message, 'assistant', { mode: 'research' });
        return;
      }
      ctx.addMessage(ctx.getResearchEmptyStateMessage(), 'assistant', { mode: 'research' });
    } catch (error) {
      console.warn('Research corpus manifest check failed:', error);
      ctx.addMessage('Research mode is available, but I could not read the active corpus yet.', 'assistant', { mode: 'research' });
    }
    return;
  }

  if (mode === 'ops') {
    try {
      const payload = await ctx.refreshOpsReport({ loadWatch: true });
      const effectiveFeeds = Array.isArray(payload?.effective_feeds) ? payload.effective_feeds : [];
      if (effectiveFeeds.length > 0) {
        ctx.addMessage(
          `Ops mode ready. Active watch has ${effectiveFeeds.length} feed${effectiveFeeds.length === 1 ? '' : 's'}: ${effectiveFeeds.join(', ')}.`,
          'assistant',
          { mode: 'ops' }
        );
        return;
      }
      ctx.addMessage(payload?.warning || ctx.getOpsEmptyStateMessage(), 'assistant', { mode: 'ops' });
    } catch (error) {
      console.warn('Ops report check failed:', error);
      ctx.addMessage('Ops mode is available, but I could not read the active watch yet.', 'assistant', { mode: 'ops' });
    }
    return;
  }

  ctx.addMessage(welcomeMessage, 'assistant', { html: true, mode: 'explore' });
}

export function applyModeUiState(ctx, deps = {}) {
  const researchModeToggle = deps.researchModeToggle || null;
  const OverlaySelector = deps.OverlaySelector || null;
  if (researchModeToggle) {
    researchModeToggle.mode = ctx.mode;
    researchModeToggle.setSelectedCorpusId(ctx.selectedResearchCorpusId);
    researchModeToggle.updateActive();
  }
  ctx.setActiveMessagePane(ctx.mode);
  ctx.updateResearchCorpusStatus();
  OverlaySelector?.refreshVisibility?.();
  if (ctx.mode === 'ops') {
    OverlaySelector?.expand?.();
  }
  // Ops mode is "what's happening now" - there is no historical time window, so
  // enabling an overlay should not pop the time slider / animation bar. Suppress
  // (and hide) it in Ops; allow it again in Explore/Research.
  const overlayController = window.OverlayController || null;
  if (overlayController?.setTimelineAutoShowSuppressed) {
    const inOps = ctx.mode === 'ops';
    overlayController.setTimelineAutoShowSuppressed(inOps, { hide: inOps });
  }
  updateSidebarModeLayout(ctx);
  updateComposerState(ctx);
}

export function updateComposerState(ctx) {
  const { input, sendBtn } = ctx.elements;
  const disabled = !!ctx.modeRequestInFlight?.[ctx.mode];
  if (sendBtn) sendBtn.disabled = disabled;
  if (input) input.disabled = disabled;
}

export function syncSidebarToggleVisibility(ctx) {
  const { sidebar, toggle } = ctx.elements;
  if (!sidebar || !toggle) return;
  toggle.style.display = sidebar.classList.contains('collapsed') ? 'flex' : 'none';
}

export function updateSidebarModeLayout(ctx) {
  const { orderPanel, resizeOrder, form } = ctx.elements;
  const hideOrderTaker = ctx.mode === 'research' || ctx.mode === 'ops';
  const container = document.getElementById('chatContainer');
  document.body.classList.toggle('chat-mode-research', ctx.mode === 'research');
  document.body.classList.toggle('chat-mode-ops', ctx.mode === 'ops');
  document.body.classList.toggle('chat-mode-explore', ctx.mode === 'explore');
  if (container) {
    container.classList.toggle('chat-container--research', ctx.mode === 'research');
    container.classList.toggle('chat-container--ops', ctx.mode === 'ops');
    container.classList.toggle('chat-container--explore', ctx.mode === 'explore');
  }
  if (orderPanel) {
    orderPanel.hidden = hideOrderTaker;
    orderPanel.setAttribute('aria-hidden', hideOrderTaker ? 'true' : 'false');
    orderPanel.style.display = hideOrderTaker ? 'none' : '';
  }
  if (resizeOrder) {
    resizeOrder.hidden = hideOrderTaker;
    resizeOrder.setAttribute('aria-hidden', hideOrderTaker ? 'true' : 'false');
    resizeOrder.style.display = hideOrderTaker ? 'none' : '';
  }
  if (form) {
    form.setAttribute('data-chat-mode', ctx.mode);
  }
  enforceResearchUiBoundaries(ctx);
}

export function enforceResearchUiBoundaries(ctx) {
  const hideOrderTaker = ctx.mode === 'research' || ctx.mode === 'ops';
  const { orderPanel, resizeOrder } = ctx.elements;
  const container = document.getElementById('chatContainer');
  document.body.classList.toggle('chat-mode-research', ctx.mode === 'research');
  document.body.classList.toggle('chat-mode-ops', ctx.mode === 'ops');
  document.body.classList.toggle('chat-mode-explore', ctx.mode === 'explore');
  if (container) {
    container.classList.toggle('chat-container--research', ctx.mode === 'research');
    container.classList.toggle('chat-container--ops', ctx.mode === 'ops');
    container.classList.toggle('chat-container--explore', ctx.mode === 'explore');
  }
  for (const element of [orderPanel, resizeOrder]) {
    if (!element) continue;
    element.hidden = hideOrderTaker;
    element.setAttribute('aria-hidden', hideOrderTaker ? 'true' : 'false');
    element.style.display = hideOrderTaker ? 'none' : '';
    element.style.visibility = hideOrderTaker ? 'hidden' : '';
    element.style.pointerEvents = hideOrderTaker ? 'none' : '';
  }
}
