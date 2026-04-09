# x402 Test Client

This note explains how to act like a new developer testing the paid API lane.

Before attempting a paid call, use the free discovery endpoints first:

- `GET /api/v1/guide`
- `GET /api/v1/catalog`
- `GET /api/v1/packs/{pack_id}`

Current target:

- endpoint: `POST /api/v1/query/dataset`
- hosted base URL: `https://app.daedalmap.com`
- network: Base Sepolia
- payment rail: x402 wallet-pay
- current live agent/API packs in free discovery: `currency`, `earthquakes`, `volcanoes`, `tsunamis`

Useful live pair probes:

- `currency`: pack-routed FX request using `pack_id = "currency"` and `filters.time.granularity = "monthly"`
- `earthquakes`: event-count request using `source_id = "earthquakes_events"` and `metrics = ["event_count"]`
- `volcanoes`: event-count request using `source_id = "volcanoes_events"` and `metrics = ["event_count"]`
- `tsunamis`: event-count request using `source_id = "tsunamis_events"` and `metrics = ["event_count"]`

Important runtime note:

- local/self-host runtimes return `commercial_access_unavailable` on `POST /api/v1/query/dataset` unless a commercial verifier is explicitly enabled
- the hosted paid test target is `https://app.daedalmap.com`
- Stripe/account-credit mode is planned for later and is not part of the current live paid lane

Current pricing model:

- base price: `$0.01`
- rows included in the base price: `100`
- per-row fee after 100 rows: `$0.0001`
- max single-call price: `$0.50`

What a new developer should expect:

- free discovery stays free
- the paid lane prices from the request `limit`
- the unpaid `402` challenge tells you the actual amount before you pay
- small starter probes such as `limit = 3` stay at the `$0.01` base
- do not assume every source uses the same time filter shape
- use Base Sepolia explorer as the source of truth for receipt verification if a
  wallet UI looks stale or inconsistent

Worked examples:

- `limit = 30` -> `$0.01`
- `limit = 100` -> `$0.01`
- `limit = 365` -> `$0.0365`
- `limit = 500` -> `$0.05`

## MetaMask setup

Use a dedicated test account if possible.
Do not use your main wallet private key for casual local testing.

### 1. Add Base Sepolia

In MetaMask, add or switch to the Base Sepolia network.

Working values:

- Network name: `Base Sepolia`
- RPC URL: `https://sepolia.base.org`
- Chain ID: `84532`
- Currency symbol: `ETH`
- Block explorer URL: `https://sepolia.basescan.org`

### 2. Fund the wallet

The buyer wallet needs:

- Base Sepolia ETH for gas
- Base Sepolia USDC for the payment itself

### 3. Export the private key for the test account

The local test client uses:

- `EVM_PRIVATE_KEY`

Use a test-only account for this.

## Local test client

Script:

- `examples/x402_query_dataset_test.mjs`

Install dependencies:

```powershell
npm install
```

Challenge-only probe:

```powershell
$env:DAEDALMAP_API_BASE_URL = "https://app.daedalmap.com"
npm run x402:test:dataset -- --scenario earthquakes --challenge-only
```

Paid retry:

```powershell
$env:DAEDALMAP_API_BASE_URL = "https://app.daedalmap.com"
$env:EVM_PRIVATE_KEY = "0xYOUR_TEST_ACCOUNT_PRIVATE_KEY"
npm run x402:test:dataset -- --scenario earthquakes
```

Currency example:

```powershell
$env:DAEDALMAP_API_BASE_URL = "https://app.daedalmap.com"
npm run x402:test:dataset -- --scenario currency --challenge-only
```

Volcanoes example:

```powershell
$env:DAEDALMAP_API_BASE_URL = "https://app.daedalmap.com"
npm run x402:test:dataset -- --scenario volcanoes --challenge-only
```

Tsunamis example:

```powershell
$env:DAEDALMAP_API_BASE_URL = "https://app.daedalmap.com"
npm run x402:test:dataset -- --scenario tsunamis --challenge-only
```

Larger pricing probe:

```powershell
$env:DAEDALMAP_API_BASE_URL = "https://app.daedalmap.com"
npm run x402:test:dataset -- --scenario earthquakes --challenge-only --limit 250
```

What the script does:

1. sends an unpaid request and logs the `402` challenge
2. decodes the `payment-required` header
3. if `EVM_PRIVATE_KEY` is present, creates an x402 buyer client
4. pays and retries the same request automatically
5. logs the final API response plus settlement metadata
6. prints the `request_id` so the verifier row can be found in Supabase
7. accepts `--limit` so you can verify dynamic pricing at different request sizes

Explorer verification tip:

- challenge `payTo` tells you which receiving wallet should see the transfer
- `settle_response.transaction` may be the fastest receipt clue to inspect
- verify on `https://sepolia.basescan.org`
- if a wallet UI and the explorer disagree, trust the explorer

Pricing tip:

- rerun the same scenario with a larger `limit` if you want to verify that the x402 challenge amount scales with the request size
- current live pricing proofs now include:
  - `limit = 3` -> `10000`
  - `limit = 250` -> `25000`
  - `limit = 500` -> `50000`
- above-max requests should reject cleanly without false revenue attribution
- event-source public max is currently `500`, so the current live public proof is
  dynamic growth plus max-edge rejection, not yet a direct proof of the
  `$0.50` cap itself

Supported scenarios:

- `--scenario earthquakes`: `source_id = "earthquakes_events"` with `metrics = ["event_count"]` and a 2011 ISO date range
- `--scenario currency`: `pack_id = "currency"` with monthly FX routing through `time.granularity`
- `--scenario volcanoes`: `source_id = "volcanoes_events"` with `metrics = ["event_count"]`
- `--scenario tsunamis`: `source_id = "tsunamis_events"` with `metrics = ["event_count"]`

Time-shape reminder:

- `earthquakes_events` is timestamp-based, so use ISO date ranges such as `2011-01-01` to `2011-12-31`
- `currency` is also date-based, so use ISO date ranges such as `2015-01-01` to `2024-12-31`
- `volcanoes_events` and `tsunamis_events` examples here use year-style ranges
- always inspect `GET /api/v1/packs/{pack_id}` before inventing a new request shape

## Current live expectation

For a healthy x402 lane:

- unpaid request returns `402`
- paid retry returns `200`
- response body includes dataset rows
- explorer-visible receipt appears for the configured `payTo` wallet
- Supabase settlement and analytics rows agree on the successful paid run when
  you inspect the hosted backend

If unpaid requests return `200`, commercial gating is not active.
If unpaid requests return `502`, the verifier is active but unhealthy.
