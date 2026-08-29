# Shopee Xpress Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-shopee-xpress.svg)](https://github.com/ha-parcel-integrations/ha-shopee-xpress/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

> ⚠️ **Not yet verified against a real parcel from this integration.** The
> status mapping is built from real captured responses in six markets, and
> the endpoint has been re-probed from outside Home Assistant — but nobody
> has run this integration itself against a live parcel yet. Expect the
> occasional `unknown` status or missing field until that happens; please
> [open an issue](https://github.com/ha-parcel-integrations/ha-shopee-xpress/issues/new)
> if you hit one.

A custom Home Assistant integration that tracks your Shopee Xpress (SPX) parcels — Shopee's own in-house last-mile carrier, used across several of its Southeast Asian and South American markets. No account is needed: you enter the tracking code yourself, the same way you'd look it up on Shopee.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Supported markets](#supported-markets)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Shopee Xpress parcels by tracking code — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / `returning` / …), the carrier's own status text and the expected delivery window (where the market provides one)
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery windows
- `shopee_xpress.track_parcel` / `shopee_xpress.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor
- Multiple hubs for households tracking parcels across more than one market (or just to split parcels up within one)

## Supported markets

Shopee Xpress runs a separate backend host per market — a tracking code from
one market does not resolve on another's. Only markets whose host has
actually answered with a real parcel are wired in:

| Market | |
|---|---|
| Brazil | 🇧🇷 |
| Indonesia | 🇮🇩 |
| Malaysia | 🇲🇾 |
| Philippines | 🇵🇭 |
| Thailand | 🇹🇭 |
| Vietnam | 🇻🇳 |

Shopee Xpress operates in other markets too (e.g. Singapore, Taiwan) — those
aren't supported yet because their hosts haven't been confirmed. [Open a
discussion](https://github.com/ha-parcel-integrations/.github/discussions/new/choose)
if you can help test one.

## Requirements

- Home Assistant 2024.12 or newer
- A Shopee Xpress parcel and its tracking code — no account needed. Shopee
  Xpress also resolves a plain order number, so either one works.

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-shopee-xpress` as an **Integration**.
3. Install **Shopee Xpress** and restart Home Assistant.

### Manual

Copy `custom_components/shopee_xpress` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Shopee Xpress**. Setup asks for one thing — the **market** this hub is for, since Shopee Xpress runs a separate service per market and a tracking code from one does not resolve on another's. The hub is created immediately; there's nothing else to fill in.

Add parcels afterwards via the integration's **Configure** dialog, the
[`shopee_xpress.track_parcel`](#services) service, or a [dashboard
button](examples/dashboards/add_parcel_card.yaml) — just the tracking code, no
lookup happens while you add it. Tracking a parcel in a second market? Add the
integration again and pick that market; more than one hub for the same market
is fine too, if you want to split parcels across them.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes for this hub's market. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

The market itself isn't editable after setup — add a second hub for a second market instead.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Shopee Xpress → ⋮ → Delete**. Nothing is stored on Shopee Xpress's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.shopee_xpress_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.shopee_xpress_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.shopee_xpress_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.shopee_xpress_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.shopee_xpress_last_successful_update` | Diagnostic: when Shopee Xpress was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically. `weight`, `dimensions` and `pickup_point` are not part of this carrier's payload in any market, so those attributes are always empty — the expected delivery window is only present in some markets (Malaysia, Philippines, Thailand), and disappears once a parcel is delivered. `url` links to the consumer tracking page for the parcel's own market host, built from the tracking code rather than read from the API (which doesn't return one).

A **`button.shopee_xpress_refresh`** entity triggers an immediate poll outside
the regular interval, and a **`calendar.shopee_xpress_deliveries`** entity
shows expected delivery dates for active parcels — read-only, no extra API
calls.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family. Not every value is reachable on Shopee Xpress:

| Status | Meaning |
|---|---|
| `registered` | Manifested — the sender is preparing to ship it |
| `in_transit` | Moving through Shopee Xpress's sorting network |
| `out_for_delivery` | With the courier today |
| `delivered` | Delivered |
| `returning` | Delivery failed and the parcel is going back to the sender — covers both the return journey and the parcel already being back with the sender |
| `unknown` | A status code we haven't mapped yet — please report it |

`at_pickup_point` and `problem` are not produced by this integration today.
Shopee Xpress has never shown a parcel collected from a pickup point in any
capture, and a failed delivery attempt or pickup does not get its own status
code at all — the carrier records it as free text and a reason code beside
an otherwise-ordinary status, visible in the `raw_status` and `raw`
attributes rather than in `status` itself.

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Shopee Xpress device):

| Event | When |
|---|---|
| `shopee_xpress_parcel_registered` | A new parcel appears in the active list |
| `shopee_xpress_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `shopee_xpress_parcel_delivered` | A parcel is delivered |
| `shopee_xpress_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `shopee_xpress.track_parcel` | `tracking_code`, `market` (optional) | Start tracking a parcel. `market` picks the hub when more than one is set up. |
| `shopee_xpress.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.shopee_xpress: debug
```

## Troubleshooting

- **A parcel shows `unknown`**: either it hasn't been scanned yet, or its newest event carries a `milestone_code` this integration doesn't map yet (rare — please report it, see below).
- **A per-parcel sensor's `raw.resolved_number` doesn't match the code I typed**: Shopee Xpress's lookup also matches other sellers' free-text order references, so a very short or mistyped tracking code can resolve to a real stranger's parcel. Nothing is checked when you add a code — check `raw.resolved_number` (and `raw.resolved_number_is_internal`) on that parcel's sensor once it's been polled, and double-check the code you entered if it looks wrong.
- **A log line starts with "Unrecognised Shopee Xpress ..."**: this carrier's status and reason-code vocabularies are only partially confirmed. Please [open an issue](https://github.com/ha-parcel-integrations/ha-shopee-xpress/issues/new) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the Shopee Xpress mobile app and consumer-facing pages. It is not affiliated with, endorsed by, or supported by Shopee or Shopee Xpress. Be gentle with the polling interval — it is fixed rather than user-configurable for exactly this reason.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
