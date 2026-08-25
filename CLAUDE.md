# Working in this repository

Home Assistant custom integration for **Shopee Xpress** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| change which optional field this carrier populates vs. always returns `None` | Update `const.py`'s `CAPABILITIES` in the same commit — it feeds the comparison table on the docs site, so a field that starts (or stops) coming back non-null and isn't reflected there is a wrong claim on the website, not just a stale comment |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

**Status: manually verified against real parcels, and the test suite is
written and green.** The payload mapping was built from maintainer-supplied
captures plus one live re-probe made from the research repo, then confirmed
against real parcels through this integration itself — see
`carrier-research/shopee-xpress/api/`. `tests/payloads.py` reproduces the six
real (redacted) captures faithfully — same tracking-code shapes, same
milestone/tracking codes, same record counts and duplicate-code positions
(`F004` ×3 in the Brazilian fixture, `F440`/sorting-centre pairs in Malaysia
and the Philippines, the Vietnamese return's 26-record history) — and
`pytest --cov=custom_components.shopee_xpress` is 100% at 175 tests. What's
left: tag `1.0.0` and then delete `BUILD_PLAN.md` per its own repo's rule —
both deliberately held back as a separate, explicitly-confirmed step, not
done as part of writing the tests.

**A diagnostics redaction gap surfaced while writing the tests, fixed in the
same pass — worth knowing about if you touch `diagnostics.py`.**
`TO_REDACT` was missing two things that actually appear in this integration's
own diagnostic output: `tracking_code` (the user's own registered code, as
stored in `entry.options[parcels]` — the same class of sensitive value as
`spx_tn`/`sls_tn`, just in the config rather than a fetched payload), and
`raw_status` (top-level *and* per `history[]` entry) — because
`_describe_status_text()` is exactly the free text that can embed a person's
name (the Brazilian capture proves it), and the three literal field names
this module's comment used to cite (`description`/`buyer_description`/
`seller_description`) never actually appear as dict keys anywhere in this
carrier's own normalized output, only inside `_describe_status_text()`'s
input. Both are on `TO_REDACT` now, with `test_diagnostics.py` asserting it
directly rather than trusting the comment.

**Setup asks for the market only — one hub, immediate creation, no fetch.**
Shopee Xpress runs one backend per country host (`spx.com.br`, `spx.co.id`,
`spx.com.my`, `spx.ph`, `spx.co.th`, `spx.vn` — `MARKETS` in `const.py`), and a
number from one market's host does not resolve on another's, so the market has
to be picked before anything else. `config_flow.py`'s `async_step_user`
mirrors `ha-dragonfly`'s zero-input setup — entry created immediately, empty
`CONF_PARCELS` — just with the one input Dragonfly doesn't need. Tracking
codes are **not** collected at setup; they're added afterward through the
options flow, the same split the rest of the suite uses between "which hub"
and "which parcels". **Multiple hubs for the same market are allowed and not
technically prevented** — no `unique_id`/`_abort_if_unique_id_configured`
call — a deliberate maintainer call, not an oversight: entity unique_ids are
keyed on `entry.entry_id` and the device label already includes the market, so
nothing collides. `services.py` takes an optional `market` field to
disambiguate once more than one hub exists (first match wins if two hubs
happen to share a market — good enough for what was asked, not a promise of
finer disambiguation).

**The market dropdown is sorted by the active language's translated country
name, not by `MARKETS`' code order.** `MARKETS`' key order (BR/ID/MY/PH/TH/VN)
happens to be English-alphabetical, which is *not* alphabetical in every
locale this repo ships — Dutch sorts "Filipijnen" (PH) second, not fourth.
`config_flow._sorted_market_options()` reads this integration's own
`selector.market.options.*` strings via
`homeassistant.helpers.translation.async_get_translations` — the same source
`strings.json` / `translations/*.json` already carry, so there is nothing to
keep in sync by hand — for `hass.config.language`, sorts `MARKETS`' keys by
the translated name, and falls back to English when that language isn't one
of the locales this repo ships (or a translation lookup comes back empty).
One thing worth knowing if you touch this: `async_get_translations`'
flattened keys carry a `component.<domain>.` prefix ahead of the
`strings.json` path (`component.shopee_xpress.selector.market.options.br`,
not the bare `market.options.br` its own flattening helper might suggest) —
confirmed against the real loader, not assumed from reading its source.
Another thing confirmed only by testing against the real loader: HA's own
translation cache already substitutes English when a language has no
translation file for this integration at all (e.g. German — this repo ships
only `en`/`nl`), so `_sorted_market_options()`'s own explicit English-fallback
branch is unreachable through that path in practice and is exercised in
`test_config_flow.py` by monkeypatching `async_get_translations` to return an
empty dict directly. Kept anyway, as a defensive backstop rather than
provably dead code — never trust an external system's fallback behaviour to
be a substitute for your own.

