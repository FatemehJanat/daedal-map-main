from __future__ import annotations

# Shared structured registry for the live agent/API/MCP pack set.
# This is the intended single authored source for:
# - published pack order
# - free vs paid pricing lane
# - MCP facade metadata
# - public display names
# - preferred MCP routing hints
#
# Keep this module stdlib-only so runtime, site, stdio, and helper scripts can
# import it safely.

PACK_REGISTRY: dict[str, dict] = {
    "currency": {
        "display_name": "currency",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_fx_rates"),
        "mcp_prompt_allowlist": ("fx_history_for_country",),
        "mcp_name": "com.daedalmap/currency",
        "mcp_title": "DaedalMap Historical FX Rates",
        "mcp_description": "Historical daily FX rates for 100+ currencies normalized to USD, from 1940 to present. Free - no payment required. Supports daily, weekly, and monthly granularity.",
        "registry_meta": {
            "categories": ["economics", "data", "geospatial"],
            "highlights": [
                "Historical foreign exchange rate comparisons",
                "Country-level FX lookups tied to DaedalMap loc_id geography",
                "Free structured MCP access for historical currency data",
            ],
        },
        "routing": {
            "preferred_tool": "get_fx_rates",
        },
    },
    "earthquakes": {
        "display_name": "earthquakes",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_disaster_links_for_event", "get_disaster_link_chain", "search_disaster_links", "get_earthquake_events", "get_live_earthquake_events"),
        "mcp_prompt_allowlist": ("largest_earthquake_in_range", "count_disaster_events"),
        "mcp_name": "com.daedalmap/earthquakes",
        "mcp_title": "DaedalMap Earthquake Data",
        "mcp_description": "Historical earthquake events from 2150 BC to present. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical earthquake event data with structured filters",
                "Paid MCP access for earthquake counts and event rows",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "get_earthquake_events",
            "live_fallback_tool": "get_live_earthquake_events",
            "live_fallback_when": "Only when the caller explicitly asks for live/preliminary upstream data or needs time beyond canonical_available_through.",
        },
    },
    "floods": {
        "display_name": "floods",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "search_disaster_links", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/floods",
        "mcp_title": "DaedalMap Flood Events",
        "mcp_description": "Global large flood events from 1985 to present from the Dartmouth Flood Observatory Global Flood Records (CC0 public domain), including flood extent polygons, fatalities, displaced, severity, main cause, and a flood impact index, plus MODIS satellite-mapped extents from the Global Flood Database. Free - no payment required.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Global flood event records 1985-present with extent polygons",
                "Free MCP access for flood counts, fatalities, displaced, and severity",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "hurricanes": {
        "display_name": "hurricanes",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "search_disaster_links", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/hurricanes",
        "mcp_title": "DaedalMap Hurricane and Tropical Cyclone Data",
        "mcp_description": "Global tropical cyclone tracks from IBTrACS, 1842-present. Wind, pressure, and paths. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Global tropical cyclone and hurricane track records",
                "Paid MCP access for hurricane and cyclone event queries",
                "Country and basin lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "tornadoes": {
        "display_name": "tornadoes",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "search_disaster_links", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/tornadoes",
        "mcp_title": "DaedalMap Tornado Events",
        "mcp_description": "United States tornado events from 1950 to present from the NOAA Storm Prediction Center, including track paths, EF/Fujita intensity ratings, casualties, and damage estimates. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "US tornado event records 1950-present with track paths and intensity",
                "Paid MCP access for tornado counts, casualties, and damage estimates",
                "State and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "tsunamis": {
        "display_name": "tsunamis",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_disaster_links_for_event", "get_disaster_link_chain", "search_disaster_links", "get_tsunami_events"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/tsunamis",
        "mcp_title": "DaedalMap Tsunami Data",
        "mcp_description": "Historical tsunami events from 2000 BC to present. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical tsunami event data and wave-height metrics",
                "Paid MCP access for tsunami counts and event rows",
                "Country and coastal-region lookups tied to DaedalMap geography",
            ],
        },
        "routing": {
            "preferred_tool": "get_tsunami_events",
        },
    },
    "wildfires": {
        "display_name": "wildfires",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_disaster_links_for_event", "get_disaster_link_chain", "search_disaster_links", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/wildfires",
        "mcp_title": "DaedalMap Wildfire Events",
        "mcp_description": "Global, U.S., and Canada wildfire event and aggregate data, including burned area, duration, and source-aware regional routing. Paid via x402 on Base mainnet USDC. Start with an unpaid call to inspect the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Source-aware wildfire coverage across global, U.S., and Canada event lanes",
                "Paid MCP access for wildfire event discovery, burned-area questions, and regional rollups",
                "Country, province, state, and county lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "un_sdg": {
        "display_name": "UN SDG",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/un_sdg",
        "mcp_title": "DaedalMap UN Sustainable Development Goals",
        "mcp_description": "UN Sustainable Development Goal indicators across all 17 goals - poverty, health, education, gender, energy, climate, and institutions - as curated country-year panels normalized to the DaedalMap loc_id spine. Free.",
        "registry_meta": {
            "categories": ["development", "data", "geospatial"],
            "highlights": [
                "210 curated SDG indicators across all 17 goal families",
                "Normalized country-year panels on the shared DaedalMap loc_id spine",
                "Free MCP access; complements World Development Indicators and country reference data",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "world_bank_wdi": {
        "display_name": "World Bank WDI",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/world-development-indicators",
        "mcp_title": "DaedalMap World Development Indicators",
        "mcp_description": "World Bank World Development Indicators as curated country-year panels: economy, health, education, environment, debt, infrastructure, and social - normalized to the DaedalMap loc_id spine with tiered metrics. Free.",
        "registry_search_alias": "world-development-indicators",
        "registry_meta": {
            "categories": ["development", "economics", "data", "geospatial"],
            "highlights": [
                "Curated World Development Indicators across seven category sources",
                "Free MCP access for economic, health, education, and environment metrics",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "distributed_manufacturing": {
        "display_name": "Distributed Manufacturing",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/distributed-manufacturing",
        "mcp_title": "DaedalMap Distributed Manufacturing Locations",
        "mcp_description": "Global fab lab, makerspace, hackerspace, Precious Plastic, and Prusa World location data normalized to the DaedalMap loc_id spine. Free.",
        "registry_search_alias": "distributed-manufacturing",
        "registry_meta": {
            "categories": ["manufacturing", "geospatial", "data"],
            "highlights": [
                "Global registry of open manufacturing and maker facilities",
                "Free MCP access for country and facility-type location queries",
                "Point locations tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_co2": {
        "display_name": "OWID CO2",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/co2-emissions",
        "mcp_title": "DaedalMap CO2 and Greenhouse Gas Emissions",
        "mcp_description": "Our World in Data CO2 and greenhouse gas country-year metrics including totals, per-capita rates, cumulative emissions, and fuel breakdowns. Free.",
        "registry_search_alias": "co2-emissions",
        "registry_meta": {
            "categories": ["climate", "environment", "data", "geospatial"],
            "highlights": [
                "Country-year CO2 and greenhouse gas metrics from Our World in Data",
                "Free MCP access for emissions totals, per-capita rates, and cumulative metrics",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_climate_emissions": {
        "display_name": "OWID Climate and Emissions",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-climate-emissions",
        "mcp_title": "DaedalMap OWID Climate and Emissions",
        "mcp_description": "Our World in Data greenhouse gas country-year metrics: sector breakdowns (agriculture, industry, transport, buildings, electricity/heat), gas-specific totals (CO2, methane, nitrous oxide), and fossil-fuel-by-source series, 1800-present. Free.",
        "registry_search_alias": "owid-climate-emissions",
        "registry_meta": {
            "categories": ["climate", "environment", "data", "geospatial"],
            "highlights": [
                "80 country-year greenhouse gas and emissions-by-sector metrics",
                "Free MCP access for sector, gas, and fuel-source emissions breakdowns",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_education_core": {
        "display_name": "OWID Education",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-education",
        "mcp_title": "DaedalMap OWID Education",
        "mcp_description": "Our World in Data education country-year metrics: enrollment and completion rates across primary, lower-secondary, and post-secondary levels, including gender-parity indices, 1950-2100 (includes UN projections). Free.",
        "registry_search_alias": "owid-education",
        "registry_meta": {
            "categories": ["education", "development", "data", "geospatial"],
            "highlights": [
                "13 country-year education enrollment and completion metrics",
                "Free MCP access for primary, secondary, and post-secondary attainment data",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_energy_core": {
        "display_name": "OWID Energy",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-energy",
        "mcp_title": "DaedalMap OWID Energy",
        "mcp_description": "Our World in Data energy country-year metrics: renewables mix, fossil fuel and industry emissions contribution, and power-access indices, 1800-present. Free.",
        "registry_search_alias": "owid-energy",
        "registry_meta": {
            "categories": ["energy", "climate", "data", "geospatial"],
            "highlights": [
                "15 country-year energy mix and access metrics",
                "Free MCP access for renewables share, fossil-fuel contribution, and power-access indices",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_food_agriculture_nutrition": {
        "display_name": "OWID Food, Agriculture and Nutrition",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-food-agriculture-nutrition",
        "mcp_title": "DaedalMap OWID Food, Agriculture and Nutrition",
        "mcp_description": "Our World in Data food, agriculture, and nutrition country-year metrics: livestock stocks, crop production tonnage, fertilizer use, and direct human food supply by product, 1961-present. Free.",
        "registry_search_alias": "owid-food-agriculture-nutrition",
        "registry_meta": {
            "categories": ["food", "agriculture", "data", "geospatial"],
            "highlights": [
                "22 country-year food, crop, and livestock production metrics",
                "Free MCP access for cereal production, livestock stocks, and fertilizer use",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_governance_conflict": {
        "display_name": "OWID Governance and Conflict",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-governance-conflict",
        "mcp_title": "DaedalMap OWID Governance and Conflict",
        "mcp_description": "Our World in Data governance country-year metrics: V-Dem democracy indices (electoral, deliberative, egalitarian, direct-democracy), 1800-present. Free.",
        "registry_search_alias": "owid-governance-conflict",
        "registry_meta": {
            "categories": ["governance", "development", "data", "geospatial"],
            "highlights": [
                "16 country-year democracy and governance index metrics",
                "Free MCP access for V-Dem electoral, deliberative, and egalitarian democracy indices",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_health_mortality_disease": {
        "display_name": "OWID Health, Mortality and Disease",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-health-mortality-disease",
        "mcp_title": "DaedalMap OWID Health, Mortality and Disease",
        "mcp_description": "Our World in Data health country-year metrics: universal health coverage index, age-banded mortality and population shares, and disease-burden series, 1800-2100 (includes UN projections). Free.",
        "registry_search_alias": "owid-health-mortality-disease",
        "registry_meta": {
            "categories": ["health", "development", "data", "geospatial"],
            "highlights": [
                "70 country-year health, mortality, and disease-burden metrics",
                "Free MCP access for UHC service coverage and age-banded mortality data",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_labor_gender": {
        "display_name": "OWID Labor and Gender",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-labor-gender",
        "mcp_title": "DaedalMap OWID Labor and Gender",
        "mcp_description": "Our World in Data labor and gender country-year metrics: female-to-male labor force participation ratios and age-banded labor force participation, 1800-present. Free.",
        "registry_search_alias": "owid-labor-gender",
        "registry_meta": {
            "categories": ["labor", "gender", "development", "data", "geospatial"],
            "highlights": [
                "42 country-year labor-force participation and gender-gap metrics",
                "Free MCP access for age-banded and gender-ratio labor participation data",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_land_biodiversity": {
        "display_name": "OWID Land and Biodiversity",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-land-biodiversity",
        "mcp_title": "DaedalMap OWID Land and Biodiversity",
        "mcp_description": "Our World in Data land-use and biodiversity country-year metrics: agricultural land area, forest area change, and land-use category shares, 1850-present. Free.",
        "registry_search_alias": "owid-land-biodiversity",
        "registry_meta": {
            "categories": ["environment", "land_use", "data", "geospatial"],
            "highlights": [
                "27 country-year land-use and biodiversity metrics",
                "Free MCP access for agricultural land area and forest-area change data",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_population_demography": {
        "display_name": "OWID Population and Demography",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-population-demography",
        "mcp_title": "DaedalMap OWID Population and Demography",
        "mcp_description": "Our World in Data population and demography country-year metrics: population growth rate and age-banded population structure, 1800-2100 (includes UN projections). Free.",
        "registry_search_alias": "owid-population-demography",
        "registry_meta": {
            "categories": ["demographic", "development", "data", "geospatial"],
            "highlights": [
                "38 country-year population growth and age-structure metrics",
                "Free MCP access for population growth rate and age-banded demographic data",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_poverty_inequality_income": {
        "display_name": "OWID Poverty, Inequality and Income",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-poverty-inequality-income",
        "mcp_title": "DaedalMap OWID Poverty, Inequality and Income",
        "mcp_description": "Our World in Data poverty and inequality country-year metrics: number of people below international poverty lines ($1-$30/day bands) and income-decile shares, 1963-present. Free.",
        "registry_search_alias": "owid-poverty-inequality-income",
        "registry_meta": {
            "categories": ["social", "economics", "data", "geospatial"],
            "highlights": [
                "47 country-year poverty-line and income-distribution metrics",
                "Free MCP access for international poverty-line counts and income-decile shares",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "owid_water_sanitation": {
        "display_name": "OWID Water and Sanitation",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/owid-water-sanitation",
        "mcp_title": "DaedalMap OWID Water and Sanitation",
        "mcp_description": "Our World in Data water and sanitation country-year metrics: drinking-water and sanitation-facility access tiers (basic, limited, no access/open defecation), 2000-present. Free.",
        "registry_search_alias": "owid-water-sanitation",
        "registry_meta": {
            "categories": ["infrastructure", "health", "data", "geospatial"],
            "highlights": [
                "18 country-year drinking-water and sanitation access metrics",
                "Free MCP access for basic/limited/no-access drinking-water and sanitation tiers",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "un_wpp": {
        "display_name": "UN World Population Prospects",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/world-population-prospects",
        "mcp_title": "DaedalMap UN World Population Prospects",
        "mcp_description": "UN World Population Prospects country-year population, births, deaths, migration, and life expectancy metrics from 1950 through projections to 2100. Free.",
        "registry_search_alias": "world-population-prospects",
        "registry_meta": {
            "categories": ["demographic", "development", "data", "geospatial"],
            "highlights": [
                "UN WPP historical estimates and medium-variant projections",
                "Free MCP access for population, fertility, mortality, and migration metrics",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "nri": {
        "display_name": "FEMA NRI",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/fema-nri",
        "mcp_title": "DaedalMap FEMA National Risk Index",
        "mcp_description": "FEMA National Risk Index county hazard-risk layers, including baseline risk, expected annual loss, social vulnerability, resilience, and selected future scenario fields. Free.",
        "registry_search_alias": "fema-nri",
        "registry_meta": {
            "categories": ["hazard", "risk", "geospatial", "data"],
            "highlights": [
                "County-level FEMA National Risk Index hazard members",
                "Free MCP access for risk scores, expected annual loss, social vulnerability, and resilience",
                "USA county loc_id filtering for hazard-specific risk layers",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "volcanoes": {
        "display_name": "volcanoes",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_disaster_links_for_event", "get_disaster_link_chain", "search_disaster_links", "get_volcanic_activity", "get_live_volcano_events"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/volcanoes",
        "mcp_title": "DaedalMap Volcanic Activity",
        "mcp_description": "Historical volcanic eruption records from Holocene to present, including VEI and location data. Free - no payment required.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical volcanic eruption records and VEI data",
                "Free MCP access for volcanic activity queries",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "get_volcanic_activity",
            "live_fallback_tool": "get_live_volcano_events",
            "live_fallback_when": "Only when the caller explicitly asks for live/preliminary upstream data or needs time beyond canonical_available_through.",
        },
    },
    "world_factbook": {
        "display_name": "World Factbook",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/world_factbook",
        "mcp_title": "DaedalMap CIA World Factbook",
        "mcp_description": "CIA World Factbook country indicators for infrastructure, energy, demographics, and economy. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["economic", "data", "geospatial"],
            "highlights": [
                "111 CIA World Factbook indicators from 2002-2026 editions",
                "Paid MCP access for country infrastructure and economy metrics",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "worldpop": {
        "display_name": "WorldPop",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/population",
        "mcp_title": "DaedalMap Population Estimates",
        "mcp_description": "Global population estimates from WorldPop, 2000-2030, at country and sub-national admin levels. Source: WorldPop (CC-BY 4.0). Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["demographic", "data", "geospatial"],
            "highlights": [
                "WorldPop population estimates across multiple admin levels",
                "Paid MCP access for country and sub-national population queries",
                "Country and regional lookups tied to DaedalMap loc_id geography",
            ],
        },
        "registry_search_alias": "population",
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "geography": {
        "display_name": "Geography Tools",
        "kind": "tool_family",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "resolve_point", "get_boundary", "loc_id_hierarchy", "loc_id_info", "sidechain_to_admin", "admin_to_sidechain"),
        "mcp_name": "com.daedalmap/geocoding",
        "mcp_title": "DaedalMap Geography Tools (loc_id)",
        "mcp_description": "Free geography utilities built on the DaedalMap loc_id spine: resolve latitude/longitude to administrative areas, fetch boundaries and bounding boxes, walk the loc_id hierarchy, and bridge ZCTAs or tribal areas to administrative loc_ids by weighted polygon overlap. A utility tool family, not a queryable dataset pack. No payment required.",
        "registry_meta": {
            "categories": ["geospatial", "geocoding", "data"],
            "highlights": [
                "Reverse geocoding: latitude/longitude to administrative loc_id chain",
                "Boundary and bounding-box lookup for any loc_id",
                "Walk the loc_id hierarchy up and down to clip to any admin level",
                "Weighted bridges from ZCTAs and tribal areas to the admin spine",
            ],
        },
        "routing": {
            "preferred_tool": "resolve_point",
        },
        "tool_summaries": (
            {"name": "resolve_point", "summary": "lat/lon -> deepest loc_id plus the full ancestor chain"},
            {"name": "get_boundary", "summary": "loc_id -> bounding box and centroid (optional full polygon)"},
            {"name": "loc_id_hierarchy", "summary": "loc_id -> parent, ancestors, and child summary"},
            {"name": "loc_id_info", "summary": "loc_id -> name, admin level, centroid, bbox, child counts"},
            {"name": "sidechain_to_admin", "summary": "ZCTA or tribal loc_id -> ranked admin matches with overlap shares"},
            {"name": "admin_to_sidechain", "summary": "admin loc_id -> ranked overlapping ZCTAs or tribal areas"},
        ),
    },
    "reverse-geocoding": {
        "display_name": "Reverse Geocoding",
        "kind": "tool_family_alias",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "resolve_point"),
        "mcp_name": "com.daedalmap/reverse-geocoding",
        "mcp_title": "DaedalMap Reverse Geocoding (coordinates to loc_id)",
        "mcp_description": "Reverse geocoding: convert latitude/longitude into administrative areas and a hierarchical loc_id chain.",
        "registry_meta": {
            "categories": ["geospatial", "geocoding", "data"],
            "highlights": [
                "Latitude/longitude to the deepest administrative loc_id",
                "Full parent chain so you can clip to any admin level",
                "Free; maps coordinates onto the shared loc_id spine",
            ],
        },
        "routing": {"preferred_tool": "resolve_point"},
        "tool_summaries": (
            {"name": "resolve_point", "summary": "lat/lon -> deepest loc_id plus the full ancestor chain"},
        ),
    },
    "boundaries": {
        "display_name": "Boundaries",
        "kind": "tool_family_alias",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_boundary", "loc_id_info"),
        "mcp_name": "com.daedalmap/boundaries",
        "mcp_title": "DaedalMap Administrative Boundaries (loc_id to polygon)",
        "mcp_description": "Boundaries: a loc_id to its bounding box, centroid, and polygon, plus name and admin level.",
        "registry_meta": {
            "categories": ["geospatial", "boundaries", "data"],
            "highlights": [
                "Bounding box and centroid for any loc_id",
                "Full boundary polygon on request",
                "Clip or index your own grid/raster data against administrative areas",
            ],
        },
        "routing": {"preferred_tool": "get_boundary"},
        "tool_summaries": (
            {"name": "get_boundary", "summary": "loc_id -> bounding box, centroid, and optional polygon"},
            {"name": "loc_id_info", "summary": "loc_id -> name, admin level, centroid, bbox, child counts"},
        ),
    },
}


def pack_kind(pack_id: str | None) -> str:
    profile = PACK_REGISTRY.get(str(pack_id or "").strip()) or {}
    return str(profile.get("kind") or "data_pack")


def published_pack_ids() -> tuple[str, ...]:
    # Data packs only. Tool families (e.g. geography) are listed separately via
    # tool_family_ids() so existing pack/catalog/llms surfaces stay unchanged.
    return tuple(pid for pid, p in PACK_REGISTRY.items() if str(p.get("kind") or "data_pack") == "data_pack")


def tool_family_ids() -> tuple[str, ...]:
    return tuple(pid for pid, p in PACK_REGISTRY.items() if str(p.get("kind") or "data_pack") == "tool_family")


def tool_family_alias_ids() -> tuple[str, ...]:
    # Registry-discovery-only facades that route to the same geography tools under
    # their own searchable name/endpoint (the disaster-pack pattern). Excluded
    # from tool_family_ids() so the catalog still shows one geography family.
    return tuple(pid for pid, p in PACK_REGISTRY.items() if str(p.get("kind") or "data_pack") == "tool_family_alias")


def tool_family_catalog_entry(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    pricing = str(profile.get("pricing") or "free")
    return {
        "pack_id": normalized,
        "kind": "tool_family",
        "display_name": str(profile.get("display_name") or normalized.replace("_", " ")),
        "title": profile.get("mcp_title"),
        "description": profile.get("mcp_description"),
        "pricing": pricing,
        "paid_data_calls": pricing != "free",
        "tools": [dict(tool) for tool in (profile.get("tool_summaries") or ())],
    }


def tool_family_pack_detail(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    entry = tool_family_catalog_entry(normalized)
    tools = [dict(tool) for tool in (profile.get("tool_summaries") or ())]
    preferred_tool = str((profile.get("routing") or {}).get("preferred_tool") or "").strip()
    first_arguments: dict[str, object]
    start_here: list[str]
    important_rules: list[str]
    if preferred_tool == "resolve_point":
        first_arguments = {"lat": 34.0522, "lon": -118.2437}
        start_here = [
            "Call resolve_point first when you have coordinates and need a loc_id.",
            "Take the returned deepest_resolved_loc_id or any ancestor from the stack.",
            "Use that loc_id in pack filters.region_ids or with the other geography tools.",
        ]
        important_rules = [
            "These are free utility tools, not a query_dataset pack.",
            "Coordinates must be WGS84 decimal degrees.",
            "resolve_point returns the deepest loc_id plus the full ancestor chain.",
            "get_boundary returns bbox and centroid by default; request include_polygon only when you need the full geometry payload.",
            "Use sidechain_to_admin for ZIP/ZCTA or tribal-area to admin conversions. For ZCTAs, source_family is overlay_zcta and source_loc_id can be either USA-Z-10001 or 10001.",
            "Use admin_to_sidechain for reverse lookup from an admin loc_id to overlapping ZCTAs or tribal areas.",
            "Bridge tools return primary_match and overlaps. source_area_share ranks side-chain to admin results; target_area_share ranks admin to side-chain results.",
        ]
    elif preferred_tool == "get_boundary":
        first_arguments = {"loc_id": "USA-CA-037"}
        start_here = [
            "Call get_boundary when you already have a loc_id and need its extent.",
            "Use bbox and centroid for lightweight indexing and clipping.",
            "Request include_polygon only when you need the exact perimeter.",
        ]
        important_rules = [
            "These are free utility tools, not a query_dataset pack.",
            "Use canonical loc_ids such as USA, CAN-BC, or USA-CA-037.",
            "BBox/centroid is the default response shape because full polygons can be large.",
            "Use sidechain_to_admin for ZIP/ZCTA or tribal-area to admin conversions. For ZCTAs, source_family is overlay_zcta and source_loc_id can be either USA-Z-10001 or 10001.",
            "Use admin_to_sidechain for reverse lookup from an admin loc_id to overlapping ZCTAs or tribal areas.",
        ]
    else:
        first_arguments = {"loc_id": "USA-CA-037"}
        start_here = [
            "Call the preferred tool first, then expand to the other geography helpers as needed.",
        ]
        important_rules = [
            "These are free utility tools, not a query_dataset pack.",
        ]
    entry["mcp"] = {"name": profile.get("mcp_name"), "facade_url": f"/mcp/{normalized}"}
    entry["registry_meta"] = dict(profile.get("registry_meta") or {})
    entry["routing"] = dict(profile.get("routing") or {})
    entry["quick_start"] = {
        "why_it_exists": "Use the geography tool family to map coordinates and loc_ids onto the same shared loc_id spine the DaedalMap packs use.",
        "start_here": start_here,
        "first_query_template": {
            "tool": preferred_tool,
            "arguments": first_arguments,
        },
        "bridge_examples": [
            {
                "question": "What Census tracts overlap ZIP/ZCTA 10001?",
                "tool": "sidechain_to_admin",
                "arguments": {
                    "source_family": "overlay_zcta",
                    "source_loc_id": "10001",
                    "target_admin_level": "tract",
                    "limit": 10,
                },
            },
            {
                "question": "Which ZCTAs overlap this block group?",
                "tool": "admin_to_sidechain",
                "arguments": {
                    "target_loc_id": "USA-NY-061-009903-2",
                    "source_family": "overlay_zcta",
                    "target_admin_level": "block_group",
                    "limit": 10,
                },
            },
        ],
        "important_rules": important_rules,
        "starter_tools": [tool.get("name") for tool in tools if tool.get("name")],
    }
    entry["notes"] = (
        "Utility tool family on the DaedalMap loc_id spine. Free, and not a queryable "
        "dataset pack - call the listed tools directly rather than query_dataset."
    )
    return entry


def free_pack_ids() -> tuple[str, ...]:
    return tuple(pack_id for pack_id, profile in PACK_REGISTRY.items() if str(profile.get("pricing") or "") == "free")


def paid_pack_ids() -> tuple[str, ...]:
    return tuple(pack_id for pack_id, profile in PACK_REGISTRY.items() if str(profile.get("pricing") or "") != "free")


def pack_profile(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    return dict(PACK_REGISTRY.get(normalized) or {})


def pack_display_name(pack_id: str | None) -> str:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    return str(profile.get("display_name") or normalized.replace("_", " "))


def pack_registry_alias(pack_id: str | None) -> str | None:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    alias = str(profile.get("registry_search_alias") or "").strip()
    return alias or None


def pack_mcp_server_profile(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    return {
        "name": profile.get("mcp_name"),
        "title": profile.get("mcp_title"),
        "description": profile.get("mcp_description"),
        "pricing": profile.get("pricing"),
        "registry_meta": dict(profile.get("registry_meta") or {}),
    }


def pack_routing_hints() -> dict[str, dict[str, str]]:
    hints: dict[str, dict[str, str]] = {}
    for pack_id, profile in PACK_REGISTRY.items():
        routing = profile.get("routing")
        if isinstance(routing, dict) and routing:
            hints[pack_id] = dict(routing)
    return hints


def pack_tool_allowlists() -> dict[str, set[str]]:
    allowlists: dict[str, set[str]] = {}
    for pack_id, profile in PACK_REGISTRY.items():
        raw = profile.get("mcp_tool_allowlist") or ()
        allowlists[pack_id] = {str(tool) for tool in raw if str(tool).strip()}
    return allowlists


def pack_prompt_allowlists() -> dict[str, set[str]]:
    allowlists: dict[str, set[str]] = {}
    for pack_id, profile in PACK_REGISTRY.items():
        raw = profile.get("mcp_prompt_allowlist") or ()
        allowlists[pack_id] = {str(prompt) for prompt in raw if str(prompt).strip()}
    return allowlists
