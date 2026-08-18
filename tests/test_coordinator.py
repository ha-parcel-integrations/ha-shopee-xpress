"""Tests for the Shopee Xpress coordinator: fetching, caching and events.

The parcel mapping itself is covered by ``test_parcels.py``. The API client
here never returns ``None`` — it either returns a `data` dict or raises
:class:`ShopeeXpressApiError` (see ``test_api.py``); the coordinator has no
"not found" placeholder branch to test as a result.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shopee_xpress.api import ShopeeXpressApiError
from custom_components.shopee_xpress.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_MARKET,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
    ParcelStatus,
)
from custom_components.shopee_xpress.coordinator import ShopeeXpressCoordinator

from .payloads import ID_CODE, MY_CODE, br_data, id_data, my_data, vn_data

OTHER_CODE = "TH000000000000"


def _entry_with(parcels: list[dict], *, market: str = "MY") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        # Keep-most-recent-100 so the delivered-retention filter never trims
        # the (old, fixed-date) sample parcels these tests assert on.
        options={
            CONF_MARKET: market,
            CONF_PARCELS: parcels,
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 100,
        },
    )


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------


async def test_update_merges_multiple_parcels(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}, {CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = lambda code: (
        my_data(code) if code == MY_CODE else id_data(code)
    )
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()

    assert len(data) == 1  # ID is active, MY is delivered
    assert data[0]["barcode"] == ID_CODE
    assert len(coordinator.delivered) == 1
    assert coordinator.delivered[0]["barcode"] == MY_CODE
    assert coordinator.last_success_time is not None


async def test_update_stamps_requested_code_before_normalizing(hass):
    """The coordinator stamps REQUESTED_CODE_KEY so barcode can fall back to
    it — exercised here on the Brazilian shape, whose order_info is absent."""
    entry = _entry_with([{CONF_TRACKING_CODE: "BR000000000000Y"}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = br_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    await coordinator._async_update_data()

    assert coordinator.delivered[0]["barcode"] == "BR000000000000Y"


async def test_update_keeps_cached_payload_on_error(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = my_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)
    await coordinator._async_update_data()  # populates the cache

    client.async_get_parcel.side_effect = ShopeeXpressApiError("HTTP 500")
    await coordinator._async_update_data()  # error -> cached raw reused
    assert len(coordinator.delivered) == 1


async def test_update_raises_when_every_parcel_fails(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = ShopeeXpressApiError("HTTP 500")
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_reraises_unexpected_exceptions(hass):
    """Only API and network errors are tolerated; a bug must not be swallowed."""
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = ValueError("boom")
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    with pytest.raises(ValueError):
        await coordinator._async_update_data()


async def test_update_skips_items_missing_a_tracking_code(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: ""}, {CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = my_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    await coordinator._async_update_data()
    assert client.async_get_parcel.await_count == 1  # empty item never fetched


async def test_update_prunes_cache_for_untracked_parcels(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = my_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)
    coordinator._raw_cache["GONE"] = {"sls_tracking_info": {"records": []}}

    await coordinator._async_update_data()

    assert "GONE" not in coordinator._raw_cache
    assert MY_CODE in coordinator._raw_cache


async def test_update_fetches_parcels_concurrently(hass):
    """All tracked parcels go out in one gather, not one-by-one."""
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}, {CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    in_flight = 0
    peak = 0

    async def _slow_fetch(code):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return my_data(code) if code == MY_CODE else id_data(code)

    client = AsyncMock()
    client.async_get_parcel.side_effect = _slow_fetch
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    await coordinator._async_update_data()
    assert peak == 2


async def test_cache_only_poll_does_not_stamp_last_success(hass):
    """A poll served entirely from cache must not look like a success."""
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = my_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)
    await coordinator._async_update_data()
    stamp = coordinator.last_success_time
    assert stamp is not None

    client.async_get_parcel.side_effect = ShopeeXpressApiError("HTTP 500")
    await coordinator._async_update_data()  # served from cache
    assert coordinator.last_success_time == stamp


async def test_update_with_no_tracked_parcels_stamps_success(hass):
    entry = _entry_with([])
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()
    assert data == []
    assert coordinator.last_success_time is not None
    client.async_get_parcel.assert_not_awaited()


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


async def test_first_refresh_fires_nothing(hass):
    """Otherwise every restart floods the user with "registered" events."""
    entry = _entry_with([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = id_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    fired = []
    for suffix in (
        "parcel_registered",
        "parcel_status_changed",
        "parcel_delivered",
        "parcel_delivery_time_changed",
    ):
        hass.bus.async_listen(f"{DOMAIN}_{suffix}", lambda e: fired.append(e))

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert fired == []


async def test_event_carries_device_id(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
    )
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_status_changed", lambda e: events.append(e)
    )

    client.async_get_parcel.return_value = id_data()  # registered
    await coordinator._async_update_data()
    client.async_get_parcel.return_value = vn_data(ID_CODE)  # returning: a status change
    await coordinator._async_update_data()
    # A third round exercises the cached-id fast path (no second registry
    # lookup) — vn_data is already terminal so nothing new fires, but
    # _fire_change_events() still calls _device_id() once per round.
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events[0].data["device_id"] == device.id


async def test_fire_change_events_skips_parcels_without_a_barcode(hass):
    """Defensive-only path: barcode always falls back to the requested code
    in the real fetch flow, but `_fire_change_events` guards it directly."""
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)
    coordinator._known_state = {}  # not None, so the loop actually runs

    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: events.append(e))

    coordinator._fire_change_events([{"barcode": None, "status": ParcelStatus.REGISTERED}])
    await hass.async_block_till_done()

    assert events == []


async def test_fires_status_changed_event(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_status_changed", lambda e: events.append(e)
    )

    client.async_get_parcel.return_value = id_data()  # registered, single record
    await coordinator._async_update_data()  # first refresh: suppressed

    returning = vn_data(ID_CODE)
    client.async_get_parcel.return_value = returning
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_status"] == ParcelStatus.REGISTERED
    assert events[0].data["new_status"] == ParcelStatus.RETURNING


async def test_delivery_fires_delivered_event_and_not_status_changed(hass):
    """The hop to delivered fires exactly one, dedicated event."""
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    delivered = []
    changed = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", lambda e: delivered.append(e))
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_status_changed", lambda e: changed.append(e)
    )

    in_transit = my_data(MY_CODE)
    in_transit["sls_tracking_info"]["records"] = in_transit["sls_tracking_info"]["records"][1:]
    client.async_get_parcel.return_value = in_transit  # newest now F600 (out for delivery)
    await coordinator._async_update_data()
    client.async_get_parcel.return_value = my_data(MY_CODE)  # delivered
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert changed == []
    assert len(delivered) == 1
    assert delivered[0].data["barcode"] == MY_CODE
    assert delivered[0].data["status"] == ParcelStatus.DELIVERED


async def test_no_events_for_parcel_first_seen_delivered(hass):
    """A parcel already delivered when first tracked fires nothing at all."""
    entry = _entry_with([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = lambda code: (
        id_data(code) if code == ID_CODE else my_data(code)
    )
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    fired = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: fired.append(e))
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", lambda e: fired.append(e))

    await coordinator._async_update_data()  # first refresh seeds the state

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PARCELS: [
                {CONF_TRACKING_CODE: ID_CODE},
                {CONF_TRACKING_CODE: MY_CODE},
            ],
        },
    )
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert fired == []


async def test_fires_registered_event_for_new_parcel(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = id_data()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: events.append(e))

    await coordinator._async_update_data()  # first refresh: suppressed

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PARCELS: [
                {CONF_TRACKING_CODE: ID_CODE},
                {CONF_TRACKING_CODE: OTHER_CODE},
            ],
        },
    )
    client.async_get_parcel.side_effect = lambda code: (
        id_data(code) if code == ID_CODE else id_data(code)
    )
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["barcode"] == OTHER_CODE


async def test_fires_delivery_time_changed_event(hass):
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_delivery_time_changed", lambda e: events.append(e)
    )

    active = my_data(MY_CODE)
    active["sls_tracking_info"]["records"] = active["sls_tracking_info"]["records"][1:]  # not delivered
    client.async_get_parcel.return_value = active
    await coordinator._async_update_data()  # first refresh: suppressed

    moved = my_data(MY_CODE)
    moved["sls_tracking_info"]["records"] = moved["sls_tracking_info"]["records"][1:]
    moved["edd_info"] = {"edd_min": 1770400000, "edd_max": 1770420000}
    client.async_get_parcel.return_value = moved
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["new_planned_from"] == "2026-02-06T17:46:40+00:00"
    assert events[0].data["old_planned_from"] != events[0].data["new_planned_from"]


async def test_losing_the_eta_is_silent(hass):
    """value -> null just means the carrier lost the window; not worth an alert."""
    entry = _entry_with([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_delivery_time_changed", lambda e: events.append(e)
    )

    active = my_data(MY_CODE)
    active["sls_tracking_info"]["records"] = active["sls_tracking_info"]["records"][1:]
    client.async_get_parcel.return_value = active
    await coordinator._async_update_data()

    dropped = my_data(MY_CODE)
    dropped["sls_tracking_info"]["records"] = dropped["sls_tracking_info"]["records"][1:]
    del dropped["edd_info"]
    client.async_get_parcel.return_value = dropped
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events == []
