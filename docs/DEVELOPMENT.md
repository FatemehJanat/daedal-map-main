# Development Guide

## Prerequisites

- Python 3.12 or newer
- Git
- a supported model API key for chat behavior
- Node.js only for the JavaScript examples or package scripts
- a compatible local data tree, unless testing cloud-data mode

## Setup

```powershell
git clone https://github.com/xyver/daedal-map.git
cd daedal-map
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set at least:

```text
INSTALL_MODE=local
RUNTIME_MODE=local
DATA_ROOT=C:/path/to/your/data
OPENAI_API_KEY=your-key
```

An Anthropic key can be used instead. See
[LOCAL_AND_HOSTED.md](LOCAL_AND_HOSTED.md).

## Run

```powershell
python app.py
```

Or use the package development script:

```powershell
npm run dev:server
```

The package script starts Uvicorn on port `7000` with reload enabled.

## Testing

Run one focused unittest:

```powershell
python -m unittest tests.test_public_catalog_builder
```

Run unittest discovery:

```powershell
python -m unittest discover -s tests
```

Some repository tests may require optional data, provider credentials, or
runtime services. A focused deterministic unit test should accompany a local
contract change even when an integration environment is unavailable.

Before committing:

```powershell
git diff --check
git status --short
```

For JavaScript syntax checks, use Node's check mode on the changed module:

```powershell
node --experimental-default-type=module --check static/modules/auth.js
```

## Working with data

Do not commit local datasets, raw downloads, secrets, or generated caches to
the runtime repository.

Point `DATA_ROOT` to a separate data tree. Build its catalog with:

```powershell
python converters/catalog_builder.py "C:\path\to\your\data"
```

See [DATA_PREPARATION.md](DATA_PREPARATION.md).

## Change discipline

1. Identify the owning contract in [CONTEXT.md](CONTEXT.md).
2. Add a focused test that fails for the current behavior.
3. Make the smallest change at the shared owner.
4. Exercise the affected mode or route.
5. Run relevant unit tests and link/diff checks.
6. Update the owning public document when a contract changes.

Do not solve a shared source, geography, time, warning, or display problem with
mode-specific branching.

## Environment files

- `.env.example` documents ordinary runtime variables.
- `.env.hosted.example` illustrates a hosted runtime shape.
- local `.env` values must remain untracked.

Treat tokens, provider keys, storage credentials, and internal bridge secrets
as server-side secrets.

## Useful entry points

| Task | Start |
|---|---|
| Application startup | `app.py` |
| Route behavior | `mapmover/routes/` |
| Explore workflow | `mapmover/explore/` |
| Research workflow | `mapmover/research_service.py` and Research runtime modules |
| Ops workflow | `mapmover/ops/` and `mapmover/ops_*` |
| Shared execution | `mapmover/runtime/` and `mapmover/execution/` |
| Catalog loading | `mapmover/data_loading.py` |
| Geometry | `mapmover/geometry_handlers.py` and geography helpers |
| Browser behavior | `static/modules/` |
