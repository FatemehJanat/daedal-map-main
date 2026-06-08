export function buildExploreWelcomeMessage() {
  return (
    'Welcome! Explore starts with a small starter tray: earthquakes for live event motion, ' +
    'demographics for choropleth comparison, and temperature for climate graphics.<br><br>' +
    'Ask me anything about global data -- earthquakes, hurricanes, climate indicators, ' +
    'and more. To explore datasets, type a question in natural language. ' +
    'Type "help" or "how do you work?" anytime for a full guide.<br><br>' +
    '<div class="welcome-action-row">' +
    '<button class="chat-action-btn" data-action="run-preset" data-preset-id="explore:disasters_2020_2025" data-mode="explore">Load 10-year disasters</button> ' +
    '<button id="tutorialToggleBtn" class="chat-action-btn tutorial-toggle-btn" data-action="tutorial-toggle" type="button" aria-pressed="false">Tutorial Off</button>' +
    '</div>'
  );
}