**The lookup parameter matches more than a tracking code — and adding one is
now a plain add, no fetch, same as every other carrier in the suite.**
`spx_tn` also resolves against an order id, a Shopee-internal `sls_tn`, and a
merchant-supplied free-text reference (`customer_tracking_no`) — confirmed on
the wire: `?spx_tn=123` returned a real stranger's parcel because some seller
set their reference to `"123"`. This went through two revisions before
landing:

- **Revision 1 (the build plan's own §2):** config flow warns on a short
  input. Cut by the maintainer before the first build — no on-screen message,
  short input is accepted like any other.
- **Revision 2 (this repo's first cut of the redesign below):** setup fetches
  the code once and shows what resolved before creating the entry, later
  moved to a second options-flow step shown right after `parcels.add`. Cut
  too, in the same review: the maintainer wants adding a code to work exactly
  like `ha-dragonfly` and the rest of the suite — type it, it's added, done.
  No fetch-on-add anywhere in the flow.
- **What's left:** the tracking-code regex in `config_flow.py` is **warn-only,
  never a rejection** (`valid_tracking_code`/`warn_unrecognised_tracking_code`)
  — a pure-digit input is a first-class second identifier namespace (an order
  id), not a malformed code, and the alphanumeric shape has already been
  widened twice by new markets. That's a *format* check and a *log-level*
  warning, unrelated to the collision problem above — it stays. The collision
  problem itself has no active UI mitigation any more. Visibility survives
  passively instead: `normalize_parcel()` in `parcels.py` still computes
  `raw["resolved_number"]` / `raw["resolved_number_is_internal"]`
  (`order_info.spx_tn`, or `sls_tracking_info.sls_tn` labelled internal when
  `order_info` is absent) on every real poll, so the resolved number is one
  click away as a parcel attribute once a tracked code actually gets fetched —
  just not surfaced proactively at add-time any more.

**The response's block set is not uniform, and is not a per-market split.**
Only `sls_tracking_info` and two booleans are present in every response;
`order_info` / `parcel_info` / `edd_info` / `fulfillment_info` are each
absent in some responses. Which blocks arrive turns out to depend on the
**identifier namespace the request resolved against** (a "parcel view" via
`spx_tn`/`customer_tracking_no`, or an "order view" via `order_id`/`sls_tn`),
not on which market's host answered — so `normalize_parcel` in `parcels.py`
reads every block defensively, unconditionally, never branching on the
configured market. `barcode` falls back to the tracking code the coordinator
asked for (stamped onto the raw payload as `parcels.REQUESTED_CODE_KEY`
before it reaches `normalize_parcel`) whenever `order_info` is absent.

**Exceptions are never in `milestone_code`.** A failed delivery attempt and a
failed pickup both keep their ordinary happy-path milestone (`6` and `1`);
the exception only shows up in that record's `reason_code` /
`standard_reason_code` / `issue_type`. `map_parcel_status()` deliberately
does **not** derive `ParcelStatus.problem` from those fields — Option A from
the build plan, chosen because the reason vocabulary is sampled from a single
parcel and overriding on it risked more false positives than it fixed. The
reason fields still reach the user through the `raw` attribute.
`ParcelStatus.at_pickup_point` is the one canonical status this carrier has
never shown any evidence for at all.

**Timestamps are epoch seconds, not milliseconds** — the one place this repo
deviates from the template's default numeric-timestamp handling (see
`parcels._epoch_seconds_to_iso`).

**Pre-1.0-style one-shot warnings stay even though this ships at 1.0.0 — with
one deliberate exception.** `status_vocab` is `partial` (five of an unknown
number of `milestone_code` values; both reason vocabularies sampled from one
parcel), so `parcels.py` carries one-shot `_warn_once` log lines for: an
unmapped `milestone_code`, an unrecognised `reason_code`/
`standard_reason_code`/`issue_type` and the `standard_reason_code` shape
check, an unrecognised `tracking_code`, an unrecognised
`tracking_code_group_name`/`subgroup_name`, and a payload shape that has
drifted from the documented key set. Shipping at 1.0.0 instead of the suite's
usual unverified-until-a-real-parcel `0.x` staging does not remove the
obligation to keep logging what is still unconfirmed — that was an explicit
maintainer call.

**The exception, cut after real-parcel testing:** there used to also be a
one-shot warning for a response missing `order_info`/`parcel_info`/
`edd_info` (`_check_missing_blocks()`). It fired on real BR and VN parcels
exactly as designed — the block-set divergence is real and expected — and the
maintainer's call on seeing it in practice was that it's noise, not a signal:
every read of those three blocks is already defensive (`.get()` with a sane
fallback everywhere in `normalize_parcel`), so there is no functional gap for
a user to report, and prompting "open an issue" for something that isn't
actionable just trains people to ignore the prompts that *are*. Removed
outright, function and call site both — not folded into a rate limit or a
debug-level log, gone. If block-set questions need revisiting later, the
per-market pattern table in `tracking.md` is still the place to look, not a
runtime warning.

**`url` is constructed, not read from the payload — no API response in any
market carries one.** `const.py`'s `TRACKING_URL` template
(`https://{host}/track?{tracking_code}`) reuses each market's API host with a
different, client-rendered path; `parcels.py`'s `_tracking_url()` fills it in
with the same `barcode` value the parcel already carries. The pattern came
from the maintainer's own device use across all six markets, not a capture —
a probe from this repo could only confirm the domain serves an app at that
path (a bogus code and a nonexistent path both `200` with an identical SPA
shell), not that the content is correct for a given code. `CAPABILITIES`
gained `url` in the same change (1.1.0).

**API mechanics live in `carrier-research/shopee-xpress/api/`, NOT here and
not in a local `docs/api/`** — the endpoint, the `MARKETS` host/language
table, the `milestone_code`/reason-code vocabularies and their `ParcelStatus`
mapping, and the full annotated captures. See CONVENTIONS.md.

**Translations cover four of the six supported markets, not all six — `my`
and `ph` are skipped on purpose.** CONVENTIONS.md's rule is one translation
per country-picker option, and `pt-BR`/`id`/`th`/`vi` (Brazil, Indonesia,
Thailand, Vietnam) follow it (1.2.0). Malaysia and the Philippines don't:
Home Assistant's own frontend has no Malay or Filipino/Tagalog interface
language at all (confirmed against `translationMetadata.json` in
`home-assistant/frontend`), so a `ms.json`/`tl.json` file could never be
selected by any HA user — English already covers both markets in practice.
Re-check that upstream list before adding either file; don't assume the gap
is permanent.

## Options and reloads

The options flow is one sectioned form (`data_entry_flow.section`); changes apply
without a restart. Two models, **do not mix them**:
- **Account-less carriers** (the default) apply changes live: an update listener
  retunes `coordinator.update_interval` and calls `async_request_refresh()`, so
  added/removed parcel sensors appear immediately.
- **Account-based carriers** call `async_schedule_reload` on submit and register
  **no** update listener. Combining a listener with a reload-on-update flow is
  deprecated, an error in HA 2026.12+.

The user-tunable poll interval is a deliberate HACS divergence (see
CONVENTIONS.md); a carrier that throttles is generated with a fixed cadence and no
polling option at all.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`, account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the gather
loop (one bad parcel doesn't fail the poll) but **not** around the whole update
(the coordinator wraps that). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics — they get pasted
into public issues.

## Running tests

```
python -m pytest tests/ --cov=custom_components.shopee_xpress
```

Coverage must stay **above 95%** (silver `test-coverage` rule) — currently
100%, 175 tests. Run before committing. A code change updates the README +
this file + `docs/` in the same commit; the API reference lives in this
carrier's own directory under the private `carrier-research/shopee-xpress/api/`,
never in this repo.
