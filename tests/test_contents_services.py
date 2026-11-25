"""Tests for the contents action, the track_parcel field and the store lifecycle."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.shopee_xpress.const import (
    CONF_MARKET,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
)
from custom_components.shopee_xpress.coordinator import ShopeeXpressCoordinator
from custom_components.shopee_xpress.parcels import REQUESTED_CODE_KEY, normalize_parcel

from .payloads import ID_CODE, id_data, my_data

CLIENT = "custom_components.shopee_xpress.api.ShopeeXpressApiClient"
REFRESH = f"{ShopeeXpressCoordinator.__module__}.ShopeeXpressCoordinator"
UNTRACKED = "SPXID111111111111"
STORE_KEY = f"{DOMAIN}.contents.%s"


def _sample(code: str = ID_CODE) -> dict:
    return id_data(code)


def _config_entry(parcels: list[dict], market: str = "ID") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, options={CONF_MARKET: market, CONF_PARCELS: parcels}
    )


async def _setup(hass, codes: list[str] | None = None) -> MockConfigEntry:
    entry = _config_entry([{CONF_TRACKING_CODE: code} for code in codes or []])
    entry.add_to_hass(hass)
    with patch(f"{CLIENT}.async_get_parcel", new=AsyncMock(return_value=_sample())):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _call(hass, service: str, data: dict) -> None:
    with patch(
        f"{CLIENT}.async_get_parcel",
        new=AsyncMock(side_effect=lambda code: _sample(code)),
    ):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
        await hass.async_block_till_done()
        # A refresh requested inside the debouncer's cooldown runs after it.
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()


def _contents(entry: MockConfigEntry, code: str) -> str | None:
    parcels = {p["barcode"]: p for p in entry.runtime_data.coordinator.data}
    return parcels[code]["contents"]


async def test_a_parcel_has_no_contents_without_a_stored_value(hass):
    entry = await _setup(hass, [ID_CODE])
    assert _contents(entry, ID_CODE) is None


async def test_an_entry_without_a_stored_file_still_sets_up(hass, hass_storage):
    assert STORE_KEY % "x" not in hass_storage
    entry = await _setup(hass, [ID_CODE])
    assert entry.state is ConfigEntryState.LOADED


async def test_update_contents_sets_replaces_and_clears(hass):
    entry = await _setup(hass, [ID_CODE])

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": " Running  shoes "},
    )
    assert _contents(entry, ID_CODE) == "Running shoes"

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Winter socks"},
    )
    assert _contents(entry, ID_CODE) == "Winter socks"

    await _call(
        hass, "update_contents", {CONF_TRACKING_CODE: ID_CODE, "contents": "  "}
    )
    assert _contents(entry, ID_CODE) is None


async def test_update_contents_without_text_clears(hass):
    entry = await _setup(hass, [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )

    await _call(hass, "update_contents", {CONF_TRACKING_CODE: ID_CODE})

    assert _contents(entry, ID_CODE) is None


async def test_update_contents_normalizes_the_code(hass):
    entry = await _setup(hass, [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: f" {ID_CODE.lower()} ", "contents": "Running shoes"},
    )
    assert _contents(entry, ID_CODE) == "Running shoes"


async def test_update_contents_works_for_a_code_that_is_not_tracked(hass):
    entry = await _setup(hass, [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: UNTRACKED, "contents": "Running shoes"},
    )

    assert entry.runtime_data.coordinator.contents_store.get(UNTRACKED) == (
        "Running shoes"
    )
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ID_CODE}]


async def test_update_contents_never_polls_and_notifies_once_per_change(hass):
    entry = await _setup(hass, [ID_CODE])
    coordinator = entry.runtime_data.coordinator
    data = {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"}
    with (
        patch(f"{REFRESH}.async_request_refresh", new=AsyncMock()) as refresh,
        patch(f"{CLIENT}.async_get_parcel", new=AsyncMock()) as fetch,
        patch.object(
            coordinator,
            "async_update_listeners",
            wraps=coordinator.async_update_listeners,
        ) as listeners,
    ):
        await hass.services.async_call(DOMAIN, "update_contents", data, blocking=True)
        assert listeners.call_count == 1
        await hass.services.async_call(DOMAIN, "update_contents", data, blocking=True)
        assert listeners.call_count == 1
        await hass.services.async_call(
            DOMAIN, "update_contents", {CONF_TRACKING_CODE: UNTRACKED}, blocking=True
        )
        assert listeners.call_count == 1
        await hass.services.async_call(
            DOMAIN, "update_contents", {CONF_TRACKING_CODE: ID_CODE}, blocking=True
        )
        assert listeners.call_count == 2
    refresh.assert_not_called()
    fetch.assert_not_called()
    assert _contents(entry, ID_CODE) is None


async def test_update_contents_rejects_an_empty_code(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "update_contents", {CONF_TRACKING_CODE: ""})


async def test_update_contents_needs_a_loaded_entry(hass):
    entry = await _setup(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
        )


async def test_track_parcel_stores_contents_for_a_new_code(hass):
    entry = await _setup(hass)
    await _call(
        hass,
        "track_parcel",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )

    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ID_CODE}]
    assert _contents(entry, ID_CODE) == "Running shoes"


async def test_track_parcel_without_contents_is_unchanged(hass):
    entry = await _setup(hass)
    await _call(hass, "track_parcel", {CONF_TRACKING_CODE: ID_CODE})

    assert entry.runtime_data.coordinator.contents_store.get(ID_CODE) is None
    assert _contents(entry, ID_CODE) is None


async def test_track_parcel_with_contents_needs_a_loaded_entry(hass):
    entry = await _setup(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "track_parcel",
            {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
        )
    assert entry.options[CONF_PARCELS] == []


async def test_track_parcel_replaces_and_clears_contents_of_a_tracked_code(hass):
    entry = await _setup(hass, [ID_CODE])
    track = {CONF_TRACKING_CODE: ID_CODE}

    await _call(hass, "track_parcel", {**track, "contents": "Running shoes"})
    assert _contents(entry, ID_CODE) == "Running shoes"

    await _call(hass, "track_parcel", {**track, "contents": "Winter socks"})
    assert _contents(entry, ID_CODE) == "Winter socks"

    await _call(hass, "track_parcel", {**track, "contents": ""})
    assert _contents(entry, ID_CODE) is None
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ID_CODE}]


async def test_track_parcel_on_a_tracked_code_never_polls(hass):
    entry = await _setup(hass, [ID_CODE])
    coordinator = entry.runtime_data.coordinator
    data = {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"}
    with (
        patch(f"{REFRESH}.async_request_refresh", new=AsyncMock()) as refresh,
        patch(f"{CLIENT}.async_get_parcel", new=AsyncMock()) as fetch,
        patch.object(
            coordinator,
            "async_update_listeners",
            wraps=coordinator.async_update_listeners,
        ) as listeners,
    ):
        await hass.services.async_call(DOMAIN, "track_parcel", data, blocking=True)
        await hass.services.async_call(DOMAIN, "track_parcel", data, blocking=True)
    assert listeners.call_count == 1
    refresh.assert_not_called()
    fetch.assert_not_called()
    assert _contents(entry, ID_CODE) == "Running shoes"


async def test_a_newly_tracked_code_still_refreshes_via_the_options_listener(hass):
    entry = await _setup(hass)
    fetch = AsyncMock(side_effect=lambda code: _sample(code))
    with patch(f"{CLIENT}.async_get_parcel", new=fetch):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
            blocking=True,
        )
        await hass.async_block_till_done()
    fetch.assert_awaited()
    assert _contents(entry, ID_CODE) == "Running shoes"


async def test_reapply_contents_covers_delivered_parcels(hass):
    entry = await _setup(hass, [ID_CODE])
    coordinator = entry.runtime_data.coordinator
    delivered = normalize_parcel(
        {**my_data(ID_CODE), REQUESTED_CODE_KEY: ID_CODE}, market="ID"
    )
    coordinator.delivered = [delivered]

    coordinator.contents_store.async_set(ID_CODE, "Running shoes")
    coordinator.async_reapply_contents()
    assert coordinator.delivered[0]["contents"] == "Running shoes"

    coordinator.contents_store.async_set(ID_CODE, None)
    coordinator.async_reapply_contents()
    assert coordinator.delivered[0]["contents"] is None


# ---------------------------------------------------------------------------
# routing across entries
# ---------------------------------------------------------------------------


async def _setup_two(hass, id_codes: list[str], th_codes: list[str]):
    entries = []
    for market, codes in (("ID", id_codes), ("TH", th_codes)):
        entry = _config_entry([{CONF_TRACKING_CODE: c} for c in codes], market)
        entry.add_to_hass(hass)
        entries.append(entry)
    with patch(f"{CLIENT}.async_get_parcel", new=AsyncMock(return_value=_sample())):
        await hass.config_entries.async_setup(entries[0].entry_id)
        await hass.async_block_till_done()
    return entries


async def _unload_all(hass, *entries) -> None:
    for entry in entries:
        entry.mock_state(hass, ConfigEntryState.LOADED)
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _stored(entry: MockConfigEntry, code: str) -> str | None:
    return entry.runtime_data.coordinator.contents_store.get(code)


async def test_update_contents_goes_to_every_entry_listing_the_code(hass):
    first, second = await _setup_two(hass, [ID_CODE], [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )
    assert _stored(first, ID_CODE) == "Running shoes"
    assert _stored(second, ID_CODE) == "Running shoes"


async def test_update_contents_goes_only_to_the_entry_listing_the_code(hass):
    first, second = await _setup_two(hass, [ID_CODE], [])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )
    assert _stored(first, ID_CODE) == "Running shoes"
    assert _stored(second, ID_CODE) is None


async def test_update_contents_needs_an_entry_when_none_lists_the_code(hass):
    await _setup_two(hass, [ID_CODE], [])
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: UNTRACKED, "contents": "Running shoes"},
        )
    assert err.value.translation_key == "update_contents_entry_required"


async def test_config_entry_id_targets_exactly_that_entry(hass):
    first, second = await _setup_two(hass, [ID_CODE], [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {
            CONF_TRACKING_CODE: UNTRACKED,
            "contents": "Running shoes",
            "config_entry_id": second.entry_id,
        },
    )
    assert _stored(second, UNTRACKED) == "Running shoes"
    assert _stored(first, UNTRACKED) is None


async def test_config_entry_id_of_an_unloaded_or_unknown_entry_is_rejected(hass):
    first, second = await _setup_two(hass, [ID_CODE], [ID_CODE])
    second.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for entry_id in (second.entry_id, "nope"):
        with pytest.raises(ServiceValidationError):
            await _call(
                hass,
                "update_contents",
                {
                    CONF_TRACKING_CODE: ID_CODE,
                    "contents": "Running shoes",
                    "config_entry_id": entry_id,
                },
            )
    await _unload_all(hass, first, second)


async def test_an_unloaded_entry_is_never_targeted(hass):
    first, second = await _setup_two(hass, [ID_CODE], [ID_CODE])
    second.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: UNTRACKED, "contents": "Running shoes"},
    )
    assert _stored(first, UNTRACKED) == "Running shoes"
    assert _stored(second, UNTRACKED) is None
    await _unload_all(hass, first, second)


async def test_untrack_parcel_drops_the_contents(hass):
    entry = await _setup(hass, [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )

    await _call(hass, "untrack_parcel", {CONF_TRACKING_CODE: ID_CODE})

    assert entry.runtime_data.coordinator.contents_store.get(ID_CODE) is None
    assert entry.options[CONF_PARCELS] == []


async def test_untrack_parcel_skips_an_entry_that_is_not_loaded(hass):
    entry = await _setup(hass, [ID_CODE])
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)

    await _call(hass, "untrack_parcel", {CONF_TRACKING_CODE: ID_CODE})

    assert entry.options[CONF_PARCELS] == []


async def test_a_stored_value_survives_a_restart_of_the_entry(hass, hass_storage):
    entry = await _setup(hass, [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )
    store = entry.runtime_data.coordinator.contents_store
    await store._store.async_save(store._data_to_save())

    assert await hass.config_entries.async_unload(entry.entry_id)
    with patch(f"{CLIENT}.async_get_parcel", new=AsyncMock(return_value=_sample())):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert _contents(entry, ID_CODE) == "Running shoes"


async def test_removing_the_entry_removes_its_store(hass, hass_storage):
    entry = await _setup(hass, [ID_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )
    store = entry.runtime_data.coordinator.contents_store
    await store._store.async_save(store._data_to_save())
    key = STORE_KEY % entry.entry_id
    assert key in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


async def test_a_contents_change_alone_fires_no_event(hass):
    await _setup(hass, [ID_CODE])
    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", events.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", events.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", events.append)

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ID_CODE, "contents": "Running shoes"},
    )

    assert events == []
