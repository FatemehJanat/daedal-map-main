/**
 * Unified Disaster Popup System
 *
 * Provides consistent popup UI across all disaster types with:
 * - Quick stats cards (Power, Time, Impact)
 * - Three action buttons (Details, Sequence, Related)
 * - State machine for popup transitions
 *
 * See docs/DISASTER_DISPLAY.md for full specification.
 */

const DisasterPopup = {
  // Current popup state
  state: 'CLOSED', // CLOSED, BASIC, DETAIL, SEQUENCE, RELATED
  currentEvent: null,
  currentType: null,
  cachedData: {}, // Cache for sequence/related data

  // Event type icons
  icons: {
    earthquake: 'E',
    volcano: 'V',
    tsunami: 'T',
    hurricane: 'H',
    tornado: 'N',
    wildfire: 'W',
    flood: 'F',
    generic: '*'
  },

  // Event type colors
  colors: {
    earthquake: '#ff6b6b',
    volcano: '#feb24c',
    tsunami: '#4dd0e1',
    hurricane: '#9c27b0',
    tornado: '#32cd32',
    wildfire: '#ff6600',
    flood: '#0066cc',
    generic: '#888888'
  },

  /**
   * Format power stat based on disaster type
   */
  formatPower(props, eventType) {
    switch (eventType) {
      case 'earthquake':
        const mag = props.magnitude?.toFixed(1) || 'N/A';
        return { label: 'Power', value: `M ${mag}`, detail: 'Magnitude' };

      case 'tsunami':
        const height = props.max_water_height_m;
        if (height != null) {
          return { label: 'Power', value: `${height.toFixed(1)}m`, detail: 'Max wave height' };
        }
        const eqMag = props.eq_magnitude;
        if (eqMag != null) {
          return { label: 'Power', value: `M ${eqMag.toFixed(1)}`, detail: 'Triggering quake' };
        }
        return { label: 'Power', value: 'N/A', detail: '' };

      case 'volcano':
        const vei = props.VEI;
        if (vei != null) {
          return { label: 'Power', value: `VEI ${vei}`, detail: 'Eruption index' };
        }
        return { label: 'Power', value: 'Unknown', detail: 'VEI not recorded' };

      case 'hurricane':
      case 'tropical_storm':
        const cat = props.category || props.max_category;
        const wind = props.wind_kt || props.max_wind_kt;
        if (cat != null) {
          return { label: 'Power', value: `Cat ${cat}`, detail: wind ? `${wind} kt` : '' };
        }
        if (wind != null) {
          return { label: 'Power', value: `${wind} kt`, detail: 'Max wind' };
        }
        return { label: 'Power', value: 'N/A', detail: '' };

      case 'tornado':
        const scale = props.tornado_scale || 'Unknown';
        return { label: 'Power', value: scale, detail: this.getTornadoDescription(scale) };

      case 'wildfire':
        const area = props.area_km2;
        if (area != null) {
          if (area >= 1000) {
            return { label: 'Size', value: `${(area/1000).toFixed(1)}K km2`, detail: 'Burned area' };
          }
          return { label: 'Size', value: `${Math.round(area)} km2`, detail: 'Burned area' };
        }
        return { label: 'Size', value: 'N/A', detail: '' };

      case 'flood':
        const severity = props.severity || props.flood_severity;
        if (severity) {
          return { label: 'Severity', value: severity, detail: '' };
        }
        const floodArea = props.area_km2;
        if (floodArea != null) {
          return { label: 'Area', value: `${Math.round(floodArea)} km2`, detail: 'Affected area' };
        }
        return { label: 'Severity', value: 'N/A', detail: '' };

      default:
        return { label: 'Power', value: 'N/A', detail: '' };
    }
  },

  /**
   * Format time/duration stat based on disaster type
   */
  formatTime(props, eventType) {
    // Check for duration first
    const durationDays = props.duration_days;
    const durationMinutes = props.duration_minutes;

    if (durationDays != null && durationDays > 0) {
      if (durationDays >= 365) {
        const years = (durationDays / 365).toFixed(1);
        return { label: 'Duration', value: `${years} yr`, detail: 'Active period' };
      }
      if (durationDays >= 30) {
        const months = Math.round(durationDays / 30);
        return { label: 'Duration', value: `${months} mo`, detail: `${durationDays} days` };
      }
      return { label: 'Duration', value: `${durationDays} days`, detail: '' };
    }

    if (durationMinutes != null && durationMinutes > 0) {
      if (durationMinutes >= 60) {
        const hours = (durationMinutes / 60).toFixed(1);
        return { label: 'Duration', value: `${hours} hr`, detail: '' };
      }
      return { label: 'Duration', value: `${durationMinutes} min`, detail: '' };
    }

    // Type-specific time formatting
    switch (eventType) {
      case 'earthquake':
        // Earthquakes are instantaneous, show shaking estimate
        const mag = props.magnitude || 0;
        const shakeSec = Math.max(10, Math.round(Math.pow(10, (mag - 5) * 0.5) * 10));
        return { label: 'Shaking', value: `~${shakeSec}s`, detail: 'Estimated' };

      case 'tsunami':
        // Show travel time or runup count
        if (props.travel_time_hours != null) {
          const hrs = props.travel_time_hours;
          if (hrs < 1) {
            return { label: 'Travel', value: `${Math.round(hrs * 60)} min`, detail: 'To coast' };
          }
          return { label: 'Travel', value: `${hrs.toFixed(1)} hr`, detail: 'To coast' };
        }
        return { label: 'Time', value: 'N/A', detail: '' };

      case 'hurricane':
      case 'tropical_storm':
        // Calculate from start_date and end_date
        if (props.start_date && props.end_date) {
          const start = new Date(props.start_date);
          const end = new Date(props.end_date);
          const days = Math.round((end - start) / (1000 * 60 * 60 * 24));
          return { label: 'Duration', value: `${days} days`, detail: '' };
        }
        return { label: 'Duration', value: 'N/A', detail: '' };

      case 'tornado':
        // Estimate duration from path length (avg tornado speed ~30 mph)
        const pathMiles = props.path_length_miles || props.tornado_length_mi;
        if (pathMiles != null && pathMiles > 0) {
          const estMinutes = Math.max(1, Math.round(pathMiles * 2)); // ~30 mph avg forward speed
          if (estMinutes >= 60) {
            return { label: 'Time', value: `~${(estMinutes/60).toFixed(1)} hr`, detail: 'Estimated' };
          }
          return { label: 'Time', value: `~${estMinutes} min`, detail: 'Estimated' };
        }
        return { label: 'Time', value: 'Brief', detail: 'Seconds to minutes' };

      case 'volcano':
        if (props.is_ongoing) {
          return { label: 'Status', value: 'Ongoing', detail: 'Still active' };
        }
        return { label: 'Duration', value: 'N/A', detail: '' };

      default:
        return { label: 'Time', value: 'N/A', detail: '' };
    }
  },

  /**
   * Format impact stat based on disaster type
   */
  formatImpact(props, eventType) {
    switch (eventType) {
      case 'earthquake':
        const feltKm = props.felt_radius_km;
        if (feltKm != null && feltKm > 0) {
          return { label: 'Felt', value: `${Math.round(feltKm)} km`, detail: 'Radius' };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      case 'tsunami':
        const runups = props.runup_count;
        if (runups != null && runups > 0) {
          return { label: 'Runups', value: runups.toString(), detail: 'Observations' };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      case 'volcano':
        const damageKm = props.damage_radius_km;
        if (damageKm != null && damageKm > 0) {
          return { label: 'Damage', value: `${Math.round(damageKm)} km`, detail: 'Radius' };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      case 'hurricane':
      case 'tropical_storm':
        const maxWind = props.max_wind_kt || props.wind_kt;
        if (maxWind != null) {
          return { label: 'Wind', value: `${maxWind} kt`, detail: 'Maximum' };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      case 'tornado':
        const pathLen = props.path_length_miles || props.tornado_length_mi;
        const pathWidth = props.path_width_yards || props.tornado_width_yd;
        if (pathLen != null && pathLen > 0) {
          const widthStr = pathWidth ? ` x ${pathWidth}yd` : '';
          return { label: 'Path', value: `${pathLen.toFixed(1)} mi`, detail: widthStr };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      case 'wildfire':
        const spread = props.spread_speed || props.spread_km_day;
        if (spread != null) {
          return { label: 'Spread', value: `${spread.toFixed(1)} km/d`, detail: '' };
        }
        const fireDuration = props.duration_days;
        if (fireDuration != null) {
          return { label: 'Duration', value: `${fireDuration} days`, detail: '' };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      case 'flood':
        const dead = props.deaths;
        if (dead != null && dead > 0) {
          return { label: 'Deaths', value: dead.toLocaleString(), detail: '' };
        }
        const displaced = props.displaced_count;
        if (displaced != null && displaced > 0) {
          return { label: 'Displaced', value: displaced.toLocaleString(), detail: '' };
        }
        return { label: 'Impact', value: 'N/A', detail: '' };

      default:
        return { label: 'Impact', value: 'N/A', detail: '' };
    }
  },

  /**
   * Get tornado scale description
   */
  getTornadoDescription(scale) {
    const descriptions = {
      'EF0': 'Light', 'F0': 'Light',
      'EF1': 'Moderate', 'F1': 'Moderate',
      'EF2': 'Significant', 'F2': 'Significant',
      'EF3': 'Severe', 'F3': 'Severe',
      'EF4': 'Devastating', 'F4': 'Devastating',
      'EF5': 'Incredible', 'F5': 'Incredible'
    };
    return descriptions[scale] || '';
  },

  /**
   * Get event title
   */
  getTitle(props, eventType) {
    switch (eventType) {
      case 'earthquake':
        const mag = props.magnitude?.toFixed(1) || 'N/A';
        return `M${mag} Earthquake`;

      case 'tsunami':
        if (props.is_source || props._isSource) {
          return 'Tsunami Source';
        }
        return 'Coastal Runup';

      case 'volcano':
        return props.volcano_name || 'Volcanic Eruption';

      case 'hurricane':
      case 'tropical_storm':
        const name = props.name || props.storm_name;
        if (name) {
          return name;
        }
        return 'Tropical Storm';

      case 'tornado':
        const scale = props.tornado_scale || 'Unknown';
        return `${scale} Tornado`;

      case 'wildfire':
        return props.fire_name || 'Wildfire';

      case 'flood':
        return props.event_name || 'Flood Event';

      default:
        return `${eventType} Event`;
    }
  },

  /**
   * Get event subtitle (location, date)
   */
  getSubtitle(props, eventType) {
    const parts = [];

    // Location
    if (props.place) {
      parts.push(props.place);
    } else if (props.location_name) {
      parts.push(props.location_name);
    } else if (props.country) {
      parts.push(props.country);
    }

    // Date
    if (props.timestamp) {
      const date = new Date(props.timestamp);
      if (!isNaN(date.getTime())) {
        parts.push(date.toLocaleDateString());
      }
    } else if (props.year) {
      const yr = props.year < 0 ? `${Math.abs(props.year)} BCE` : props.year;
      parts.push(yr.toString());
    }

    return parts.join(' - ');
  },

  /**
   * Check if event has sequence data
   */
  hasSequence(props, eventType) {
    // Middle button always enabled for basic animation (impact radius, path, etc.)
    // Even without linked events, we show a solo animation for the event itself
    switch (eventType) {
      case 'earthquake':
        // Always show - at minimum displays impact radius animation
        return true;

      case 'tsunami':
        // Always show - at minimum displays wave impact animation
        return true;

      case 'hurricane':
      case 'tropical_storm':
        // Always show - has track data
        return true;

      case 'tornado':
        // Always show - at minimum displays path or point animation
        return true;

      case 'volcano':
        // Always show - at minimum displays impact radius animation
        return true;

      case 'wildfire':
        // Always show - at minimum displays area circle, enhanced with progression data
        return true;

      case 'flood':
        // Always show - at minimum displays area circle, enhanced with geometry data
        return true;

      default:
        return false;
    }
  },

  /**
   * Get sequence button text
   */
  getSequenceText(props, eventType) {
    switch (eventType) {
      case 'earthquake':
        if (props.aftershock_count > 0) {
          return `Aftershocks (${props.aftershock_count})`;
        }
        return 'Impact';

      case 'tsunami':
        if (props.runup_count > 0) {
          return `Runups (${props.runup_count})`;
        }
        return 'Impact';

      case 'hurricane':
      case 'tropical_storm':
        return 'Track';

      case 'tornado':
        if (props.sequence_count > 1) {
          return `Sequence (${props.sequence_count})`;
        }
        return 'Path';

      case 'volcano':
        return 'Impact';

      case 'wildfire':
        return 'Progression';

      case 'flood':
        return 'Extent';

      default:
        return 'Sequence';
    }
  },

  /**
   * Check if event has related cross-type links
   */
  hasRelated(props, eventType) {
    // Check for explicit links
    if (props.parent_event_id) return true;
    if (props.eq_event_id) return true;
    if (props.volcano_id) return true;
    if (props.hurricane_id) return true;
    if (props.related_events && props.related_events.length > 0) return true;

    // Type-specific related data opportunities
    switch (eventType) {
      case 'earthquake':
        // Can link to volcanoes or tsunamis
        return props.year >= 1900;

      case 'tsunami':
        // Can link back to triggering earthquake
        return props.cause === 'Earthquake' || props.cause === 'Volcano';

      case 'volcano':
        // Can link to earthquakes
        return props.year >= 1900;

      default:
        return false;
    }
  },

  /**
   * Build the basic popup HTML
   */
  buildBasicPopup(props, eventType) {
    const icon = this.icons[eventType] || this.icons.generic;
    const color = this.colors[eventType] || this.colors.generic;
    const title = this.getTitle(props, eventType);
    const subtitle = this.getSubtitle(props, eventType);

    const power = this.formatPower(props, eventType);
    const time = this.formatTime(props, eventType);
    const impact = this.formatImpact(props, eventType);

    const hasSeq = this.hasSequence(props, eventType);
    const hasRel = this.hasRelated(props, eventType);
    const seqText = this.getSequenceText(props, eventType);

    // Build HTML
    let html = `
      <div class="disaster-popup" data-type="${eventType}" data-id="${props.event_id || ''}">
        <div class="popup-header" style="border-left: 4px solid ${color}">
          <span class="popup-icon" style="background: ${color}">${icon}</span>
          <div class="popup-title-group">
            <div class="popup-title">${title}</div>
            <div class="popup-subtitle">${subtitle}</div>
          </div>
        </div>

        <div class="popup-stats">
          <div class="stat-card">
            <div class="stat-label">${power.label}</div>
            <div class="stat-value">${power.value}</div>
            ${power.detail ? `<div class="stat-detail">${power.detail}</div>` : ''}
          </div>
          <div class="stat-card">
            <div class="stat-label">${time.label}</div>
            <div class="stat-value">${time.value}</div>
            ${time.detail ? `<div class="stat-detail">${time.detail}</div>` : ''}
          </div>
          <div class="stat-card">
            <div class="stat-label">${impact.label}</div>
            <div class="stat-value">${impact.value}</div>
            ${impact.detail ? `<div class="stat-detail">${impact.detail}</div>` : ''}
          </div>
        </div>

        <div class="popup-actions">
          <button class="popup-btn btn-details" data-action="details">
            Details
          </button>
          <button class="popup-btn btn-sequence${hasSeq ? '' : ' disabled'}" data-action="sequence" ${hasSeq ? '' : 'disabled'}>
            ${seqText}
          </button>
          <button class="popup-btn btn-related${hasRel ? '' : ' disabled'}" data-action="related" ${hasRel ? '' : 'disabled'}>
            Related
          </button>
        </div>
      </div>
    `;

    return html;
  },

  /**
   * Build the detail view popup HTML
   */
  buildDetailPopup(props, eventType, detailData) {
    const icon = this.icons[eventType] || this.icons.generic;
    const color = this.colors[eventType] || this.colors.generic;
    const title = this.getTitle(props, eventType);

    // Merge props with detail data
    const data = { ...props, ...detailData };

    let html = `
      <div class="disaster-popup popup-detail" data-type="${eventType}" data-id="${props.event_id || ''}">
        <div class="popup-header-detail" style="border-left: 4px solid ${color}">
          <button class="popup-back" data-action="back">&lt; Back</button>
          <span class="popup-title-detail">${title}</span>
        </div>

        <div class="popup-tabs">
          <button class="tab-btn active" data-tab="overview">Overview</button>
          <button class="tab-btn" data-tab="impact">Impact</button>
          <button class="tab-btn" data-tab="technical">Technical</button>
          <button class="tab-btn" data-tab="source">Source</button>
        </div>

        <div class="tab-content active" data-tab="overview">
          ${this.buildOverviewTab(data, eventType)}
        </div>
        <div class="tab-content" data-tab="impact">
          ${this.buildImpactTab(data, eventType)}
        </div>
        <div class="tab-content" data-tab="technical">
          ${this.buildTechnicalTab(data, eventType)}
        </div>
        <div class="tab-content" data-tab="source">
          ${this.buildSourceTab(data, eventType)}
        </div>

        <div class="popup-actions">
          <button class="popup-btn btn-sequence" data-action="sequence">
            ${this.getSequenceText(props, eventType)}
          </button>
          <button class="popup-btn btn-related" data-action="related">
            Related
          </button>
        </div>
      </div>
    `;

    return html;
  },

  /**
   * Build overview tab content
   */
  buildOverviewTab(data, eventType) {
    const lines = [];

    // Location
    if (data.place) {
      lines.push(`<div class="detail-row"><span class="detail-label">Location:</span> ${data.place}</div>`);
    }
    if (data.country) {
      lines.push(`<div class="detail-row"><span class="detail-label">Country:</span> ${data.country}</div>`);
    }

    // Coordinates
    if (data.latitude != null && data.longitude != null) {
      lines.push(`<div class="detail-row"><span class="detail-label">Coordinates:</span> ${data.latitude.toFixed(4)}, ${data.longitude.toFixed(4)}</div>`);
    }

    // Date/time
    if (data.timestamp) {
      const date = new Date(data.timestamp);
      lines.push(`<div class="detail-row"><span class="detail-label">Date/Time:</span> ${date.toLocaleString()}</div>`);
    } else if (data.year) {
      const yr = data.year < 0 ? `${Math.abs(data.year)} BCE` : data.year;
      lines.push(`<div class="detail-row"><span class="detail-label">Year:</span> ${yr}</div>`);
    }

    // Type-specific
    if (eventType === 'tsunami' && data.cause) {
      lines.push(`<div class="detail-row"><span class="detail-label">Cause:</span> ${data.cause}</div>`);
    }
    if (eventType === 'volcano' && data.activity_type) {
      lines.push(`<div class="detail-row"><span class="detail-label">Activity:</span> ${data.activity_type}</div>`);
    }

    return lines.join('\n') || '<div class="detail-empty">No overview data available</div>';
  },

  /**
   * Build impact tab content
   */
  buildImpactTab(data, eventType) {
    const lines = [];

    // Deaths (deaths_direct used by tornadoes)
    const deaths = data.deaths || data.deaths_direct;
    if (deaths != null && deaths > 0) {
      lines.push(`<div class="detail-row impact-deaths"><span class="detail-label">Deaths:</span> ${deaths.toLocaleString()}</div>`);
    }

    // Injuries
    const injuries = data.injuries || data.injuries_direct;
    if (injuries != null && injuries > 0) {
      lines.push(`<div class="detail-row"><span class="detail-label">Injuries:</span> ${injuries.toLocaleString()}</div>`);
    }

    // Displaced
    if (data.displaced_count != null && data.displaced_count > 0) {
      lines.push(`<div class="detail-row"><span class="detail-label">Displaced:</span> ${data.displaced_count.toLocaleString()}</div>`);
    }

    // Damage
    const damage = data.damage_usd || data.damage_property;
    if (damage != null && damage > 0) {
      let damageStr;
      if (damage >= 1e9) {
        damageStr = `$${(damage / 1e9).toFixed(1)}B`;
      } else if (damage >= 1e6) {
        damageStr = `$${(damage / 1e6).toFixed(1)}M`;
      } else {
        damageStr = `$${damage.toLocaleString()}`;
      }
      lines.push(`<div class="detail-row"><span class="detail-label">Damage:</span> ${damageStr}</div>`);
    }

    // Area affected
    if (data.area_km2 != null) {
      lines.push(`<div class="detail-row"><span class="detail-label">Area:</span> ${data.area_km2.toLocaleString()} km2</div>`);
    }

    return lines.join('\n') || '<div class="detail-empty">No impact data recorded</div>';
  },

  /**
   * Build technical tab content
   */
  buildTechnicalTab(data, eventType) {
    const lines = [];

    switch (eventType) {
      case 'earthquake':
        if (data.magnitude != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Magnitude:</span> ${data.magnitude.toFixed(1)} Mw</div>`);
        }
        if (data.depth_km != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Depth:</span> ${data.depth_km.toFixed(1)} km</div>`);
        }
        if (data.felt_radius_km != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Felt radius:</span> ${Math.round(data.felt_radius_km)} km</div>`);
        }
        if (data.damage_radius_km != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Damage radius:</span> ${Math.round(data.damage_radius_km)} km</div>`);
        }
        break;

      case 'tsunami':
        if (data.eq_magnitude != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Triggering EQ:</span> M${data.eq_magnitude.toFixed(1)}</div>`);
        }
        if (data.max_water_height_m != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Max wave:</span> ${data.max_water_height_m.toFixed(1)} m</div>`);
        }
        if (data.runup_count != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Runups:</span> ${data.runup_count}</div>`);
        }
        break;

      case 'volcano':
        if (data.VEI != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">VEI:</span> ${data.VEI}</div>`);
        }
        if (data.activity_type) {
          lines.push(`<div class="detail-row"><span class="detail-label">Type:</span> ${data.activity_type}</div>`);
        }
        if (data.felt_radius_km != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Felt radius:</span> ${Math.round(data.felt_radius_km)} km</div>`);
        }
        break;

      case 'tornado':
        if (data.tornado_scale) {
          lines.push(`<div class="detail-row"><span class="detail-label">Scale:</span> ${data.tornado_scale}</div>`);
        }
        if (data.path_length_miles != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Path length:</span> ${data.path_length_miles.toFixed(1)} miles</div>`);
        }
        if (data.path_width_yards != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Path width:</span> ${data.path_width_yards} yards</div>`);
        }
        break;

      case 'wildfire':
        if (data.area_km2 != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Area:</span> ${data.area_km2.toLocaleString()} km2</div>`);
        }
        if (data.duration_days != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Duration:</span> ${data.duration_days} days</div>`);
        }
        if (data.land_cover) {
          lines.push(`<div class="detail-row"><span class="detail-label">Vegetation:</span> ${data.land_cover}</div>`);
        }
        break;

      case 'hurricane':
      case 'tropical_storm':
        if (data.max_wind_kt != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Max wind:</span> ${data.max_wind_kt} kt</div>`);
        }
        if (data.min_pressure_mb != null) {
          lines.push(`<div class="detail-row"><span class="detail-label">Min pressure:</span> ${data.min_pressure_mb} mb</div>`);
        }
        if (data.basin) {
          lines.push(`<div class="detail-row"><span class="detail-label">Basin:</span> ${data.basin}</div>`);
        }
        break;
    }

    return lines.join('\n') || '<div class="detail-empty">No technical data available</div>';
  },

  /**
   * Build source tab content with clickable links to original data sources
   */
  buildSourceTab(data, eventType) {
    const lines = [];

    // Source URLs by type - most data sources have predictable URL patterns
    const sourceUrlBuilders = {
      earthquake: (id) => id ? `https://earthquake.usgs.gov/earthquakes/eventpage/${id}` : null,
      tsunami: (id, data) => {
        // NOAA NCEI tsunami events - link to event search
        if (id) return `https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/event-more-info/${id}`;
        return null;
      },
      volcano: (id, data) => {
        // Smithsonian GVP uses volcano number, not event_id
        const vnum = data.volcano_number || data.vnum;
        if (vnum) return `https://volcano.si.edu/volcano.cfm?vn=${vnum}`;
        return null;
      },
      hurricane: (id, data) => {
        // IBTrACS storms can be looked up by storm_id (SID format)
        const sid = data.storm_id || id;
        if (sid) return `https://www.ncei.noaa.gov/products/international-best-track-archive?name=${sid}`;
        return null;
      },
      tornado: (id, data) => {
        // NOAA Storm Events Database - link to event details if episode/event IDs available
        const episodeId = data.episode_id;
        const eventId = data.event_id || id;
        if (episodeId) return `https://www.ncdc.noaa.gov/stormevents/eventdetails.jsp?id=${eventId}`;
        return null;
      },
      wildfire: (id, data) => {
        // NASA FIRMS or Global Fire Atlas - link to FIRMS map
        if (data.latitude && data.longitude) {
          return `https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@${data.longitude},${data.latitude},10z`;
        }
        return null;
      },
      flood: (id, data) => {
        // DFO Flood Observatory archive
        const dfoId = data.dfo_id || data.flood_id || id;
        if (dfoId) return `https://floodobservatory.colorado.edu/Archives/index.html`;
        return null;
      }
    };

    // Default source names
    const defaultSources = {
      earthquake: 'USGS Earthquake Catalog',
      tsunami: 'NOAA NCEI Tsunami Database',
      volcano: 'Smithsonian Global Volcanism Program',
      hurricane: 'NOAA IBTrACS',
      tornado: 'NOAA Storm Events Database',
      wildfire: 'NASA FIRMS / Global Fire Atlas',
      flood: 'DFO Flood Observatory'
    };

    // Build source URL if available
    const urlBuilder = sourceUrlBuilders[eventType];
    const sourceUrl = urlBuilder ? urlBuilder(data.event_id, data) : null;
    const sourceName = data.source || data.data_source || defaultSources[eventType] || 'Unknown';

    // Event ID row - make clickable if we have a URL
    if (data.event_id) {
      if (sourceUrl) {
        lines.push(`<div class="detail-row"><span class="detail-label">Event ID:</span> <a href="${sourceUrl}" target="_blank" rel="noopener" class="source-link">${data.event_id}</a></div>`);
      } else {
        lines.push(`<div class="detail-row"><span class="detail-label">Event ID:</span> ${data.event_id}</div>`);
      }
    }

    // Source row - also make clickable if we have a URL
    if (sourceUrl) {
      lines.push(`<div class="detail-row"><span class="detail-label">Source:</span> <a href="${sourceUrl}" target="_blank" rel="noopener" class="source-link">${sourceName}</a></div>`);
    } else {
      lines.push(`<div class="detail-row"><span class="detail-label">Source:</span> ${sourceName}</div>`);
    }

    if (data.last_updated) {
      lines.push(`<div class="detail-row"><span class="detail-label">Updated:</span> ${data.last_updated}</div>`);
    }

    return lines.join('\n') || '<div class="detail-empty">No source information</div>';
  },

  /**
   * Build sequence view popup HTML
   */
  buildSequencePopup(props, eventType, sequenceData) {
    const icon = this.icons[eventType] || this.icons.generic;
    const color = this.colors[eventType] || this.colors.generic;
    const title = this.getTitle(props, eventType);

    let sequenceList = '';
    let summary = '';

    if (sequenceData && sequenceData.events && sequenceData.events.length > 0) {
      summary = `${sequenceData.events.length} events`;
      sequenceList = sequenceData.events.slice(0, 20).map((evt, idx) => {
        const label = evt.label || `Event ${idx + 1}`;
        const sublabel = evt.timestamp ? new Date(evt.timestamp).toLocaleString() : '';
        return `<div class="sequence-item" data-id="${evt.event_id || idx}">
          <span class="seq-marker">${idx === 0 ? '*' : 'o'}</span>
          <span class="seq-label">${label}</span>
          <span class="seq-sublabel">${sublabel}</span>
        </div>`;
      }).join('\n');

      if (sequenceData.events.length > 20) {
        sequenceList += `<div class="sequence-more">... and ${sequenceData.events.length - 20} more</div>`;
      }
    } else {
      summary = 'Loading...';
      sequenceList = '<div class="sequence-loading">Loading sequence data...</div>';
    }

    let html = `
      <div class="disaster-popup popup-sequence" data-type="${eventType}" data-id="${props.event_id || ''}">
        <div class="popup-header-detail" style="border-left: 4px solid ${color}">
          <button class="popup-back" data-action="back">&lt; Back</button>
          <span class="popup-title-detail">${this.getSequenceText(props, eventType)}</span>
        </div>

        <div class="sequence-summary">
          <strong>${title}</strong>
          <div class="seq-count">${summary}</div>
        </div>

        <div class="sequence-list">
          ${sequenceList}
        </div>

        <div class="popup-actions">
          <button class="popup-btn btn-related" data-action="related">
            View Related Disasters
          </button>
        </div>
      </div>
    `;

    return html;
  },

  /**
   * Build related view popup HTML
   */
  buildRelatedPopup(props, eventType, relatedData) {
    const icon = this.icons[eventType] || this.icons.generic;
    const color = this.colors[eventType] || this.colors.generic;
    const title = this.getTitle(props, eventType);

    let relatedList = '';

    if (relatedData && relatedData.related && relatedData.related.length > 0) {
      relatedList = relatedData.related.map(rel => {
        const relIcon = this.icons[rel.event_type] || this.icons.generic;
        const relColor = this.colors[rel.event_type] || this.colors.generic;
        const relTitle = this.getTitle(rel, rel.event_type);
        const linkType = rel.link_type || 'linked';

        return `<div class="related-item" data-id="${rel.event_id}" data-type="${rel.event_type}">
          <span class="related-icon" style="background: ${relColor}">${relIcon}</span>
          <div class="related-info">
            <div class="related-title">${relTitle}</div>
            <div class="related-link-type">${linkType}</div>
          </div>
        </div>`;
      }).join('\n');
    } else {
      relatedList = '<div class="related-empty">No related disasters found</div>';
    }

    let html = `
      <div class="disaster-popup popup-related" data-type="${eventType}" data-id="${props.event_id || ''}">
        <div class="popup-header-detail" style="border-left: 4px solid ${color}">
          <button class="popup-back" data-action="back">&lt; Back</button>
          <span class="popup-title-detail">Related Disasters</span>
        </div>

        <div class="related-primary">
          <span class="related-icon" style="background: ${color}">${icon}</span>
          <div class="related-info">
            <div class="related-title">${title}</div>
            <div class="related-subtitle">${this.getSubtitle(props, eventType)}</div>
          </div>
        </div>

        <div class="related-chain-label">Disaster Chain:</div>

        <div class="related-list">
          ${relatedList}
        </div>

        <div class="popup-footer">
          Click any event to view details
        </div>
      </div>
    `;

    return html;
  },

  /**
   * Show basic popup
   */
  show(lngLat, props, eventType) {
    this.currentEvent = props;
    this.currentType = eventType;
    this.state = 'BASIC';

    const html = this.buildBasicPopup(props, eventType);

    if (MapAdapter) {
      MapAdapter.showPopup(lngLat, html);
      MapAdapter.popupLocked = true;
    }

    // Setup button handlers after popup is in DOM
    setTimeout(() => this.setupButtonHandlers(), 50);
  },

  /**
   * Setup click handlers for popup buttons
   */
  setupButtonHandlers() {
    const popup = document.querySelector('.disaster-popup');
    if (!popup) return;

    // Action buttons
    popup.querySelectorAll('.popup-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const action = btn.dataset.action;
        this.handleAction(action);
      });
    });

    // Back button
    popup.querySelectorAll('.popup-back').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.handleBack();
      });
    });

    // Tab buttons
    popup.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const tab = btn.dataset.tab;
        this.switchTab(tab);
      });
    });

    // Related items
    popup.querySelectorAll('.related-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const id = item.dataset.id;
        const type = item.dataset.type;
        this.handleRelatedClick(id, type);
      });
    });

    // Sequence items
    popup.querySelectorAll('.sequence-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const id = item.dataset.id;
        this.handleSequenceItemClick(id);
      });
    });
  },

  /**
   * Handle action button click
   */
  handleAction(action) {
    if (!this.currentEvent || !this.currentType) return;

    switch (action) {
      case 'details':
        this.showDetails();
        break;
      case 'sequence':
        this.showSequence();
        break;
      case 'related':
        this.showRelated();
        break;
    }
  },

  /**
   * Handle back button
   */
  handleBack() {
    this.state = 'BASIC';
    const html = this.buildBasicPopup(this.currentEvent, this.currentType);
    this.updatePopupContent(html);
  },

  /**
   * Switch tab in detail view
   */
  switchTab(tabName) {
    const popup = document.querySelector('.disaster-popup');
    if (!popup) return;

    // Update tab buttons
    popup.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update tab content
    popup.querySelectorAll('.tab-content').forEach(content => {
      content.classList.toggle('active', content.dataset.tab === tabName);
    });
  },

  /**
   * Show detail view
   */
  showDetails() {
    this.state = 'DETAIL';

    // For now, use local data. In future, fetch from API
    const html = this.buildDetailPopup(this.currentEvent, this.currentType, {});
    this.updatePopupContent(html);
  },

  /**
   * Show sequence view - triggers animations for all disaster types
   * All sequence actions (aftershocks, runups, tracks, progressions, extents)
   * are handled as map animations, not popup lists
   */
  showSequence() {
    // Trigger the sequence handler FIRST (before hide clears currentEvent)
    this.triggerSequenceHandler();

    // Then hide popup - sequence actions trigger map animations
    this.hide();
  },

  /**
   * Show related view
   */
  showRelated() {
    this.state = 'RELATED';

    // Check cache first
    const cacheKey = `rel_${this.currentType}_${this.currentEvent.event_id}`;

    if (this.cachedData[cacheKey]) {
      const html = this.buildRelatedPopup(this.currentEvent, this.currentType, this.cachedData[cacheKey]);
      this.updatePopupContent(html);
      return;
    }

    // Show loading state
    const html = this.buildRelatedPopup(this.currentEvent, this.currentType, { related: [] });
    this.updatePopupContent(html);

    // Trigger existing related handlers
    this.triggerRelatedHandler();
  },

  /**
   * Update popup content without closing
   */
  updatePopupContent(html) {
    const popupContent = document.querySelector('.maplibregl-popup-content');
    if (popupContent) {
      popupContent.innerHTML = html;
      setTimeout(() => this.setupButtonHandlers(), 50);
    }
  },

  /**
   * Trigger existing sequence handler based on event type
   */
  triggerSequenceHandler() {
    const props = this.currentEvent;
    const eventType = this.currentType;

    // Dispatch custom event that existing handlers can listen to
    document.dispatchEvent(new CustomEvent('disaster-sequence-request', {
      detail: {
        eventId: props.event_id,
        eventType: eventType,
        props: props
      }
    }));
  },

  /**
   * Trigger existing related handler based on event type
   */
  triggerRelatedHandler() {
    const props = this.currentEvent;
    const eventType = this.currentType;

    // Dispatch custom event that existing handlers can listen to
    document.dispatchEvent(new CustomEvent('disaster-related-request', {
      detail: {
        eventId: props.event_id,
        eventType: eventType,
        props: props
      }
    }));
  },

  /**
   * Handle click on related item
   */
  handleRelatedClick(eventId, eventType) {
    // Dispatch event for handling
    document.dispatchEvent(new CustomEvent('disaster-related-click', {
      detail: {
        eventId: eventId,
        eventType: eventType
      }
    }));
  },

  /**
   * Handle click on sequence item
   */
  handleSequenceItemClick(eventId) {
    // Dispatch event for handling
    document.dispatchEvent(new CustomEvent('disaster-sequence-item-click', {
      detail: {
        eventId: eventId,
        parentType: this.currentType,
        parentId: this.currentEvent?.event_id
      }
    }));
  },

  /**
   * Hide popup
   */
  hide() {
    this.state = 'CLOSED';
    this.currentEvent = null;
    this.currentType = null;

    if (MapAdapter) {
      MapAdapter.hidePopup();
    }
  },

  /**
   * Check if popup is open
   */
  isOpen() {
    return this.state !== 'CLOSED';
  },

  /**
   * Get current state
   */
  getState() {
    return this.state;
  }
};

// Dependency injection
let MapAdapter = null;

export function setDependencies(deps) {
  if (deps.MapAdapter) MapAdapter = deps.MapAdapter;
}

// ES6 module export
export { DisasterPopup };

// Also expose globally for backwards compatibility
window.DisasterPopup = DisasterPopup;
