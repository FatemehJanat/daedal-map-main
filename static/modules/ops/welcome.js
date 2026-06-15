export function buildOpsFriendlyWelcomeMessage() {
  return 'Welcome to Ops. Use this mode to watch what is happening now, what changed recently, and what deserves attention across the last 72 hours.<br><br>Good first asks are "what is active right now", "show the biggest live event", or "what changed in the last day".';
}

export function buildOpsWelcomeMessage(payload, fallbackMessage) {
  const effectiveFeeds = Array.isArray(payload?.effective_feeds) ? payload.effective_feeds : [];
  if (effectiveFeeds.length > 0) {
    return `Active watch has ${effectiveFeeds.length} feed${effectiveFeeds.length === 1 ? '' : 's'}: ${effectiveFeeds.join(', ')}. Ask what is active, what changed recently, or tell me to show the biggest live event.`;
  }
  return payload?.warning || fallbackMessage;
}
