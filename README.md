# DaedalMap

DaedalMap is a map-first geographic query engine. This repository is the open app/runtime for developers who want to run it locally, self-host it, point it at their own data, or extend it with compatible geographic datasets.

Public surfaces:
- App: `https://app.daedalmap.com`
- Website/docs: `https://daedalmap.com`

If you are using this public GitHub repo as a self-host/local runtime, the practical setup contract right now is:
- a local data location (`DATA_ROOT`, unless you use the default app-data path)
- an LLM API key (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`)

Supabase and hosted account wiring are optional for self-host use.

## What This Repo Is For

Use this repo if you want to:
- run the DaedalMap runtime on your own machine or server
- point the runtime at local data or a cloud-backed data plane you control
- inspect or extend the open runtime behavior
- build compatible geographic datasets and pack-style workflows around the engine

Typical use cases:
- show earthquakes, floods, wildfires, storms, volcanoes, or tsunamis for a place and time window
- compare population, economic, and disaster context in the same workflow
- move between local development, self-hosted runtime operation, and hosted-style runtime behavior without changing the basic mental model

DaedalMap itself is built around three ideas:
- ask in plain language instead of assembling GIS workflows first
- keep the map as the primary interface, not an afterthought
- separate runtime delivery from maintained data-pack delivery

## Data Coverage

The hosted runtime ships with 40+ curated sources across disasters, demographics, economics, and climate. Coverage below reflects the current maintained pack inventory.

### Global Disasters

| Source | Scale | Time Range |
|--------|-------|------------|
| USGS Earthquakes | 1M+ events | 2150 BC - present |
| IBTrACS Hurricanes/Cyclones | 13K storms | 1842 - present |
| NOAA Tsunamis | 2.6K events | 2000 BC - present |
| Smithsonian Volcanoes | 11K eruptions | Holocene |
| Global Wildfires | 940K events/year | 2002 - 2024 |
| USA/CAN Tornadoes | 81K events | 1950 - present |
| Global Floods | 4.8K events | 1985 - 2019 |
| Global Landslides | 45K events | 1760 - present |

Disaster events include 22M+ geographic location relationships and 566K cross-disaster links (aftershocks, triggered events).

### Global Indicators

| Source | Countries | Years | Category |
|--------|-----------|-------|----------|
| Our World in Data CO2 | 217 | 1750 - 2024 | Environment |
| WHO Health Statistics | 198 | 2015 - 2024 | Health |
| IMF Balance of Payments | 195 | 2005 - 2022 | Economy |
| UN Sustainable Development Goals | 200+ | 2000 - 2023 | SDGs 1-17 |
| Eurostat Demographics | 37 European countries | 2000 - 2024 | Demographics |

### Country-Specific Sources

| Country | Source Count | Examples |
|---------|-------------|---------|
| USA | 15+ | Census, FEMA National Risk Index, NOAA storms |
| Canada | 3 | Statistics Canada, NRCan earthquakes, drought |
| Australia | 2 | ABS population, BOM cyclones |

### Disaster Display

Disasters are displayed with animated, type-specific rendering:
- Point + radius: earthquakes, volcanoes, tornadoes
- Track/trail: hurricanes and cyclones
- Radial wave: tsunamis
- Polygon fill: wildfires, floods

## Current Runtime Shape

DaedalMap now treats runtime behavior as a 2-axis matrix:

- `INSTALL_MODE`
  - `local` = local app/runtime install
  - `cloud` = hosted/server deployment
- `RUNTIME_MODE`
  - `local` = query local data
  - `cloud` = query managed cloud-backed data via local cache + DuckDB httpfs

Supported combinations:
- `local install + local data`
- `local install + cloud data`
- `cloud install + cloud data`

Not supported as a first-class runtime shape:
- `cloud install + local data`

The current hosted/runtime direction is:
- a hosted app runtime
- object storage for runtime data
- optional auth and account services

In `RUNTIME_MODE=cloud`, the runtime:
- eagerly syncs only small metadata files to local cache
- queries parquet directly from object storage via DuckDB `httpfs`
- does not sync the full parquet tree at startup

Hosted deployment topology, release lanes, and operator control-plane details
belong in private deployment notes.

That means the same codebase can be used in:
- full local-data mode
- hosted-style cloud-data mode

## Guest And Logged-In Behavior

Guest users can open the app and try the public workflow without logging in.

Logged-in users currently get:
- authenticated session identity
- user-scoped frontend persistence
- user-scoped backend session cache
- account-owned settings and login on `daedalmap.com`

The public app no longer owns the account/settings UI.
`app.daedalmap.com` stays focused on the runtime and map engine, while `.com`
owns login, account, billing, and admin/runtime control-plane views.

## Quick Start

### 1. Install dependencies

```powershell
cd county-map
pip install -r requirements.txt
```

### 2. Add environment variables

Create a `.env` file for local development. The minimum useful local setup is:

```env
ANTHROPIC_API_KEY=your_key_here
DATA_ROOT=C:/path/to/your/local/data
```

You can use `OPENAI_API_KEY` instead of `ANTHROPIC_API_KEY` if that is your preferred provider.
If you leave `DATA_ROOT` blank, DaedalMap uses the default local app-data path and expects your data to live there.

Hosted-style object-storage configuration is intentionally deployment-specific.
For public self-hosting, start with local data. Operators who run a cloud-backed
deployment should provide their own object-storage bucket, endpoint, and
credentials through environment variables.

Most local users should leave these blank unless they intentionally want overrides:

```env
DATA_ROOT=
APP_URL=
SITE_URL=
```

What they mean:
- `DATA_ROOT`
  only used in `RUNTIME_MODE=local`; leave blank to use the default local app-data folder
- `APP_URL`
  optional advertised app URL; leave blank for normal local runs
- `SITE_URL`
  optional website/docs/account URL override; leave blank for normal local runs

If you are configuring your own hosted deployment, set:

```env
INSTALL_MODE=cloud
RUNTIME_MODE=cloud
PORT=7000
```

If you want optional Supabase-backed auth locally:

```env
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
```

Keep service-role keys server-side only. They are not needed for ordinary local
evaluation.

### 3. Run the app

```powershell
python app.py
```

Open:
- `http://localhost:7000`

## API Discovery

The runtime exposes discovery and query endpoints on your local instance.

Discovery (no auth, no payment):

- `GET /api/v1/guide`
- `GET /api/v1/catalog`
- `GET /api/v1/packs/{pack_id}`

Execution:

- `POST /api/v1/query/dataset`

Self-host instances return `commercial_access_unavailable` for the paid execution lane unless a commercial verifier is configured. Discovery endpoints work without additional setup.

For managed data access via the hosted API or MCP, see [daedalmap.com/docs/for-agents](https://daedalmap.com/docs/for-agents).

## Data Resolution

The runtime resolves behavior from two explicit modes:

1. `INSTALL_MODE`
   controls deployment defaults like writable directories and default URLs
2. `RUNTIME_MODE`
   controls the data plane

Data mode behavior:

1. `RUNTIME_MODE=local`
   uses `DATA_ROOT`
2. `RUNTIME_MODE=cloud`
   uses the hydrated local cloud cache as `DATA_ROOT`

Default local writable folders on Windows:
- `CONFIG_DIR=%LOCALAPPDATA%\DaedalMap\config`
- `STATE_DIR=%LOCALAPPDATA%\DaedalMap\state`
- `CACHE_DIR=%LOCALAPPDATA%\DaedalMap\cache`
- `LOG_DIR=%LOCALAPPDATA%\DaedalMap\logs`
- `PACKS_ROOT=%LOCALAPPDATA%\DaedalMap\packs`
- `DATA_ROOT=%LOCALAPPDATA%\DaedalMap\data`

In hosted/cloud mode:
- metadata is cached locally
- parquet is queried remotely from object storage

That makes local cloud-mode testing useful for reproducing hosted-runtime behavior before deploy.

Important note:
- the current public repo does not include a bundled `data/` demo tree
- a source checkout therefore needs either `DATA_ROOT` in `local` mode, or `RUNTIME_MODE=cloud` with cloud storage configured
- for a usable chat experience, you should also set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

## Data And Pack Direction

The old “demo data folder plus converters” framing is no longer the whole story.

The current direction is:
- the engine stays open
- maintained data is packaged as packs
- packs are validated and promoted with explicit release gates
- runtime catalogs eventually depend on pack availability, installation, and entitlement state

Key concepts:
- `available packs`
- `installed packs`
- `entitled packs`
- `active runtime catalog`

These are intentionally distinct.

## Explore And Research Contract

Explore chat and Research chat use different discovery paths:
- Explore starts from the runtime catalog, then selects sources.
- Research starts from the active corpus manifest or loaded artifacts, then selects sources.

After a specific source is selected, they should follow the same source contract:
- source-level `temporal_coverage` is discovery guidance
- metric-level `metrics.{metric_id}.years` is the execution truth
- default year windows, slider bounds, and metric year ranges should clamp to the selected metric when available

That shared source-specific logic now lives in [mapmover/source_time_contract.py](mapmover/source_time_contract.py).
Use that helper module for metric-aware year bounds instead of re-implementing time-range logic separately in Explore or Research code paths.

## Settings Page

`/settings` now behaves differently depending on mode:

- hosted/account-aware mode: redirects to the paired account surface
- self-host/local mode: shows local runtime setup guidance

For self-host users, `/settings` is the in-app reminder page for:
- required LLM key setup
- current runtime/data/config paths
- the current state of local data vs future pack install flow

## Useful Paths In This Repo

Important files and folders:
- `app.py` - FastAPI app entrypoint
- `mapmover/` - runtime logic, routes, path helpers, DuckDB helpers
- `static/` - frontend app modules and styles
- `templates/` - app HTML shell
- `supabase_client.py` - auth/control-plane integration
- `docs/` - local documentation for schemas, runtime notes, and reference material

## Documentation In This Repo

Public runtime docs live in [docs/README.md](docs/README.md).

Recommended starting points:
- [docs/LOCAL_AND_HOSTED.md](docs/LOCAL_AND_HOSTED.md) - runtime mode selection and self-host basics
- [docs/DATA_SCHEMAS.md](docs/DATA_SCHEMAS.md) - schema and `loc_id` conventions
- [docs/APP_OVERVIEW.md](docs/APP_OVERVIEW.md) - higher-level runtime/app overview

## Local Development Modes

Useful local modes:

1. Full local-data mode
- points at your local `DATA_ROOT`
- best current self-host mode for GitHub users

2. Hosted-style S3 mode
- local server, but object-storage-backed data path
- best for reproducing hosted runtime behavior before deploy

3. Installed/runtime-pack mode
- planned product direction beyond raw source checkout
- engine/runtime installed separately from data packs
- pack selection and updates handled outside the repo clone flow

## Contact

Questions, feedback, or self-host issues: support@daedalmap.com

## License

MIT

---

If an agent or tool was pointed at this README for programmable access, use:
- Agent docs: https://daedalmap.com/docs/for-agents
- Machine-readable entry: https://daedalmap.com/llms.txt
