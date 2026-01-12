"""
NOAA Storm Events Category Consolidation

Consolidates 41+ NOAA event types into 8 manageable disaster categories.
See docs/disaster data.md for full documentation.

Categories:
1. tornadoes - Tornado, Funnel Cloud, Waterspout
2. severe_thunderstorms - Thunderstorm Wind, Hail, Lightning
3. tropical_cyclones - Hurricane, Tropical Storm (handled separately via IBTrACS)
4. flooding - Flash Flood, Flood, Coastal Flood, Storm Surge, Heavy Rain
5. high_winds - High Wind, Strong Wind, Dust Storm
6. winter_weather - Blizzard, Heavy Snow, Ice Storm, Cold
7. extreme_heat - Heat, Excessive Heat
8. landslides - Debris Flow
"""

# NOAA event type -> Consolidated category
NOAA_CATEGORY_MAP = {
    # Category 1: Tornadoes
    'Tornado': 'tornadoes',
    'Funnel Cloud': 'tornadoes',
    'Waterspout': 'tornadoes',

    # Category 2: Severe Thunderstorms
    'Thunderstorm Wind': 'severe_thunderstorms',
    'Hail': 'severe_thunderstorms',
    'Lightning': 'severe_thunderstorms',
    'Marine Thunderstorm Wind': 'severe_thunderstorms',
    'Marine Hail': 'severe_thunderstorms',
    'Marine Lightning': 'severe_thunderstorms',

    # Category 3: Tropical Cyclones (handled separately via IBTrACS)
    'Hurricane (Typhoon)': 'tropical_cyclones',
    'Hurricane': 'tropical_cyclones',
    'Tropical Storm': 'tropical_cyclones',
    'Tropical Depression': 'tropical_cyclones',

    # Category 4: Flooding
    'Flash Flood': 'flooding',
    'Flood': 'flooding',
    'Coastal Flood': 'flooding',
    'Storm Surge/Tide': 'flooding',
    'Lakeshore Flood': 'flooding',
    'Heavy Rain': 'flooding',  # Only if damage > 0

    # Category 5: High Winds
    'High Wind': 'high_winds',
    'Strong Wind': 'high_winds',
    'Marine High Wind': 'high_winds',
    'Marine Strong Wind': 'high_winds',
    'Dust Storm': 'high_winds',
    'Dust Devil': 'high_winds',

    # Category 6: Winter Weather
    'Blizzard': 'winter_weather',
    'Heavy Snow': 'winter_weather',
    'Winter Weather': 'winter_weather',
    'Winter Storm': 'winter_weather',
    'Ice Storm': 'winter_weather',
    'Frost/Freeze': 'winter_weather',
    'Cold/Wind Chill': 'winter_weather',
    'Extreme Cold/Wind Chill': 'winter_weather',
    'Sleet': 'winter_weather',
    'Freezing Fog': 'winter_weather',
    'Lake-Effect Snow': 'winter_weather',

    # Category 7: Extreme Heat
    'Heat': 'extreme_heat',
    'Excessive Heat': 'extreme_heat',

    # Category 8: Landslides
    'Debris Flow': 'landslides',
    'Avalanche': 'landslides',

    # Excluded from disaster overlays (climate data, not disaster events)
    'Dense Fog': None,
    'Dense Smoke': None,
    'Drought': None,  # Handled separately via USDM
    'High Surf': None,
    'Rip Current': None,
    'Sneakerwave': None,
    'Seiche': None,
    'Astronomical Low Tide': None,
    'Volcanic Ash': None,  # Handled via Smithsonian
    'Wildfire': None,  # Handled via Global Fire Atlas
    'Other': None,
}

# Category display labels
CATEGORY_LABELS = {
    'tornadoes': 'Tornadoes',
    'severe_thunderstorms': 'Severe Thunderstorms',
    'tropical_cyclones': 'Tropical Cyclones',
    'flooding': 'Flooding',
    'high_winds': 'High Winds',
    'winter_weather': 'Winter Weather',
    'extreme_heat': 'Extreme Heat',
    'landslides': 'Landslides',
}

# Category display models
CATEGORY_MODELS = {
    'tornadoes': 'track',
    'severe_thunderstorms': 'point-radius',
    'tropical_cyclones': 'track',
    'flooding': 'point-radius',
    'high_winds': 'point-radius',
    'winter_weather': 'point-radius',
    'extreme_heat': 'choropleth',
    'landslides': 'point-radius',
}


