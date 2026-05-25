/**
 * Chat response routing helpers.
 */

export function routeMapResponse(ctx, response, options = {}, deps = {}) {
  const App = deps.App || null;
  if (!response || !App) return false;
  const origin = options.origin || 'unknown';

  if (origin === 'research' && Array.isArray(response.layers) && response.layers.length) {
    const validLayers = response.layers.filter(layer => layer?.geojson?.features?.length);
    if (validLayers.length) {
      const keepLayers = validLayers.filter(layer => String(layer.context_visibility || '').trim().toLowerCase() === 'keep');
      const replaceLayers = validLayers.filter(layer => String(layer.context_visibility || '').trim().toLowerCase() !== 'keep');
      if (replaceLayers.length) {
        ctx.setResearchDisplayLayersForMode('research', replaceLayers);
        for (const layer of keepLayers) {
          ctx.appendResearchDisplayForMode('research', layer);
        }
      } else {
        ctx.setResearchDisplayLayersForMode('research', validLayers);
      }
      App.displayMapPayload?.(response, { origin, order: options.order });
      return true;
    }
  }

  if (response.action === 'remove' && response.data_type) {
    App.displayMapPayload?.(response, { origin, order: options.order });
    return true;
  }

  if (response.geojson?.features?.length) {
    if (origin === 'research') {
      if (String(response.context_visibility || '').trim().toLowerCase() === 'keep') {
        ctx.appendResearchDisplayForMode('research', response);
      } else {
        ctx.setResearchDisplayForMode('research', response);
      }
    }
    App.displayMapPayload?.(response, { origin, order: options.order });
    return true;
  }

  return false;
}

export function applyFilterUpdate(ctx, response, deps = {}) {
  const OverlayController = deps.OverlayController || null;
  const { overlay, filters } = response;

  if (!OverlayController) {
    console.warn('OverlayController not available for filter update');
    return;
  }

  if (filters.clear) {
    OverlayController.clearFilters?.(overlay);
  } else {
    OverlayController.updateFilters?.(overlay, filters);
  }

  OverlayController.reloadOverlay?.(overlay);
}

