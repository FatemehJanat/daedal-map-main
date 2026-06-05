export function buildOpsWelcomeMessage(payload, fallbackMessage) {
  const effectiveFeeds = Array.isArray(payload?.effective_feeds) ? payload.effective_feeds : [];
  if (effectiveFeeds.length > 0) {
    return `Ops mode ready. Active watch has ${effectiveFeeds.length} feed${effectiveFeeds.length === 1 ? '' : 's'}: ${effectiveFeeds.join(', ')}. Ask what is active, what changed recently, or tell me to show the biggest live event.`;
  }
  return payload?.warning || fallbackMessage;
}
