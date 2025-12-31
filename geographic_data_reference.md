# Geographic Data Reference

Reference guide for data sources, geographic frameworks, and edge cases.

---

## Alternative Geographic Frameworks

Beyond the standard admin hierarchy (country > state > county), other frameworks exist:

### Statistical and Functional Regions
- **Metropolitan Statistical Areas (MSAs)**: Cross city/county boundaries, defined by economic ties
- **OECD Functional Urban Areas**: Globally standardized metropolitan definitions
- **Eurostat NUTS Regions**: Hierarchical system for Europe

### Grid-Based Systems
- **H3 Hexagonal Grids**: Uber's hierarchical geospatial indexing
- **Lat/Long Grid Cells**: Climate data (1x1 or 0.5x0.5 degree cells)
- **MGRS/UTM Zones**: Military Grid Reference System

### Natural Boundaries
- **Watershed/River Basins**: Water resource and environmental data
- **Ecoregions/Biomes**: Biodiversity and conservation
- **Climate Zones**: Koppen climate classification

### Supranational Regions
- **UN Geoscheme**: "Western Africa", "Southern Asia"
- **Trade Blocs**: USMCA, MERCOSUR, ASEAN, EU
- Already implemented in conversions.json

---

## Edge Cases and Special Geographies

Data that doesn't fit standard hierarchies:

