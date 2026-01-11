/**
 * Model Registry - Routes event types to appropriate display models.
 * Central registry for all display models (Point+Radius, Track, Polygon).
 * Choropleth is handled separately by ChoroplethManager.
 */

// Model imports
import { PointRadiusModel, setDependencies as setPointDeps } from './model-point-radius.js';
import { TrackModel, setDependencies as setTrackDeps } from './model-track.js';
import { PolygonModel, setDependencies as setPolygonDeps } from './model-polygon.js';

// Map event types to model IDs
const TYPE_TO_MODEL = {
  // Point + Radius events (Model A)
  earthquake: 'point-radius',
  volcano: 'point-radius',
  tornado: 'point-radius',
  tsunami: 'point-radius',
  generic_event: 'point-radius',

  // Track events (Model B)
  hurricane: 'track',
  typhoon: 'track',
  cyclone: 'track',
  storm_track: 'track',

  // Polygon events (Model C)
  wildfire: 'point-radius',  // Points for overview, perimeter on-demand for animation
  flood: 'polygon',
  ash_cloud: 'polygon',
  drought_area: 'polygon'
};

// Model registry
const models = {
  'point-radius': PointRadiusModel,
  'track': TrackModel,
  'polygon': PolygonModel
};

export const ModelRegistry = {
  /**
   * Set dependencies on all models
   */
  setDependencies(deps) {
    // Wire dependencies to each model
    setPointDeps(deps);
    setTrackDeps(deps);
    setPolygonDeps(deps);
    console.log('ModelRegistry: Dependencies set');
  },

  /**
   * Get model ID for a given event type
   * @param {string} eventType - Event type (e.g., 'earthquake')
   * @returns {string|null} Model ID or null
   */
  getModelIdForType(eventType) {
    return TYPE_TO_MODEL[eventType] || null;
  },

  /**
   * Get model for a given event type
   * @param {string} eventType - Event type
   * @returns {Object|null} Model object or null
   */
  getModelForType(eventType) {
    const modelId = TYPE_TO_MODEL[eventType];
    return modelId ? models[modelId] : null;
  },

  /**
   * Get model by ID
   * @param {string} modelId - Model ID (e.g., 'point-radius')
   * @returns {Object|null} Model object or null
   */
  getModel(modelId) {
    return models[modelId] || null;
  },

  /**
   * Check if an event type is supported
   * @param {string} eventType - Event type
   * @returns {boolean}
   */
  isSupported(eventType) {
    return eventType in TYPE_TO_MODEL;
  },

  /**
   * Render data using appropriate model
   * @param {Object} geojson - GeoJSON data
   * @param {string} eventType - Event type
   * @param {Object} options - Render options
   * @returns {boolean} True if rendered
   */
  render(geojson, eventType, options = {}) {
    const model = this.getModelForType(eventType);
    if (model) {
      model.render(geojson, eventType, options);
      return true;
    }
    console.warn(`ModelRegistry: No model found for event type: ${eventType}`);
    return false;
  },

  /**
   * Clear all active model layers
   */
  clearActive() {
    for (const model of Object.values(models)) {
      if (model && model.clear) {
        model.clear();
      }
    }
  },

  /**
   * Get currently active model (one with activeType set)
   * @returns {Object|null} Active model or null
   */
  getActiveModel() {
    for (const model of Object.values(models)) {
      if (model && (model.activeType || model.activeTrackId)) {
        return model;
      }
    }
    return null;
  },

  /**
   * List all registered event types
   * @returns {string[]} Array of event types
   */
  getEventTypes() {
    return Object.keys(TYPE_TO_MODEL);
  },

  /**
   * List all model IDs
   * @returns {string[]} Array of model IDs
   */
  getModelIds() {
    return Object.keys(models);
  }
};