def get_disaster_category(event_type):
    """
    Get consolidated disaster category for a NOAA event type.

    Args:
        event_type: NOAA event type string

    Returns:
        Category string or None if excluded
    """
    return NOAA_CATEGORY_MAP.get(event_type)


def is_significant(row):
    """
    Determine if a NOAA storm event meets significance threshold.

    Significance criteria vary by event type. Events must either:
    - Be inherently significant (tornadoes, floods, etc.)
    - Have caused deaths or injuries
    - Have caused property/crop damage
    - Meet magnitude thresholds (hail size, wind speed, etc.)

    Args:
        row: DataFrame row with event data

    Returns:
        Boolean indicating if event is significant
    """
    event_type = row.get('event_type') or row.get('EVENT_TYPE', '')

    # Always significant categories
    always_significant = [
        'Tornado', 'Funnel Cloud', 'Waterspout',
        'Flash Flood', 'Flood', 'Coastal Flood', 'Lakeshore Flood',
        'Storm Surge/Tide', 'Blizzard', 'Debris Flow', 'Avalanche',
        'Hurricane (Typhoon)', 'Hurricane', 'Tropical Storm'
    ]
    if event_type in always_significant:
        return True

    # Significance by damage/casualties
    deaths = (row.get('deaths_direct', 0) or row.get('DEATHS_DIRECT', 0) or 0)
    injuries = (row.get('injuries_direct', 0) or row.get('INJURIES_DIRECT', 0) or 0)
    damage_prop = (row.get('damage_property', 0) or row.get('damage_property_usd', 0) or 0)
    damage_crop = (row.get('damage_crops', 0) or row.get('damage_crops_usd', 0) or 0)

    if deaths > 0 or injuries > 0:
        return True
    if damage_prop > 0 or damage_crop > 0:
        return True

    # Magnitude-based significance
    magnitude = row.get('magnitude', 0) or row.get('MAGNITUDE', 0) or 0

    if event_type == 'Hail':
        # Hail >= 1 inch is significant
        return magnitude >= 1.0

    if event_type in ['Thunderstorm Wind', 'High Wind', 'Strong Wind',
                      'Marine High Wind', 'Marine Strong Wind']:
        # Wind >= 58 mph (severe threshold) is significant
        return magnitude >= 58

    if event_type in ['Heavy Snow', 'Winter Weather', 'Lake-Effect Snow']:
        # 4+ inches of snow is significant
        return magnitude >= 4

    if event_type in ['Heat', 'Excessive Heat']:
        # Heat events are significant if explicitly recorded
        return True

    if event_type == 'Heavy Rain':
        # Heavy rain only significant if damage > 0 (already checked above)
        return False

    return False


def add_category_columns(df, event_type_col='event_type'):
    """
    Add disaster category and significance columns to a DataFrame.

    Args:
        df: DataFrame with event data
        event_type_col: Name of the event type column

    Returns:
        DataFrame with added columns:
        - disaster_category: Consolidated category ID
        - is_significant: Boolean significance flag
    """
    import pandas as pd

    df = df.copy()

    # Add category
    df['disaster_category'] = df[event_type_col].apply(get_disaster_category)

    # Add significance
    df['is_significant'] = df.apply(is_significant, axis=1)

    return df


def filter_significant_events(df):
    """
    Filter DataFrame to only significant events.

    Args:
        df: DataFrame with is_significant column

    Returns:
        Filtered DataFrame
    """
    if 'is_significant' not in df.columns:
        df = add_category_columns(df)

    return df[df['is_significant'] == True].copy()


def get_category_stats(df, event_type_col='event_type'):
    """
    Get statistics by disaster category.

    Args:
        df: DataFrame with event data
        event_type_col: Name of the event type column

    Returns:
        DataFrame with category counts
    """
    import pandas as pd

    if 'disaster_category' not in df.columns:
        df = add_category_columns(df, event_type_col)

    # Count by category
    stats = df.groupby('disaster_category').agg({
        event_type_col: 'count'
    }).reset_index()
    stats.columns = ['category', 'count']

    # Add labels
    stats['label'] = stats['category'].map(CATEGORY_LABELS)

    # Sort by count
    stats = stats.sort_values('count', ascending=False)

    return stats
