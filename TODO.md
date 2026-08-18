# Shopee Xpress — still to do

Generated from ha-carrier-template (`--auth none --interval fixed`), then built out against
the real endpoint per `carrier-research/api/shopee-xpress/BUILD_PLAN.md`. Coordinator, config
flow, `normalize_parcel`, the status map, all five `TODO(carrier)` markers, and (after two
rounds of real-parcel-testing fixes) the test suite are all done.

`pytest tests/ --cov=custom_components.shopee_xpress` is green: 175 tests, 100% coverage.
`ruff check custom_components tests` is clean.

## Remaining before a `1.0.0` release

Deliberately held back as a separate, explicitly-confirmed step — not part of writing the
tests:

- [ ] Tag `1.0.0`.
- [ ] Flip `carrier-research/shopee-xpress/shopee-xpress.md`'s `state` to `built`, set
      `version`.
- [ ] Delete `carrier-research/api/shopee-xpress/BUILD_PLAN.md` (its §6 test-fixture guidance
      has now been used; fold any further correction into `tracking.md` first if one turns up).
- [ ] Add `shopee_xpress` to the aggregator's `KNOWN_CARRIERS` and `CARRIER_EVENT_PREFIXES`
      (in `ha-parcel-aggregator`, a separate repo) once the above is done.

Delete this file once it is empty.
