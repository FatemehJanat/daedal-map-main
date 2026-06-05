export function buildResearchWelcomeMessage(manifest, fallbackMessage) {
  if ((manifest?.artifact_count || 0) > 0 && !manifest?.stale_artifacts) {
    return `Research mode ready. Active corpus has ${manifest.artifact_count} loaded artifact${manifest.artifact_count === 1 ? '' : 's'}. Ask for rankings, comparisons, summaries, or map-backed evidence from this bounded workspace.`;
  }

  if (manifest?.saved_corpus) {
    const saved = manifest.saved_corpus;
    if (manifest?.stale_artifacts) {
      return `Research mode is ready, but "${saved.name}" is out of date in this local session. Click Load Data to refresh the corpus, then ask bounded analytical questions about it.`;
    }
    return `Research mode is ready. "${saved.name}" is selected. Click Load Data to activate it for this session, then ask for rankings, comparisons, or evidence-backed findings.`;
  }

  return fallbackMessage;
}