export function handleResponse(ctx, response, deps = {}) {
  const {
    App = null,
    OverlayController = null,
    OverlaySelector = null,
    SelectionManager = null,
    TutorialMode = null,
    SavedOrders = null,
    orderPanel = null,
    ingestEventsToOverlay = null
  } = deps;

  const targetMode = response?._requestMode || ctx.mode;
  if (targetMode === 'research' || ctx.mode === 'research') {
    ctx.enforceResearchUiBoundaries();
  }
  const add = (text, type = 'assistant', options = {}) => ctx.addMessage(text, type, { ...options, mode: targetMode });
  switch (response.type) {
    case 'order':
      ctx.pendingMetricOrder = null;
      add('Added to your order. Click "Display on Map" when ready.', 'assistant');
      orderPanel.setOrder(response.order, response.summary, response.full_order || response.order);
      break;

    case 'already_loaded':
      add(response.message || 'This data is already loaded on your map.', 'assistant');
      if (orderPanel.switchTab) orderPanel.switchTab('loaded');
      break;

    case 'metric_warning': {
      ctx.pendingResearchDisplayWarning = null;
      ctx.pendingMetricOrder = {
        order: response.pending_order,
        full_order: response.full_order,
        summary: response.summary
      };
      const msgEl = add(response.message, 'assistant');
      const btnContainer = document.createElement('div');
      btnContainer.className = 'metric-warning-buttons';

      const yesBtn = document.createElement('button');
      yesBtn.textContent = 'Yes, show all';
      yesBtn.className = 'chat-action-btn confirm';
      yesBtn.addEventListener('click', () => {
        btnContainer.remove();
        ctx.resendWithForce();
      });

      const noBtn = document.createElement('button');
      noBtn.textContent = 'No, let me narrow it';
      noBtn.className = 'chat-action-btn cancel';
      noBtn.addEventListener('click', () => {
        btnContainer.remove();
        add('Sure - what specific metrics would you like?', 'assistant');
      });

      btnContainer.appendChild(yesBtn);
      btnContainer.appendChild(noBtn);
      msgEl.appendChild(btnContainer);
      break;
    }

    case 'display_warning': {
      ctx.pendingMetricOrder = null;
      ctx.pendingResearchDisplayWarning = {
        level: response.warning_level,
        rowCount: response.row_count,
        softCap: response.soft_cap,
        hardCap: response.hard_cap,
        overrideAllowed: Boolean(response.override_allowed)
      };
      const msgEl = add(response.message, 'assistant');
      const btnContainer = document.createElement('div');
      btnContainer.className = 'metric-warning-buttons';

      if (response.override_allowed) {
        const yesBtn = document.createElement('button');
        yesBtn.textContent = 'Continue anyway';
        yesBtn.className = 'chat-action-btn confirm';
        yesBtn.addEventListener('click', () => {
          btnContainer.remove();
          ctx.resendWithResearchDisplayForce();
        });
        btnContainer.appendChild(yesBtn);
      }
      if (btnContainer.childNodes.length) {
        msgEl.appendChild(btnContainer);
      }
      break;
    }

    case 'clarify':
      ctx.pendingMetricOrder = null;
      ctx.pendingResearchDisplayWarning = null;
      add(response.message || 'Could you be more specific?', 'assistant');
      break;

    case 'disambiguate':
      add(response.message || 'Please select a location:', 'assistant');
      ctx.lastDisambiguationOptions = response.options || [];
      if (SelectionManager) {
        SelectionManager.enter(response, (selected, originalQuery) => {
          ctx.handleDisambiguationSelection(selected, originalQuery);
        });
      }
      break;

    case 'navigate':
      add(response.message || 'Showing locations.', 'assistant');
      ctx.handleNavigation(response);
      break;

    case 'drilldown':
      add(response.message || 'Loading...', 'assistant');
      if (App && response.loc_id) {
        App.drillDown(response.loc_id, response.name || response.loc_id);
      }
      break;

    case 'data':
      add(response.summary || 'Here is your data.', 'assistant');
      routeMapResponse(ctx, response, { origin: targetMode }, deps);
      break;

    case 'events':
      add(response.summary || `Showing ${response.count} ${response.event_type} events.`, 'assistant');
      ingestEventsToOverlay?.(response);
      routeMapResponse(ctx, response, { origin: targetMode }, deps);
      break;

    case 'cache_answer':
      add(response.message || 'Here is the current state.', 'assistant');
      break;

    case 'order_response':
      if (response.action === 'remove') {
        add(response.summary || `Removed ${response.count || 0} ${response.data_type || 'items'}.`, 'assistant');
      } else {
        add(response.summary || 'Order complete.', 'assistant');
      }
      routeMapResponse(ctx, response, { origin: targetMode }, deps);
      break;

    case 'mixed_order':
      if (response.results) {
        for (const result of response.results) {
          routeMapResponse(ctx, result, { origin: targetMode }, deps);
        }
      }
      add(response.summary || `Updated: added ${response.add_count || 0}, removed ${response.remove_count || 0}`, 'assistant');
      break;

    case 'geometry_remove':
      add(response.message || 'Removing geometry.', 'assistant');
      routeMapResponse(ctx, { ...response, action: 'remove', data_type: 'geometry' }, { origin: targetMode }, deps);
      break;

    case 'filter_update':
      add(response.message || 'Updating filters.', 'assistant');
      applyFilterUpdate(ctx, response, deps);
      break;

    case 'filter_existing':
      add(response.message || 'Filtering cached data.', 'assistant');
      if (response.overlay && response.filters && OverlayController) {
        OverlayController.updateFilters(response.overlay, response.filters);
        OverlayController.rerenderFromCache?.();
      }
      break;

    case 'overlay_toggle':
      add(response.message || (response.enabled ? 'Enabling overlay.' : 'Disabling overlay.'), 'assistant');
      if (response.overlay && OverlaySelector) {
        const isCurrentlyActive = OverlaySelector.isActive(response.overlay);
        if (response.enabled && !isCurrentlyActive) {
          OverlaySelector.toggle(response.overlay);
        } else if (!response.enabled && isCurrentlyActive) {
          OverlaySelector.toggle(response.overlay);
        }
        if (response.enabled && response.filters && OverlayController) {
          OverlayController.updateFilters(response.overlay, response.filters);
          OverlayController.reloadOverlay(response.overlay);
        }
      }
      break;

    case 'tutorial_mode': {
      const result = TutorialMode.applyCommand(response.action || (response.enabled ? 'on' : 'off'));
      add(response.message || result.message, 'assistant');
      break;
    }

    case 'address_prompt':
      ctx.showAddressPrompt(response);
      break;

    case 'save_order':
      if (response.name) {
        const saved = SavedOrders.save(
          response.name,
          orderPanel?.currentOrder?.items || [],
          orderPanel?.currentOrder?.summary || ''
        );
        if (saved) {
          add(`Order saved as "${saved.name}"`, 'assistant');
        } else {
          add('No order to save.', 'assistant');
        }
      } else {
        add('Please specify a name to save the order (e.g., "save as California Data").', 'assistant');
      }
      break;

    case 'list_orders': {
      const savedOrders = SavedOrders.getAll();
      if (savedOrders.length === 0) {
        add('No saved orders. Save an order first with "save as [name]".', 'assistant');
      } else {
        const names = savedOrders.map(o => `- ${o.name}`).join('\n');
        add(`Saved orders:\n${names}`, 'assistant');
      }
      break;
    }

    case 'load_order':
      if (response.name) {
        const order = SavedOrders.load(response.name);
        if (order && orderPanel) {
          orderPanel.currentOrder = {
            items: JSON.parse(JSON.stringify(order.items)),
            summary: order.summary || 'Loaded saved order: ' + order.name
          };
          orderPanel.render(orderPanel.currentOrder.summary);
          orderPanel.switchTab('order');
          add(`Loaded saved order: "${order.name}"`, 'assistant');
        } else if (!order) {
          add(`No saved order found with name "${response.name}".`, 'assistant');
        }
      } else {
        const allOrders = SavedOrders.getAll();
        if (allOrders.length > 0) {
          const names = allOrders.map(o => `- ${o.name}`).join('\n');
          add(`Which order? Available:\n${names}`, 'assistant');
        } else {
          add('No saved orders available.', 'assistant');
        }
      }
      break;

    case 'delete_order':
      if (response.name) {
        if (SavedOrders.deleteOrder(response.name)) {
          add(`Deleted saved order: "${response.name}"`, 'assistant');
        } else {
          add(`No saved order found with name "${response.name}".`, 'assistant');
        }
      } else {
        add('Please specify which order to delete (e.g., "delete order California Analysis").', 'assistant');
      }
      break;

    case 'error':
      add(response.message || 'An error occurred. Please try again.', 'assistant');
      break;

    case 'chat':
    default:
      ctx.pendingMetricOrder = null;
      ctx.pendingResearchDisplayWarning = null;
      ctx.applySupplementalChatActions(response);
      if (response.geojson && response.geojson.features && response.geojson.features.length > 0) {
        add(response.summary || response.message || 'Found data for you.', 'assistant');
        if (response.event_type) {
          ingestEventsToOverlay?.(response);
        }
        App?.displayMapPayload(response);
      } else {
        add(response.summary || response.message || 'Could you be more specific?', 'assistant');
      }
      break;
  }
}
