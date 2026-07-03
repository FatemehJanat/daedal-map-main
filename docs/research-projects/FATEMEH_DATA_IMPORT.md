# Fatemeh Data Import

> Public research-project log. Historical local paths, private converter names,
> cloud publication notes, and dated status entries are preserved for
> provenance; they are not prerequisites for using the public runtime.

## Project Direction (updated 2026-05-19)

This project has not officially started yet. Data collection is intentionally broad so the
datasets are useful as the question evolves over the next few months.

**Core research question:** What areas are disadvantaged and need better shelter access?

**Mode split (added 2026-05-30):** The project bisects across Research and Ops mode.

- The disadvantaged-area-shelter-access *analysis* (CEJST + NRI + NSS
  snapshot + EPA SLD joined to answer "where are shelter deserts?") is
  **Research mode** — cross-domain, historical, evidence-building.
- The address-entry shelter-finder ("show me open shelters within 30
  or 60 minutes of this address, alert me when a threat approaches")
  is **Ops mode**. It is documented as the canonical Address-Scoped
  Shelter Watch worked example in
  the historical Ops shelter-watch design.
  The FEMA NSS OpenShelters API and the isochrone routing capability
  are now in Tier 1 of the
  the historical Ops feed-priority list
  and the Operational Capabilities subsection there.

The Pattern A (live API facade) vs Pattern B (static snapshot)
distinction this doc established for NSS Shelters is the bridge: Ops
mode uses Pattern A; Research mode uses Pattern B; same FEMA source,
different runtime path.

**Two shelter product shapes (current design):**

1. `Pattern B` static shelter snapshot for Research mode
   - import the full shelter inventory as point data
   - attach tract/county context so it can be compared against `CEJST`,
     `NRI`, wildfire history, and later `EPA Smart Location`
   - use it to map shelter concentration vs scarcity and to support derived
     road-access metrics such as `nearest_shelter_drive_minutes`,
     `shelters_within_30min`, and `shelters_within_60min`
2. `Pattern A` live open-shelter runtime for Ops mode
   - query FEMA `OpenShelters` live at request time
   - answer operational questions like "is a shelter open near me right now?"
     and "which open shelters can I reach within 30 or 60 minutes?"

The same shelter family supports both products, but the runtime contracts are
different. `Pattern B` is the next implementation target because it unlocks the
core Fatemeh analysis and the first round of shelter-access calculations.

## Live Freshness Check (2026-06-25, side-check while other work ran)

Quick check: does the local `Fatemeh Data` folder have anything new, and
has anything newer dropped upstream since the 2026-04-30 backfill sweep?

- **Local folder**: confirmed actual path is
  `C:\Users\bryan\Desktop\Fatemeh Data\Data\` (not `fatemah` as an earlier
  note in this doc said - that correction was itself wrong, or the folder
  was renamed back). Every file is timestamped Apr 14 - nothing added
  since the original drop.
- **FEMA NRI**: live ArcGIS service (`National_Risk_Index_Counties`)
  still reports 3,232 counties - exact match to the v1.20 (Dec 2025)
  already backfilled. No newer version has shipped.
- **NSS Shelters**: live counts have grown modestly since the April
  check - 71,538 closed / 71,524 total shelter locations, vs 71,362 /
  71,354 in April (~170-180 row growth, consistent with an operational
  registry, not a new release). **Actionable**: since the Pattern B
  shelter import still hasn't happened, pull a live snapshot at import
  time instead of using the April static CSV - same effort, ~0.25%
  fresher data, and establishes the habit of always importing live
  rather than the folder snapshot for this source going forward.
  So: no surprise new dataset, but one concrete actionable finding - when
  we do import shelters, grab a live snapshot instead of the April CSV.
  Treat the folder copy as fallback / historical insurance, not the
  default import source.
- **CEJST**: no recheck needed, CEQ stopped publishing after v2.0.
- **ClimRR**: not re-checked against the live Argonne portal this pass -
  the April backfill already grabbed the richer master tables; a fresh
  diff would be a separate, bigger effort if wanted.

## Status Note (2026-06-25)

Current practical status for the Fatemeh workflow:

- `NRI` is already live in the normal published app lane as the hazard-split
  `nri` pack. The wildfire member already combines baseline NRI fields with
  future scenario fields where available.
- `CEJST` has moved materially forward. The main tract-routing / county-bridge
  runtime issues were fixed, the geometry spine is now aligned for the hosted
  cases we care about, and the main published queries are no longer showing the
  earlier hard routing failures. Treat CEJST as substantially usable now, with
  any remaining work being QA polish / synonym coverage rather than a core
  ingest blocker.
- existing wildfire event/history layers are already available and should be
  used in the research framing alongside NRI wildfire risk, not deferred until
  a later data-collection pass.
- the next real data dependency for the core research question is still
  `NSS Shelters Pattern B` (static shelter snapshot import). Without shelter
  points, the shelter-access analysis is still incomplete even with CEJST and
  NRI live.
- `EPA Smart Location` remains useful context for built-environment /
  accessibility analysis, but it is secondary to getting shelters imported.
- road-network work should now proceed because the shelter snapshot is in place.
  The design target is not tract-level routing; it is:
  - address-level runtime shelter search for Ops mode
  - California block-group precompute for Research mode
  - metrics such as `nearest_shelter_drive_minutes`, `shelters_within_30min`,
    and `shelters_within_60min`
- Ops input normalization should reuse the existing local geometry tools:
  - address or lat/lon -> canonical point-to-loc_id stack
  - ZIP -> ZCTA lookup plus representative-point normalization back to block group
  - county/state -> coarse region aggregation unless the user supplies a finer origin
- the implementation should stay generic: admin level -> representative
  coordinate(s) -> routing computation -> rolled-up accessibility metrics, so
  the same system can later support hospitals, cooling centers, grocery access,
  and other destination families beyond shelters
- do not optimize for easiest setup. Favor the stack that best supports the
  final user experience, even if initial build complexity is higher.
- practical interpretation: we have now removed most of the "can the current
  packs answer the right tract/county questions?" uncertainty. The biggest gap
  is no longer CEJST packaging or shelter import; it is the downstream
  road-network travel-time system built on top of them.

### Desktop Resume Note (2026-06-25)

Current handoff state for moving this work from laptop to desktop:

- reusable private-repo road-access scaffolding now exists under
  `county-map-private/build/data_prep/road_access/`
- prep + calculator + lookup paths are already wired:
  - `prepare_access_inputs.py`
  - `run_access_calculator.py`
  - `lookup_precomputed_access.py`
  - `road_access/` helper package
- local smoke validation already succeeded for the non-router path:
  - California `admin_4` prep found `25,586` block-group origins
  - California NSS shelter extract found `6,600` destinations
  - checkpointed sample calculator runs completed with the debug provider
  - point / ZIP / loc_id / admin-text lookup into the precomputed table works
- first real router target is now `Valhalla`, using the matrix service for
  precomputed table generation
- the batch calculator is recoverable if it crashes mid-run:
  - checkpoint JSON stores completed `origin_id`s
  - partial parquet stores already computed rows
  - rerunning the same output path resumes rather than restarting
- current laptop lesson: this is better moved to the desktop before the real
  California graph build and full run

What was in progress when the handoff decision was made:

- California Geofabrik extract download started toward:
  `county-map-raw/source_data/osm/geofabrik/california-latest.osm.pbf`
- Docker Desktop on the laptop was still unstable / inaccessible from the
  shell, so Valhalla was not actually launched here

Recommended resume sequence on the desktop:

1. pull latest repo changes and confirm the analytics files above are present
2. confirm Docker engine is callable from shell
3. confirm or redownload:
   `county-map-raw/source_data/osm/geofabrik/california-latest.osm.pbf`
4. stand up local Valhalla against the California extract
5. rerun input prep:
  `python county-map-private/build/data_prep/road_access/prepare_access_inputs.py --state CA --origin-level admin_4 --output-dir "county-map-private/build/data_prep/road_access/output/road_access_ca"`
6. run a very small real-router test first:
  `python county-map-private/build/data_prep/road_access/run_access_calculator.py --input-dir "county-map-private/build/data_prep/road_access/output/road_access_ca" --output-path "county-map-private/build/data_prep/road_access/output/road_access_ca/results_valhalla_sample.parquet" --provider valhalla_matrix --valhalla-url "http://localhost:8002" --max-origins 10 --valhalla-target-batch-size 100`
7. inspect timings and plausibility before launching the larger California run

Interpretation:

- the important design work is no longer the blocker
- the next blocker is operational: stable Docker + local Valhalla + desktop
  compute headroom
- once Valhalla responds cleanly, the existing batch + checkpoint machinery is
  ready for real California timing tests

### Desktop Setup Progress (2026-06-25)

Desktop resume work completed enough to start real-router smoke testing:

- Docker Desktop is running and accessible from the shell when commands are
  elevated.
- California Geofabrik extract was downloaded locally:
  `county-map-raw/source_data/osm/geofabrik/california-latest.osm.pbf`
  (`1,317,280,262` bytes).
- Local Valhalla container is running as `valhalla-ca` on
  `http://localhost:8002` using `ghcr.io/gis-ops/docker-valhalla/valhalla:latest`.
  The first build generated `valhalla_tiles.tar` and the matrix endpoint
  responded successfully.
- Fresh FEMA NSS layer-5 inventory was downloaded on this desktop:
  `county-map-raw/Raw data/nss_shelters/National_Shelter_System_Facilities.csv`
  (`71,524` rows).
- `convert_nss_shelters.py` completed locally and wrote
  `county-map-data/countries/USA/nss_shelters/shelters.parquet` plus
  metadata/reference/review CSVs.
- California road-access prep now matches the laptop handoff counts:
  `25,586` block-group origins and `6,600` shelter destinations.
- First Valhalla-backed samples completed:
  - `results_valhalla_smoke3.parquet` (`3` origins)
  - `results_valhalla_sample.parquet` (`10` origins)
- First full California Research-mode road-access run completed using the
  practical top-75 candidate policy:
  - summary:
    `county-map-private/build/data_prep/road_access/output/road_access_ca/access_summary_admin4_valhalla_top75.parquet`
  - reachable edge table:
    `county-map-private/build/data_prep/road_access/output/road_access_ca/access_edges_within_60min_admin4_valhalla_top75.parquet`
  - `25,586` block-group origins
  - `1,827,753` origin-shelter edge rows within the configured 60-minute edge
    output
  - `25,450` origins with a finite nearest routed shelter
  - `136` origins with no finite route among the routed candidates
  - `440` origins with zero shelters reachable within 60 minutes among the
    routed candidates
  - runtime was about `3.5` hours at roughly `2` origins/second
  - candidate policy: nearest `75` shelters within `90 km` straight-line
    distance per origin, Valhalla search radius `5,000 m`, target batch size
    `25`

Implementation fixes discovered during the desktop smoke:

- Valhalla `sources_to_targets` returns travel time in seconds, so the
  provider now converts to minutes before writing access metrics.
- The Valhalla provider now prefilters far targets by straight-line distance
  before matrix calls, avoiding the service's max-distance failure for
  irrelevant far-away shelters.
- Per-target Valhalla failures such as "no path" or "no suitable edges" are
  treated as unreachable destinations instead of failing the whole origin batch.
- Calculator output now leaves nearest destination fields empty when no finite
  route exists for an origin, rather than attaching a misleading first shelter.
- The full California output is a capped Research-mode screening layer:
  `routed_candidate_limited = true` means the origin had more possible nearby
  candidates than were routed; `reachable_60min = 75` should be read as
  "many nearby shelters, capped at 75" rather than an exhaustive count.

Observed sample caveat:

- Some block-group centroids still do not snap to the routable road network.
  The next quality improvement should be a better representative point strategy
  for road access, likely point-on-surface / nearest-road snapping rather than
  raw geometry centroid for every origin.

Working priority order as of 2026-06-25:

1. design the California road-network stack around address runtime + block-group precompute
2. prototype California shelter travel-time metrics
3. bring in `EPA Smart Location`
4. continue CEJST QA polish / extra synonym and crosswalk coverage only where needed

### Planning / Scenario Expansion (added 2026-06-26)

The next research question is no longer only "where are current shelter deserts?"
It is also "how would shelter access change if the shelter network changed?"
This should be treated as a first-class Research-mode extension, with a later
Ops-mode interactive version.

Core planning questions:

- If 10 new shelters could be added, where would they give the most people
  access within 30, 60, or 90 minutes?
- How many new shelters would be needed so the bottom 10% most disadvantaged
  communities have at least one shelter within 60 minutes?
- Which existing shelters are most critical because removing them causes the
  largest access loss?
- Which counties or regions have both high hazard/disadvantage burden and weak
  shelter redundancy?
- Which candidate site types are best: schools, churches, community centers,
  hotels/motels, fairgrounds, casinos, public buildings, or other large venues?

Recommended computation shape:

- Keep the California baseline as the statewide screening layer.
- For optimization and "what if" planning, scope the first serious work to a
  county or small region rather than recalculating all California for every
  scenario.
- Build a reusable travel-time matrix:
  `block group -> candidate shelter/site -> drive minutes`.
- Run optimization on top of that matrix instead of rerouting from scratch for
  every question.
- Start with greedy maximum-coverage logic because it is easy to explain to
  researchers: each added site is the candidate that covers the most still-
  uncovered target population or priority population.
- Add more formal optimization later if needed: facility-location / set-cover /
  max-cover models with capacity, equity weights, and hazard weights.

Population/equity weighting:

- The baseline "most people helped" objective should use block-group population
  once joined.
- The equity objective should weight or filter by CEJST, NRI social
  vulnerability, EPA Smart Location, and hazard risk.
- A strong first paper/product framing is:
  "shelter placement for disadvantaged high-risk communities under realistic
  road-network travel time."

### Hotel / Motel Augmentation (added 2026-06-26)

Hotels and motels should be added, but not merged blindly into the official
FEMA shelter layer. They are better modeled as a separate destination family:
`potential_emergency_lodging`.

Recommended layer split:

1. `official_shelters` - FEMA NSS facilities and live open shelters.
2. `potential_lodging` - hotels, motels, hostels, guest houses, extended-stay
   lodging, and possibly campgrounds/RV parks for scenario work.
3. `combined_emergency_accommodation` - an analysis view combining official
   shelters plus potential lodging, with clear labeling and caveats.

Recommended source priority:

- Primary: Overture Maps Places. The Places theme is global, distributed as
  GeoParquet, includes categories, addresses, confidence, operating status, and
  a Lodging top-level category. For California first, query only US/CA lodging
  records instead of downloading the full global file.
- Secondary cross-check: OpenStreetMap tourism tags such as `tourism=hotel`,
  `tourism=motel`, `tourism=hostel`, `tourism=guest_house`, `tourism=camp_site`,
  and `tourism=caravan_site`.
- Tertiary supplement: the Kaggle TBO hotels dataset can be inspected, but only
  after checking license, freshness, coordinates, and redistribution terms. It
  should not be the primary source unless those checks are clean.
- Local validation: county business-license, transient occupancy tax, tourism,
  or emergency-management lists may be useful for individual case-study
  counties, but they are too fragmented to be the national/global spine.

Research scenarios to keep separate:

- FEMA shelters only.
- hotels/motels only.
- FEMA shelters plus hotels/motels.
- FEMA shelters plus only high-confidence / active lodging records.
- FEMA shelters plus lodging filtered by hazard-safe location, if fire/flood
  risk layers suggest that some lodging sites are also exposed.

### Interactive Scenario Mode (added 2026-06-26)

The map-click version is plausible, but it should be scoped differently from
the statewide Research batch.

Interactive actions:

- click to add a candidate shelter and show newly covered block groups
- click to remove an existing shelter and show lost coverage
- change a shelter's capacity and show demand pressure
- compare before/after 30-, 60-, and 90-minute access bands
- restrict analysis to disadvantaged or hazard-exposed communities

Practical runtime approach:

- For removing a shelter, use the already-computed edge table / travel-time
  matrix to recompute each block group's next-best reachable shelter.
- For adding a clicked shelter, route only from nearby block groups to the new
  point, then merge that one new destination into the existing scenario matrix.
- For first implementation, keep clicks county-scoped or regional-scoped.
- Do not promise instant statewide rerouting on every click.

### Disaster Disruption / Live Ops Extension (added 2026-06-26)

The weather/fire/traffic idea is important, but it is a different modeling layer
from static shelter access. Treat it as "shelter access under disruption."

Useful disruption inputs:

- active fire points, perimeters, and incident updates
- wind direction/speed and short-term weather forecast
- evacuation zones and road closures
- traffic congestion where licensing/API access allows
- road hierarchy, capacity proxies, bridges, mountain passes, and other
  chokepoints
- official evacuation or disaster routes where state/county sources publish
  them

Recommended modeling posture:

- Start with static road-network access.
- Add scenario-based road closures next: "what if this road segment or polygon
  is unavailable?"
- Then add active fire/weather context as a risk overlay, not as a precise fire
  spread forecast at first.
- Treat traffic congestion as a later Ops-mode enhancement because reliable
  live traffic feeds are usually licensed, expensive, and harder to redistribute.
- Build a road-vulnerability layer for research: communities with only one or
  two viable routes, routes through high wildfire/flood risk, and shelters whose
  access depends on a small number of chokepoints.

Near-term recommended prototype:

1. Pick one county with meaningful access gaps, such as Lake County for a small
   case study or San Bernardino County for a larger desert case.
2. Add candidate sites from FEMA shelters plus Overture lodging.
3. Build a county-level travel-time matrix from block groups to all candidates.
4. Run "best 5 / best 10 new sites" coverage scenarios.
5. Add an equity-weighted version focused on CEJST/NRI/EPA Smart Location
   disadvantaged communities.
6. Save outputs as scenario tables so the results can become maps, rankings,
   and eventually interactive before/after layers.

**Future public project page (not built yet):** When this project is
ready to publish, it gets a public page following the existing
Research projects pattern in
the private website template folder (see
`research_project_fairfax.html`, `research_project_usa_industrial_oz.html`,
`research_project_disaster_aggregates.html`, `research_project_data_we_kept.html`
for shape). Likely landing URL:
`/research/projects/disadvantaged-shelter-access` (or a slug Fatemeh
prefers). The page would index from
`research_projects.html`
alongside the other Research project pages.

Do not build the page yet — wait until the analysis and findings have
enough shape to publish. Link this section back from
`research_projects.html` only when the page actually exists.

**Planned methodology components:**

1. Disadvantaged area identification - CEJST, NRI social vulnerability, EPA Smart Location
2. Shelter access coverage - FEMA NSS Shelters (locations, capacity, ADA, status)
3. Change over time - NRI time series v1.17-v1.20 (2020-2025), ClimRR projections through end of century
4. Road network / actual travel time to shelters - OSM + routing engine
   (Valhalla first, OSRM only as a later alternative); California block-group
   to shelter screening run is complete for the current top-75 candidate policy
5. Actual wildfire event comparison - use real fire perimeter polygons from the existing
   global wildfires disaster pack (VIIRS 2002-2024), not just risk scores
6. Shelter scenario planning - add/remove/optimize shelters or potential
   lodging sites and measure coverage gains/losses
7. Disruption modeling - road closures, fire/weather context, evacuation-route
   chokepoints, and later live traffic where feasible

**Geographic scope:** California focus for the initial study, but all datasets are national.
Expanding to all states is a filter change, not a new data collection. The platform should
make this explicit in how the project is presented.

**Road-network status:** The reusable private-repo computation scaffolding is now
in place, and the first California OSM / Valhalla Research-mode screening run is
complete. OSM via Valhalla is the current preferred first implementation path.
US Census TIGER roads remain an alternative if licensing or redistribution
constraints later push the project away from OSM-derived routing.

---

Working note for the datasets in:

`C:\Users\Bryan\Desktop\fatemah`

Purpose:

- inventory the new files
- capture the useful conclusions from this session
- point to the right internal/external references
- prepare for a later execution/import session

---

## Quick Summary

Main candidate sources found:

1. `Future NRI`
2. `FEMA NRI archive`
3. `ClimRR`
4. `CEJST`
5. `EPA Smart Location`
6. `National Shelter System Facilities`

Current import status:

| Source | Status |
|---|---|
| Future NRI | Published as part of the hazard-split `nri` pack where future scenario fields are combined into the relevant hazard members |
| FEMA NRI (18-hazard pack) | Published in the normal app lane as the hazard-split `nri` pack |
| CEJST | Published and downloadable; major tract/county routing issues fixed, with only QA polish / synonym coverage still worth improving |
| Distributed Manufacturing | Staging / secondary to the current Fatemeh workflow |
| EPA Smart Location | Not started - data on disk, no converter yet |
| NSS Shelters (Pattern B static) | Local build complete from the live FEMA layer-5 inventory. Conservative post-pass recovered `542` state fallbacks to county and excluded `36` clearly questionable rows. Current parquet: `68,901` rows with `67,660` tract, `926` county, and `315` state anchors |
| ClimRR | Not started - data downloaded, still needs the grid-geometry vs aggregated-first decision |

Next actionable imports (no geometry blockers, data on disk):

1. `EPA Smart Location` - block-group scale, static v3.0, no geometry blocker
2. `ClimRR` - must decide: new grid geometry layer vs county/tract aggregation first
3. NSS local QA follow-up - inspect state-only fallbacks and `(0,0)` source rows in `docs/other/nss_shelters_audit/`

---

## Scale and Time

| Dataset | Scale | Time shape |
|---------|-------|------------|
| Future NRI | county | scenario source, not annual series |
| FEMA NRI archive | state / county / census tract / tribal county / tribal tract | release snapshots; 2023 broad archive plus 2024/2025 tract/county refreshes |
| ClimRR | 12km grid cells | historical baseline plus mid/end-century climate scenarios |
| CEJST | census tract | snapshot release with mixed underlying vintages |
| EPA Smart Location | block group | single snapshot |
| Shelter System | point locations | current operational inventory with partial lifecycle fields |

County Map shorthand:

- county = `admin_2`
- tract = `admin_3`
- block group = `admin_4`
- ClimRR grid = non-admin gridded climate surface
- shelters = point/facility layer

---

## Dataset Notes

## 1. Future NRI

Files:

- `NRI_Future_Risk_Master_Datasheet_12052024.xlsx`
- `NRI_Data_Dictionary.xlsx`
- `combined_nri_counties_borders.json`
- `tiny-usa-county-borders.json`

Observed shape:

- about `3,231` rows
- about `181` columns
- county-scale

Hazard families present:

- `CFLD` = coastal flooding
- `DRGT` = drought
- `EXHT` = extreme heat
- `HRCN` = hurricane
- `WFIR` = wildfire

Scenario structure:

- `MID_LOWER`
- `MID_HIGHER`
- `LATE_LOWER`
- `LATE_HIGHER`

Working interpretation:

- mid-century lower warming
- mid-century higher warming
- late-century lower warming
- late-century higher warming

Use it as:

- county scenario metrics
- county choropleth / comparison source
- likely the best first import candidate from this folder

For exact suffix meanings and methodology, prefer the source technical documentation instead of re-explaining here.

---

## 2. FEMA NRI Archive

Files:

- `FEMA/2023/`
- `FEMA/2024/NRI_Table_CensusTracts.zip`
- `FEMA/2025/Feb 2025/`
- `FEMA/2025/NationalRiskIndex_Metadata.zip`

Observed folder size:

- `2023`: about `3.41 GB`, `117` files
- `2024`: about `0.58 GB`, one tract table zip
- `2025`: about `3.81 GB`, `27` files

2023 archive coverage:

- table downloads:
  - national `states`, `counties`, `census tracts`, `tribal counties`, `tribal census tracts`
  - 51 state/district tract table slices
  - 51 state/district county table slices
- shapefile downloads:
  - `states`
  - `counties`
  - `census tracts`
  - `tribal counties`
  - `tribal census tracts`
- geodatabase downloads:
  - `states`
  - `counties`
  - `census tracts`
  - `tribal counties`
  - `tribal census tracts`

2023 observed table shapes:

| File | Rows | Columns |
|------|------|---------|
| `NRI_Table_States.zip` | `51` | `230` |
| `NRI_Table_Counties.zip` | `3,142` | `365` |
| `NRI_Table_CensusTracts.zip` | `72,739` | `367` |
| `NRI_Table_Tribal_Counties.zip` | `1,241` | `374` |
| `NRI_Table_Tribal_CensusTracts.zip` | `3,157` | `376` |

2024 archive coverage:

- `NRI_Table_CensusTracts.zip`
- observed shape: `85,154` rows, `467` columns
- appears to be a newer tract-table schema than the 2023 archive

2025 archive coverage:

- `Feb 2025/NRI_Table_CensusTracts.zip`
- `Feb 2025/NRI_Table_Counties.zip`
- `Feb 2025/NRI_Shapefile_CensusTracts.zip`
- `Feb 2025/NRI_Shapefile_Counties.zip`
- `Feb 2025/NRI_Shapefile_Tribal_CensusTracts.zip`
- `Feb 2025/NRI_Shapefile_Tribal_Counties.zip`
- `NationalRiskIndex_Metadata.zip`

2025 observed table shapes:

| File | Rows | Columns |
|------|------|---------|
| `NRI_Table_Counties.zip` | `3,231` | `465` |
| `NRI_Table_CensusTracts.zip` | `85,154` | `467` |

2025 extracted working files:

- `Feb 2025/NRI_Table_CensusTracts/NRI_Table_CensusTracts.csv`
- `Feb 2025/NRI_Table_CensusTracts/NRIDataDictionary.csv`
- `Feb 2025/NRI_Table_CensusTracts/NRI_HazardInfo.csv`
- `Feb 2025/NRI_Shapefile_CensusTracts/`

Hazards present in the 2025 `NRI_HazardInfo.csv`:

- `AVLN` = avalanche
- `CFLD` = coastal flooding
- `CWAV` = cold wave
- `DRGT` = drought
- `ERQK` = earthquake
- `HAIL` = hail
- `HWAV` = heat wave
- `HRCN` = hurricane
- `ISTM` = ice storm
- `LNDS` = landslide
- `LTNG` = lightning
- `RFLD` = riverine flooding
- `SWND` = strong wind
- `TRND` = tornado
- `TSUN` = tsunami
- `VLCN` = volcanic activity
- `WFIR` = wildfire
- `WNTW` = winter weather

Major metric families:

- composite risk: `RISK_VALUE`, `RISK_SCORE`, `RISK_RATNG`, `RISK_SPCTL`
- expected annual loss: `EAL_SCORE`, `EAL_RATNG`, `EAL_SPCTL`, `EAL_VALT`, `EAL_VALB`, `EAL_VALP`, `EAL_VALPE`, `EAL_VALA`
- expected annual loss rate: `ALR_VALB`, `ALR_VALP`, `ALR_VALA`, `ALR_NPCTL`, `ALR_VRA_NPCTL`
- social vulnerability: `SOVI_SCORE`, `SOVI_RATNG`, `SOVI_SPCTL`
- community resilience: `RESL_SCORE`, `RESL_RATNG`, `RESL_SPCTL`, `RESL_VALUE`
- community risk factor: `CRF_VALUE`
- per-hazard families: event count, annualized frequency, exposure, historic loss ratio, expected annual loss, annual loss rate, hazard risk value/score/rating

Working interpretation:

- this is the baseline FEMA National Risk Index archive, distinct from `Future NRI`
- `Future NRI` is a climate-scenario extension for selected future hazards at county scale
- FEMA NRI is broader current/baseline risk, loss, exposure, social vulnerability, and resilience context
- the 2025 county and tract tables look like the best first comparison target against existing County Map NRI imports
- the 2023 archive is useful for historical release comparison and for state/geodatabase/tribal coverage not present in the 2025 folder

Import caution:

- shapefile downloads use `-9999` for null values and may have minor large-number differences versus CSV/geodatabase formats
- prefer CSV tables for numeric import if geometry is already available internally
- compare existing repo NRI import code before creating a new converter, because there are likely already mappings for `SOVI_SCORE` and related fields

Use it as:

- baseline NRI county and tract metrics
- social vulnerability / resilience metrics already embedded in FEMA NRI
- hazard-specific current risk and expected annual loss metrics
- source comparison against old NRI imports and `Future NRI`

---

## 3. ClimRR

Files:

- `ClimRR/ClimRR Data Download.zip`
- `ClimRR/ClimRR Data Download/ClimRR Data Download/`
- `ClimRR/ClimRR Metadata and Data Dictionary.pdf`
- duplicate root copy of `FireWeatherIndex_Wildfire.csv`

Observed shape:

- grid-cell climate projection source
- primary key appears to be `Crossmodel`
- `GridCellsShapefile/GridCells.dbf`: `62,834` grid cells
- `GridCells2Shapefile/GridCells2.dbf`: `62,919` grid cells
- README says `GridCells2` includes `85` more 12km grid cells around coastlines and borders due to a larger buffer

CSV files:

| File | Rows | Columns | Notes |
|------|------|---------|-------|
| `AnnualTemperatureMaximum.csv` | `62,834` | `12` | historical, RCP 4.5/8.5 mid/end-century, deltas |
| `AnnualTemperatureMinimum.csv` | `62,834` | `12` | historical, RCP 4.5/8.5 mid/end-century, deltas |
| `ConsecutiveDayswithNoPrecipitation.csv` | `55,896` | `13` | dry-day projection surface |
| `CoolingDegreeDays.csv` | `62,834` | `6` | historical and RCP 8.5 mid-century |
| `FireWeatherIndex_Wildfire.csv` | `62,919` | `29` | seasonal wildfire/fire-weather index; matches `GridCells2` count |
| `heatindex.csv` | `63,458` | `39` | heat-index max/seasonal max/day thresholds and changes |
| `HeatingDegreeDays.csv` | `62,834` | `4` | historical and RCP 8.5 mid-century |
| `Precipitation_inches_AnnualTotal.csv` | `55,896` | `12` | annual precipitation projection surface |
| `SeasonalTemperatureMaximum.csv` | `62,834` | `21` | seasonal max temperature |
| `SeasonalTemperatureMinimum.csv` | `62,834` | `21` | seasonal min temperature |
| `WindSpeed.csv` | `62,834` | `12` | historical, RCP 4.5/8.5 mid/end-century, deltas |

Scenario/column shorthand observed:

- `hist` / `HIS` = historical baseline
- `rcp45_midc` = RCP 4.5 mid-century
- `rcp45_endc` = RCP 4.5 end-century
- `rcp85_midc` / `M85` = RCP 8.5 mid-century
- `rcp85_endc` / `E85` = RCP 8.5 end-century
- `mid45_hist`, `end45_hist`, `mid85_hist`, `end85_hist` = scenario minus historical deltas
- `Dmid`, `Dend` = mid/end-century absolute change
- `Pmid`, `Pend` = mid/end-century percent change

Working interpretation:

- ClimRR is not an admin-boundary dataset; it is a modeled climate grid
- it is probably best treated as a gridded raster-like/vector-cell overlay first
- county/tract aggregation could come later, but would require spatial intersection or nearest/grid summarization
- it complements `Future NRI`: ClimRR gives physical climate variables, while Future NRI gives selected future risk metrics by county

Grid system clarification:

- ClimRR ships as **vector polygon shapefiles** (`GridCells`, `GridCells2`) plus CSVs joined by `Crossmodel`, NOT as a raster/GeoTIFF
- the underlying lattice is the **WRF (Weather Research and Forecasting) regional climate model output grid** that Argonne ran for the contiguous US, exported as polygons so non-raster GIS tools can consume it
- conceptually it is downscaled climate model output; packaging is vector, science is grid

Vector-grid vs raster-grid contrast:

| Aspect | ClimRR (vector grid) | Raster/GeoTIFF (e.g. WorldClim, MODIS, NLCD) |
|---|---|---|
| Storage | shapefile of polygons + CSV join | binary array of pixel values + georeferencing header |
| Geometry primitive | polygon feature per cell | implicit (row/col -> bbox via affine transform) |
| Per-cell values | columns in a CSV row | bands in the image |
| Per-cell coords | each cell carries its own polygon coords | single transform applies to all pixels |
| Reader | shapefile / geopandas / parquet | rasterio / GDAL |
| Size | small (~63k features) | usually millions of pixels |
| Resampling | spatial join / aggregation by polygon | bilinear/nearest array resample |

Pipeline implications:

- joins like any other vector source (`Crossmodel` plays the role of `loc_id` for the grid layer)
- not an `admin_2`/`admin_3` source; needs one of:
  1. publish `GridCells2` as a new geometry layer, e.g. `countries/USA/geometry/climrr_grid/...`, OR
  2. pre-aggregate to county/tract via area-weighted mean for choropleth use, OR
  3. both: keep the grid as the canonical layer and ship admin-level derivatives for map rendering
- closest existing repo pattern is the Fairfax custom-geometry path (vector, non-admin); the QA README "geometry serialization reminder" applies (geometry must be GeoJSON-string at runtime, not GeoParquet WKB)
- rasterization is possible but lossless only because the cells form a regular lattice; not required unless a raster consumer needs it

Use it as:

- future climate exposure surface
- heat, precipitation, drought/dry-days, wind, and wildfire fire-weather projection layer
- possible later source for derived county/tract summaries

Import caution:

- the metadata/data dictionary PDF should travel with the source
- `FireWeatherIndex_Wildfire.csv` at the `ClimRR` root is byte-identical to the nested copy
- use `GridCells2` for wildfire/fire-weather because its row count matches the wildfire CSV
- inspect why `heatindex.csv` has `63,458` rows before import; it exceeds both grid shapefile record counts

---

## 4. CEJST

Files:

- `21 Jan 2025/2.0-communities.csv`
- `21 Jan 2025/2.0-communities.xlsx`
- `21 Jan 2025/2.0-shapefile-codebook.zip`
- `21 Jan 2025/cejst-technical-support-document.pdf`
- `21 Jan 2025/CEQ-CEJST-Instructions.pdf`

Observed shape:

- about `74,134` rows
- about `136` columns
- census tract scale

Key tract field:

- `Census tract 2010 ID`

Working interpretation:

- tract-level disadvantaged community screening source
- one current release snapshot (`2.0`)
- not a clean time series
- includes mixed underlying source vintages and comparison fields to `v1.0`

Plain-English meaning:

- not just a single “social risk score”
- a tract-level screening/classification source built from burden thresholds plus socioeconomic conditions
- good for environmental justice / disadvantaged community mapping

Use it as:

- tract snapshot metrics source
- disadvantaged community / environmental justice source

For full category logic, use the CEJST technical support document.

**Import status (2026-05-19):** DONE. Pack `cejst` in staging with `cejst_classification` (binary decision + 32 threshold flags + demographics) and `cejst_burdens` (raw metric values + percentile ranks). Both sources synced to R2, browser artifacts live. Pending live Explore QA run to flip release markers.

---

## 5. EPA Smart Location

Files:

- `EPA_SmartLocationDatabase_V3_Jan_2021_Final.csv`
- `SmartLocationDatabase.gdb`
- `EPA.zip`
- EPA technical documentation

Observed shape:

- about `220,740` rows
- `117` columns
- census block group scale

Key geography columns:

- `GEOID10`
- `GEOID20`
- `STATEFP`
- `COUNTYFP`
- `TRACTCE`
- `BLKGRPCE`

Working interpretation:

- January 2021-era snapshot
- built environment / accessibility / walkability-style source

Metric family shorthand:

- `D1` = density
- `D2` = employment / housing diversity
- `D3` = urban design / street connectivity
- `D4` = transit accessibility
- `D5` = destination accessibility
- `NatWalkInd` = national walkability-style composite

Use it as:

- block-group snapshot metrics source
- urban analytics / transit / walkability source
- heavier lift than CEJST/Future NRI

For full field decoding, prefer the EPA user guide.

---

## 6. National Shelter System Facilities

Files:

- `2025/National_Shelter_System_Facilities.csv`
- `2025/National_Shelter_System_Facilities.zip`
- older shapefile material in `2024/`

Observed shape:

- `70,589` rows
- `74` local CSV columns
- nationwide US point dataset

Live API:

- `https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer`
- full inventory layer for Research mode:
  `https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer/5`
  (`Shelter Locations`)
- live open subset for Ops mode:
  `https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer/0`
  (`FEMA Open Shelters`)

Current live counts observed during this session:

- `Open Shelters`: `19`
- `Closed Shelters`: `71,362`
- `Full Shelters`: `0`
- `Alert Shelters`: `17`
- `Shelter Locations`: `71,354`

Working interpretation:

- not “70k continuously open shelters”
- broad operational inventory / registry of emergency shelter resources
- likely many sleeper / standby shelters that open during incidents and close later

Status interpretation for working use:

- `OPEN`: currently active
- `CLOSED`: not currently active, likely can reopen later
- `ALERT`: standby / heightened status
- `INACTIVE`: closest thing to likely unavailable / out of rotation
- `CANDIDATE`: likely potential shelter resource not yet in regular operational use

Historical/lifecycle caution:

- local file has partial lifecycle dates, but they are not clean enough for a first historical product
- after a first cleanup pass:
  - earliest sane `open` date: `2007-06-25`
  - latest sane `open` date: `2025-07-08`
  - obvious future dates existed and were flagged
  - many rows had `close_date < open_date` and do not look safe for naive animation

API behavior:

- live API exists
- public historical replay does not appear to exist
- service reported:
  - `hasArchivedData: false`
  - `supportsQueryWithHistoricMoment: false`

Current product direction:

- treat shelters as a live/current API-backed layer
- prioritize current operational status and facility discovery/filtering
- do not prioritize historical animation in the first version

**Two-pattern model (see the internal live-pipeline program, bucket 5):**

Pattern A — Live API facade (primary vision):
- "Find open shelters near this address" — runtime proximity query against
  FEMA's live OpenShelters endpoint
- `https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer/0`
  returns currently-active shelters with status, capacity, ADA, and location
- DaedalMap queries this at request time, no local parquet write needed
- Can be enriched with CEJST/NRI context for the surrounding area to answer
  "are the open shelters near me in a disadvantaged community?"
- Does not go through the collect-canonicalize-integrate-propagate pipeline

Pattern B — Static snapshot parquet (Research/analysis):
- The 70,589-row snapshot on disk feeds Research mode analysis:
  shelter coverage across disadvantaged tracts, shelter deserts by county, etc.
- Pairs with CEJST (which tracts are disadvantaged?) and NRI (what hazard
  risk do those tracts face?) to answer the core research question
- Standard static import pipeline; manual refresh when FEMA publishes updates
- Not live; no collector required unless we decide to build a time series of
  snapshots for historical coverage analysis

Useful live field families:

- location: `state`, `city`, `county_parish`, `zip`
- capacities: `evacuation_capacity`, `post_impact_capacity`, `total_population`
- accessibility: `ada_compliant`, `wheelchair_accessible`, `pet_accommodations_*`
- hazard context: floodplain / surge area flags
- incident context: `incident_id`, `incident_name`, `incident_code`
- status/lifecycle: `shelter_status_code`, `shelter_open_date`, `shelter_closed_date`, `reporting_period`

---

## Geometry Readiness

These sources are viable against the current published USA geometry system:

- county: supported
- tract: supported
- block group: supported
- points: supported as point layers; polygon joins/filtering can be added later

Cloud checks during this session confirmed:

- global geometry exists in `published/geometry/`
- USA deep geometry exists in `published/countries/USA/geometry/`
- tract and blockgroup files are broadly present
- published block files currently include at least:
  - `CA`
  - `DE`
  - `MD`
  - `NY`
  - `VA`
  - `WA`
  - `WV`

### Local Geometry Verification (2026-04-30)

Direct check of `county-map-data/countries/USA/geometry/` and `county-map-data/geometry/` confirms:

| Level | loc_id used by | Local coverage | Status for this batch |
|---|---|---|---|
| County | Future NRI, FEMA NRI counties | `county.parquet` (single national file) | Ready |
| Tract | FEMA NRI tracts, CEJST | All 50 states + DC + AS, GU, MP, PR, VI (56 files) | Ready |
| Blockgroup | EPA Smart Location | All 50 states + DC + AS, GU, MP, PR, VI (56 files) | Ready |
| Block | (not needed for this batch) | CA, DE, MD, NY, VA, WA, WV only | Partial; not blocking |
| Tribal | FEMA NRI tribal tables | `USA.parquet` single national file (+ geojson, metadata, reference) | Ready |
| Points | Shelters | n/a (point geometry on the source itself) | Ready |
| ClimRR grid | ClimRR | NOT present in repo | Blocker (see below) |

`crosswalk.json` is present at `countries/USA/`.

Cloud `published/` lane was NOT re-verified this session. Per the QA README, local presence does not guarantee cloud presence. Before treating any tract/blockgroup import as publish-ready, run:

```
python county-map-private/build/r2_sync.py status --prefix published --filter countries/USA/geometry/ --details
```

### Geometry Blockers For This Batch

Only one: **ClimRR has no grid geometry in the repo**. Resolution requires one of:

1. publish `GridCells2` as a new geometry layer (e.g. `countries/USA/geometry/climrr_grid/...`)
2. pre-aggregate to county/tract via area-weighted mean for choropleth
3. both: keep grid as canonical layer, ship admin derivatives for map rendering

---

## Step 1 Verification Findings (2026-04-30)

Direct inventory of `C:\Users\Bryan\Desktop\fatemah` against this doc and the existing repo state.

### Folder name correction

- doc previously referenced `C:\Users\bryan\Desktop\Fatemeh Data`
- actual folder is `C:\Users\Bryan\Desktop\fatemah` (lowercase, no space, no "Data" suffix)
- doc has been updated to reference the correct path

### Source inventory (confirmed present)

- **Future NRI**: both `NRI_Future_Risk_Master_Datasheet_12052024.xlsx` files present (one is a `(1)` duplicate); data dictionary; `combined_nri_counties_borders.json`; `tiny-usa-county-borders.json`
- **FEMA 2023**: full archive (~3.4 GB), all GDB/shapefile/table downloads including tribal
- **FEMA 2024**: `NRI_Table_CensusTracts.zip` (~625 MB)
- **FEMA Feb 2025**: county+tract tables, plus full shapefile set (counties, tracts, tribal counties, tribal tracts). The doc previously listed only the tract shapefile; the county and tribal shapefiles are also present
- **ClimRR**: extracted, with `GridCells`/`GridCells2` shapefile zips and all CSVs
- **CEJST**: both `1.0` (root, with `usa.shp` already extracted from `1.0-shapefile-codebook.zip`, ~605 MB) AND `2.0` (`21 Jan 2025/`)
- **Shelters 2025**: CSV + zip; 2024 shapefile set also present
- **EPA Smart Location V3**: CSV (~577 MB and ~201 MB variants), `SmartLocationDatabase.gdb`, tech doc

### Existing converters in repo

- `county-map-private/data_converters/converters/convert_fema_nri.py`
- `county-map-private/data_converters/converters/convert_fema_nri_timeseries.py`
- `county-map-private/data_converters/converters/convert_nri_tracts.py`
- **CEJST converter complete**: `convert_cejst.py` outputs two parquets (cejst_classification + cejst_burdens); pack in staging as of 2026-05-19
- no converters yet for `ClimRR`, `Shelters`, or `EPA Smart Location`

The three NRI converters mean **FEMA Feb 2025 is a refresh decision, not greenfield**. They have not yet been read for column-mapping compatibility against the 465-column 2025 county schema or 467-column 2025 tract schema.

### Pre-import housekeeping items

1. **Stale GDB lock files** in `SmartLocationDatabase.gdb` from a `FATEMEH` machine (`.sr.lock`, `.rd.lock`, `_gdb.FATEMEH.*.sr.lock`). Harmless to read but worth deleting before opening in geopandas/fiona to avoid driver warnings
2. **CEJST 1.0 shapefile already extracted** at the root (`1.0-shapefile-codebook/usa/usa.shp`); duplicate of what is inside `1.0-shapefile-codebook.zip`. Decide which copy is canonical. The doc only meaningfully discusses the 2.0 release
3. **Future NRI duplicate xlsx**: `NRI_Future_Risk_Master_Datasheet_12052024.xlsx` and `NRI_Future_Risk_Master_Datasheet_12052024 (1).xlsx` both exist. Pick one canonical
4. **ClimRR `heatindex.csv` row count** (`63,458`) still exceeds both `GridCells` (`62,834`) and `GridCells2` (`62,919`); flagged in original doc, still unresolved
5. **Existing NRI converter overlap**: read all three before importing FEMA Feb 2025 to avoid double-import or schema drift

### Net result of Step 1

- data is intact; no missing files, no redownload required
- one real geometry blocker (ClimRR grid)
- one real conversion-side decision blocker (refresh-vs-new for FEMA Feb 2025 against existing converters)
- everything else can start building locally now; cloud `published/` geometry verification is the only remaining lane gate before publish

---

## Working Posture: Complete History First, Imports Second

Updated 2026-04-30. Decision: round out the **complete published history** of every source in this batch before doing any conversion or pack-building work. Reasoning:

- once we have full history on disk, ongoing maintenance reduces to "watch for the next release and pull it"
- live-collector design becomes a single watch-and-fetch operation, not "watch + retroactively rebuild what we missed"
- at the rate FEMA / CEQ / EPA hosts have been decaying, the cost of "I'll grab the older versions later" is rising; do it while the mirrors are still up
- import order from the original doc is now subordinate to completeness order

Per-source completeness state is tracked in the audit below. Status as of 2026-05-19:

| Source | Completeness | Import status |
|---|---|---|
| FEMA NRI baseline | Near-complete (v1.17, v1.18.1, v1.19, v1.20 on disk; v1.18.0 missing - minor patch gap) | **PUBLISHED**: 18-hazard `nri` pack, S3 synced, QA run complete |
| Future NRI | Complete; mirror enriched (+10 cols incl. Coastal Flooding family) | Staging (Stage 2 complete) |
| ClimRR | Near-complete for FeatureServer-extractable layers; MapServer raster gaps documented | Not started; grid geometry decision needed |
| CEJST | Complete; PEDP mirror is canonical (216-row data corrections) | **STAGING 2026-05-19**: `cejst` pack (classification + burdens), 74,134 tracts, 99.6% loc_id, browser artifacts live, pending live QA run |
| EPA Smart Location | Complete for current schema (v3.0); v1/v2 obsolete | Not started; no converter yet |
| NSS Shelters | Snapshot-only (no historical archive exists) | Pattern B local static build complete (`68,901` rows after conservative QA cleanup, `0` unmatched loc_ids). Pattern A live API remains a separate Ops-mode runtime path |

---

## Completeness Audit (2026-04-30)

Goal: for each source, identify the universe of releases and mark whether what we have on disk is "the entire publicly released history" or partial.

### 1. FEMA NRI (baseline) - NEAR-COMPLETE (post-2026-04-30 backfill)

Known FEMA NRI release history:

| Version | Released | Notes |
|---|---|---|
| v1.17.0 | Nov 16, 2020 | Phase 1 / initial public release |
| v1.18.0 | Aug 16, 2021 | SHELDUS v19 historic loss ratio refresh; 2020 dollar inflation |
| v1.18.1 | Nov 2021 | Minor patch on 1.18 |
| v1.19.0 | Mar 23, 2023 | 2020 census tract refresh; SoVI -> CDC SVI; territory EAL coverage; precalculated EAL rates |
| (Feb 2025 schema bump) | Feb 2025 | tract+county refresh in this folder; metadata zip still references "March2023" |
| v1.20 | Dec 2025 | latest; available via RAPT and download |

What we have:

- 2023 archive (full, ~3.4 GB) - corresponds to v1.19.0
- 2024 tract-only - intermediate snapshot
- Feb 2025 county+tract+shapefiles - schema bump (~465/467 cols)

What we are missing:

- v1.17.0 (Nov 2020), v1.18.0 (Aug 2021), v1.18.1 (Nov 2021)
- v1.20 (Dec 2025, current latest)

### 2. Future NRI - COMPLETE; mirror copy is BETTER than local Fatemeh copy

- prototype released Dec 12, 2024 (datasheet stamped 12052024)
- **REMOVED by FEMA in Feb 2025**; lawsuit filed Apr 15, 2025; dismissed Mar 13, 2026 for lack of standing
- only one public release was ever made; we have it
- **the EELP/Fulton-Ring recreation has enriched the master datasheet** with 10 columns the FEMA original lacked (see "Future NRI Mirror Enrichment" below); treat mirror as canonical going forward

### 3. ClimRR - NEAR-COMPLETE for FeatureServer-extractable layers (post-2026-04-30 backfill)

- portal launched Nov 2022 (Argonne / AT&T / FEMA collaboration; primary host is DOE/Argonne, not FEMA, so less politically exposed)
- significant additions since the original Box bulk download (which the local Fatemeh copy is from):
  - inland flooding (HUC12-scale, multiple return periods)
  - WBGT (wet bulb globe temperature) hazard family
  - freeze-free days
  - plant hardiness zones
  - heat IDF curves (1-7 day, 2/5/10/25/50-yr return, 50%/95% confidence)
  - CMIP6 SSP245/SSP585 scenarios alongside the original CMIP5 RCP4.5/RCP8.5
- Puerto Rico/Caribbean expansion was planned but not visible in current portal layer titles as of 2026-04-30
- **the original local CSVs are now superseded** by joined master tables hosted on the portal's ArcGIS REST service

### 4. CEJST - COMPLETE; PEDP mirror has 216 rows of data corrections vs local

- beta: Feb 18, 2022
- v1.0: Nov 22, 2022
- v2.0: Dec 2024 (final release)
- White House public access discontinued Jan 22, 2025; tool/data still mirrored
- we have both 1.0 and 2.0 on disk
- no further releases expected
- **the PEDP CloudFront mirror has 216 rows of value corrections in 3 columns** vs the Jan 2025 local Fatemeh copy (see "CEJST Mirror Drift" below); treat PEDP mirror as canonical going forward

### 5. EPA Smart Location - LIKELY COMPLETE for current schema

- v1.0: 2012
- v2.0: Mar 2014
- v3.0: 2021 (current; 2019 census block group geographies)
- we have v3.0
- v1.0 and v2.0 use older Census geographies and pre-2021 schemas; not worth a backfill unless a longitudinal SLD product is intended
- EPA hosting has been less affected than FEMA/CEQ to date; refresh risk is moderate, not urgent

### 6. National Shelter System Facilities - SNAPSHOT-ONLY (no historical archive exists)

- live ArcGIS FeatureServer at `gis.fema.gov`; service reports `hasArchivedData: false`, `supportsQueryWithHistoricMoment: false`
- there is no public retrospective archive; "all-time" data does not exist server-side
- our 2025 CSV (70,589 rows) and 2024 shapefile are point-in-time snapshots
- "complete" here means: the latest live snapshot. To build a true time series we would need to start collecting our own snapshots going forward

---

## Alternative Sources (FEMA / CEQ link decay)

FEMA and White House (CEQ) hosted data has substantial dead-link, removal, and rollback issues post-2025. Where the FEMA primary is unreliable, prefer mirrors. ClimRR (Argonne/DOE) and EPA SLD have not been pulled to the same degree.

### FEMA NRI mirror network

| Source | URL | Coverage |
|---|---|---|
| Esri / ArcGIS Living Atlas (FEMA Hub) | `https://resilience-fema.hub.arcgis.com/` | NRI counties, tracts, states feature layers; current v1.20 published here |
| FEMA Geospatial Resource Center | `https://gis-fema.hub.arcgis.com/` | NRI plus other FEMA layers |
| Resilience.climate.gov | `https://resilience.climate.gov/datasets/FEMA::national-risk-index-census-tracts/about` | climate.gov republish of NRI tract layer |
| NOAA Digital Coast | `https://coast.noaa.gov/digitalcoast/data/fema-risk.html` | NOAA-hosted NRI mirror |
| DataLumos (ICPSR) | `https://www.datalumos.org/datalumos/project/218382/view` | ICPSR-hosted NRI archive |
| heat.gov | `https://heat.gov/tools-resources/national-risk-index-fema/` | heat.gov NRI republish |
| Georgia Tech Drawdown | `https://drawdownga.gatech.edu/nri/` | academic mirror |
| nri-data-downloads.s3.amazonaws.com | `https://nri-data-downloads.s3.amazonaws.com/webpages/home.html` | S3-hosted resources page |

Use Esri ArcGIS Hub or DataLumos as the primary fallbacks. They are the most likely to have archived per-version downloads.

### Future NRI mirrors (FEMA removed it)

| Source | URL |
|---|---|
| EELP Harvard Law tracker (recreation + underlying data) | `https://eelp.law.harvard.edu/tracker/rollback-fema-removed-future-risk-index/` |
| Public Environmental Data Partners | `https://screening-tools.com/` |
| ArcGIS archived item | `https://www.arcgis.com/home/item.html?id=f079e172677446bdbf31d098b8116c6a` |
| EELP technical doc PDF (already used in research) | `https://eelp.law.harvard.edu/wp-content/uploads/2025/03/NRI_Future_Risk_Technical_Document.pdf` |
| reliance.school archive note | `https://www.reliance.school/blog/archived-fema-future-risk-index` |

### CEJST mirrors (CEQ/White House removed it)

| Source | URL |
|---|---|
| Public Environmental Data Partners (data + screening) | `https://screening-tools.com/climate-economic-justice-screening-tool` |
| EDGI gov-data archiving GitHub Pages copy of the tool | `https://edgi-govdata-archiving.github.io/j40-cejst-2/en/` |
| PEDP GitHub Pages copy of the tool | `https://public-environmental-data-partners.github.io/j40-cejst-2/en/` |
| Data Rescue Project Portal | `https://portal.datarescueproject.org/datasets/climate-and-economic-justice-screening-tool-cejst/` |
| Biden White House archives (FAQ/instructions PDFs) | `https://bidenwhitehouse.archives.gov/wp-content/uploads/2022/02/CEQ-CEJST-QandA.pdf` |
| EELP tracker | `https://eelp.law.harvard.edu/tracker/ceqs-climate-economic-justice-screening-tool-removed/` |

### ClimRR (Argonne) - still live

- portal: `https://climrr.anl.gov/`
- DOE/Argonne portal item: `https://disgeoportal.egs.anl.gov/ClimRR/`
- Box metadata folder: `https://anl.box.com/s/hmkkgkrkzxxocfe9kpgrzk2gfc4gizp8`
- no removal events known as of April 2026

### EPA SLD - still live

- main page: `https://www.epa.gov/smartgrowth/smart-location-mapping`
- ArcGIS Hub overview item: `https://www.arcgis.com/home/item.html?id=b4e03f5dce75480c94c1dc06aa96152c`

### NSS Shelters - still live

- FeatureServer: `https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer`
- Full inventory layer (`Shelter Locations`, research snapshot source): `https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer/5`
- OpenShelters mirror: `https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer/0`
- prep-response-portal mirror: `https://prep-response-portal.napsgfoundation.org/datasets/d000037396514f70a2ba3683e037caee_0/about`
- HSIP/PDC metadata: `https://rapids.pdc.org/rapids/metadata/hsip_national_shelter_system.html`

### Cross-cutting preservation networks (good to know)

- **Public Environmental Data Partners (PEDP)**: `https://envirodatagov.org/public-environmental-data-partners/` - coalition mirror for FEMA/CEQ/EPA data at risk
- **EDGI**: `https://envirodatagov.org/` - environmental data preservation
- **Data Rescue Project**: `https://portal.datarescueproject.org/`
- **Internet Archive Wayback Machine**: useful for reaching specific dead FEMA URLs at known historical timestamps

---

## Completeness-First Action List

Pure backfill priorities (chase before doing import work):

1. **FEMA NRI v1.20 (Dec 2025)** - latest version not in our archive. Try Esri Living Atlas / ArcGIS Hub first, DataLumos second
2. **FEMA NRI v1.17.0, v1.18.0, v1.18.1** - earlier baseline versions for time-series comparison. Likely on DataLumos or Wayback Machine snapshots of the FEMA archive page
3. **Future NRI second copy** - pull from EELP or screening-tools.com as a preservation copy of what we already have, since FEMA removed it
4. **ClimRR refresh check** - compare our local CSVs against current `climrr.anl.gov` to see if PR/Caribbean, higher-res, or new flooding layers shipped after our copy

Sources already complete enough for first import:

- **CEJST** (both 1.0 and 2.0 on disk; final release was 2.0)
- **Future NRI** (only release was Dec 2024; we have it; mirror as insurance)
- **EPA Smart Location v3** (only current schema; v1/v2 are obsolete)
- **NSS Shelters** (no archive exists; we have current snapshot)

---

## NRI Backfill Plan (full historical archive)

Goal: hold every FEMA NRI release ever published (v1.17.0 through v1.20) so the maintenance burden becomes "track the next release", not "rebuild history every time".

### Confirmed FEMA archive URL pattern

The FEMA archive serves files under a versioned path even when the listing pages 404:

```
https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/Archive/<version>/<filename>
```

Confirmed examples surfaced by search:

- `Archive/v117_0/fema_national-risk-index_technical-documentation.pdf`
- `Archive/v118_1/fema_national-risk-index_technical-documentation.pdf`

Inferred slug pattern: `v117_0`, `v118_0`, `v118_1`, `v119_0`, then `v120` or `v120_0` for Dec 2025.

The static FEMA bucket itself appears to still serve direct file URLs even when the listing page is broken. This means a small downloader script that targets known filenames (e.g. `NRI_Table_Counties.zip`, `NRI_Table_CensusTracts.zip`, etc.) per version slug is likely the highest-yield approach.

### Hub mirrors known to be live

| Mirror | URL | Use for |
|---|---|---|
| FEMA Geospatial Resource Center | https://gis-fema.hub.arcgis.com/ | NRI feature layer downloads |
| Esri / ArcGIS Hub (FEMA Resilience) | https://resilience-fema.hub.arcgis.com/ | NRI counties / tracts / states feature layers |
| RAPT FEMA ArcGIS Hub data download | https://rapt-fema.hub.arcgis.com/pages/nri-datadownload | direct NRI download surface |
| Resilience.climate.gov | https://resilience.climate.gov/ | FEMA layer republish |
| NOAA Digital Coast | https://coast.noaa.gov/digitalcoast/data/fema-risk.html | NRI mirror for current version |
| DataLumos (ICPSR) | https://www.datalumos.org/datalumos/project/218382/version/V1/view | academic archive snapshot |

### Recommended backfill order

1. **v1.20 (Dec 2025)** - try `rapt-fema.hub.arcgis.com/pages/nri-datadownload` first. Fall back to direct FEMA archive URLs (`v120_0` or similar). Highest priority because it is the current public version and probably has another schema bump beyond Feb 2025
2. **v1.19.0 (Mar 2023)** - we already have the 2023 archive in local files; just confirm version match with the technical doc
3. **v1.18.1 (Nov 2021)** - URL slug `v118_1` confirmed exists; pull table + shapefile + GDB
4. **v1.18.0 (Aug 2021)** - URL slug `v118_0` inferred; pull same set
5. **v1.17.0 (Nov 2020)** - URL slug `v117_0` confirmed exists; pull same set
6. **DataLumos project 218382** - second copy of whatever versions it carries, as preservation insurance

For each version, target the same minimum file set:

- `NRI_Table_Counties.zip`
- `NRI_Table_CensusTracts.zip`
- `NRI_Table_States.zip` (where present)
- `NRI_Table_Tribal_Counties.zip` (where present)
- `NRI_Table_Tribal_CensusTracts.zip` (where present)
- technical documentation PDF
- data dictionary CSV
- hazard info CSV

Shapefiles and geodatabases are nice-to-have but redundant with the CSV tables if geometry is already published in repo geometry.

### Why this approach

- Once we have all five versions on disk, we can build a `fema_nri` source as a temporal series rather than a series of "snapshot" sources
- Future maintenance reduces to monitoring `hazards.fema.gov/nri/updates` (or its mirror equivalent) and pulling the next slug when a new version drops
- The live-collector path becomes "fetch the latest archive slug on a schedule", not "re-derive what we missed"

### Mirror discipline

- Always preserve a second copy from a non-FEMA mirror (DataLumos, NOAA Digital Coast, or Esri) at the same time we pull from the FEMA primary
- Treat FEMA primary as untrustworthy for long-term retrieval; treat ArcGIS Hub as commercially backed and likely durable
- Wayback Machine is the fallback when both primary and mirror are gone

See the internal federal-data preservation mirror notes for the full network reference.

---

## NRI Backfill Execution Log (2026-04-30)

### Outcome

`hazards.fema.gov` confirmed broken at the TLS layer from this machine (curl exit 35; PowerShell `Authentication failed because the remote party has closed the transport stream`). `www.fema.gov` works fine; the OpenFEMA API at `www.fema.gov/api/open` is reachable but does not expose NRI as an OpenFEMA dataset.

Working route: **`services.arcgis.com/XG15cJAlne2vxtgt`** (FEMA's public ArcGIS REST host) hosts every historical NRI version concurrently as separate FeatureServer endpoints. No rate limit hit. Script: `county-map-private/data_converters/downloaders/download_fema_nri_full_history.py`.

### Endpoint mapping (confirmed working)

| Version | Slug | Service prefix |
|---|---|---|
| v1.17.0 (Nov 2020) | `v117_0` | `NRI_<Table>_v117` |
| v1.18.1 (Nov 2021) | `v118_1` | `NRI_<Table>_Prod_v1181_view` |
| v1.19.0 (Mar 2023) | `v119_0` | `National_Risk_Index_<Table>_(March_2023)` |
| v1.20 (Dec 2025) | `v120_0` | `National_Risk_Index_<Table>` (no suffix) |

### Downloaded inventory

Stored at `county-map-raw/Raw data/fema_nri/<slug>/`:

| Version | Table | Rows | Cols | Size |
|---|---|---:|---:|---:|
| v1.17.0 | counties | 3,142 | 353 | 13 MB |
| v1.17.0 | census_tracts | 72,739 | 363 | 282 MB |
| v1.17.0 | hazard_info | 18 | 14 | 2 KB |
| v1.18.1 | counties | 3,142 | 367 | 14 MB |
| v1.18.1 | census_tracts | 72,739 | 369 | 305 MB |
| v1.18.1 | hazard_info | 18 | 13 | 2 KB |
| v1.18.1 | states | 51 | 232 | 161 KB |
| v1.18.1 | summary_stats | 52 | 27 | 21 KB |
| v1.19.0 | counties | 3,231 | 467 | 19 MB |
| v1.19.0 | census_tracts | 85,154 | 469 | 471 MB |
| v1.19.0 | hazard_info | 18 | 13 | 2 KB |
| v1.19.0 | states | 56 | 315 | 248 KB |
| v1.19.0 | summary_stats | 57 | 14 | 10 KB |
| v1.20 | counties | 3,232 | 467 | 20 MB |
| v1.20 | census_tracts | 85,154 | 469 | 484 MB |
| v1.20 | hazard_info | 18 | 13 | 2 KB |
| v1.20 | states | 56 | 315 | 256 KB |
| v1.20 | summary_stats | 57 | 14 | 10 KB |
| v1.20 | tribal_counties | 1,232 | 476 | 8 MB |
| v1.20 | tribal_census_tracts | 3,364 | 478 | 21 MB |

Total: ~1.6 GB across 21 tables, 4 versions. Each table also has a `<table>.meta.json` sidecar capturing field list, service URL, expected/actual row count, and timestamp. Per-version `_version_log.json` and a top-level `_download_log.json` summarize the run.

### Schema progression observed

- **v1.17 -> v1.18.1**: +14 county fields, +6 tract fields. States and summary_stats first appear in v1.18.1 on Esri.
- **v1.18.1 -> v1.19.0**: +100 county fields, +100 tract fields. This is the SoVI -> CDC SVI migration plus precalculated EAL rates landing. Geographies refresh: counties 3,142 -> 3,231 (territories), tracts 72,739 -> 85,154 (2020 census tract refresh + territories), states 51 -> 56 (territory addition).
- **v1.19.0 -> v1.20**: schema identical (467/469 cols). Counties 3,231 -> 3,232 — one new county, almost certainly the Connecticut Planning Region restructure. Tribal layers (`tribal_counties`, `tribal_census_tracts`) first appear at v1.20 on Esri.

### Still missing

- **v1.18.0 (Aug 2021)**: Esri only hosts the v1.18.1 patch, not the original v1.18.0. Difference between 1.18.0 and 1.18.1 is documented as a minor patch in the FEMA changelog. Worth a Wayback Machine pass on the FEMA archive page if a true 1.18.0 snapshot is needed; otherwise treat 1.18.1 as the canonical 1.18-line release.
- **Pre-2025 tribal layers**: only v1.20 has tribal layers in the Esri service. The v1.19.0 (March 2023) FEMA archive shapefile we already have on local disk includes `NRI_Table_Tribal_Counties.zip` and `NRI_Table_Tribal_CensusTracts.zip` from the original FEMA download — those cover the v1.19 tribal slice, so this gap is already filled by the existing local archive, not by the new ArcGIS pull.

### Implication for live-collector posture

NRI maintenance from here is just "watch for the next non-suffixed `National_Risk_Index_<Table>` schema bump, or watch for a new `(<Month_Year>)`-tagged service to appear, then re-run the downloader with the new version slug added". No more catch-up backfill needed. This is the "we have complete history, now stay current" posture the user asked for.

---

## ClimRR Backfill Execution Log (2026-04-30)

### Outcome

Original local Fatemeh ClimRR copy is the AT&T Box bulk drop circa 2023: 11 separate CSVs covering temperature, precipitation, wind, drought, FWI, heat index, degree days, all on the WRF 12 km vector grid (62,834 / 62,919 cells). Time-shape: historical baseline + RCP4.5/RCP8.5 mid/end-century (CMIP5 generation).

The current Argonne ClimRR portal serves substantially more on its public ArcGIS REST host at `disgeoportal.egs.anl.gov/arcgis/rest/services/`:

- a single 562-field master table (`Hosted/All_Climate_Variables_for_Report_Generation_WBGT`) joining everything in one row per grid cell
- a 227-field `CCRDS/Crossmodel` master that supersedes our 11 separate CSVs
- new hazard families not in the original drop: **inland flood, WBGT, freeze-free days, plant hardiness, heat IDF curves**
- CMIP6 SSP245/SSP585 scenarios alongside CMIP5 RCP scenarios (HI_AllClimateVariables, HI_MeanTemp_*, HI_PrecipitationRate_*)

Working route: `disgeoportal.egs.anl.gov/arcgis/rest/services` is publicly readable; FeatureServer endpoints support paginated `query?outFields=*` extraction. Script: `county-map-private/data_converters/downloaders/download_climrr_full.py`.

### Downloaded inventory

Stored at `county-map-raw/Raw data/climrr_2026/`:

| Service | Type | Rows | Cols | Size | Note |
|---|---|---:|---:|---:|---|
| all_climate_variables_wbgt | CSV | 62,834 | 562 | 302 MB | master joined CMIP5+WBGT, supersedes 11 original CSVs |
| crossmodel_attributes | CSV | 62,834 | 227 | 144 MB | CMIP5/RCP master |
| crossmodel_geometry | GeoJSON | 62,834 | (geometry) | 531 MB | grid cell polygons; canonical `Crossmodel` geometry layer |
| hi_all_climate_variables | CSV | 54 | 223 | 0.1 MB | CMIP6 SSP245/SSP585 aggregated stats (small lookup table) |
| freeze_free_days_gc2 | CSV | 63,524 | 100 | 43 MB | freeze-free days hazard, GridCells2 grid |
| idf_curves_heat_gc2 | CSV | 63,558 | 129 | 89 MB | mid-century RCP8.5 heat IDF curves (1-7 day x 2/5/10/25/50-yr return x 5/50/95 percentile) |
| idf_curves_heat_hist_gc2 | CSV | 63,558 | 129 | 76 MB | historical baseline heat IDF curves |
| inland_flood_pct_change_50yr | CSV | 82,389 | 48 | 59 MB | 50-yr return inland flood percent change in depth, by HUC12 watershed |
| tribal_boundaries_2021 | CSV | 867 | 5 | 65 KB | tribal boundary join layer |
| ClimRR_Metadata_Data_Dictionary_2025-02-18.pdf | PDF | -- | -- | 714 KB | newer Feb 18, 2025 metadata dictionary |

Total: ~1.25 GB across 9 services, 1 metadata PDF. Each table also has a `<service>.meta.json` sidecar capturing field list, service URL, expected/actual row count, and timestamp. Top-level `_download_log.json` summarizes the run plus the MapServer-only gap list.

### MapServer-only gaps (not bulk-extractable via FeatureServer)

These layers exist on the portal as MapServer raster tiles only, with no FeatureServer mirror. Bulk numeric extraction would require ImageServer sampling per grid cell, raster export via ArcGIS Pro, or direct contact with Argonne (CCRDS@anl.gov) for the source CSVs:

- WBGT_Days_Above_Threshold_Hist_MidC
- WBGT_Daytime_Hours_Above_Threshold_Hist_MidC
- WBGT_Mean_Daily_Max_Hist_MidC
- PlantHardiness_GC2
- Inland_Flood_Historical_Median_{10,25,50}_year (3 layers)
- Inland_Flood_Mid_century_Median_{10,25,50}_year (3 layers)
- Inland_Flood_Change_in_flood_depth_Median_{10,25}_year (50-year IS available as FS)
- HI_MeanTemp_Fahrenheit_*  (16 seasonal/SSP scenario MapServers)
- HI_PrecipitationRate_*    (15 seasonal/SSP scenario MapServers)
- Wildfire_Percentile_Bins_Decadal
- Wildfire_Percentile_Bins_Seasonal

The aggregated FeatureServer pulls (`all_climate_variables_wbgt` for WBGT means, `inland_flood_pct_change_50yr` for the 50-year flood, `hi_all_climate_variables` for HI_*) cover most of the substantive content of these MapServer layers; the raster MapServer copies are the user-facing tiles, not the underlying numeric primary. So the gap is "we have every variable in joined-table form, we don't have the per-pixel raster export of each variable rendered separately" — usually not load-bearing for analytic use.

### Local-copy disposition

The original 11 Fatemeh CSVs are now **superseded** by `all_climate_variables_wbgt.csv` (everything joined plus WBGT) and `crossmodel_attributes.csv` (the CMIP5/RCP master without WBGT). Recommended posture:

- treat `county-map-raw/Raw data/climrr_2026/` as the canonical ClimRR source going forward
- keep the original Fatemeh `ClimRR/` folder as historical-snapshot insurance, but do not build off it
- the local FireWeatherIndex_Wildfire.csv was correctly noted as a duplicate; ignore both copies in favor of the master table

### Implication for live-collector posture

ClimRR maintenance from here is "re-run the downloader on a schedule and diff the field list against the previous `_download_log.json`". New variables surface as new fields in `all_climate_variables_wbgt`. New MapServer layers surface in the portal search; if any get a FeatureServer twin later, add it to `SERVICES` in the downloader. No more retroactive bulk-CSV diffing across the original 11 files.

The remaining "true backfill" gap is the MapServer-only set above. Decision deferred until a downstream consumer specifically needs raster sampling — most use cases are covered by the FeatureServer joined tables.

---

## CEJST + Future NRI Mirror Backfill (2026-04-30)

### Outcome

Started this as a "preservation insurance" exercise — pull a second copy of CEJST and Future NRI from the PEDP / EELP mirror network in case the local Fatemeh copies get lost. Hash-verified both downloads against the local copies and **discovered the mirrors are not just preservation copies; they are the canonical, more-complete data**. Both should now be treated as primary, with the original Fatemeh copies relegated to historical-snapshot status.

### CEJST mirror snapshot

Source: **Public Environmental Data Partners CloudFront CDN** (`dblew8dgr6ajz.cloudfront.net`). Discovered via the EDGI / PEDP `j40-cejst-2` GitHub Pages downloads page.

Stored at `county-map-raw/Raw data/cejst_mirror/v2.0/`:

| File | Bytes | SHA256 vs local |
|---|---:|---|
| 2.0-communities.csv | 45,316,854 | DIFFER (216 rows in 3 cols) |
| 2.0-communities.xlsx | 38,378,818 | DIFFER (likely same data, xlsx encoding) |
| 2.0-shapefile-codebook.zip | 367,608,133 | DIFFER (likely flows from CSV change) |
| cejst-technical-support-document.pdf | 793,196 | MATCH |
| CEQ-CEJST-Instructions.pdf | 233,861 | MATCH |

### CEJST Mirror Drift

The PEDP CSV has **216 rows with differing values** vs the Jan 2025 Fatemeh local copy. Same 74,134 row count, same 136-column schema — only values changed. Affected columns:

- `Interpolated number of off-campus students in poverty`
- `Share of the tract's land area that is covered by impervious surface or cropland as a percent`
- `Percent of the Census tract that is within Tribal areas`

Plausible explanation: CEQ pushed a small data-correction patch between the original Dec 2024 v2.0 release and the Jan 22, 2025 White House removal date, and PEDP captured that patched build. The local Fatemeh copy ("21 Jan 2025" folder) was downloaded one day before removal and may pre-date the patch by hours.

CEJST v1.0 is **not** mirrored on the PEDP CDN (only `1.0-shapefile-codebook.zip` returns 200; everything else returns 403). PEDP curated only the latest release. Local Fatemeh `1.0-*` files remain the only copy of v1.0 for our purposes.

### Future NRI mirror snapshot

Source: **fulton-ring/nri-future-risk** GitHub repo (the EELP-pointed recreation team's underlying repo) plus the **EELP Harvard Law tech doc PDF**.

Stored at `county-map-raw/Raw data/future_nri_mirror/`:

| File | Bytes | SHA256 vs local |
|---|---:|---|
| NRI_Data_Dictionary.xlsx | 26,191 | MATCH |
| NRI_Future_Risk_Master_Datasheet_12052024.xlsx | 3,996,952 | DIFFER (+10 columns) |
| combined_nri_counties_borders.json | 28,610,431 | MATCH |
| tiny-usa-county-borders.json | 3,436,564 | MATCH |
| NRI_Future_Risk_Technical_Document.pdf (EELP) | 4,303,946 | (no local equivalent; new) |
| 16 hazard PNGs (CFLD/DRGT/EXHT/HRCN/WFIR × PALR/PRISK) | varies | (no local equivalent; new) |

### Future NRI Mirror Enrichment

The fulton-ring master datasheet has the **same 3,231 rows** as the local copy, but **191 columns vs the local 181** — 10 extra columns:

| Group | Added columns |
|---|---|
| Standard NRI ID columns | `OBJECTID`, `NRI_ID`, `STATE`, `STATEABBRV`, `STCOFIPS` |
| Coastal Flooding hazard family | `CFLD_EALT`, `CFLD_EALR`, `CFLD_RISKV`, `CFLD_RISKR`, `CFLD_RISKS` |

The ID columns make the dataset directly joinable to the baseline FEMA NRI tables (which use `NRI_ID` and `STCOFIPS` as keys). The Coastal Flooding hazard family adds CFLD-prefixed Expected Annual Loss and Risk values that the original FEMA "Future Risk Index" prototype omitted — the `CFLD` hazard was listed in the methodology but not exposed in the public data file. Whether this is genuine FEMA-internal data that EELP/Fulton-Ring obtained, or an EELP-side enrichment derived from FEMA NRI baseline coastal flood + climate scenario projection, is documented in their NRI_Future_Risk_Technical_Document.pdf — read that before relying on those columns.

The 16 hazard PNGs (CFLD_PALR / CFLD_PRISK / DRGT_PALR / DRGT_PRISK / etc.) are pre-rendered choropleth maps the recreation tool ships with. Useful as visual sanity checks; not load-bearing data.

### Disposition

For both sources, the mirror copy is now the **canonical** version:

- `cejst_mirror/v2.0/` supersedes the Jan 2025 Fatemeh local copy for v2.0 work; the local copy stays as a "as of Jan 21, 2025" historical snapshot
- `future_nri_mirror/` supersedes the Fatemeh `Future NRI/` copy for any actual import work; the EELP technical doc PDF is the authoritative documentation

### Implication for live-collector posture

CEJST and Future NRI both have only one canonical release each (v2.0 / Dec 2024). There is no future-release watch needed; both source agencies have stopped publishing. Maintenance burden = zero. Any future drift will come from the **mirrors** (PEDP / EELP / Fulton-Ring), not from the original government source. Re-pull mirrors on the same monthly cadence as FEMA NRI to capture any further patch-style corrections.

This completes the completeness sweep across the Fatemeh batch. All sources are now in "complete history, monitor for drift" posture.

---

---

## QA Progress Log

### 1. Future NRI - Stage 1 COMPLETE (2026-05-06)

Converter: `county-map-private/data_converters/converters/convert_future_nri.py`
Output: `county-map-data/countries/USA/future_nri/USA.parquet`
Metadata: `county-map-data/countries/USA/future_nri/metadata.json`
Reference: `county-map-data/countries/USA/future_nri/reference.json`
QA suite: `county-map-private/build/qa/suites/future_nri_v1.json`

Parquet shape: 3,231 rows, 155 columns (7 ID/ref cols + 148 numeric metric cols)
Loc_id format: `USA-{state_abbr}-{county_3digit_fips}` via `build_usa_loc_id()` from `us_fips.py`
Loc_id audit: 99.88% coverage (3,227/3,231). 4 mismatches are known FIPS migration issues:
  - USA-AK-063, USA-AK-066: 2019 Alaska split of Valdez-Cordova into Chugach + Copper River
  - USA-VA-159, USA-VA-161: Virginia edge cases
  All are documented exceptions, not data quality issues. Passes 90% threshold.

Schema checks passed:
  - Required columns present: loc_id, source
  - Non-temporal source: no timestamp (correct for scenario dataset)
  - 0 null loc_ids, 0 duplicate loc_ids
  - All 148 metric columns are float64
  - No 0-sentinel values (NRI uses NaN for missing; negative values are expected for no-hazard counties in NRI baseline)

Stage 1 gate: PASS. Ready for Stage 2 (push to staging) after catalog entry.

Stage 2 complete (2026-05-06):
  - wip_catalog.json updated (no pack_id, release_state=can_share)
  - Pushed to staging: countries/USA/future_nri/ (USA.parquet, metadata.json, reference.json, wip_catalog.json)

Historical note:

- the first workable QA shape was one combined `nri` pack containing `fema_nri` + `future_nri`
- that was useful as a bridge, but it was not the final public form
- on 2026-05-07 the pack moved to a hazard-split multi-source structure instead

---

### 2. FEMA NRI v1.20 - Stage 2 COMPLETE, Stage 3A NEXT (2026-05-06)

Converter: `county-map-private/data_converters/converters/convert_fema_nri_v120.py`
Output: `county-map-data/countries/USA/fema_nri/USA.parquet`
Metadata: `county-map-data/countries/USA/fema_nri/metadata.json`
Reference: `county-map-data/countries/USA/fema_nri/reference.json`
QA suite: `county-map-private/build/qa/suites/fema_nri_v1.json`

Parquet shape: 3,232 rows, 104 columns (8 ID/ref cols + 96 numeric metric cols)
Loc_id format: `USA-{state_abbr}-{county_3digit_fips}` via `build_usa_loc_id()` from `us_fips.py`
Loc_id audit: 3,219/3,232 matched (99.6%). 13 mismatches are known geography migration cases, not converter failures:
  - USA-AK-063, USA-AK-066: 2019 Alaska Valdez-Cordova borough split
  - USA-VA-159, USA-VA-161: Virginia edge cases
  - USA-CT-110 through USA-CT-190 (9 entries): Connecticut moved from 8 historical counties to 9 planning regions for the 2020 census
Passes the 90% threshold.

Converter output:
  - 3,232 counties with valid FIPS
  - 0 null loc_ids, 0 duplicate loc_ids
  - 18 hazards x 4 suffixes (RISKS, RISKV, EALT, EALR) + composite metrics
  - NRI version field: "December 2025"
  - risk_score: mean=50.02, max=100.00 (n=3,144)
  - wfir_risks: 3,143 counties with positive wildfire exposure

Current packaging decision (implemented 2026-05-07):

- the public `nri` pack is now **multi-source by hazard**, analogous to `un_sdg` being multi-source by goal
- each NRI hazard source is self-contained and duplicates the shared composite / vulnerability / resilience context fields on purpose
- hazards with Future NRI coverage include both baseline + future fields in the same hazard source
- hazards without Future NRI coverage stay baseline-only

Implemented member sources:

- `nri_avalanche`
- `nri_coastal_flood`
- `nri_cold_wave`
- `nri_drought`
- `nri_earthquake`
- `nri_extreme_heat`
- `nri_hail`
- `nri_hurricane`
- `nri_ice_storm`
- `nri_inland_flood`
- `nri_landslide`
- `nri_lightning`
- `nri_strong_wind`
- `nri_tornado`
- `nri_tsunami`
- `nri_volcano`
- `nri_wildfire`
- `nri_winter_weather`

Coverage rule:

- `nri_coastal_flood`, `nri_drought`, `nri_extreme_heat`, `nri_hurricane`, and `nri_wildfire` include future scenario fields
- all other hazard members are baseline-only because the preserved Future NRI mirror has no future counterpart for them

Why this is the final public shape:

- it keeps the packs page readable
- it matches user intent better than one giant baseline source plus one giant future source
- it makes Research corpus building more targeted (`load flood risk` instead of `load all NRI risk`)
- it preserves the current-vs-future pairing inside each hazard where future data exists
- the duplication cost is acceptable because the shared context fields are small and make each hazard source self-contained

Metadata / reference decision:

- document the hazard-split structure explicitly in `reference.json` / `metadata.json`
- make it clear this is SDG-style multi-source packaging: one public `nri` pack, many member sources inside it
- keep duplicated context fields in each hazard source and explain that duplication as intentional

Current implementation status:

- the public `nri` pack is now the hazard-split form
- the old combined `fema_nri` and `future_nri` sources are retained only as internal staging/build sources
- `future_nri` PALR / DELTAR fields are preserved as text labels plus `0-5` ordinal `*_band` helpers

QA status:

- legacy combined-source suites still exist: `fema_nri_v1.json` and `future_nri_v1.json`
- those are now transitional checks against the staging sources, not the final public pack shape
- final public QA was moved to the hazard-member `nri` pack shape
- Reminder: suite files must use `query` as the case key, not `prompt`

Final reviewed QA state as of 2026-05-07:

- Explore suite: `25` questions total
  - broad suite run + targeted reruns used for cost control
  - final targeted fixes cleared:
    - `NRI-P-005` earthquake expected annual loss
    - `NRI-P-007` hail risk score defaulting
    - `NRI-P-021` projected wildfire map routing
- Research suite: `15` questions total
  - one full-suite run completed after the final state-filter and prompt/tool-schema fixes
  - focused reruns were used earlier to stabilize Florida coastal flood and other scenario/state cases before paying for the full run

What is considered closed:

- hazard-member routing works for the public `nri` pack
- future-covered hazards route through their own member sources
- baseline-only hazards answer honestly as baseline-only
- Research and Explore both behave credibly enough to move into publishing steps

What is not yet claimed from this session:

- cloud-side release-marker / R2 publishing verification
- `pack_release_status.py` was attempted locally, but the storage check was blocked by network/socket access to R2

Next steps:
- run the release-marker / storage visibility check in a network-enabled environment
- continue through the normal publishing steps once cloud visibility is confirmed

---

## Import Direction (updated 2026-06-25)

Done:

- `FEMA NRI` - 18-hazard published pack (`nri_*`); includes Future NRI fields for 5 hazards
- `CEJST` - published and downloadable; the remaining work is QA polish and broader synonym/routing coverage
- `NSS Shelters Pattern B` - local Pattern B build complete from the live FEMA layer-5 inventory; conservative QA post-pass recovered direct county matches and excluded the small clearly-bad source bucket

Next actionable (no blockers):

1. `EPA Smart Location` - block-group walkability/accessibility; static v3.0, geometry is supported, no special setup needed
2. NSS local QA follow-up - remaining retained state-level rows are mostly coastline / territory / island cases; the clear junk bucket is already separated into `questionable_rows.csv`

Needs a decision before starting:

3. `ClimRR` - Decide: grid-cell geometry layer (new `climrr_grid` geometry pack) vs pre-aggregate to county/tract for first product. Grid path is more correct but requires building a new geometry layer. County/tract aggregation is faster but loses spatial precision.

For each remaining source:

**NSS Shelters Pattern B:**
- Input: prefer a fresh live FEMA snapshot at import time; use the local folder snapshot only as fallback / historical insurance
- Output: `countries/USA/nss_shelters/shelters.parquet`
- Current local output: `68,901` rows, `0` unmatched `loc_id`, with `67,660` tract-level anchors, `926` county-level anchors, and `315` retained state-level anchors
- Focused local audit extracts:
  - `docs/other/nss_shelters_audit/state_only_fallback_rows.csv`
  - `docs/other/nss_shelters_audit/zero_zero_coordinate_rows.csv`
- Review outputs from the conservative QA pass:
  - `county-map-data/countries/USA/nss_shelters/questionable_rows.csv`
  - `county-map-data/countries/USA/nss_shelters/state_fallback_review_rows.csv`
- Remaining QA questions: whether any of the retained coastline / territory / island state-level fallbacks should be improved later with geometry/runtime tuning
- Pairs with: `cejst_classification` (is the shelter tract disadvantaged?), `nri_*` (hazard risk for the shelter location)

**EPA Smart Location:**
- Input: `EPA_SmartLocationDatabase_V3_Jan_2021_Final.csv`
- 220,740 rows, 117 cols, block group scale (`GEOID10`/`GEOID20`)
- Key decision: block-group loc_id uses `USA-{state}-{county3}-{tract6}-{bg1}` format; confirm with geometry
- Metric families: D1 density, D2 diversity, D3 design, D4 transit, D5 destination access, NatWalkInd composite

**ClimRR:**
- Input: `county-map-raw/Raw data/climrr_2026/all_climate_variables_wbgt.csv` (562 fields, 62,834 rows)
- Primary key: `Crossmodel` (grid cell ID)
- Grid geometry: `crossmodel_geometry.geojson` (531 MB) already downloaded
- Decision: publish `climrr_grid` as a new geometry type, OR aggregate to county/tract as first pass

---

## Home Machine Comparison

When back on the home machine with the larger raw-data archive, compare that older collection against this Fatemeh folder.

Main comparison groups:

1. HVRI family
   - `BRIC`
   - `SoVI`
   - `HazDash`
   - `SHELDUS`

2. FEMA family
   - prior NRI county material
   - prior NRI tract material
   - this folder's 2023 FEMA NRI complete archive
   - this folder's 2024 FEMA NRI tract table
   - this folder's Feb 2025 FEMA NRI county/tract refresh
   - this `Future NRI`
   - this shelter system material

3. Climate projection family
   - `ClimRR`
   - `Future NRI`
   - any existing climate/weather projection imports or notes

4. Justice / built-environment family
   - `CEJST`
   - `EPA Smart Location`
   - related justice / vulnerability / built-form sources

For each overlap, record:

- source name
- file path
- version / release date
- geometry level
- whether it already has code/notes/import traces

Then classify each as:

- new and high priority
- duplicate but newer
- duplicate and already covered
- research-only / not worth importing now

---

## Related Families and Prior Repo References

Likely adjacent external family:

- HVRI data/resources:
  - `https://sc.edu/study/colleges_schools/artsandsciences/centers_and_institutes/hvri/data_and_resources/`

Relevant external source families:

- `BRIC`
- `SoVI`
- `HazDash`
- `SHELDUS`

Strong existing repo breadcrumbs:

- disaster upgrades archive (internal historical reference)
  - has prior notes on `BRIC`, `SoVI`, `SHELDUS`, `HazDash`

- USA pack profile (internal historical reference)
  - references `SoVI`, `SHELDUS`, `BRIC`
  - notes that FEMA NRI already carries county-level social vulnerability/resilience context

- [DATA_PREPARATION.md](../DATA_PREPARATION.md)
  - includes a `sovi_score` metric reference

- `convert_nri_tracts.py` (private production converter reference)
  - includes `SOVI_SCORE` mapping in code

Repo-memory split:

- older explored family:
  - `BRIC`
  - `SoVI`
  - `SHELDUS`
  - `HazDash`
- newer session discoveries:
  - `FEMA NRI archive`
  - `ClimRR`
  - `CEJST`
  - `EPA Smart Location`
  - `National Shelter System Facilities`
  - `Future NRI`

---

## External References

- FEMA National Risk Index:
  - `https://www.fema.gov/national-risk-index`
- FEMA shelter service:
  - `https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer`
- FEMA shelter full inventory layer (`Shelter Locations`):
  - `https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer/5`
- FEMA open shelters service:
  - `https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer/0`
- ArcGIS overview item:
  - `https://www.arcgis.com/home/item.html?id=d000037396514f70a2ba3683e037caee`
- FEMA NSS fact sheet:
  - `https://www.fema.gov/pdf/media/factsheets/2011/fema_national_shelter_system.pdf`
- EPA Smart Location overview:
  - `https://www.epa.gov/smartgrowth/smart-location-mapping`
- EPA Smart Location V3 user guide:
  - `https://www.epa.gov/system/files/documents/2023-10/epa_sld_3.0_technicaldocumentationuserguide_may2021_0.pdf`
- ClimRR portal:
  - `https://disgeoportal.egs.anl.gov/ClimRR/`
- ClimRR metadata/data dictionary Box link from local README:
  - `https://anl.box.com/s/hmkkgkrkzxxocfe9kpgrzk2gfc4gizp8`
- Future Risk Index technical documentation mirror used during research:
  - `https://eelp.law.harvard.edu/wp-content/uploads/2025/03/NRI_Future_Risk_Technical_Document.pdf`
- Overture Maps Places:
  - `https://docs.overturemaps.org/guides/places/`
- Overture Places schema:
  - `https://docs.overturemaps.org/schema/reference/places/place/`
- OpenStreetMap tourism tags:
  - `https://wiki.openstreetmap.org/wiki/Key:tourism`
- Kaggle TBO hotels dataset to inspect as a possible supplement:
  - `https://www.kaggle.com/datasets/raj713335/tbo-hotels-dataset`

---

## Session Notes

- `CONTEXT.md` was updated to work more clearly as an index
- `GEOMETRY.md` was clarified to distinguish model/examples from live operational inventory
- `data_pipeline.md` and `data_import.md` were clarified to distinguish deep explanation vs quick-reference checklist
- cloud geometry was checked via `r2_sync.py`
- `FEMA NRI archive` and `ClimRR` were added after deeper inventory of `C:\Users\Bryan\Desktop\fatemah`

---

*Created: 2026-04-14*
