# Bramley Crossing for Home Assistant

A standalone HACS integration for the public Bramley crossing service.
It exposes **advisory crossing state inferred from protecting-signal aspects,
not physical barrier telemetry**, and the service's closure predictions.

**Always obey physical crossing lights and barriers. Advisory only; not for
safety-critical control.** An inferred `Open` state is not permission to cross.
Do not use these sensors to control safety equipment or decide whether crossing
the railway is safe.

## Installation

Requires Home Assistant 2025.2 or newer and HACS.

1. In HACS, open **Custom repositories**, add
   `https://github.com/aelking/home-assistant-bramley-crossing`, and select
   **Integration** as the category.
2. Find **Bramley Crossing (signal-inferred advisory)** and download it.
3. Restart Home Assistant.
4. Open **Settings > Devices & services > Add integration**, search for
   **Bramley Crossing**, and enter your crossing service's base URL.

This repository has the HACS integration layout and metadata. It is installed
as a custom repository; inclusion in HACS's default catalog is a separate process.
For manual installation, copy `custom_components/bramley_crossing` into
`config/custom_components/bramley_crossing`, restart, and use the same UI flow.
No YAML configuration, token, or additional Python dependency is required.

## Configuration

Enter the HTTP(S) **base URL**, for example `https://crossing.example.org`,
not the `/api/status` endpoint. Reverse-proxy prefixes such as
`https://example.org/crossing` are supported. Home Assistant must be able to
reach the service. URLs containing credentials, queries, or fragments are rejected.
Trailing slashes are normalized and duplicate service URLs are rejected.

The integration polls unauthenticated `GET <base URL>/api/status` every
**30 seconds**, with a **10-second request timeout**. The configurable heartbeat
stale timeout defaults to **90 seconds** (range 30-3600 seconds). Change it
using the integration's **Configure** options; the integration reloads automatically.
Setup checks that the API and feed are healthy. A failed initial refresh is
retried by Home Assistant.

## Entities

All three sensors belong to a service device labeled **signal-inferred advisory**;
its model identifies protecting-signal aspects rather than barrier telemetry.
Entity IDs are assigned by Home Assistant; use the entity registry to find them.

| Sensor | Source | Representation |
| --- | --- | --- |
| Inferred crossing state (protecting signals) | `state` | Enum: `Unknown`, `Open`, `ClosingSoon`, `Closed` |
| Next predicted closure (protecting signals) | `predictedCloseAt` | Timestamp, converted to UTC |
| Typical predicted closure duration (protecting signals) | `typicalClosureSeconds` | Duration in seconds |

`Unknown` is an explicit enum value for absent/unrecognized crossing state.
Absent/null predictions and durations remain Home Assistant `unknown` values,
not zero, the current time, or a fabricated prediction. A valid duration of zero
is retained. There are no daily closure statistics or control services.

Each sensor carries `inference_basis`, `advisory`, `observed_at`,
`feed_updated_at`, and `last_message_at` attributes. `observed_at` comes only
from the API's `observedAt`: a heartbeat never becomes a crossing observation.

### Availability and freshness

All entities become **unavailable** together for HTTP/network errors, request
timeouts, invalid JSON/status data, missing or malformed `feedStatus`,
`connected != true`, or an expired `feedStatus.updatedAt` heartbeat. They
recover automatically on the next healthy poll. Missing optional prediction
values alone do not make the device unavailable.

Freshness is based on `feedStatus.updatedAt`, which the service refreshes every
15 seconds independently of observations. An old `observedAt` or null/old
`lastMessageAt` does **not** indicate staleness when the feed heartbeat is healthy.
ISO timestamps must include a timezone. Heartbeats over 30 seconds in the future
are rejected to catch clock errors. Exactly the configured stale timeout is
accepted; expiration is detected on the next poll (up to 30 seconds later,
plus request latency). Keep the service and Home Assistant clocks synchronized.

The integration consumes the existing status contract only; it does not change
the service, infer extra predictions, or use physical barrier telemetry.

## Development

Run tests on Linux with Python 3.13+ (Home Assistant's test environment is not
supported on Windows). With [uv](https://docs.astral.sh/uv/) installed:

```text
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The test dependencies select a compatible Home Assistant release; a newer
release may require a newer Python interpreter. Tests cover data validation,
configuration/options, coordinator failures/recovery, entity mapping and
heartbeat/observation separation.