### Transboundary Phenomena
- Air quality/pollution (doesn't respect borders)
- Ocean data and maritime boundaries
- Cross-border river systems (Mekong, Danube)

### Special Jurisdictions
- Indigenous/tribal lands (may overlap multiple admin units)
- Special economic zones
- Exclusive Economic Zones (EEZ) in oceans
- Disputed territories
- Extraterritorial areas (embassies, military bases)

### Point-Based Data
- Weather stations
- Seismic monitoring stations
- Shipping routes

---

## Geometry Sources

### GADM (Current Source)
- **URL**: gadm.org
- **Coverage**: Admin boundaries for every country, levels 0-5
- **Format**: GeoPackage, Shapefiles
- **License**: Free for non-commercial, attribution required
- **Notes**: Used for process_gadm.py

### Natural Earth
- **URL**: naturalearthdata.com
- **Coverage**: Admin boundaries, populated places, physical features
- **Scales**: 1:10m (detailed), 1:50m (medium), 1:110m (small)
- **License**: Public domain
- **Best for**: Simplified country borders, physical features

### geoBoundaries
- **URL**: geoboundaries.org
- **Coverage**: Open admin boundaries, simplified versions
- **Format**: GeoJSON, Shapefiles, API
- **License**: Fully open (better than GADM for commercial)
- **Notes**: Good alternative, has pre-simplified versions

### US Census TIGER/Line
- **URL**: census.gov/geographies/mapping-files.html
- **Coverage**: States, counties, ZCTAs, census tracts, blocks
- **License**: Public domain
- **Notes**: Most detailed US boundaries, updated annually

### Country-Specific Sources
- **UK**: ONS Geography Portal (geoportal.statistics.gov.uk)
- **Canada**: Statistics Canada Boundary Files
- **Australia**: ABS (Australian Bureau of Statistics)
- **EU**: Eurostat GISCO (ec.europa.eu/eurostat/web/gisco)

### Humanitarian Data
- **HDX**: data.humdata.org - Often more current for developing nations

---

## Data Sources - Free vs Paid

### Always Free (Use These)

**Government Statistical Agencies:**
- US Census Bureau - public domain
- BLS (Bureau of Labor Statistics)
- NOAA/NASA - public domain
- USGS - public domain
- EIA (Energy Information Administration)
- Most national statistical offices (Eurostat, Statistics Canada, etc.)
- Central banks (Federal Reserve, ECB, etc.)

**International Organizations:**
- World Bank Open Data
- IMF Data
- UN agencies (UNDP, WHO, FAO)
- OECD Data (core data free)

**Climate/Environmental:**
- NOAA Climate Data
- NASA Earth Data
- Copernicus (EU Earth observation)
- Landsat (USGS) and Sentinel (ESA)

### Avoid (Paid/Restricted)

**Financial Data:**
- Bloomberg Terminal ($20k+/year)
- Refinitiv (Thomson Reuters)
- S&P Capital IQ
- FactSet

**Commercial Data:**
- Nielsen data
- Experian/Equifax consumer data
- CoreLogic real estate
- Esri demographic layers (repackaged census data)

**Energy (Paid):**
- S&P Global Platts
- Wood Mackenzie
- IHS Markit

**Rule of thumb**: If it requires a "sales inquiry" or "demo", it's paid.

### Licensing Notes

**GADM**: Free for non-commercial. For commercial, technically need license.

**OpenStreetMap**: ODbL license - requires attribution and share-alike.

---

## Bulk Download Tips

**Look for these on data portals:**
1. "Bulk download" or "Data dump" links (often in footer)
2. FTP servers (many government sites still use these)
3. "API" pages often link to bulk files
4. Check robots.txt for bulk data locations

**For SDG data:**
- Use World Bank or OECD bulk downloads over UN's interface
- API: `https://api.worldbank.org/v2/sdg/Goal/1/Target/1.1/Indicator/1.1.1?format=json`
- Better: Use bulk CSV/Excel files at data.worldbank.org

---

*Last Updated: 2025-12-21*

NOTES ON CONVERSIONS.JSON, compare against the metadata we have.  Also compare and see how to integrate with C:\Users\Bryan\Desktop\county-map\optimized_prompting_strategy.md


Canonical country metadata object (single source of truth)

Right now you have:

iso_country_codes

iso_2_to_3

income groups

regions

admin levels

These are all parallel. I’d add a canonical per-country metadata block so you can attach attributes without hunting across maps.

Add
"countries": {
  "USA": {
    "name": "United States",
    "iso2": "US",
    "capital": "Washington, DC",
    "region": "North_America",
    "income_group": "High_Income",
    "admin_levels_supported": 6,
    "uses_states": true,
    "osm_admin_level_mapping": {
      "1": 4,
      "2": 6,
      "3": 8
    }
  }
}


Why

Lets you answer questions like “does this country support admin_level 4?”

Lets UI logic branch cleanly (Leaflet popups, filters, chat interpretation)

Avoids hardcoding assumptions elsewhere

2. Explicit admin_level → OSM/GADM mapping

You already imply this, but making it explicit saves pain later.

Add
"admin_level_mappings": {
  "OSM": {
    "USA": {
      "1": 4,
      "2": 6,
      "3": 8,
      "4": 10
    },
    "FRA": {
      "1": 4,
      "2": 6,
      "3": 7,
      "4": 8,
      "5": 9
    }
  },
  "GADM": {
    "default": {
      "1": "GID_1",
      "2": "GID_2",
      "3": "GID_3"
    }
  }
}


Why

OSM admin levels are not consistent

This prevents subtle bugs when swapping data sources

Very useful for spatial queries + auto labeling

3. Language / localization metadata (lightweight)

You don’t need full i18n, but a minimal layer helps.

Add
"country_languages": {
  "CAN": {
    "official": ["en", "fr"],
    "display_preference": "bilingual"
  },
  "BEL": {
    "official": ["nl", "fr", "de"]
  },
  "CHE": {
    "official": ["de", "fr", "it", "rm"]
  }
}


Why

Explains why admin names vary

Enables future localized labels

Avoids incorrect singular naming assumptions

4. Capital / centroid fallbacks (beyond limited_geometry)

You already have limited_geometry_countries. I’d generalize this into a country point fallback strategy.

Add
"country_point_strategy": {
  "default": "capital",
  "fallback_order": ["capital", "centroid", "bbox_center"],
  "exceptions": {
    "ZAF": "capital",
    "BOL": "centroid",
    "CHE": "capital"
  }
}


Why

Avoids special-case logic

Cleanly explains why a point is chosen

Useful for map zoom logic and clustering

5. Supranational entities (EU, UN, regions-as-entities)

You already list memberships, but you don’t define them as entities.

Add
"supranational_entities": {
  "EU": {
    "name": "European Union",
    "type": "political_union",
    "has_geometry": true
  },
  "UN": {
    "name": "United Nations",
    "type": "intergovernmental"
  }
}


Why

Lets you treat the EU as a selectable “region”

Enables region-level stats or geometry overlays

Cleaner than implicit grouping-only logic

6. Time-sensitivity metadata (quiet but powerful)

Some of your data will change (income groups, memberships).

Add
"temporal_metadata": {
  "income_groups": {
    "source": "World Bank",
    "last_updated": "2024",
    "update_frequency": "annual"
  },
  "OECD": {
    "last_updated": "2023"
  }
}


Why

Prevents silent data rot

Makes audits and updates trivial

Helps when users ask “is this current?”

7. Synonym & fuzzy-match helpers (for chat + search)

You already have region_aliases. Extend this idea to countries.

Add
"country_aliases": {
  "USA": ["United States of America", "US", "U.S.", "America"],
  "CIV": ["Ivory Coast", "Côte d’Ivoire"],
  "KOR": ["South Korea", "Republic of Korea"],
  "PRK": ["North Korea", "DPRK"]
}


Why

Hugely improves user input parsing

Reduces brittle string comparisons

Pairs well with chat interpretation

8. Validation / integrity helpers (developer-friendly)

This is subtle but extremely useful.

Add
"validation": {
  "required_iso3": true,
  "enforce_uppercase": true,
  "allow_duplicates_across_groups": true
}


Or even:

"_schema_version": "1.1.0"


Why

Makes refactors safer

Lets you evolve this without breaking consumers

Signals “this is a real data model”

9. Optional: geopolitical sensitivity flags

Only if relevant, but useful for display logic.

"country_flags": {
  "PSE": {
    "disputed": true,
    "note": "Status varies by international recognition"
  },
  "TWN": {
    "disputed": true
  }
}

1. Language Support (Your Request)
json
"language_codes": {
  "_description": "ISO 639-1 language codes with native names and scripts",
  "_format": "code: [English name, Native name, Writing system]",
  
  "ar": ["Arabic", "العربية", "Arabic script"],
  "zh": ["Chinese", "中文", "Hanzi (Simplified/Traditional)"],
  "en": ["English", "English", "Latin"],
  "fr": ["French", "Français", "Latin"],
  "de": ["German", "Deutsch", "Latin"],
  "hi": ["Hindi", "हिन्दी", "Devanagari"],
  "id": ["Indonesian", "Bahasa Indonesia", "Latin"],
  "it": ["Italian", "Italiano", "Latin"],
  "ja": ["Japanese", "日本語", "Kanji/Hiragana/Katakana"],
  "ko": ["Korean", "한국어", "Hangul/Hanja"],
  "pt": ["Portuguese", "Português", "Latin"],
  "ru": ["Russian", "Русский", "Cyrillic"],
  "es": ["Spanish", "Español", "Latin"],
  "sw": ["Swahili", "Kiswahili", "Latin"],
  "th": ["Thai", "ไทย", "Thai script"],
  "tr": ["Turkish", "Türkçe", "Latin"],
  "vi": ["Vietnamese", "Tiếng Việt", "Latin"],
  
  "regional": {
    "ar-EG": ["Egyptian Arabic", "اللهجة المصرية", "Arabic script"],
    "zh-CN": ["Simplified Chinese", "简体中文", "Simplified Hanzi"],
    "zh-TW": ["Traditional Chinese", "繁體中文", "Traditional Hanzi"],
    "en-GB": ["British English", "English", "Latin"],
    "en-US": ["American English", "English", "Latin"],
    "es-419": ["Latin American Spanish", "Español latinoamericano", "Latin"],
    "pt-BR": ["Brazilian Portuguese", "Português brasileiro", "Latin"],
    "pt-PT": ["European Portuguese", "Português europeu", "Latin"]
  }
},

"country_languages": {
  "_description": "Official and major languages by country (ISO3 -> [primary, other major])",
  "USA": ["en", "es"],
  "CAN": ["en", "fr"],
  "MEX": ["es"],
  "GBR": ["en"],
  "FRA": ["fr"],
  "DEU": ["de"],
  "ITA": ["it"],
  "ESP": ["es", "ca", "eu", "gl"],
  "RUS": ["ru"],
  "CHN": ["zh"],
  "IND": ["hi", "en"],
  "JPN": ["ja"],
  "KOR": ["ko"],
  "IDN": ["id"],
  "BRA": ["pt"],
  "ZAF": ["en", "af", "zu", "xh"],
  "NGA": ["en"],
  "EGY": ["ar"],
  "SAU": ["ar"],
  "TUR": ["tr"],
  "IRN": ["fa"],
  "ISR": ["he", "ar"],
  "PAK": ["ur", "en"],
  "BGD": ["bn"],
  "PHL": ["fil", "en"]
},
2. Currency & Economic Data
json
"country_currencies": {
  "_description": "Primary currency by country",
  "_format": "ISO3: [Currency code, Symbol, Currency name]",
  
  "USA": ["USD", "$", "US Dollar"],
  "GBR": ["GBP", "£", "British Pound"],
  "EUR": ["EUR", "€", "Euro"],
  "JPN": ["JPY", "¥", "Japanese Yen"],
  "CHN": ["CNY", "¥", "Chinese Yuan"],
  "IND": ["INR", "₹", "Indian Rupee"],
  "RUS": ["RUB", "₽", "Russian Ruble"],
  "BRA": ["BRL", "R$", "Brazilian Real"],
  "ZAF": ["ZAR", "R", "South African Rand"],
  "AUS": ["AUD", "A$", "Australian Dollar"],
  "CAN": ["CAD", "C$", "Canadian Dollar"],
  "CHE": ["CHF", "CHF", "Swiss Franc"],
  "MEX": ["MXN", "$", "Mexican Peso"],
  "KOR": ["KRW", "₩", "South Korean Won"],
  "TUR": ["TRY", "₺", "Turkish Lira"],
  "SAU": ["SAR", "﷼", "Saudi Riyal"],
  "ARE": ["AED", "د.إ", "UAE Dirham"]
},

"eurozone": {
  "_description": "Countries using the Euro",
  "countries": ["AUT", "BEL", "CYP", "EST", "FIN", "FRA", "DEU", "GRC", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "PRT", "SVK", "SVN", "ESP"]
},
3. Time Zones & Regional Time Data
json
"timezone_groups": {
  "_description": "Major timezone groupings",
  
  "North_America_TZ": {
    "code": "NA_TZ",
    "_note": "North American time zones",
    "countries": ["USA", "CAN", "MEX"],
    "zones": ["EST", "CST", "MST", "PST", "AKST", "HST"]
  },
  
  "European_TZ": {
    "code": "EU_TZ",
    "_note": "European time zones (excluding Russia)",
    "countries": ["GBR", "IRL", "PRT", "ESP", "FRA", "DEU", "ITA", "NLD", "BEL", "CHE", "AUT", "DNK", "SWE", "NOR", "FIN", "POL", "CZE", "SVK", "HUN", "ROU", "BGR", "GRC"],
    "zones": ["GMT", "CET", "EET", "WET"]
  },
  
  "Asia_Pacific_TZ": {
    "code": "AP_TZ",
    "_note": "Asia-Pacific time zones",
    "countries": ["CHN", "JPN", "KOR", "TWN", "HKG", "MAC", "MNG", "AUS", "NZL", "SGP", "MYS", "PHL", "IDN", "THA", "VNM", "KHM", "LAO"],
    "zones": ["CST", "JST", "KST", "AEST", "NZST", "SGT", "ICT", "PHT"]
  }
},

"daylight_saving_countries": {
  "_description": "Countries observing DST/Summer Time",
  "major": ["USA", "CAN", "MEX", "GBR", "IRL", "PRT", "ESP", "FRA", "DEU", "ITA", "POL", "CZE", "AUT", "CHE", "SWE", "NOR", "FIN", "AUS", "NZL", "CHL"],
  "none": ["CHN", "JPN", "KOR", "IND", "IDN", "THA", "VNM", "PHL", "SGP", "MYS", "ZAF", "EGY", "SAU", "ARE", "TUR"]
},
4. Population & Demographics Metadata
json
"population_categories": {
  "_description": "Population size categories for quick filtering",
  
  "megacountries": {
    "_note": "100M+ population",
    "threshold": 100000000,
    "countries": ["CHN", "IND", "USA", "IDN", "PAK", "BRA", "NGA", "BGD", "RUS", "MEX", "JPN", "ETH", "PHL", "EGY", "VNM", "COD", "TUR", "IRN", "DEU", "THA"]
  },
  
  "large_countries": {
    "_note": "50-100M population",
    "threshold": 50000000,
    "countries": ["GBR", "FRA", "ITA", "TZA", "ZAF", "KOR", "ESP", "COL", "ARG", "DZA", "SDN", "UKR", "UGA", "IRQ", "POL", "CAN", "MAR", "SAU", "UZB", "PER", "MYS", "VNM"]
  },
  
  "small_countries": {
    "_note": "Under 1M population",
    "threshold": 1000000,
    "countries": ["CYP", "LUX", "MLT", "ISL", "BHR", "BRN", "MDV", "MCO", "SMR", "LIE", "SYC", "ATG", "DMA", "GRD", "KNA", "LCA", "VCT", "PLW", "NRU", "TUV", "KIR", "MHL", "FSM", "AND", "VAT"]
  }
},
5. Geographic & Climate Metadata
json
"geographic_features": {
  "_description": "Major geographic characteristics",
  
  "island_nations": {
    "_note": "Countries that are primarily islands",
    "countries": ["AUS", "NZL", "JPN", "PHL", "IDN", "GBR", "IRL", "ISL", "CYP", "MLT", "SGP", "SYC", "MUS", "MDV", "FJI", "PNG", "SLB", "VUT", "WSM", "TON", "KIR", "TUV", "MHL", "PLW", "FSM", "NRU", "COK", "NIU"]
  },
  
  "landlocked": {
    "_note": "Countries without ocean access",
    "countries": ["AFG", "AND", "ARM", "AUT", "AZE", "BLR", "BOL", "BWA", "BFA", "BDI", "CAF", "TCD", "CZE", "ETH", "HUN", "KAZ", "KGZ", "LAO", "LSO", "MWI", "MLI", "MDA", "MNG", "NPL", "NER", "MKD", "PRY", "RWA", "SRB", "SVK", "SSD", "SWZ", "TJK", "TKM", "UGA", "UZB", "ZMB", "ZWE"]
  },
  
  "arctic_circle": {
    "_note": "Countries extending into Arctic Circle",
    "countries": ["CAN", "USA", "RUS", "NOR", "SWE", "FIN", "ISL", "GRL"]
  },
  
  "equatorial": {
    "_note": "Countries on or near equator",
    "countries": ["ECU", "COL", "BRA", "GAB", "COD", "UG", "KEN", "SOM", "IDN", "MYS", "SGP"]
  }
},

"climate_zones": {
  "_description": "Primary climate classifications",
  
  "tropical": {
    "_note": "Hot and humid year-round",
    "countries": ["BRA", "COL", "VEN", "GHA", "NGA", "KEN", "TZA", "IDN", "PHL", "THA", "VNM", "MYS", "SGP"]
  },
  
  "temperate": {
    "_note": "Four distinct seasons",
    "countries": ["USA", "CAN", "CHN", "JPN", "KOR", "GBR", "FRA", "DEU", "ITA", "ESP", "AUS", "NZL", "ARG", "CHL", "ZAF"]
  },
  
  "arid_desert": {
    "_note": "Dry, desert climates",
    "countries": ["SAU", "ARE", "QAT", "OMN", "KWT", "BHR", "DZA", "LBY", "EGY", "MRT", "NAM", "BOT", "AUS", "MEX", "PER", "CHL"]
  },
  
  "polar": {
    "_note": "Cold, Arctic/Antarctic climates",
    "countries": ["CAN", "RUS", "USA", "NOR", "SWE", "FIN", "ISL"]
  }
},
6. Development & Infrastructure Metadata
json
"development_indicators": {
  "_description": "Quick reference development indicators",
  
  "high_hdi": {
    "_note": "Very High Human Development (HDI > 0.8)",
    "countries": ["NOR", "CHE", "IRL", "DEU", "AUS", "ISL", "SWE", "NLD", "DNK", "FIN", "SGP", "GBR", "BEL", "NZL", "CAN", "USA", "JPN", "KOR", "ISR", "LUX", "AUT", "FRA", "ESP", "ITA", "CZE", "GRC", "POL", "EST", "LTU", "SVN"]
  },
  
  "digital_advanced": {
    "_note": "Highly digitized societies",
    "countries": ["DNK", "FIN", "SWE", "NOR", "NLD", "SGP", "KOR", "USA", "GBR", "DEU", "CHE", "AUS", "NZL", "CAN", "JPN", "EST", "ISL"]
  },
  
  "renewable_leaders": {
    "_note": "High renewable energy usage",
    "countries": ["ISL", "NOR", "SWE", "FIN", "DNK", "URU", "CRI", "NZL", "AUT", "BRA", "CAN", "PRT", "ESP", "DEU"]
  }
},
7. Historical & Cultural Context
json
"historical_regions": {
  "_description": "Historical/cultural region names for context",
  
  "Balkan": {
    "countries": ["ALB", "BIH", "BGR", "HRV", "GRC", "KOS", "MNE", "MKD", "ROU", "SRB", "SVN", "TUR"],
    "alternate_names": ["Balkans", "Southeastern Europe"]
  },
  
  "Scandinavia": {
    "countries": ["DNK", "NOR", "SWE"],
    "alternate_names": ["Nordic Countries", "Scandinavian Peninsula"]
  },
  
  "Middle_East_Historical": {
    "countries": ["EGY", "IRN", "IRQ", "ISR", "JOR", "LBN", "PSE", "SYR", "TUR", "SAU", "YEM"],
    "alternate_names": ["Levant", "Mashriq", "Fertile Crescent"]
  },
  
  "Indochina": {
    "countries": ["KHM", "LAO", "MMR", "THA", "VNM"],
    "alternate_names": ["Mainland Southeast Asia"]
  },
  
  "West_Indies": {
    "countries": ["ATG", "BHS", "BRB", "CUB", "DMA", "DOM", "GRD", "HTI", "JAM", "KNA", "LCA", "VCT", "TTO"],
    "alternate_names": ["Caribbean Islands", "Antilles"]
  }
},
8. International Organization Memberships
json
"organization_memberships": {
  "_description": "Additional international organizations",
  
  "UNSC_permanent": {
    "_note": "UN Security Council permanent members",
    "countries": ["CHN", "FRA", "RUS", "GBR", "USA"]
  },
  
  "G77": {
    "_note": "Group of 77 developing nations",
    "countries": ["AFG", "AGO", "ARG", "BGD", "BRA", "CHN", "EGY", "IND", "IDN", "MEX", "NGA", "PAK", "SAU", "ZAF"]  // And 63 others
  },
  
  "Non_Aligned_Movement": {
    "_note": "NAM - not formally aligned with major power blocs",
    "countries": ["IND", "IDN", "EGY", "IRN", "CUB", "ZAF", "MYS", "VEN", "ALG", "SGP"]
  },
  
  "Pacific_Islands_Forum": {
    "countries": ["AUS", "NZL", "FJI", "PNG", "WSM", "TON", "KIR", "VUT", "FSM", "MHL", "NRU", "PLW", "SLB", "TUV", "COK", "NIU"]
  }
},
9. Key Missing Countries from Your country_level_names
json
// Add these to your existing country_level_names:
{
  "NPL": {  // Nepal
    "1": ["provinces", "pradesh"],
    "2": ["districts", "jilla"],
    "3": ["municipalities", "nagarpalika", "rural municipalities", "gaunpalika"],
    "4": ["wards"]
  },
  
  "LKA": {  // Sri Lanka
    "1": ["provinces", "palata"],
    "2": ["districts", "distrikkaya"],
    "3": ["divisions", "divisional secretariats"],
    "4": ["grama niladhari divisions", "villages"]
  },
  
  "MMR": {  // Myanmar
    "1": ["states", "regions", "pyi-neh"],
    "2": ["districts", "kayaing"],
    "3": ["townships", "myone"],
    "4": ["wards", "villages", "ywa"]
  },
  
  "KAZ": {  // Kazakhstan
    "1": ["regions", "oblystar", "cities of republican significance"],
    "2": ["districts", "audandar"],
    "3": ["cities of regional significance", "rural districts"]
  },
  
  "UKR": {  // Ukraine
    "1": ["oblasts", "regions", "cities with special status"],
    "2": ["raions", "districts"],
    "3": ["hromadas", "territorial communities"],
    "4": ["settlements", "villages"]
  }
}
10. Smart Query Synonyms
json
"query_synonyms": {
  "_description": "Common user query terms mapping to technical terms",
  
  "admin_level_synonyms": {
    "country": ["nation", "sovereign state", "independent state"],
    "state": ["province", "region", "oblast", "prefecture", "department"],
    "county": ["district", "borough", "parish", "shire", "raion"],
    "city": ["town", "municipality", "commune", "urban area"],
    "village": ["hamlet", "settlement", "locality", "rural area"],
    "neighborhood": ["ward", "quarter", "district", "sector", "barrio"]
  },
  
  "region_synonyms": {
    "developing": ["Third World", "Global South", "emerging economies"],
    "developed": ["First World", "Global North", "industrialized", "advanced economies"],
    "middle east": ["MENA", "Arab world", "Levant", "Gulf region"],
    "southeast asia": ["ASEAN region", "Indochina", "Maritime Southeast Asia"],
    "latin america": ["Hispanic America", "Ibero-America", "Spanish America"],
    "caribbean": ["West Indies", "Antilles", "Caribbean islands"]
  }
}

This is a goldmine of ideas. The notes suggest a much richer metadata model, and conversions.json is definitely getting too large to manage. Looking at the un_sdg pattern (reference.json alongside metadata.json), here's what I'd recommend: Proposed Architecture: Split by Domain

mapmover/
  conversions.json              # LEAN: Just core lookups
  reference/
    admin_levels.json           # Level names + synonyms (what we just built)
    country_metadata.json       # Canonical per-country info
    geographic_features.json    # Islands, landlocked, climate zones
    languages.json              # Language codes + country languages
    development.json            # Income groups, HDI, currencies
    query_synonyms.json         # For chat/LLM interpretation
What stays in conversions.json (core lookups):
iso_country_codes - quick name lookups
iso_2_to_3 - code conversion
regional_groupings - G20, EU, etc.
region_aliases - "Europe" -> "WHO_European_Region"
What moves to reference files:
File	Contents	Used By
admin_levels.json	Level names + synonyms by country	Popup display, chat interpretation
country_metadata.json	Capital, languages, max_depth, income, OSM mapping	Popup enrichment, validation
geographic_features.json	Island nations, landlocked, climate zones	Chat context, filtering
development.json	Income groups, currencies, HDI	Querying, grouping
languages.json	ISO language codes, country languages	Localization, display
query_synonyms.json	User term -> technical term mappings	Chat interpretation
Benefits:
Faster startup - Only load what's needed
Easier maintenance - Update currencies without touching admin levels
LLM context - Include relevant reference file in prompts
Schema evolution - Version each file independently
Matches un_sdg pattern - reference.json concept scales
Example: country_metadata.json

{
  "_schema_version": "1.0.0",
  "_last_updated": "2025-01",
  "USA": {
    "name": "United States",
    "iso2": "US",
    "capital": "Washington, D.C.",
    "max_admin_level": 6,
    "languages": ["en", "es"],
    "currency": "USD",
    "income_group": "high",
    "region": "North_America",
    "osm_admin_mapping": {"1": 4, "2": 6, "3": 8}
  }
}
Want me to start splitting conversions.json into this structure? I'd begin with moving country_level_names to reference/admin_levels.json since we just built that.