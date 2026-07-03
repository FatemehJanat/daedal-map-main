# Local And Hosted Deployment

This guide explains where DaedalMap runs and where it reads data. For Explore,
Research, Ops, and Tutorial behavior, see
[RUNTIME_MODES.md](RUNTIME_MODES.md).

DaedalMap uses two environment settings:

- `INSTALL_MODE`: where the application is installed
- `RUNTIME_MODE`: where runtime data is read

## Supported configurations

| Install | Data runtime | Use case |
|---|---|---|
| `local` | `local` | Research, development, and self-hosting with a local data tree |
| `local` | `cloud` | Local application testing against object storage |
| `cloud` | `cloud` | Hosted application with object-storage data |

`INSTALL_MODE=cloud` with `RUNTIME_MODE=local` is not a supported first-class
configuration.

## Local application and local data

Use:

```text
INSTALL_MODE=local
RUNTIME_MODE=local
DATA_ROOT=C:/path/to/your/data
OPENAI_API_KEY=your-key
```

You may use `ANTHROPIC_API_KEY` instead of an OpenAI key.

This is the clearest path for academic work:

- data stays on a machine or mounted volume you control;
- imported sources can be rebuilt and tested without cloud publication;
- local packs can be grouped into Research corpora;
- hosted account infrastructure is not required.

If `DATA_ROOT` is blank, the runtime uses the platform's default local
application-data folder. On Windows this is normally:

```text
%LOCALAPPDATA%\DaedalMap\data
```

The public source checkout does not include a full data tree, so a useful local
run needs data at that default location or an explicit `DATA_ROOT`.

## Local application and cloud data

Use:

```text
INSTALL_MODE=local
RUNTIME_MODE=cloud
```

Configure object storage using the variables documented in
[../.env.example](../.env.example).

In this configuration:

- metadata is hydrated or cached locally;
- Parquet can be queried remotely through DuckDB;
- local code exercises the same general data path as a cloud deployment.

Use storage and credentials you are authorized to access. A local installation
does not imply local data when `RUNTIME_MODE=cloud`.

## Cloud application and cloud data

Use:

```text
INSTALL_MODE=cloud
RUNTIME_MODE=cloud
```

This is the deployment shape for a hosted instance. The public runtime can be
deployed using infrastructure and object storage you control.

Hosted account, billing, admin, collector, and publication-control systems are
separate concerns and are not required to run the open runtime.

## Common local choices

Set:

- `DATA_ROOT` when your data is outside the default app-data folder;
- one supported model-provider key;
- `INSTALL_MODE=local`;
- `RUNTIME_MODE=local` for local research data.

Leave `APP_URL` and `SITE_URL` unset unless the instance needs to advertise
specific external URLs.

Private hosted bridge variables are not needed for ordinary local operation.
Without them, `/settings` remains a local setup surface.

## Next steps

- [DATA_PREPARATION.md](DATA_PREPARATION.md) — prepare a source
- [PACK_AUTHORING.md](PACK_AUTHORING.md) — group sources into a pack
- [RUNTIME_MODES.md](RUNTIME_MODES.md) — choose Explore, Research, or Ops
- [DATA_SCHEMAS.md](DATA_SCHEMAS.md) — inspect the exact data contract
