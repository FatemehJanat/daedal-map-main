# Hosted Runtime Guardrails

This public note describes DaedalMap's guardrail posture at a high level.
Detailed hosted thresholds and operational runbooks live in the private
operations/security docs.

## Goals

Hosted runtimes should stay responsive when users, agents, or crawlers ask for
large data slices.

The main safety goals are:

- bound per-request work
- bound response size
- avoid unbounded live upstream calls
- return structured guidance when a request should be narrowed
- keep free and paid lanes subject to the same live-work safety checks

## Public Contract

Small queries stay cheap and fast. Very broad scans cost more or need narrower
filters. Some requests are too broad for live API access and should be narrowed
before retrying.

Good query shapes usually include:

- a time range
- one or more `region_ids`
- an aggregate metric such as `event_count` when raw rows are not needed
- a modest `limit`

Broad sorting across an entire historical source is intentionally discouraged.

## Runtime Behavior

The API may return structured errors such as:

- `result_too_large`
- `query_too_broad`
- `rate_limited`

These errors should include enough guidance for a caller or agent to retry with
a narrower request.

## Self-Host Notes

Self-hosted deployments should set their own limits based on available memory,
CPU, bandwidth, and data-pack size. The public runtime defaults are conservative,
but production operators should still configure explicit environment variables
for rate limits and concurrency.

## Related Docs

- [../README.md](../README.md)
- [X402_TEST_CLIENT.md](X402_TEST_CLIENT.md)
- [DATA_SCHEMAS.md](DATA_SCHEMAS.md)
